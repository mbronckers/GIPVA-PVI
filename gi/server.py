from __future__ import annotations
from collections import defaultdict
import logging

import sys
import os

import torch

from gi.models.bnn import BaseBNN


file_dir = os.path.dirname(__file__)
_root_dir = os.path.abspath(os.path.join(file_dir, ".."))
sys.path.insert(0, os.path.abspath(_root_dir))

from gi import Client
from gi.gibnn import GIBNN

from experiments.utils.colors import Color

logger = logging.getLogger()


class Server:
    def __init__(self, clients: list[Client], model: BaseBNN):

        self.clients = clients

        self.model = model

        self.log = defaultdict(list)

        # Number of times communicated with clients. Once for factor collection, once for posterior sending => 2 * num clients to optimize in iteration
        self.communications: int = 0

        self.max_iters: int = None
        self.curr_iter: int = 0

        # List of all clients' names that have been optimized at least once.
        self.optimized_clients = set()

    def __iter__(self):
        return self

    def update_log(self, metrics: defaultdict):
        for k, v in metrics.items():
            self.log[k].append(v)

    def evaluate_performance(self):
        """Runs evaluation of the global (shared) model on training and test data."""
        with torch.no_grad():

            # Get performance metrics.
            train_metrics = self.model.performance_metrics(self.train_loader)
            test_metrics = self.model.performance_metrics(self.test_loader)
            error_key = self.model.error_metric
            logger.info(
                "SERVER - {} - iter [{:2}/{:2}] - {}train mll: {:8.3f}, train {}: {:8.4f}, test mll: {:8.3f}, test {}: {:8.4f}{}".format(
                    self.name,
                    self.curr_iter,
                    self.max_iters,
                    Color.BLUE,
                    train_metrics["mll"],
                    error_key,
                    train_metrics[error_key],
                    test_metrics["mll"],
                    error_key,
                    test_metrics[error_key],
                    Color.END,
                )
            )

            # Save metrics.
            self.log["communications"].append(self.communications)
            self.log["iteration"].append(self.curr_iter)

            train_metrics = {"train_" + k: v for k, v in train_metrics.items()}
            test_metrics = {"test_" + k: v for k, v in test_metrics.items()}

            metrics = {**train_metrics, **test_metrics}
            for k, v in metrics.items():
                self.log[k].append(v.item())

    def update_optimized_clients(self, clients):
        """Updates the list of optimized clients if not all clients have been seen yet."""

        if len(self.optimized_clients) != len(self.clients):
            self.optimized_clients.update([c.name for c in clients])


class SynchronousServer(Server):
    def __init__(self, clients: list[Client], model: GIBNN, iters: int):
        super().__init__(clients, model)
        self.name = "synchronous"

        self.max_iters = iters

    def __next__(self):
        logger.info(f"SERVER - {self.name} - iter [{self.curr_iter+1:2}/{self.max_iters}] - optimizing {list(self.clients.keys())}")

        # Increment communication counter: one for collection, one for sending out
        self.communications += 2 * len(self.clients.keys())

        return list(self.clients.values())


class SequentialServer(Server):
    def __init__(self, clients: list[Client], model: GIBNN, iters: int):
        super().__init__(clients, model)
        self.name = "sequential"
        self._idx = 0

        # Want to have equal number of posterior updates for same number of iterations.
        self.max_iters = iters * len(self.clients)

    def current_client(self):
        return self.clients[list(self.clients.keys())[self._idx]]

    def __next__(self):
        client = self.current_client()
        self._idx = (self._idx + 1) % len(self.clients)

        # Increment communication counter.
        self.communications += 2

        logger.info(f"SERVER - {self.name} - iter [{self.curr_iter+1:2}/{self.max_iters}] - optimizing {list(self.clients.keys())}")

        return [client]


class NewServer(Server):
    def __init__(self, clients: list[Client], model: GIBNN, iters: int):
        super().__init__(clients, model)
        self.name = "seq-sync"
        self._global_iter = 0
        self._idx = 0

        # Want to have equal number of posterior updates for same number of iterations.
        self.max_iters = len(self.clients) + (len(self.clients) - 1)

    def current_client(self):
        return self.clients[list(self.clients.keys())[self._idx]]

    def __next__(self):
        if self._global_iter < len(self.clients):
            client = self.current_client()
            self._idx = (self._idx + 1) % len(self.clients)

            # Increment communication counter.
            self.communications += 2

            logger.info(f"SERVER - {self.name} - iter [{self.curr_iter+1:2}/{self.max_iters}] - optimizing {list(self.clients.keys())}")

            # Increment global iteration counter.
            self._global_iter += 1

            return [client]
        else:
            return list(self.clients.values())
