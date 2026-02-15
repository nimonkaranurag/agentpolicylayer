from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apl.layer import PolicyLayer


class BaseFrameworkAdapter(ABC):
    
    def __init__(self, policy_layer: "PolicyLayer"):
        self._policy_layer = policy_layer

    @property
    def policy_layer(self) -> "PolicyLayer":
        return self._policy_layer

    @property
    @abstractmethod
    def framework_name(self) -> str: ...

    @staticmethod
    @abstractmethod
    def is_available() -> bool: ...

    @abstractmethod
    def wrap(self, agent: Any) -> Any: ...
