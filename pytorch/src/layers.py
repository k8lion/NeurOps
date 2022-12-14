import torch
import torch.nn as nn
from torch.nn.parameter import Parameter
from .initializations import *


"""
    A modifiable version of Conv2D that can increase or decrease channel count and/or be masked
"""


class ModLinear(nn.Linear):
    def __init__(self, in_features: int, out_features: int, bias: bool = True, masked: bool = False,
                 learnable_mask: bool = False, nonlinearity: str = 'relu', prebatchnorm: bool = False):

        super().__init__(in_features, out_features, bias)

        self.masked = masked

        if masked:
            self.mask_tensor = Parameter(torch.ones(
                self.out_features, self.in_features), requires_grad=learnable_mask)
            self.mask_vector = Parameter(torch.ones(
                self.out_features), requires_grad=learnable_mask)

        if nonlinearity == 'relu':
            self.nonlinearity = nn.ReLU()
        elif nonlinearity == '':
            self.nonlinearity = nn.Identity()
        else:
            raise ValueError('Nonlinearity not supported')

        if prebatchnorm:
            self.batchnorm = nn.BatchNorm1d(self.in_features)
        else:
            self.batchnorm = nn.Identity()
    
    def weightparameters(self):
        if self.bias is not None:
            return [self.weight, self.bias]
        else:
            return [self.weight]

    def forward(self, x: torch.Tensor):
        return self.nonlinearity(nn.functional.linear(self.batchnorm(x), self.mask_tensor * self.weight if self.masked else self.weight,
                                                      self.mask_vector * self.bias if self.masked else self.bias))

    """
        Mask fanin weights of neurons of this layer that have indices in fanin and fanout weights 
        of neurons of the previous layer that have indices in fanout.

        fanin: list of indices of neurons of this layer
        fanout: list of indices of neurons of the previous layer
    """

    def mask(self, fanin=[], fanout=[]):
        if self.masked:
            self.mask_tensor.data[fanin, :] = 0
            self.mask_vector.data[fanin] = 0
            self.mask_tensor.data[:, fanout] = 0
        else:
            print("No mask found")

    """
        Unmask fanin weights of neurons of this layer that have indices in fanin and fanout weights 
        of neurons of the previous layer that have indices in fanout.

        fanin: list of indices of neurons of this layer
        fanout: list of indices of neurons of the previous layer
    """

    def unmask(self, fanin=[], fanout=[]):
        if self.masked:
            self.mask_tensor.data[fanin, :] = 1
            self.mask_vector.data[fanin] = 1
            self.mask_tensor.data[:, fanout] = 1
            if not isinstance(self.batchnorm, nn.Identity):
                if self.batchnorm.running_mean is not None:
                    self.batchnorm.running_mean[fanout] = 0
                    self.batchnorm.running_var[fanout] = 1
                if self.batchnorm.weight is not None:
                    self.batchnorm.weight.data[fanout] = 1
                    self.batchnorm.bias.data[fanout] = 0  
        else:
            print("No mask found")  

    """
        Remove fanin weights of neurons (of this layer) in list fanin_to_prune from the layer, and 
        fanout weights of neurons (of previous layer) in list fanout_to_prune.

        fanin_to_prune: list of neurons to remove from this layer
        fanout_to_prune: list of neurons to remove from previous layer
        optimizer: optimizer to update to new shape of the layer
    """

    def prune(self, fanin_to_prune=[], fanout_to_prune=[], optimizer=None):
        fanin_to_keep = range(self.out_features)
        fanin_to_keep = [
            fitk for fitk in fanin_to_keep if fitk not in fanin_to_prune]

        fanout_to_keep = range(self.in_features)
        fanout_to_keep = [
            fotk for fotk in fanout_to_keep if fotk not in fanout_to_prune]

        if self.masked:
            self.mask_tensor.data = self.mask_tensor.data[fanin_to_keep,
                                                        :][:, fanout_to_keep]
            self.mask_vector.data = self.mask_vector.data[fanin_to_keep]

        with torch.no_grad():
            new_weight = Parameter(self.weight[fanin_to_keep, :][:, fanout_to_keep])
            if self.bias is not None:
                new_bias = Parameter(self.bias[fanin_to_keep])
            if not isinstance(self.batchnorm, nn.Identity) and self.batchnorm.weight is not None:
                new_batchnorm_weight = Parameter(self.batchnorm.weight[fanout_to_keep])
                new_batchnorm_bias = Parameter(self.batchnorm.bias[fanout_to_keep])

        if optimizer is not None:
            for group in optimizer.param_groups:
                for (i, param) in enumerate(group['params']):
                    if param is self.weight:
                        for (_, v) in optimizer.state[param].items():
                            if isinstance(v, torch.Tensor) and v.shape == self.weight.shape:
                                v.data = v.data[fanin_to_keep,
                                                :][:, fanout_to_keep]
                        optimizer.state[new_weight] = optimizer.state[param]
                        group['params'][i] = new_weight
                    if self.bias is not None and param is self.bias:
                        for (_, v) in optimizer.state[param].items():
                            if isinstance(v, torch.Tensor) and v.shape == self.bias.shape:
                                v.data = v.data[fanin_to_keep]
                        optimizer.state[new_bias] = optimizer.state[param]
                        group['params'][i] = new_bias
                    if not isinstance(self.batchnorm, nn.Identity):
                        if self.batchnorm.weight is not None and param is self.batchnorm.weight:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.weight.shape:
                                    v.data = v.data[fanout_to_keep]
                            optimizer.state[new_batchnorm_weight] = optimizer.state[param]
                            group['params'][i] = new_batchnorm_weight
                        if self.batchnorm.bias is not None and param is self.batchnorm.bias:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.bias.shape:
                                    v.data = v.data[fanout_to_keep]
                            optimizer.state[new_batchnorm_bias] = optimizer.state[param]
                            group['params'][i] = new_batchnorm_bias

        self.weight = new_weight
        if self.bias is not None:
            self.bias = new_bias

        self.out_features = len(fanin_to_keep)
        self.in_features = len(fanout_to_keep)

        if not isinstance(self.batchnorm, nn.Identity):
            if self.batchnorm.running_mean is not None:
                self.batchnorm.running_mean = self.batchnorm.running_mean[fanout_to_keep]
                self.batchnorm.running_var = self.batchnorm.running_var[fanout_to_keep]
            if self.batchnorm.weight is not None:
                self.batchnorm.weight = new_batchnorm_weight
                self.batchnorm.bias = new_batchnorm_bias

    """
        Add new_out_features new neurons to the layer (and new_in_features new inputs to the layer), with 
        weights fanin_weights and fanout_weights respectively.

        If fanin_weights and/or fanout_weights are None, they are initialized with zeros.

        If fanin_weights and/or fanout_weights are 1D tensors, they are expanded to 2D tensors
        with the appropriate number of neurons/inputs.

        If fanin_weights and/or fanout_weights is "kaiming", they are initialized with the
        Kaiming initialization.

        new_out_features: number of neurons to add to this layer
        new_in_features: number of inputs to add to this layer
        fanin_weights: weights of the new neurons
        fanout_weights: weights of the new inputs (adding neurons to the previous layer)
        optimizer: optimizer to update to new shape of the layer
    """

    def grow(self, new_out_features=0, new_in_features=0, fanin_weights=None, fanout_weights=None, optimizer=None, activations=None):
        if new_in_features > 0:
            if fanout_weights is None:
                fanout_weights = torch.zeros(self.out_features, new_in_features)
            elif fanout_weights == "kaiming":
                fanout_weights = kaiming_uniform(torch.zeros(self.out_features,self.in_features+new_in_features))[:, :new_in_features]
            elif fanout_weights == "iterative_orthogonalization":
                fanout_weights = iterative_orthogonalization(torch.zeros(self.out_features,
                                                                        self.in_features+new_in_features), 
                                                            input=activations)[:, :new_in_features]
            elif isinstance(fanin_weights, torch.Tensor) and len(fanout_weights.shape) == 1:
                fanout_weights = fanout_weights.unsqueeze(0)

            with torch.no_grad():
                new_weight = Parameter(
                    torch.cat((self.weight.data, fanout_weights), dim=1))
                if not isinstance(self.batchnorm, nn.Identity) and self.batchnorm.weight is not None:
                    new_batchnorm_weight = Parameter(
                        torch.cat((self.batchnorm.weight.data, torch.ones(new_in_features)), dim=0))
                    new_batchnorm_bias = Parameter(
                        torch.cat((self.batchnorm.bias.data, torch.zeros(new_in_features)), dim=0))

            if optimizer is not None:
                for group in optimizer.param_groups:
                    for (i, param) in enumerate(group['params']):
                        if param is self.weight:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.weight.shape:
                                    v.data = torch.cat(
                                        (v.data, torch.zeros_like(fanout_weights)), dim=1)
                            optimizer.state[new_weight] = optimizer.state[param]
                            group['params'][i] = new_weight
                        if not isinstance(self.batchnorm, nn.Identity):
                            if self.batchnorm.weight is not None and param is self.batchnorm.weight:
                                for (_, v) in optimizer.state[param].items():
                                    if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.weight.shape:
                                        v.data = torch.cat(
                                            (v.data, torch.ones(new_in_features)), dim=1)
                                optimizer.state[new_batchnorm_weight] = optimizer.state[param]
                                group['params'][i] = new_batchnorm_weight
                            if self.batchnorm.bias is not None and param is self.batchnorm.bias:
                                for (_, v) in optimizer.state[param].items():
                                    if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.bias.shape:
                                        v.data = torch.cat(
                                            (v.data, torch.ones(new_in_features)), dim=1)
                                optimizer.state[new_batchnorm_bias] = optimizer.state[param]
                                group['params'][i] = new_batchnorm_bias

            self.weight = new_weight
            if self.masked:
                self.mask_tensor.data = torch.cat(
                    (self.mask_tensor.data, torch.ones(self.out_features, new_in_features)), dim=1)

            self.in_features = self.in_features + new_in_features

            if not isinstance(self.batchnorm, nn.Identity):
                if self.batchnorm.running_mean is not None:
                    self.batchnorm.running_mean = torch.cat(
                        (self.batchnorm.running_mean, torch.zeros(new_in_features)))
                    self.batchnorm.running_var = torch.cat(
                        (self.batchnorm.running_var, torch.ones(new_in_features)))
                if self.batchnorm.weight is not None:
                    self.batchnorm.weight = new_batchnorm_weight
                    self.batchnorm.bias = new_batchnorm_bias

        if new_out_features > 0:
            if fanin_weights is None:
                fanin_weights = torch.zeros(new_out_features, self.in_features)
            elif fanin_weights == "kaiming":
                fanin_weights = kaiming_uniform(torch.zeros(new_out_features+self.out_features, self.in_features))[:new_out_features, :]
            elif fanin_weights == "iterative_orthogonalization":
                fanin_weights = iterative_orthogonalization(torch.zeros(new_out_features+self.out_features, 
                                                                       self.in_features), 
                                                           input=activations)[:new_out_features, :]
            elif isinstance(fanin_weights, torch.Tensor) and len(fanin_weights.shape) == 1:
                fanin_weights = fanin_weights.unsqueeze(1)

            with torch.no_grad():
                new_weight = Parameter(
                    torch.cat((self.weight.data, fanin_weights), dim=0))
                if self.bias is not None:
                    new_bias = Parameter(
                        torch.cat((self.bias.data, torch.zeros(new_out_features))))

            if optimizer is not None:
                for group in optimizer.param_groups:
                    for (i, param) in enumerate(group['params']):
                        if param is self.weight:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.weight.shape:
                                    v.data = torch.cat(
                                        (v.data, torch.zeros_like(fanin_weights)), dim=0)
                            optimizer.state[new_weight] = optimizer.state[param]
                            group['params'][i] = new_weight
                        if self.bias is not None and param is self.bias:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.bias.shape:
                                    v.data = torch.cat(
                                        (v.data, torch.zeros(new_out_features)))
                            optimizer.state[new_bias] = optimizer.state[param]
                            group['params'][i] = new_bias

            self.weight = new_weight
            if self.bias is not None:
                self.bias = new_bias
            if self.masked:
                self.mask_tensor.data = torch.cat(
                    (self.mask_tensor.data, torch.ones(new_out_features, self.in_features)), dim=0)
                self.mask_vector.data = torch.cat(
                    (self.mask_vector.data, torch.ones(new_out_features)))

            self.out_features = self.out_features + new_out_features


