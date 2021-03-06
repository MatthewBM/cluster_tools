# Cluster Tools

Workflows for distributed Bio Image Analysis and Segmentation.
Supports Slurm, LSF and local execution, easy to extend to more scheduling systems.


## Workflows

- [Hierarchical (lifted) Multicut](http:/openaccess.thecvf.com/content_ICCV_2017_workshops/papers/w1/Pape_Solving_Large_Multicut_ICCV_2017_paper.pdf)
  - Distance Transform Watersheds
  - Region Adjacency Graph
  - Edge Feature Extraction from Boundary-or-Affinity Maps
  - Agglomeration via (lifted) Multicut
- [Mutex Watershed](https://link.springer.com/chapter/10.1007/978-3-030-01225-0_34)
- Connected Components
- Downscaling and Pyramids
  - [Paintera Format](https://github.com/saalfeldlab/paintera)
  - [BigDataViewer Format](https://imagej.net/BigDataViewer)
  - [Bigcat Format](https://github.com/saalfeldlab/bigcat)
- [Ilastik Prediction](https://www.ilastik.org/)
- Skeletonization
- Distributed Neural Network Prediction (originally implemented [here](https://github.com/constantinpape/simpleference))


## Installation

All dependencies can be installed via conda, using the `environment.yml` file:
```
conda env create -f environment.yml
```
For now, this only supports linux and python3.7.
The package itself must be added to the python environment manually, e.g. by
creating a softlink in the lib/python3.7/site-packages of the conda env.
