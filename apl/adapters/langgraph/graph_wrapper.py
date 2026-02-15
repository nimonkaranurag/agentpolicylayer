from typing import Any

from apl.layer import PolicyLayer
from apl.logging import get_logger
from apl.types import EventType

from .checkpoint import PolicyCheckpoint
from .node_wrapper import NodeWrapper

logger = get_logger("adapter.langgraph")

DEFAULT_CHECKPOINTS = [
    PolicyCheckpoint(EventType.INPUT_RECEIVED, before_node_execution=True),
    PolicyCheckpoint(EventType.TOOL_PRE_INVOKE, before_node_execution=True),
    PolicyCheckpoint(EventType.OUTPUT_PRE_SEND, before_node_execution=False),
]


class APLGraphWrapper:
    
    def __init__(self, policy_layer: PolicyLayer | None = None):
        self._layer = policy_layer or PolicyLayer()
        self._checkpoints: list[PolicyCheckpoint] = []

    def add_server(self, uri: str) -> "APLGraphWrapper":
        self._layer.add_server(uri)
        return self

    def add_checkpoint(
        self,
        event_type: str | EventType,
        node_name: str | None = None,
        before: bool = True,
    ) -> "APLGraphWrapper":
        if isinstance(event_type, str):
            event_type = EventType(event_type)

        self._checkpoints.append(
            PolicyCheckpoint(
                event_type=event_type,
                node_name=node_name,
                before_node_execution=before,
            )
        )
        return self

    def wrap(self, graph: Any) -> Any:
        if not hasattr(graph, "nodes") or not hasattr(graph, "add_node"):
            logger.warning("Object doesn't appear to be a LangGraph StateGraph")
            return graph

        checkpoints = self._checkpoints or DEFAULT_CHECKPOINTS
        node_wrapper = NodeWrapper(self._layer, checkpoints)

        original_nodes = dict(graph.nodes)

        for node_name, node_func in original_nodes.items():
            graph.nodes[node_name] = node_wrapper.wrap(node_name, node_func)

        logger.info(f"Wrapped {len(original_nodes)} nodes with APL policies")

        return graph
