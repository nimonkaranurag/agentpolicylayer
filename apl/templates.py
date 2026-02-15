"""
APL Project Templates

Templates for initializing new APL policy projects.

Usage:
    from apl.templates import create_policy_project

    project_path = create_policy_project("my-policy", template="basic")
"""

from __future__ import annotations

import os
from pathlib import Path

# =============================================================================
# TEMPLATES
# =============================================================================

TEMPLATES = {
    "basic": {
        "policy.py": '''#!/usr/bin/env python3
"""
{name} - APL Policy Server

A simple policy server template.

Run:
    apl serve policy.py
    apl serve policy.py --http 8080
"""

from apl import PolicyServer, Verdict, PolicyEvent

server = PolicyServer(
    name="{name}",
    version="1.0.0",
    description="A custom APL policy server"
)


@server.policy(
    name="example-policy",
    events=["output.pre_send"],
    context=["payload.output_text"],
    description="An example policy that allows everything"
)
async def example_policy(event: PolicyEvent) -> Verdict:
    """
    Example policy implementation.
    
    Modify this to implement your policy logic.
    """
    output = event.payload.output_text or ""
    
    # Example: Block responses containing "SECRET"
    if "SECRET" in output.upper():
        return Verdict.deny(
            reasoning="Response contains sensitive information",
            confidence=0.95
        )
    
    return Verdict.allow()


if __name__ == "__main__":
    server.run()
''',
        "policy.yaml": """# {name} - Declarative Policy
# 
# This is an alternative way to define policies using YAML.
# Run with: apl serve policy.yaml

name: {name}
version: 1.0.0
description: A declarative policy example

policies:
  - name: example-declarative
    events:
      - output.pre_send
    rules:
      - when:
          payload.output_text:
            contains: "SECRET"
        then:
          decision: deny
          reasoning: "Response contains sensitive information"
      
      - when:
          payload.output_text:
            matches: ".*"
        then:
          decision: allow
""",
        "README.md": """# {name}

An APL (Agent Policy Layer) policy server.

## Quick Start

```bash
# Run with stdio transport
apl serve policy.py

# Run with HTTP transport
apl serve policy.py --http 8080

# Run declarative policy
apl serve policy.yaml

# Test the policy
apl test policy.py
```

## Policy Structure

- `policy.py` - Python policy implementation
- `policy.yaml` - Declarative YAML policy (alternative)

## Learn More

- [APL Documentation](https://github.com/nimonkaranurag/agentpolicylayer)
- [Policy Examples](https://github.com/nimonkaranurag/agentpolicylayer/tree/main/examples)
""",
    },
    "pii": {
        "policy.py": '''#!/usr/bin/env python3
"""
{name} - PII Filter Policy

Detects and redacts Personally Identifiable Information (PII) from agent outputs.

Supported PII types:
- Social Security Numbers (SSN)
- Credit Card Numbers
- Email Addresses
- Phone Numbers
- IP Addresses

Run:
    apl serve policy.py --http 8080
"""

import re
from apl import PolicyServer, Verdict, PolicyEvent

server = PolicyServer(
    name="{name}",
    version="1.0.0",
    description="PII detection and redaction policy"
)

# PII Patterns
PATTERNS = {{
    "ssn": (r'\\b\\d{{3}}-\\d{{2}}-\\d{{4}}\\b', '[SSN REDACTED]'),
    "credit_card": (r'\\b\\d{{4}}[-\\s]?\\d{{4}}[-\\s]?\\d{{4}}[-\\s]?\\d{{4}}\\b', '[CC REDACTED]'),
    "email": (r'\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{{2,}}\\b', '[EMAIL REDACTED]'),
    "phone": (r'\\b\\d{{3}}[-.]?\\d{{3}}[-.]?\\d{{4}}\\b', '[PHONE REDACTED]'),
    "ip_address": (r'\\b\\d{{1,3}}\\.\\d{{1,3}}\\.\\d{{1,3}}\\.\\d{{1,3}}\\b', '[IP REDACTED]'),
}}


@server.policy(
    name="redact-pii-output",
    events=["output.pre_send"],
    context=["payload.output_text"],
    description="Redacts PII from agent output"
)
async def redact_pii_output(event: PolicyEvent) -> Verdict:
    """Scan output for PII and redact if found."""
    text = event.payload.output_text
    if not text:
        return Verdict.allow()
    
    found = []
    redacted = text
    
    for name, (pattern, replacement) in PATTERNS.items():
        matches = re.findall(pattern, redacted)
        if matches:
            found.append(f"{{name}}: {{len(matches)}}")
            redacted = re.sub(pattern, replacement, redacted)
    
    if found:
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted,
            reasoning=f"Redacted PII: {{', '.join(found)}}",
            confidence=0.95
        )
    
    return Verdict.allow()


@server.policy(
    name="block-pii-tools",
    events=["tool.pre_invoke"],
    context=["payload.tool_args"],
    description="Prevents PII from being sent to external tools"
)
async def block_pii_tools(event: PolicyEvent) -> Verdict:
    """Block tool calls that would send PII externally."""
    args_str = str(event.payload.tool_args or {{}})
    
    for name, (pattern, _) in PATTERNS.items():
        if re.search(pattern, args_str):
            return Verdict.deny(
                reasoning=f"Tool arguments contain {{name}} - refusing to send externally",
                confidence=0.9
            )
    
    return Verdict.allow()


if __name__ == "__main__":
    server.run()
''',
        "README.md": """# {name} - PII Filter

An APL policy that detects and redacts Personally Identifiable Information.

## Supported PII Types

- Social Security Numbers (SSN)
- Credit Card Numbers
- Email Addresses
- Phone Numbers
- IP Addresses

## Usage

```bash
apl serve policy.py --http 8080
```

## Testing

```bash
apl test policy.py
```
""",
    },
    "budget": {
        "policy.py": '''#!/usr/bin/env python3
"""
{name} - Budget Limiter Policy

Enforces token and cost budgets on agent sessions.

Run:
    apl serve policy.py --http 8080
"""

from apl import PolicyServer, Verdict, PolicyEvent

server = PolicyServer(
    name="{name}",
    version="1.0.0",
    description="Token and cost budget enforcement"
)

# Default limits
DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_COST_BUDGET = 1.00
WARNING_THRESHOLD = 0.8


@server.policy(
    name="token-budget",
    events=["llm.pre_request"],
    context=["metadata.token_count", "metadata.token_budget"],
    description="Enforces token limits"
)
async def token_budget(event: PolicyEvent) -> Verdict:
    """Check token budget before LLM calls."""
    count = event.metadata.token_count
    budget = event.metadata.token_budget or DEFAULT_TOKEN_BUDGET
    ratio = count / budget if budget > 0 else 0
    
    if ratio >= 1.0:
        return Verdict.deny(
            reasoning=f"Token budget exceeded: {{count:,}} / {{budget:,}}",
            confidence=1.0
        )
    
    if ratio >= WARNING_THRESHOLD:
        return Verdict.observe(
            reasoning=f"Token budget at {{ratio*100:.0f}}%",
            trace={{"token_count": count, "token_budget": budget}}
        )
    
    return Verdict.allow()


@server.policy(
    name="cost-budget",
    events=["llm.pre_request", "tool.pre_invoke"],
    context=["metadata.cost_usd", "metadata.cost_budget_usd"],
    description="Enforces cost limits"
)
async def cost_budget(event: PolicyEvent) -> Verdict:
    """Check cost budget."""
    cost = event.metadata.cost_usd
    budget = event.metadata.cost_budget_usd or DEFAULT_COST_BUDGET
    ratio = cost / budget if budget > 0 else 0
    
    if ratio >= 1.0:
        return Verdict.deny(
            reasoning=f"Cost budget exceeded: ${{cost:.4f}} / ${{budget:.2f}}",
            confidence=1.0
        )
    
    return Verdict.allow()


if __name__ == "__main__":
    server.run()
''',
        "README.md": """# {name} - Budget Limiter

An APL policy that enforces token and cost budgets.

## Configuration

Set budgets via session metadata:
- `token_budget`: Maximum tokens per session
- `cost_budget_usd`: Maximum cost in USD

## Usage

```bash
apl serve policy.py --http 8080
```
""",
    },
    "confirm": {
        "policy.py": '''#!/usr/bin/env python3
"""
{name} - Confirmation Policy

Requires human confirmation for dangerous operations.

Run:
    apl serve policy.py --http 8080
"""

import re
from apl import PolicyServer, Verdict, PolicyEvent

server = PolicyServer(
    name="{name}",
    version="1.0.0",
    description="Human confirmation for destructive operations"
)

DESTRUCTIVE_PATTERNS = [
    r".*delete.*",
    r".*remove.*",
    r".*drop.*",
    r".*destroy.*",
    r".*purge.*",
    r"rm\\b",
]


@server.policy(
    name="confirm-destructive",
    events=["tool.pre_invoke"],
    context=["payload.tool_name", "payload.tool_args"],
    description="Requires confirmation for destructive tools"
)
async def confirm_destructive(event: PolicyEvent) -> Verdict:
    """Check if tool is destructive and require confirmation."""
    tool_name = event.payload.tool_name or ""
    tool_args = event.payload.tool_args or {{}}
    
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.match(pattern, tool_name.lower()):
            target = tool_args.get("target") or tool_args.get("path") or str(tool_args)
            
            return Verdict.escalate(
                type="human_confirm",
                prompt=f"⚠️ Destructive action: {{tool_name}}\\n\\nTarget: {{target}}\\n\\nProceed?",
                options=["Proceed", "Cancel"],
                reasoning=f"Tool '{{tool_name}}' matches destructive pattern",
                timeout_ms=60000
            )
    
    return Verdict.allow()


if __name__ == "__main__":
    server.run()
''',
        "README.md": """# {name} - Confirmation Policy

An APL policy that requires human confirmation for destructive operations.

## Destructive Patterns

Tools matching these patterns require confirmation:
- delete, remove, drop, destroy, purge
- rm (shell command)

## Usage

```bash
apl serve policy.py --http 8080
```
""",
    },
}


# =============================================================================
# PROJECT CREATION
# =============================================================================


def create_policy_project(
    name: str, template: str = "basic"
) -> Path:
    """
    Create a new APL policy project.

    Args:
        name: Project name (used as directory name)
        template: Template to use (basic, pii, budget, confirm)

    Returns:
        Path to created project directory

    Raises:
        ValueError: If template doesn't exist
        FileExistsError: If directory already exists
    """
    if template not in TEMPLATES:
        raise ValueError(
            f"Unknown template: {template}. Available: {', '.join(TEMPLATES.keys())}"
        )

    project_path = Path(name)

    if project_path.exists():
        raise FileExistsError(
            f"Directory already exists: {name}"
        )

    project_path.mkdir(parents=True)

    template_files = TEMPLATES[template]

    for filename, content in template_files.items():
        file_path = project_path / filename
        file_path.write_text(content.format(name=name))

    # Make policy.py executable
    policy_py = project_path / "policy.py"
    if policy_py.exists():
        os.chmod(policy_py, 0o755)

    return project_path.absolute()
