from __future__ import annotations

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
from gi.server import SequentialServer, Server, SynchronousServer
from gi.kl import KL

from .config import Config, set_experiment_name


# The default config settings below follow Ober et al.'s toy regression experiment details


@dataclass
class GI_OberConfig(Config):
    posterior_type: str = "pvi_ober"
    location = os.path.basename(__file__)
    dgp: DGP = DGP.ober_regression

    prior: Prior = Prior.NealPrior

    # GI settings
    deterministic: bool = False  # deterministic client training
    random_z: bool = False  # random inducing point initialization
    linspace_yz: bool = False  # True => use linspace(-1, 1) for yz initialization

    # Ober fixes ll variance to 3/scale(x_tr)

    # Model architecture
    N: int = 40  # train_split
    M: int = 5
    S: int = 2
    I: int = 50
    dims = [1, 50, 1]
    batch_size: int = 40

    # Likelihood settings
    fix_ll: bool = False  # true => fix ll variance
    ll_scale: float = 0.1

    # Learning rates
    sep_lr = False
    lr_global: float = 0.01

    # Communication settings
    global_iters: int = 1  # server iterations
    local_iters: int = 10000  # client-local iterations

    split_type: str = None

    # Server & clients
    server_type: Server = SequentialServer
    num_clients: int = 1
    dampening_factor = None  # 0.25

    def __post_init__(self):
        # Precisions of the inducing points per layer

        # Loose
        # self.nz_inits: list[float] = [B.exp(-4) for _ in range(len(self.dims) - 1)]
        # self.nz_inits[-1] = 1.0  # According to paper, last layer precision gets initialized to 1

        #  Tight
        # self.nz_inits: list[float] = [1e3 - (self.dims[i] + 1) for i in range(len(self.dims) - 1)]

        self.nz_inits: list[float] = [1 for _ in range(len(self.dims) - 1)]

        self.name = set_experiment_name(self)
        # Homogeneous, equal-sized split.
        self.client_splits: list[float] = [float(1 / self.num_clients) for _ in range(self.num_clients)]
        self.optimizer_params: dict = {"lr": self.lr_global}


@dataclass
class MFVI_OberConfig(Config):
    posterior_type: str = "mfvi_ober"
    location = os.path.basename(__file__)
    dgp: DGP = DGP.ober_regression

    prior: Prior = Prior.NealPrior

    # Model architecture
    N: int = 40  # train_split
    S: int = 2
    I: int = 50
    dims = [1, 50, 1]
    batch_size: int = 40

    deterministic: bool = False  # deterministic client training
    fix_ll: bool = False  # true => fix ll variance
    ll_scale: float = 0.1

    # Communication settings
    global_iters: int = 1  # server iterations
    local_iters: int = 30000  # client-local iterations

    split_type: str = None

    # Server & clients
    server_type: Server = SequentialServer
    num_clients: int = 1
    dampening_factor = None

    sep_lr: bool = False  # True => use seperate learning rates
    lr_global: float = 0.01

    # Initialize weight layer mean from N(0,1)
    random_mean_init: bool = True

    def __post_init__(self):
        # Precisions of weights per layer
        # Tight => low variance
        # self.nz_inits: list[float] = [1e3 - (self.dims[i] + 1) for i in range(len(self.dims) - 1)]
        self.nz_inits: list[float] = [1e3 for i in range(len(self.dims) - 1)]

        # Medium => reasonable variance
        # self.nz_inits: list[float] = [1 for _ in range(len(self.dims) - 1)]

        # Loose => high variance
        # self.nz_inits: list[float] = [B.exp(-4) for _ in range(len(self.dims) - 1)]
        # self.nz_inits[-1] = 1.0  # According to paper, last layer precision gets initialized to 1

        self.name = set_experiment_name(self)

        # Homogeneous, equal-sized split.
        self.client_splits: list[float] = [float(1 / self.num_clients) for _ in range(self.num_clients)]
        self.optimizer_params: dict = {"lr": self.lr_global}
