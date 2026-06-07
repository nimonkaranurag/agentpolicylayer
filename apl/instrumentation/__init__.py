from typing import List, Optional

from apl.layer import PolicyLayer
from apl.logging import console
from apl.types import CompositionConfig, FailMode

from .providers import PROVIDER_REGISTRY
from .state import InstrumentationState


def auto_instrument(
    policy_servers: List[str],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    custom_metadata: Optional[dict] = None,
    enabled_providers: Optional[List[str]] = None,
    fail_mode: FailMode = FailMode.CLOSED,
) -> InstrumentationState:
    console.print("\n[bold cyan]🛡️  APL Auto-Instrumentation[/bold cyan]\n")

    # fail_mode flows onto the layer's composition config; CompositionConfig
    # emits a startup warning if fail-open is chosen. The evaluator reads it back
    # so policy errors fail closed (deny) by default.
    policy_layer = PolicyLayer(composition=CompositionConfig(fail_mode=fail_mode))
    for server_uri in policy_servers:
        policy_layer.add_server(server_uri)
        console.print(f"  [green]✓[/green] Connected: [cyan]{server_uri}[/cyan]")

    state = InstrumentationState(
        policy_layer=policy_layer,
        session_id=session_id,
        user_id=user_id,
        custom_metadata=custom_metadata or {},
    )

    target_providers = enabled_providers or list(PROVIDER_REGISTRY.keys())

    for provider_name in target_providers:
        provider_class = PROVIDER_REGISTRY.get(provider_name)
        if provider_class is None:
            continue
        if not provider_class.is_available():
            continue

        provider_instance = provider_class(state)
        provider_instance.patch_all_methods()
        state.register_provider(provider_instance)
        console.print(
            f"  [green]✓[/green] Instrumented: [white]{provider_name}[/white]"
        )

    console.print("\n[bold green]  ✓ Complete[/bold green]\n")
    return state


def uninstrument(state: InstrumentationState) -> None:
    for provider in state.active_providers:
        provider.unpatch_all_methods()
    state.clear_providers()
    # Restoring the patches isn't enough — the sync bridge may have spun up a daemon
    # event loop; tear it down so uninstrument leaves no live thread behind (WP-6).
    state.shutdown_background_loop()
    console.print("[dim]APL instrumentation removed[/dim]")
