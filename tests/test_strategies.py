from logging import getLogger
from pathlib import Path

import numpy as np
import pytest

from connectlib import execute_experiment
from connectlib.algorithms import Algo
from connectlib.dependency import Dependency
from connectlib.evaluation_strategy import EvaluationStrategy
from connectlib.nodes import AggregationNode
from connectlib.nodes import TestDataNode
from connectlib.nodes import TrainDataNode
from connectlib.remote import remote_data
from connectlib.strategies import FedAVG

from . import assets_factory
from . import utils

logger = getLogger("tests")


@pytest.mark.slow
@pytest.mark.substra
def test_fed_avg(network, constant_samples, numpy_datasets, session_dir, default_permissions):
    # makes sure that federated average strategy leads to the averaging output of the models from both partners.
    # The data for the two partners consists of only 0s or 1s respectively. The train() returns the data.
    # predict() returns the data, score returned by AccuracyMetric (in the metric) is the mean of all the y_pred
    # passed to it. The tests asserts if the score is 0.5
    # This test only runs on two nodes.

    class MyAlgo(Algo):
        # this class must be within the test, otherwise the Docker will not find it correctly (ie because of the way
        # pytest calls it)

        @remote_data
        def train(
            self,
            x: np.ndarray,
            y: np.ndarray,
            shared_state,
        ):
            return dict(test=x, n_samples=len(x))

        @remote_data
        def predict(self, x: np.array, shared_state):
            return shared_state["test"]

        def load(self, path: Path):
            return self

        def save(self, path: Path):
            assert path.parent.exists()
            with path.open("w") as f:
                f.write("test")

    # Add 0s and 1s constant to check the averaging of the function
    # We predict the shared state, an array of 0.5

    metric = assets_factory.add_python_metric(
        client=network.clients[0],
        tmp_folder=session_dir,
        python_formula="int((y_pred == np.ones(1)*0.5).all())",  # Check that all shared states values are 0.5
        name="Average",
        permissions=default_permissions,
    )
    train_data_nodes = [
        TrainDataNode(network.msp_ids[0], numpy_datasets[0], [constant_samples[0]]),
        TrainDataNode(network.msp_ids[1], numpy_datasets[1], [constant_samples[1]]),
    ]

    test_data_nodes = [
        TestDataNode(
            network.msp_ids[0],
            numpy_datasets[0],
            [constant_samples[0]],
            metric_keys=[metric],
        ),
        TestDataNode(
            network.msp_ids[1],
            numpy_datasets[1],
            [constant_samples[1]],
            metric_keys=[metric],
        ),
    ]

    num_rounds = 2
    # TODO For now, num_rounds is passed to both algorithm and
    # execute_experiment because of the way the indexer works. It is to be refactored as
    # a generator with a fixed seed.
    aggregation_node = AggregationNode(network.msp_ids[0])
    my_algo0 = MyAlgo()
    algo_deps = Dependency(pypi_dependencies=["pytest"], editable_mode=True)
    strategy = FedAVG()
    # test every two rounds
    my_eval_strategy = EvaluationStrategy(test_data_nodes=test_data_nodes, rounds=2)
    compute_plan = execute_experiment(
        client=network.clients[0],
        algo=my_algo0,
        strategy=strategy,
        train_data_nodes=train_data_nodes,
        evaluation_strategy=my_eval_strategy,
        aggregation_node=aggregation_node,
        num_rounds=num_rounds,
        dependencies=algo_deps,
    )
    # Wait for the compute plan to be finished
    utils.wait(network.clients[0], compute_plan)

    # read the results from saved performances
    testtuples = network.clients[0].list_testtuple(filters=[f"testtuple:compute_plan_key:{compute_plan.key}"])
    testtuple = testtuples[0]
    # assert that the metrics returns int(True) i.e. 1
    assert list(testtuple.test.perfs.values())[0] == 1
