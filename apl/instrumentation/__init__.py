from contextlib import contextmanager
from typing import Iterator, List, Optional

from apl.layer import PolicyLayer
from apl.logging import get_logger
from apl.types import CompositionConfig, FailMode

from .providers import PROVIDER_REGISTRY
from .state import InstrumentationState

logger = get_logger("instrumentation")

# The currently-active instrumentation, if any. SDK methods are patched on the
# *class*, so instrumentation is process-global: a second auto_instrument() with a
# different layer would find every method already patched, install nothing, and
# silently keep the first layer — while logging success. We refuse that instead.
_ACTIVE_STATE: Optional[InstrumentationState] = None


def auto_instrument(
    policy_servers: List[str],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    custom_metadata: Optional[dict] = None,
    enabled_providers: Optional[List[str]] = None,
    fail_mode: FailMode = FailMode.CLOSED,
) -> InstrumentationState:
    """
    Monkeypatch supported LLM SDKs so APL policies run around every call.

    Progress is logged (quietly), never printed: a library that writes to stdout on
    import/setup corrupts CLIs and JSON consumers. Call ``apl.logging.setup_logging``
    (or configure the ``apl`` logger) to surface these messages.

    Returns the :class:`InstrumentationState`; pass it to :func:`uninstrument` to
    restore the original methods, or use the :func:`instrument` context manager.

    Raises:
        RuntimeError: if APL is already instrumented. The SDK methods are patched on
            the class (process-global), so a second call would no-op silently; call
            :func:`uninstrument` first to re-point at a different layer.
    """
    global _ACTIVE_STATE
    if _ACTIVE_STATE is not None:
        raise RuntimeError(
            "APL is already instrumented. Call uninstrument() before instrumenting "
            "again — a second auto_instrument() would silently no-op (the SDK "
            "methods are already patched) and keep the first policy layer."
        )

    # fail_mode flows onto the layer's composition config; CompositionConfig
    # emits a startup warning if fail-open is chosen. The evaluator reads it back
    # so policy errors fail closed (deny) by default.
    policy_layer = PolicyLayer(composition=CompositionConfig(fail_mode=fail_mode))
    for server_uri in policy_servers:
        # add_server is lazy: it registers the server, it does not connect (the
        # old "✓ Connected" message was misleading).
        policy_layer.add_server(server_uri)
    logger.debug(f"Registered {len(policy_servers)} policy server(s)")

    state = InstrumentationState(
        policy_layer=policy_layer,
        session_id=session_id,
        user_id=user_id,
        custom_metadata=custom_metadata or {},
    )

    target_providers = enabled_providers or list(PROVIDER_REGISTRY.keys())

    instrumented: list[str] = []
    for provider_name in target_providers:
        provider_class = PROVIDER_REGISTRY.get(provider_name)
        if provider_class is None:
            continue
        if not provider_class.is_available():
            continue

        provider_instance = provider_class(state)
        provider_instance.patch_all_methods()
        state.register_provider(provider_instance)
        instrumented.append(provider_name)

    if instrumented:
        logger.info(f"Auto-instrumented providers: {', '.join(instrumented)}")
    else:
        # Patching nothing is almost always a misconfiguration (SDK not
        # installed / wrong name), so say so loudly rather than silently.
        logger.warning(
            "Auto-instrumentation enabled but no supported provider SDKs were "
            "found to patch."
        )

    _ACTIVE_STATE = state
    return state


def uninstrument(state: InstrumentationState) -> None:
    """
    Restore everything :func:`auto_instrument` patched and free its resources.
    """
    global _ACTIVE_STATE

    for provider in state.active_providers:
        provider.unpatch_all_methods()
    state.clear_providers()
    # Close the policy layer (stdio subprocesses, aiohttp sessions) *before* the
    # background loop is gone — close() is async and runs on that loop. Restoring
    # the patches alone left those subprocesses/sessions orphaned.
    state.close_policy_layer()
    # The sync bridge may have spun up a daemon event loop; tear it down so
    # uninstrument leaves no live thread behind.
    state.shutdown_background_loop()

    if _ACTIVE_STATE is state:
        _ACTIVE_STATE = None
    logger.info("APL instrumentation removed")


@contextmanager
def instrument(
    policy_servers: List[str],
    **kwargs,
) -> Iterator[InstrumentationState]:
    """
    Context-manager form of :func:`auto_instrument`.

    Instruments on entry and always restores the original SDK methods on exit,
    even if the body raises. Accepts the same keyword arguments as
    :func:`auto_instrument` (``session_id``, ``user_id``, ``custom_metadata``,
    ``enabled_providers``, ``fail_mode``).

    Example:
        with apl.instrument(["stdio://./policies.py"]):
            client.chat.completions.create(...)
    """
    state = auto_instrument(policy_servers, **kwargs)
    try:
        yield state
    finally:
        uninstrument(state)
