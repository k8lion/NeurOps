## NeurOps

![Neuron representations (Adapted from a Maile et al. (2022))](images/neurops.png)
This repository contains an implementation of neural operations: growing and pruning for architectural optimization of neural networks. It extends the basic operations and functionality of [https://github.com/k8lion/Neurogenesis](https://github.com/k8lion/Neurogenesis) from Julia to PyTorch, in addition to implementing techniques from other architectural optimization works. It allows for growing and pruning of basic neural network layers, `Linear` and `Conv2d`, from both a masking approach as well as by changing the weight tensor shapes. It also handles normalization layers and optimizer states to enable iterative architectural optimization in addition to standard training. Various metrics and initialization strategies are implemented for informing the neural operations. These techniques are extended to larger models, including deep sequential models and transformers. 

The goal of this repository is to streamline and unify architectural optimization techniques to permit further research. We hope to continue to extend the utility of this repository in future updates, including more languages and frameworks (namely Julia/Flux and Jax/Flax), more growing and pruning algorithms, more architecture backbones, more structures to grow and prune, and more subfields of architectural optimization such as neural architecture search. We welcome use of this repository as well as contributions. See `pytorch/README.md` for further details, as well as `tutorial.ipynb` for example usage.
