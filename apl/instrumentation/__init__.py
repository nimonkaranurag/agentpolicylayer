from typing import List, Optional

from apl.layer import PolicyLayer
from apl.logging import console

from .providers import PROVIDER_REGISTRY
from .state import InstrumentationState


def auto_instrument(
    policy_servers: List[str],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    custom_metadata: Optional[dict] = None,
    enabled_providers: Optional[List[str]] = None,
) -> InstrumentationState:
    console.print(
        "\n[bold cyan]🛡️  APL Auto-Instrumentation[/bold cyan]\n"
    )

    policy_layer = PolicyLayer()
    for server_uri in policy_servers:
        policy_layer.add_server(server_uri)
        console.print(
            f"  [green]✓[/green] Connected: [cyan]{server_uri}[/cyan]"
        )

    state = InstrumentationState(
        policy_layer=policy_layer,
        session_id=session_id,
        user_id=user_id,
        custom_metadata=custom_metadata or {},
    )

    target_providers = enabled_providers or list(
        PROVIDER_REGISTRY.keys()
    )

    for provider_name in target_providers:
        provider_class = PROVIDER_REGISTRY.get(
            provider_name
        )
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

    console.print(
        "\n[bold green]  ✓ Complete[/bold green]\n"
    )
    return state


def uninstrument(state: InstrumentationState) -> None:
    for provider in state.active_providers:
        provider.unpatch_all_methods()
    state.clear_providers()
    console.print("[dim]APL instrumentation removed[/dim]")
