import sys
import os
from dataclasses import dataclass

file_dir = os.path.dirname(__file__)
_root_dir = os.path.abspath(os.path.join(file_dir, ".."))
sys.path.insert(0, os.path.abspath(_root_dir))

from priors import Prior
from dgp import DGP
import lab as B
import torch

@dataclass
class Config:
    name: str = ""
    seed: int = 0
    plot: bool = True
    
    epochs: int = 1000
    
    N: int = 100        # Number of training data pts
    M: int = 10         # Number of inducing points
    S: int = 10         # Number of training weight samples
    I: int = 100        # Number of inference samples

    nz_init: float = B.exp(-4)  # precision
    ll_var: float = 1e-3        # likelihood variance

    # Learning rates
    lr_global: float = 1e-2
    lr_nz: float = 1e-3
    lr_output_var: float = 1e-3
    lr_client_z: float = lr_global
    lr_yz: float = lr_global

    separate_lr: bool = False
    
    batch_size: int = 100

    # prior: Prior = Prior.NealPrior
    prior: Prior = Prior.StandardPrior
    dgp: DGP = DGP.ober_regression

    random_z: bool = False
    bias: bool = True

    dims = [1, 50, 50, 1]

    load: str = None

################################################################

# The default config settings follow Ober et al.'s toy regression experiment details

class Color:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   WHITE = '\033[97m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'