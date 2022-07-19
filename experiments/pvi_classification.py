from __future__ import annotations
from copy import copy, deepcopy
from locale import currency

import os
import shutil
import sys
from datetime import datetime
from typing import Callable, Optional

from matplotlib import pyplot as plt
import pandas as pd

file_dir = os.path.dirname(__file__)
_root_dir = os.path.abspath(os.path.join(file_dir, ".."))
sys.path.insert(0, os.path.abspath(_root_dir))

import argparse
import logging
import logging.config
from pathlib import Path

import gi
import lab as B
import lab.torch
import numpy as np
import torch
import torch.nn as nn

from gi.server import SequentialServer, SynchronousServer

from gi.client import GI_Client

from slugify import slugify
from wbml import experiment, out

from config.config import PVIConfig, ClassificationConfig
from utils.colors import Color
from dgp import DGP, generate_data, generate_mnist, split_data_clients
from priors import build_prior
from torch.utils.data import DataLoader, TensorDataset
from utils.optimization import (
    collect_frozen_vp,
    construct_optimizer,
    collect_vp,
    estimate_local_vfe,
)


def main(args, config, logger):
    # Lab variable initialization
    B.default_dtype = torch.float32
    B.epsilon = 0.0
    key = B.create_random_state(B.default_dtype, seed=args.seed)
    torch.set_printoptions(precision=10, sci_mode=False)

    # Setup dataset. One-hot encode the labels.
    train_data, test_data = generate_mnist(data_dir=f"{_root_dir}/gi/data")
    x_tr, y_tr, x_te, y_te = (
        train_data["x"],
        train_data["y"],
        test_data["x"],
        test_data["y"],
    )
    y_tr = torch.squeeze(torch.nn.functional.one_hot(y_tr, num_classes=-1))
    y_te = torch.squeeze(torch.nn.functional.one_hot(y_te, num_classes=-1))
    train_loader = DataLoader(TensorDataset(x_tr, y_tr), batch_size=config.batch_size, shuffle=False, num_workers=4)
    test_loader = DataLoader(TensorDataset(x_te, y_te), batch_size=config.batch_size, shuffle=True, num_workers=4)
    N = len(x_tr)

    # Define model and clients.
    model = gi.GIBNN_Classification(nn.functional.relu, args.bias, config.kl)
    clients: dict[str, GI_Client] = {}

    # Build prior.
    M = args.M  # number of inducing points
    dims = config.dims
    assert dims[0] == x_tr.shape[1]
    ps = build_prior(*dims, prior=args.prior, bias=config.bias)

    # Build clients.
    logger.info(f"{Color.WHITE}Client splits: {config.client_splits}{Color.END}")
    if config.deterministic and args.num_clients == 1:
        _client = gi.GI_Client(
            key,
            f"client0",
            x_tr,
            y_tr,
            M,
            *dims,
            random_z=args.random_z,
            nz_inits=config.nz_inits,
            linspace_yz=config.linspace_yz,
        )
        key = _client.key
        clients[f"client0"] = _client
    else:
        # We use a separate key here to create consistent keys with deterministic (i.e. not calling split_data) runs of PVI.
        # otherwise, replace _tmp_key with key
        _tmp_key = B.create_random_state(B.default_dtype, seed=1)
        _tmp_key, splits = split_data_clients(_tmp_key, x_tr, y_tr, config.client_splits)
        for client_i, (client_x_tr, client_y_tr) in enumerate(splits):
            _client = GI_Client(
                key,
                f"client{client_i}",
                client_x_tr,
                client_y_tr,
                M,
                *dims,
                random_z=args.random_z,
                nz_inits=config.nz_inits,
                linspace_yz=config.linspace_yz,
            )
            key = _client.key
            clients[f"client{client_i}"] = _client

    # Optimizer parameters
    S = args.training_samples  # number of training inference samples
    log_step = config.log_step

    # Construct server.
    server = config.server_type(clients, model, args.global_iters)
    server.train_loader = train_loader
    server.test_loader = test_loader

    # Perform PVI.
    max_global_iters = server.max_iters
    for iter in range(max_global_iters):
        server.curr_iter = iter

        # Construct frozen zs, ts by iterating over all the clients. Automatically links back the previously updated clients' t & z.
        frozen_ts, frozen_zs = collect_vp(clients)

        # Log performance of global server model.
        with torch.no_grad():
            # Resample <S> inference weights
            key, _ = model.sample_posterior(key, ps, frozen_ts, frozen_zs, S=args.inference_samples, cavity_client=None)

            server.evaluate_performance()

        # Get next client(s).
        curr_clients = next(server)

        # Run client-local optimization.
        for idx, curr_client in enumerate(curr_clients):

            # Construct optimiser of only client's parameters.
            opt = construct_optimizer(args, config, curr_client, pvi=True)

            # Communicated posterior communicated to client in 1st iter is the prior
            if iter == 0:
                tmp_ts = {k: {curr_client.name: curr_client.t[k]} for k, _ in frozen_ts.items()}
                tmp_zs = {curr_client.name: curr_client.z}
            else:
                # Construct the posterior communicated to client.
                tmp_ts, tmp_zs = collect_frozen_vp(frozen_ts, frozen_zs, curr_client)  # All detached except current client.

            # Run client-local optimization
            client_data_size = curr_client.x.shape[0]
            batch_size = min(client_data_size, min(args.batch_size, N))
            max_local_iters = args.local_iters
            for client_iter in range(max_local_iters):

                # Construct epoch-th minibatch {x, y} training data
                inds = (B.range(batch_size) + batch_size * client_iter) % client_data_size
                x_mb = B.take(curr_client.x, inds)
                y_mb = B.take(curr_client.y, inds)

                key, local_vfe, exp_ll, kl, error = estimate_local_vfe(
                    key,
                    model,
                    curr_client,
                    x_mb,
                    y_mb,
                    ps,
                    tmp_ts,
                    tmp_zs,
                    S,
                    N=client_data_size,
                )
                loss = -local_vfe
                loss.backward()
                opt.step()
                curr_client.update_nz()
                opt.zero_grad()

                if client_iter == 0 or (client_iter + 1) % log_step == 0 or (client_iter + 1) == max_local_iters:
                    logger.info(
                        f"CLIENT - {curr_client.name} - global iter {iter+1:2}/{max_global_iters} - local iter [{client_iter+1:4}/{max_local_iters:4}] - local vfe: {round(local_vfe.item(), 3):13.3f}, ll: {round(exp_ll.item(), 3):13.3f}, kl: {round(kl.item(), 3):8.3f}, error: {round(error.item(), 5):8.5f}"
                    )
                else:
                    logger.debug(
                        f"CLIENT - {curr_client.name} - global {iter+1:2}/{max_global_iters} - local [{client_iter+1:4}/{max_local_iters:4}] - local vfe: {round(local_vfe.item(), 3):13.3f}, ll: {round(exp_ll.item(), 3):13.3f}, kl: {round(kl.item(), 3):8.3f}, error: {round(error.item(), 5):8.5f}"
                    )

    # Log global/server model post training
    server.curr_iter += 1
    with torch.no_grad():
        frozen_ts, frozen_zs = collect_vp(clients)
        key, _ = model.sample_posterior(key, ps, frozen_ts, frozen_zs, S=args.inference_samples, cavity_client=None)

        server.evaluate_performance()

    # Save the state of optimizable variables
    _global_vs_state_dict = {}
    for _, _c in clients.items():
        _vs_state_dict = dict(zip(_c.vs.names, [_c.vs[_name] for _name in _c.vs.names]))
        _global_vs_state_dict.update(_vs_state_dict)
    torch.save(_global_vs_state_dict, os.path.join(config.results_dir, "model/_vs.pt"))

    # Save model metrics.
    metrics = pd.DataFrame(server.log)
    metrics.to_csv(os.path.join(config.metrics_dir, f"server_log.csv"), index=False)

    logger.info(f"Total time: {(datetime.utcnow() - config.start)} (H:MM:SS:ms)")


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")

    config = ClassificationConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", "-s", type=int, help="seed", nargs="?", default=config.seed)
    parser.add_argument("--local_iters", "-l", type=int, help="client-local optimization iterations", default=config.local_iters)
    parser.add_argument("--global_iters", "-g", type=int, help="server iters (running over all clients <iters> times)", default=config.global_iters)
    parser.add_argument("--plot", "-p", action="store_true", help="Plot results", default=config.plot)
    parser.add_argument("--no_plot", action="store_true", help="Do not plot results")
    parser.add_argument("--name", "-n", type=str, help="Experiment name", default="")
    parser.add_argument("--M", "-M", type=int, help="number of inducing points", default=config.M)
    parser.add_argument("--N", "-N", type=int, help="number of training points", default=config.N)
    parser.add_argument("--det", action="store_true", help="Deterministic training data split and ll variance", default=config.deterministic)
    parser.add_argument(
        "--training_samples",
        "-S",
        type=int,
        help="number of training weight samples",
        default=config.S,
    )
    parser.add_argument(
        "--inference_samples",
        "-I",
        type=int,
        help="number of inference weight samples",
        default=config.I,
    )
    parser.add_argument(
        "--nz_init",
        type=float,
        help="Initial value of client's likelihood precision",
        default=config.nz_init,
    )
    parser.add_argument("--lr", type=float, help="learning rate", default=config.lr_global)
    parser.add_argument("--ll_var", type=float, help="likelihood var", default=config.ll_var)
    parser.add_argument(
        "--batch_size",
        "-b",
        type=int,
        help="training batch size",
        default=config.batch_size,
    )
    parser.add_argument("--data", "-d", type=int, help="dgp/dataset type", default=config.dgp)
    parser.add_argument(
        "--load",
        type=str,
        help="model directory to load (e.g. experiment_name)",
        default=config.load,
    )
    parser.add_argument(
        "--random_z",
        "-z",
        action="store_true",
        help="Randomly initializes global inducing points z",
        default=config.random_z,
    )
    parser.add_argument("--prior", "-P", type=str, help="prior type", default=config.prior)
    parser.add_argument("--bias", help="Use bias vectors in BNN", default=config.bias)
    parser.add_argument(
        "--sep_lr",
        help="Use separate LRs for parameters (see config)",
        default=config.separate_lr,
    )
    parser.add_argument(
        "--num_clients",
        "-nc",
        help="Number of clients (implicit equal split)",
        default=config.num_clients,
    )
    args = parser.parse_args()

    # Create experiment directories
    config.name += f"_{args.name}"
    _start = datetime.utcnow()
    _time = _start.strftime("%m-%d-%H.%M.%S")
    _results_dir_name = "results"
    _results_dir = os.path.join(_root_dir, _results_dir_name, f"{_time}_{slugify(config.name)}")
    _wd = experiment.WorkingDirectory(_results_dir, observe=True, seed=args.seed)
    _plot_dir = os.path.join(_results_dir, "plots")
    _metrics_dir = os.path.join(_results_dir, "metrics")
    _model_dir = os.path.join(_results_dir, "model")
    _training_plot_dir = os.path.join(_plot_dir, "training")
    _server_dir = os.path.join(_plot_dir, "server")
    Path(_plot_dir).mkdir(parents=True, exist_ok=True)
    Path(_training_plot_dir).mkdir(parents=True, exist_ok=True)
    Path(_model_dir).mkdir(parents=True, exist_ok=True)
    Path(_metrics_dir).mkdir(parents=True, exist_ok=True)
    Path(_server_dir).mkdir(parents=True, exist_ok=True)

    if args.no_plot:
        config.plot = False
        args.plot = False
    config.start = _start
    config.start_time = _time
    config.results_dir = _results_dir
    config.wd = _wd
    config.plot_dir = _plot_dir
    config.metrics_dir = _metrics_dir
    config.model_dir = _model_dir
    config.training_plot_dir = _training_plot_dir
    config.server_dir = _server_dir

    # Save script
    if os.path.exists(os.path.abspath(sys.argv[0])):
        shutil.copy(os.path.abspath(sys.argv[0]), _wd.file("script.py"))
        shutil.copy(
            os.path.join(_root_dir, "experiments/config/config.py"),
            _wd.file("config.py"),
        )

    else:
        out("Could not save calling script.")

    #### Logging ####
    logging.config.fileConfig(
        os.path.join(file_dir, "config/logging.conf"),
        defaults={"logfilepath": _results_dir},
    )
    logger = logging.getLogger()
    np.set_printoptions(linewidth=np.inf)

    # Log program info
    logger.debug(f"Call: {sys.argv}")
    logger.debug(f"Root: {_results_dir}")
    logger.debug(f"Time: {_time}")
    logger.debug(f"Seed: {args.seed}")
    logger.info(f"{Color.WHITE}Args: {args}{Color.END}")

    main(args, config, logger)
