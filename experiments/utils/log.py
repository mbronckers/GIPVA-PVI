from __future__ import annotations

import logging
import os
import shutil
import sys
from typing import Optional, Tuple

import pandas as pd
import seaborn as sns
from matplotlib import pyplot as plt
import numpy as np
from pathlib import Path

import torch

file_dir = os.path.dirname(__file__)
_root_dir = os.path.abspath(os.path.join(file_dir, ".."))
sys.path.insert(0, os.path.abspath(_root_dir))

import gi
from config.config import Config
from utils.colors import Color
from gi.utils.plotting import line_plot, plot_confidence, plot_predictions, scatter_plot
from wbml import experiment, out, plot

logger = logging.getLogger()

from tueplots import figsizes, fontsizes

colors = sns.color_palette("bright")
sns.set_style("whitegrid")
sns.set_palette(colors)
plt.rcParams.update({**figsizes.neurips2022(ncols=1), **fontsizes.neurips2022(), "figure.dpi": 200})


def plot_client_vp(config, curr_client, iter, epoch):
    _client_plot_dir = os.path.join(config.training_plot_dir, curr_client.name)
    Path(_client_plot_dir).mkdir(parents=True, exist_ok=True)
    fig, _ax = plt.subplots(1, 1, figsize=(10, 10))
    scatterplot = plot.patch(sns.scatterplot)
    _ax.set_title(f"Variational parameters - iter {iter}, epoch {epoch}")
    _ax.set_xlabel("x")
    _ax.set_ylabel("y")
    if curr_client.x.shape[-1] == 1:
        scatterplot(curr_client.x, curr_client.y, label=f"Training data - {curr_client.name}", ax=_ax)
    else:
        # Take PCA.
        U, S, V = torch.pca_lowrank(curr_client.x)
        proj_x = torch.matmul(curr_client.x, V[:, :1])
        scatterplot(proj_x, curr_client.y, label=f"Training data - {curr_client.name} (PCA)", ax=_ax)
    if curr_client.z.shape[-1] == 1:
        if curr_client.z.shape[0] == 1:
            df = pd.DataFrame({"x": curr_client.z.squeeze().item(), "y": curr_client.get_final_yz().squeeze().item()}, index=[0])
            scatterplot(data=df, x="x", y="y", label=f"Initial inducing points - {curr_client.name}", ax=_ax)
        else:
            scatterplot(curr_client.z, curr_client.get_final_yz(), label=f"Initial inducing points - {curr_client.name}", ax=_ax)
    else:
        # Take PCA.
        U, S, V = torch.pca_lowrank(curr_client.z)
        proj_z = torch.matmul(curr_client.z, V[:, :1])
        scatterplot(proj_z, curr_client.get_final_yz(), label=f"Initial inducing points - {curr_client.name} (PCA)", ax=_ax)

    plot.tweak(_ax)
    plt.savefig(os.path.join(_client_plot_dir, f"{iter}_{epoch}.png"), pad_inches=0.2, bbox_inches="tight")


def plot_all_inducing_pts(clients, _plot_dir):

    fig, _ax = plt.subplots(1, 1, figsize=(10, 10))
    scatterplot = plot.patch(sns.scatterplot)
    _ax.set_title(f"Inducing points and training data - all clients")
    _ax.set_xlabel("x")
    _ax.set_ylabel("y")
    for i, (name, c) in enumerate(clients.items()):
        scatterplot(c.x, c.y, label=f"Training data - {name}", ax=_ax)
        if c.z.shape[0] == 1:
            df = pd.DataFrame({"x": c.z.squeeze().item(), "y": c.get_final_yz().squeeze().item()}, index=[0])
            scatterplot(data=df, x="x", y="y", label=f"Initial inducing points - {name}", ax=_ax)
        else:
            scatterplot(c.z, c.get_final_yz(), label=f"Initial inducing points - {name}", ax=_ax)

    plot.tweak(_ax)
    plt.savefig(os.path.join(_plot_dir, "init_zs.png"), pad_inches=0.2, bbox_inches="tight")


