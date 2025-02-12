import os
from typing import Optional, Tuple
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import logging
from pathlib import Path

from torch import Tensor

from wbml import plot

colors = sns.color_palette("bright")
sns.set_style("whitegrid")
sns.set_palette(colors)
# matplotlib.rcParams["figure.dpi"] = 500  # for high quality, retina plots
# matplotlib.use("Agg")


def scatter_plot(
    ax,
    x1: Tensor,
    y1: Tensor,
    x2: Tensor,
    y2: Tensor,
    desc1: str,
    desc2: str,
    xlabel: Optional[str] = None,
    ylabel: Optional[str] = None,
    title: Optional[str] = None,
    ylim: Optional[Tuple[float, float]] = None,
    xlim: Optional[Tuple[float, float]] = None,
):

    if ax == None:
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))

    scatterplot = plot.patch(sns.scatterplot)
    scatterplot(y=y1, x=x1, label=desc1, ax=ax)
    scatterplot(y=y2, x=x2, label=desc2, ax=ax)

    if ylim != None:
        ax.set_ylim(ylim)
    if xlim != None:
        ax.set_xlim(xlim)
    if xlabel != None:
        ax.set_xlabel(xlabel)
    if ylabel != None:
        ax.set_ylabel(ylabel)
    if title != None:
        ax.set_title(title)
    ax.legend(loc="lower right", prop={"size": 9})

    plot.tweak(ax)

    return ax


def plot_predictions(
    ax,
    x: Tensor,
    y: Tensor,
    desc: str,
    xlabel: Optional[str] = None,
    ylabel: Optional[str] = None,
    title: Optional[str] = None,
    ylim: Optional[Tuple[float, float]] = None,
    xlim: Optional[Tuple[float, float]] = None,
):

    if ax == None:
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))

    lineplot = plot.patch(sns.lineplot)
    if len(y.shape) == 3:
        for i in range(y.shape[0]):
            lineplot(y=y[i], x=x, ax=ax, color=colors[0], alpha=0.3)
    else:
        lineplot(y=y, x=x, ax=ax, color=colors[0], alpha=0.3)

    if ylim != None:
        ax.set_ylim(ylim)
    if xlim != None:
        ax.set_xlim(xlim)
    if xlabel != None:
        ax.set_xlabel(xlabel)
    if ylabel != None:
        ax.set_ylabel(ylabel)
    if title != None:
        ax.set_title(title)

    plot.tweak(ax)

    return ax


def plot_confidence(ax, x, quartiles, all: bool = False):
    assert len(quartiles) == 4  # [num quartiles x num preds]
    if x.is_cuda:
        x = x.detach().cpu()

    x_sorted, q0, q1, q2, q3 = zip(*sorted(zip(x, quartiles[0, :], quartiles[1, :], quartiles[2, :], quartiles[3, :])))

    if all:
        ax.fill_between(x_sorted, q0, q3, color=colors[7], alpha=0.20, label="μ ± 2σ")
    ax.fill_between(x_sorted, q1, q2, color=colors[1], alpha=0.20, label="μ ± σ")

    return ax


def line_plot(x, y, desc, xlabel=None, ylabel=None, title=None, ylim: Optional[Tuple[float, float]] = None, xlim: Optional[Tuple[float, float]] = None):

    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    lw = 2  # linewidth=lw

    sns.lineplot(y=y, x=x, label=f"{desc}", ax=ax, color=colors[0])

    if ylim != None:
        ax.set_ylim(ylim)
    if xlim != None:
        ax.set_xlim(xlim)
    if xlabel != None:
        ax.set_xlabel(xlabel)
    if ylabel != None:
        ax.set_ylabel(ylabel)
    if title != None:
        ax.set_title(title)
    ax.legend(loc="lower right", prop={"size": 9})

    plot.tweak(ax)

    return ax
