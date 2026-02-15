from typing import Any

from apl.layer import PolicyLayer

from .checkpoint import PolicyCheckpoint
from .checkpoint_evaluator import CheckpointEvaluator
from .graph_wrapper import APLGraphWrapper
from .node_wrapper import NodeWrapper
from .state_extractor import LangGraphStateExtractor


def create_apl_graph(
    graph: Any, policy_servers: list[str]
) -> Any:
    wrapper = APLGraphWrapper()
    for uri in policy_servers:
        wrapper.add_server(uri)
    return wrapper.wrap(graph)


__all__ = [
    "APLGraphWrapper",
    "PolicyCheckpoint",
    "CheckpointEvaluator",
    "NodeWrapper",
    "LangGraphStateExtractor",
    "create_apl_graph",
]