def eval_logging(
    x,
    y,
    x_tr,
    y_tr,
    y_pred,
    error,
    pred_var,
    data_name,
    _results_dir,
    _fname,
    _plot_dir: str = None,
    ylim: Optional[Tuple[float, float]] = None,
    xlim: Optional[Tuple[float, float]] = None,
    save_metrics: bool = True,
    plot_samples: bool = True,
):
    """Logs the model inference results and saves plots

    Args:
        x (_type_): eval input locations
        y (_type_): eval labels
        x_tr (_type_): training data
        y_tr (_type_): training labels
        y_pred (_type_): model predictions (S x Dout)
        error (_type_): (y - y_pred)
        pred_var (_type_): y_pred.var
        data_name (str): type of (x,y) dataset, e.g. "test", "train", "eval", "all"
        _results_dir (_type_): results directory to save plots
        _fname (_type_): plot file name
        _plot (bool): save plot figure
    """
    _S = y_pred.shape[0]  # number of inference samples

    # Log test error and variance
    logger.info(f"{Color.WHITE}{data_name} error (RMSE): {round(error.item(), 3):3}, var: {round(y_pred.var().item(), 3):3}{Color.END}")

    if y_pred.device != y.device:
        y_pred = y_pred.to(y.device)

    # Save only 1D tensors
    if x.shape[-1] == 1:
        _results_eval = pd.DataFrame(
            {
                "x_eval": x.squeeze().detach().cpu(),
                "y_eval": y.squeeze().detach().cpu(),
                "pred_errors": (y - y_pred.mean(0)).squeeze().detach().cpu(),
                "pred_var": pred_var.squeeze().detach().cpu(),
                "y_pred_mean": y_pred.mean(0).squeeze().detach().cpu(),
            }
        )
    else:
        _results_eval = pd.DataFrame(
            {
                "y_eval": y.squeeze().detach().cpu(),
                "pred_errors": (y - y_pred.mean(0)).squeeze().detach().cpu(),
                "pred_var": pred_var.squeeze().detach().cpu(),
                "y_pred_mean": y_pred.mean(0).squeeze().detach().cpu(),
            }
        )
    for num_sample in range(_S):
        _results_eval[f"preds_{num_sample}"] = y_pred[num_sample].squeeze().detach().cpu()

    # Save model predictions
    if save_metrics:
        _results_eval.to_csv(os.path.join(_results_dir, f"model/{_fname}.csv"), index=False)

    # Plot model predictions:
    if x.shape[-1] == 1:
        # Plot training data and model predictions (in that order)
        scatterplot = plot.patch(sns.scatterplot)
        fig, _ax = plt.subplots(1, 1)
        scatterplot(y=y_tr, x=x_tr, label="Training data", ax=_ax)

        if ylim:
            _ax.set_ylim(ylim)
        if xlim:
            _ax.set_xlim(xlim)
        _ax.set_xlabel("x")
        _ax.set_ylabel("y")
        # _ax.set_title(f"Model predictions - ({_S} samples)")
        _ax.set_title(f"Predictive distribution")

        lineplot = plot.patch(sns.lineplot)
        lineplot(ax=_ax, y=y_pred.mean(0), x=x, label="Model predictions (μ)", color=gi.utils.plotting.colors[3])

        # Plot confidence bounds (1 and 2 std deviations)
        _preds_idx = [f"preds_{i}" for i in range(_S)]
        # [num quartiles x num preds]
        quartiles = np.quantile(_results_eval[_preds_idx], np.array((0.02275, 0.15865, 0.84135, 0.97725)), axis=1)
        _ax = plot_confidence(_ax, x.squeeze().detach().cpu(), quartiles, all=True)

        _ax.legend(loc="lower right", prop={"size": 9})

        plt.savefig(os.path.join(_plot_dir, f"{_fname}.png"), pad_inches=0.2, bbox_inches="tight")
        # plt.savefig(os.path.join(_plot_dir, f"{_fname}.png"))

        # Plot all sampled functions
        if plot_samples:
            ax = plot_predictions(None, x, y_pred, "Model predictions", "x", "y", f"Model predictions on {data_name.lower()} data ({_S} samples)", ylim=ylim, xlim=xlim)

            _sampled_funcs_dir = os.path.join(_plot_dir, "sampled_funcs")
            Path(_sampled_funcs_dir).mkdir(parents=True, exist_ok=True)
            plt.savefig(os.path.join(_sampled_funcs_dir, f"{_fname}_samples.png"), pad_inches=0.2, bbox_inches="tight")