"""
    A modifiable version of Conv2D that can increase or decrease channel count and/or be masked
"""
class ModConv2d(nn.Conv2d):
    def __init__(self, masked: bool = False, bias: bool = True, learnable_mask: bool = False, nonlinearity: str = 'relu',
                 prebatchnorm: bool = False, *args, **kwargs):

        super().__init__(bias=bias, *args, **kwargs)

        self.masked = masked
        self.learnable_mask = learnable_mask

        if masked:
            self.mask_tensor = Parameter(torch.ones(self.out_channels, self.in_channels,
                                        self.kernel_size[0], self.kernel_size[1]), requires_grad=learnable_mask)
            self.mask_vector = Parameter(torch.ones(
                self.out_channels), requires_grad=learnable_mask)

        if nonlinearity == 'relu':
            self.nonlinearity = nn.ReLU()
        elif nonlinearity == '':
            self.nonlinearity = nn.Identity()
        else:
            raise ValueError('Nonlinearity not supported')

        if prebatchnorm:
            self.batchnorm = nn.BatchNorm2d(self.in_channels)
        else:
            self.batchnorm = nn.Identity()

    def weightparameters(self):
        if self.bias is not None:
            return [self.weight, self.bias]
        else:
            return [self.weight]
            
    def forward(self, x):
        return self.nonlinearity(nn.functional.conv2d(self.batchnorm(x), self.mask_tensor * self.weight if self.masked else self.weight,
                                                      self.mask_vector * self.bias if self.masked else self.bias, self.stride, 
                                                      self.padding, self.dilation, self.groups))

    """
        Mask fanin weights of neurons of this layer that have indices in fanin and fanout weights 
        of neurons of the previous layer that have indices in fanout.

        fanin: list of indices of neurons of this layer
        fanout: list of indices of neurons of the previous layer
    """

    def mask(self, fanin=[], fanout=[]):
        self.mask_tensor.data[fanin, :, :, :] = 0
        self.mask_vector.data[fanin] = 0
        self.mask_tensor.data[:, fanout, :, :] = 0

    """
        Unmask fanin weights of channels of this layer that have indices in fanin and fanout weights 
        of channels of the previous layer that have indices in fanout.

        fanin: list of indices of channels of this layer
        fanout: list of indices of channels of the previous layer
    """

    def unmask(self, fanin=[], fanout=[]):
        self.mask_tensor.data[fanin, :, :, :] = 1
        self.mask_vector.data[fanin] = 1
        self.mask_tensor.data[:, fanout, :, :] = 1
        if not isinstance(self.batchnorm, nn.Identity):
            if self.batchnorm.running_mean is not None:
                self.batchnorm.running_mean[fanout] = 0
                self.batchnorm.running_var[fanout] = 1
            if self.batchnorm.weight is not None:
                self.batchnorm.weight.data[fanout] = 1
                self.batchnorm.bias.data[fanout] = 0

    """
        Remove fanin weights of channels (of this layer) in list fanin_to_prune from the layer, and 
        fanout weights of channels (of previous layer) in list fanout_to_prune.

        fanin_to_prune: list of channels to remove from this layer
        fanout_to_prune: list of channels to remove from previous layer
    """

    def prune(self, fanin_to_prune=[], fanout_to_prune=[], optimizer=None):
        fanin_to_keep = range(self.out_channels)
        fanin_to_keep = [
            fitk for fitk in fanin_to_keep if fitk not in fanin_to_prune]

        fanout_to_keep = range(self.in_channels)
        fanout_to_keep = [
            fotk for fotk in fanout_to_keep if fotk not in fanout_to_prune]

        with torch.no_grad():
            new_weight = Parameter(self.weight[fanin_to_keep, :][:, fanout_to_keep])
            if self.bias is not None:
                new_bias = Parameter(self.bias[fanin_to_keep])
            if not isinstance(self.batchnorm, nn.Identity) and self.batchnorm.weight is not None:
                new_batchnorm_weight = Parameter(self.batchnorm.weight[fanout_to_keep])
                new_batchnorm_bias = Parameter(self.batchnorm.bias[fanout_to_keep])


        if optimizer is not None:
            for group in optimizer.param_groups:
                for (i, param) in enumerate(group['params']):
                    if param is self.weight:
                        for (_, v) in optimizer.state[param].items():
                            if isinstance(v, torch.Tensor) and v.shape == self.weight.shape:
                                v.data = v.data[fanin_to_keep,
                                                :][:, fanout_to_keep]
                        optimizer.state[new_weight] = optimizer.state[param]
                        group['params'][i] = new_weight
                    if self.bias is not None and param is self.bias:
                        for (_, v) in optimizer.state[param].items():
                            if isinstance(v, torch.Tensor) and v.shape == self.bias.shape:
                                v.data = v.data[fanin_to_keep]
                        optimizer.state[new_bias] = optimizer.state[param]
                        group['params'][i] = new_bias
                    if not isinstance(self.batchnorm, nn.Identity):
                        if self.batchnorm.weight is not None and param is self.batchnorm.weight:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.weight.shape:
                                    v.data = v.data[fanout_to_keep]
                            optimizer.state[new_batchnorm_weight] = optimizer.state[param]
                            group['params'][i] = new_batchnorm_weight
                        if self.batchnorm.bias is not None and param is self.batchnorm.bias:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.bias.shape:
                                    v.data = v.data[fanout_to_keep]
                            optimizer.state[new_batchnorm_bias] = optimizer.state[param]
                            group['params'][i] = new_batchnorm_bias

        self.weight = new_weight
        if self.bias is not None:
            self.bias = new_bias

        if self.masked:
            self.mask_tensor.data = self.mask_tensor.data[fanin_to_keep,
                                                        :][:, fanout_to_keep]
            self.mask_vector.data = self.mask_vector.data[fanin_to_keep]

        self.out_channels = len(fanin_to_keep)
        self.in_channels = len(fanout_to_keep)

        if not isinstance(self.batchnorm, nn.Identity):
            if self.batchnorm.running_mean is not None:
                self.batchnorm.running_mean = self.batchnorm.running_mean[fanout_to_keep]
                self.batchnorm.running_var = self.batchnorm.running_var[fanout_to_keep]
            if self.batchnorm.weight is not None:
                self.batchnorm.weight = new_batchnorm_weight
                self.batchnorm.bias = new_batchnorm_bias

    """
        Add new_out_channels new channels to the layer (and new_in_channels new inputs to the layer), with 
        weights fanin_weights and fanout_weights respectively.

        If fanin_weights and/or fanout_weights are None, they are initialized with zeros.

        If fanin_weights and/or fanout_weights are 1D tensors, they are reshaped to 4D tensors
        with the appropriate number of channels/inputs.

        If fanin_weights and/or fanout_weights are str, they are initialized with the resepective 
        initialization.

        new_out_channels: number of channels to add to this layer
        new_in_channels: number of inputs to add to this layer
        fanin_weights: weights of the new channels
        fanout_weights: weights of the new inputs (channels of previous layer)
    """

    def grow(self, new_out_channels=0, new_in_channels=0, fanin_weights=None, fanout_weights=None, optimizer=None, 
             activations: torch.Tensor = None):
        if new_in_channels > 0:
            if fanout_weights is None:
                fanout_weights = torch.zeros(
                    self.out_channels, new_in_channels, self.kernel_size[0], self.kernel_size[1])
            elif fanout_weights == "kaiming":
                fanout_weights = kaiming_uniform(torch.zeros(self.out_channels,self.in_channels+new_in_channels, 
                                                            self.kernel_size[0], self.kernel_size[1]))[:, :new_in_channels]
            elif fanout_weights == "iterative_orthogonalization":
                fanout_weights = iterative_orthogonalization(torch.zeros(self.out_channels,self.in_channels+new_in_channels, 
                                                                        self.kernel_size[0], self.kernel_size[1]), 
                                                            input=activations, stride=self.stride)[:, :new_in_channels]
            elif isinstance(fanout_weights, torch.Tensor) and len(fanout_weights.shape) <= 2:
                fanout_weights = torch.reshape(
                    fanout_weights, (self.out_channels, new_in_channels, self.kernel_size[0], self.kernel_size[1]))
            elif isinstance(fanout_weights, torch.Tensor) and len(fanout_weights.shape) == 3:
                fanout_weights = fanout_weights.unsqueeze(0)

            with torch.no_grad():
                new_weight = Parameter(
                    torch.cat((self.weight.data, fanout_weights), dim=1))
                if not isinstance(self.batchnorm, nn.Identity) and self.batchnorm.weight is not None:
                    new_batchnorm_weight = Parameter(
                        torch.cat((self.batchnorm.weight.data, torch.ones(new_in_channels)), dim=0))
                    new_batchnorm_bias = Parameter(
                        torch.cat((self.batchnorm.bias.data, torch.zeros(new_in_channels)), dim=0))


            if optimizer is not None:
                for group in optimizer.param_groups:
                    for (i, param) in enumerate(group['params']):
                        if param is self.weight:  # note: p will automatically be updated in optimizer.param_groups
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.weight.shape:
                                    v.data = torch.cat(
                                        (v.data, torch.zeros_like(fanout_weights)), dim=1)
                            optimizer.state[new_weight] = optimizer.state[param]
                            group['params'][i] = new_weight
                        if not isinstance(self.batchnorm, nn.Identity):
                            if self.batchnorm.weight is not None and param is self.batchnorm.weight:
                                for (_, v) in optimizer.state[param].items():
                                    if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.weight.shape:
                                        v.data = torch.cat(
                                            (v.data, torch.ones(new_in_channels)), dim=1)
                                optimizer.state[new_batchnorm_weight] = optimizer.state[param]
                                group['params'][i] = new_batchnorm_weight
                            if self.batchnorm.bias is not None and param is self.batchnorm.bias:
                                for (_, v) in optimizer.state[param].items():
                                    if isinstance(v, torch.Tensor) and v.shape == self.batchnorm.bias.shape:
                                        v.data = torch.cat(
                                            (v.data, torch.ones(new_in_channels)), dim=1)
                                optimizer.state[new_batchnorm_bias] = optimizer.state[param]
                                group['params'][i] = new_batchnorm_bias


            self.weight = new_weight
            if self.masked:
                self.mask_tensor.data = torch.cat((self.mask_tensor, torch.ones(
                    self.out_channels, new_in_channels, self.kernel_size[0], self.kernel_size[1])), dim=1)

            self.in_channels = self.in_channels + new_in_channels

            if not isinstance(self.batchnorm, nn.Identity):
                if self.batchnorm.running_mean is not None:
                    self.batchnorm.running_mean = torch.cat(
                        (self.batchnorm.running_mean, torch.zeros(new_in_channels)))
                    self.batchnorm.running_var = torch.cat(
                        (self.batchnorm.running_var, torch.ones(new_in_channels)))
                if self.batchnorm.weight is not None:
                    self.batchnorm.weight = new_batchnorm_weight
                    self.batchnorm.bias = new_batchnorm_bias


        if new_out_channels > 0:
            if fanin_weights is None:
                fanin_weights = torch.zeros(
                    new_out_channels, self.in_channels, self.kernel_size[0], self.kernel_size[1])
            elif fanin_weights == "kaiming":
                fanin_weights = kaiming_uniform(torch.zeros(new_out_channels+self.out_channels, self.in_channels, 
                                                           self.kernel_size[0], self.kernel_size[1]))[:new_out_channels]
            elif fanin_weights == "iterative_orthogonalization":
                fanin_weights = iterative_orthogonalization(torch.zeros(new_out_channels+self.out_channels,self.in_channels, 
                                                                       self.kernel_size[0], self.kernel_size[1]), 
                                                           input=activations, stride=self.stride)[:new_out_channels, :]
            elif isinstance(fanin_weights, torch.Tensor) and len(fanin_weights.shape) <= 2:
                fanin_weights = torch.reshape(
                    fanin_weights, (new_out_channels, self.in_channels, self.kernel_size[0], self.kernel_size[1]))
            elif isinstance(fanin_weights, torch.Tensor) and len(fanin_weights.shape) == 3:
                fanin_weights = fanin_weights.unsqueeze(1)

            new_weight = nn.Parameter(
                torch.cat((self.weight.data, fanin_weights), dim=0))
            if self.bias is not None:
                new_bias = nn.Parameter(
                    torch.cat((self.bias.data, torch.zeros(new_out_channels)), dim=0))

            if optimizer is not None:
                for group in optimizer.param_groups:
                    for (i, param) in enumerate(group['params']):
                        if param is self.weight:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.weight.shape:
                                    v.data = torch.cat(
                                        (v.data, torch.zeros_like(fanin_weights)), dim=0)
                            optimizer.state[new_weight] = optimizer.state[param]
                            group['params'][i] = new_weight
                        if self.bias is not None and param is self.bias:
                            for (_, v) in optimizer.state[param].items():
                                if isinstance(v, torch.Tensor) and v.shape == self.bias.shape:
                                    v.data = torch.cat(
                                        (v.data, torch.zeros(new_out_channels)))
                            optimizer.state[new_bias] = optimizer.state[param]
                            group['params'][i] = new_bias

            self.weight = new_weight
            if self.bias is not None:
                self.bias = new_bias
            if self.masked:
                self.mask_tensor.data = torch.cat((self.mask_tensor, torch.ones(
                    new_out_channels, self.in_channels, self.kernel_size[0], self.kernel_size[1])), dim=0)
                self.mask_vector.data = torch.cat(
                    (self.mask_vector, torch.ones(new_out_channels)))

            self.out_channels = self.out_channels + new_out_channels
