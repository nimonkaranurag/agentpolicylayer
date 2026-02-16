"""
APL - Agent Policy Layer

Portable, composable policies for AI agents.

╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     █████╗ ██████╗ ██╗         Agent Policy Layer         ║
║    ██╔══██╗██╔══██╗██║                                    ║
║    ███████║██████╔╝██║         🛡️  Secure by Default       ║
║    ██╔══██║██╔═══╝ ██║         ⚡ Fast & Composable        ║
║    ██║  ██║██║     ███████╗    🔌 Runtime Agnostic         ║
║    ╚═╝  ╚═╝╚═╝     ╚══════╝                               ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

Quick Start - Policy Server (~20 lines):

    from apl import PolicyServer, Verdict

    server = PolicyServer("my-policies")

    @server.policy(
        name="my-policy",
        events=["output.pre_send"],
        context=["payload.output_text"]
    )
    async def my_policy(event):
        if "SECRET" in (event.payload.output_text or ""):
            return Verdict.deny(reasoning="Contains secret")
        return Verdict.allow()

    if __name__ == "__main__":
        server.run()

Quick Start - Connect to Agent:

    from apl import PolicyLayer

    policies = PolicyLayer()
    policies.add_server("stdio://./my_policy.py")
    policies.add_server("https://policies.corp.com/compliance")

    verdict = await policies.evaluate(
        event_type="output.pre_send",
        payload=EventPayload(output_text="Hello world"),
    )

CLI:

    apl serve ./my_policy.py              # Run policy server
    apl serve ./my_policy.py --http 8080  # Run with HTTP transport
    apl test ./my_policy.py               # Test with sample events
    apl init my-policy                    # Create new policy project
    apl info                              # Show system info

Documentation: https://github.com/nimonkaranurag/agentpolicylayer
"""

__version__ = "0.2.0"

# =============================================================================
# CORE TYPES
# =============================================================================

from .composition import VerdictComposer
from .declarative_engine import (
    load_yaml_policy,
    validate_yaml_policy,
)
from .instrumentation import (
    auto_instrument,
    uninstrument,
)
from .layer import (
    PolicyClient,
    PolicyDenied,
    PolicyEscalation,
    PolicyLayer,
)
from .logging import (
    APLLogger,
    get_logger,
    setup_logging,
)
from .serialization import (
    EventSerializer,
    VerdictSerializer,
)
from .server import PolicyServer
from .types import (  # Events; Context (chat/completions compatible); Verdicts; Definitions; Composition
    CompositionConfig,
    CompositionMode,
    ContextRequirement,
    Decision,
    Escalation,
    EventPayload,
    EventType,
    FunctionCall,
    Message,
    Modification,
    PolicyDefinition,
    PolicyEvent,
    PolicyManifest,
    SessionMetadata,
    ToolCall,
    Verdict,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "PolicyServer",
    "PolicyLayer",
    "PolicyClient",
    # Event Types
    "EventType",
    "PolicyEvent",
    "EventPayload",
    # Context (chat/completions format)
    "Message",
    "ToolCall",
    "FunctionCall",
    "SessionMetadata",
    # Verdicts
    "Verdict",
    "Decision",
    "Modification",
    "Escalation",
    # Definitions
    "PolicyDefinition",
    "PolicyManifest",
    "ContextRequirement",
    # Composition
    "CompositionMode",
    "CompositionConfig",
    "VerdictComposer",
    # Exceptions
    "PolicyDenied",
    "PolicyEscalation",
    # Declarative
    "load_yaml_policy",
    "validate_yaml_policy",
    # Logging
    "setup_logging",
    "get_logger",
    "APLLogger",
    # Auto-instrumentation
    "auto_instrument",
    "uninstrument",
    "EventSerializer",
    "VerdictSerializer",
]
