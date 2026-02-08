"""
APL Framework Adapters

Pre-built adapters for popular agent frameworks:
- LangGraph: Wrap StateGraph with policy checkpoints
- AutoGen: (Coming soon)
- CrewAI: (Coming soon)

Usage:
    from apl.adapters.langgraph import APLGraphWrapper

    wrapper = APLGraphWrapper()
    wrapper.add_server("stdio://./my_policy.py")
    wrapped_graph = wrapper.wrap(my_graph)
"""

from .langgraph import APLGraphWrapper, create_apl_graph

__all__ = ["APLGraphWrapper", "create_apl_graph"]
