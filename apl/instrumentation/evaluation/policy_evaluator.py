from typing import TYPE_CHECKING

from apl.layer import PolicyDenied, PolicyEscalation
from apl.logging import get_logger
from apl.types import FailMode, Verdict

from ..events.base_event import BaseEvent
from ..lifecycle.context import LifecycleContext

if TYPE_CHECKING:
    from ..state import InstrumentationState

logger = get_logger("instrumentation.evaluator")


class PolicyEvaluator:
    def __init__(self, state: "InstrumentationState"):
        self.state = state

    async def evaluate_event_async(
        self,
        event: BaseEvent,
        context: LifecycleContext,
    ) -> Verdict:
        self.state.mark_policy_evaluation_started()
        try:
            payload = event.build_payload(context)
            return await self.state.policy_layer.evaluate(
                event_type=event.event_type,
                messages=context.apl_messages,
                payload=payload,
                metadata=self.state.session_metadata,
            )
        except (PolicyDenied, PolicyEscalation):
            raise
        except Exception as exc:
            logger.error(
                f"Policy evaluation failed for {event.event_type.value}: {exc}",
                exc_info=True,
            )
            return Verdict.unavailable(
                self._fail_mode,
                reasoning=f"Policy evaluation failed: {exc}",
            )
        finally:
            self.state.mark_policy_evaluation_finished()

    @property
    def _fail_mode(self) -> FailMode:
        # Honour the fail mode configured on the policy layer (set via
        # auto_instrument / CompositionConfig); default to fail-closed if the
        # collaborator doesn't expose one. Reads the public PolicyLayer.fail_mode
        # property instead of reaching into the private composition config.
        return getattr(self.state.policy_layer, "fail_mode", FailMode.CLOSED)

    def evaluate_event_sync(
        self,
        event: BaseEvent,
        context: LifecycleContext,
    ) -> Verdict:
        coroutine = self.evaluate_event_async(event, context)
        return self.state.run_coroutine_in_background_loop(coroutine)
