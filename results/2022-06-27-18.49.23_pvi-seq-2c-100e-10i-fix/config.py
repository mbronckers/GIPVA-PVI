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


@dataclass
class Config:
    name: str = "global-vi"
    seed: int = 0
    plot: bool = True

    epochs: int = 1000

    N: int = 100  # Number of training data pts
    M: int = 10  # Number of inducing points
    S: int = 10  # Number of training weight samples
    I: int = 100  # Number of inference samples

    batch_size: int = 100

    nz_init: float = B.exp(-4)  # precision
    ll_var: float = 1e-2  # likelihood variance
    fix_ll: bool = True  # fix ll variance

    # Learning rates
    separate_lr: bool = False  # True => use seperate learning rates
    lr_global: float = 1e-2
    lr_nz: float = 1e-3
    lr_output_var: float = 1e-3
    lr_client_z: float = lr_global
    lr_yz: float = lr_global

    prior: Prior = Prior.StandardPrior
    dgp: DGP = DGP.ober_regression
    optimizer: str = "Adam"

    random_z: bool = False
    bias: bool = True

    dims = [1, 50, 50, 1]

    load: str = None

    log_step: int = 20

    start = None
    start_time = None
    results_dir = None
    wd = None
    plot_dir = None
    metrics_dir = None
    model_dir = None
    training_plot_dir = None

    # Clients
    num_clients: int = 1

    def __post_init__(self):
        self.client_splits: list[float] = [1.0]
        self.optimizer_params: dict = {"lr": self.lr_global}


################################################################

# The default config settings follow Ober et al.'s toy regression experiment details


@dataclass
class PVIConfig(Config):
    name: str = "pvi"

    iters: int = 10  # server iterations
    epochs: int = 100  # client epochs

    server_type: Server = SequentialServer
    # server_type: Server = SynchronousServer

    num_clients: int = 2
    ll_var: float = 1e-2  # fixed likelihood variance
    log_step: int = 10

    def __post_init__(self):
        # Homogeneous, equal-sized split.
        self.client_splits: list[float] = [1 / self.num_clients for _ in range(self.num_clients)]
        self.optimizer_params: dict = {"lr": self.lr_global}


class Color:
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    DARKCYAN = "\033[36m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    WHITE = "\033[97m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"
