# Your AI Agent Has No Guardrails. Here's How to Fix That in 30 Lines of Python.

*A practical guide to adding runtime policy enforcement to LLM agents — using IBM watsonx.ai as the example, but applicable to any provider.*

---

## The Problem No One Talks About

You built an AI agent. It calls an LLM, uses tools, answers user questions. It works great in your demo. Then you deploy it.

Within the first week, your agent:

- Returns a customer's full SSN and credit card number in a chat response
- Burns through $400 in API tokens because a retry loop went haywire
- Silently drops a staging database because a user said "clean up the old stuff"

These aren't hypothetical. They're the top three categories of production agent incidents I hear about from teams running LLM-powered systems today.

The root cause? **There is no policy layer between your agent and the real world.** The LLM generates text, the framework executes it, and whatever happens, happens. There are no guardrails at runtime.

Prompt engineering doesn't solve this. The LLM can always be jailbroken, confused, or simply wrong. You need enforcement *outside* the model.

---

## Introducing APL — Agent Policy Layer

APL is a lightweight, open-source framework that sits between your agent and its inputs/outputs. Think of it like a firewall for AI agents:


User Query → [APL: pre-request policies] → LLM Call → [APL: post-response policies] → User
↓
[APL: tool policies] → Tool Execution

**Key design decisions:**

- **Framework-agnostic.** Works with OpenAI, Anthropic, LiteLLM, LangChain, IBM watsonx.ai — no lock-in.
- **Zero agent code changes.** APL auto-instruments your LLM client. You don't touch your agent.
- **~30 lines per policy.** Policies are small, focused Python functions.
- **Five verdict types.** Not just allow/deny — policies can also MODIFY outputs, ESCALATE to a human, or silently OBSERVE.
- **Composable.** Stack multiple policies. They run independently and APL composes their verdicts.

Let me show you exactly how it works.

---

## Setup

We'll use IBM watsonx.ai with the `ModelInference.chat()` endpoint throughout this article, but everything here applies identically to OpenAI, Anthropic, or any other provider APL supports.

```bash
pip install agent-policy-layer ibm-watsonx-ai rich

from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference

model = ModelInference(
    model_id="ibm/granite-3-8b-instruct",
    credentials=Credentials(url="https://us-south.ml.cloud.ibm.com",
                            api_key="YOUR_API_KEY"),
    project_id="YOUR_PROJECT_ID",
)

response = model.chat(
    messages=[{"role": "user", "content": "Hello, how are you?"}]
)

print(response["choices"][0]["message"]["content"])

The .chat() method returns an OpenAI-compatible dict — that's important because it means APL can instrument it with zero adapter code.
Part 1: The Problem — No Guardrails
Here's the scenario. Your agent has access to a customer database. A user asks:
User: "Show me the full customer record for Jane Doe."
And your agent happily responds:
Here are the customer details you requested:

  Name:         Jane Doe
  Email:        jane.doe@acme-corp.com
  Phone:        415-555-0198
  SSN:          329-41-8703
  Credit Card:  4532-7153-2891-0044  (Visa, exp 09/27)

Let me know if you need anything else!

<!-- SCREENSHOT: Run the demo script and capture the Part 1 output showing the red "UNPROTECTED" panel with PII visible. -->
That's a compliance violation, a potential lawsuit, and a front-page headline. The LLM doesn't know it shouldn't return this data. You told it to be helpful, and it was.
The same problem shows up with infrastructure data:
User: "Give me the infrastructure summary with server IPs."
Production DB:   db-prod-01  at 10.200.3.47   (PostgreSQL 16)
Staging DB:      db-stage-01 at 192.168.5.112  (PostgreSQL 16)
Redis Cache:     cache-01    at 10.200.3.52    (Redis 7.2)
Admin Portal:    admin.acme-corp.com → 52.14.92.210

<!-- SCREENSHOT: Capture the infrastructure response in the red panel. -->
Internal IPs, network topology, software versions — everything an attacker needs to map your private network.
Part 2: PII Filter — Automatic Redaction in 30 Lines
Here's the entire PII filter policy. This is a real, working policy server:
# policies/pii_filter.py

from apl import PolicyServer, PolicyEvent, Verdict
import re

server = PolicyServer("pii-filter", version="1.0.0")

PATTERNS = {
    "ssn":         (r"\b\d{3}-\d{2}-\d{4}\b",                           "[SSN REDACTED]"),
    "credit_card": (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",     "[CC REDACTED]"),
    "email":       (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL REDACTED]"),
    "phone_us":    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",              "[PHONE REDACTED]"),
    "ip_address":  (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",        "[IP REDACTED]"),
}

@server.policy(
    name="redact-pii",
    events=["output.pre_send"],
    context=["payload.output_text"],
)
async def redact_pii(event: PolicyEvent) -> Verdict:
    text = event.payload.output_text
    if not text:
        return Verdict.allow()

    found, redacted = [], text
    for name, (pattern, replacement) in PATTERNS.items():
        matches = re.findall(pattern, redacted)
        if matches:
            found.append(f"{name}: {len(matches)}")
            redacted = re.sub(pattern, replacement, redacted)

    if found:
        return Verdict.modify(
            target="output", operation="replace", value=redacted,
            reasoning=f"Redacted PII: {', '.join(found)}",
        )
    return Verdict.allow()

if __name__ == "__main__":
    server.run()

<!-- SCREENSHOT: The policy code above, clean and readable. -->
Let's break down what's happening:
@server.policy(events=["output.pre_send"]) — This policy fires after the LLM responds but before the output reaches the user. It subscribes to the output.pre_send lifecycle event.
Verdict.modify(target="output", value=redacted) — Instead of blocking the response entirely, the policy rewrites it. The user still gets a useful answer — just with PII scrubbed.
Verdict.allow() — If no PII is found, the response passes through unchanged. No false positives.
Connecting it to your agent
You have two options:
Option A: Auto-instrumentation (zero code changes)
import apl

apl.auto_instrument(
    policy_servers=["stdio://./policies/pii_filter.py"]
)

# Your existing agent code — completely unchanged
from ibm_watsonx_ai.foundation_models import ModelInference

model = ModelInference(model_id="ibm/granite-3-8b-instruct", ...)
response = model.chat(messages=[{"role": "user", "content": query}])
#                     ^^^^^^^^
#                     APL intercepts this call automatically

Option B: Explicit evaluation (more control)
from apl import PolicyLayer, EventPayload

policies = PolicyLayer()
policies.add_server("stdio://./policies/pii_filter.py")

# After getting the LLM response...
verdict = await policies.evaluate(
    event_type="output.pre_send",
    payload=EventPayload(output_text=response_text),
)

if verdict.decision == "modify":
    response_text = verdict.modification.value

The result
Same user query, same LLM, same agent code — but now the output looks like this:
Here are the customer details you requested:

  Name:         Jane Doe
  Email:        [EMAIL REDACTED]
  Phone:        [PHONE REDACTED]
  SSN:          [SSN REDACTED]
  Credit Card:  [CC REDACTED]  (Visa, exp 09/27)

Let me know if you need anything else!

<!-- SCREENSHOT: Capture the green "PROTECTED" panel from the demo, with the verdict table showing MODIFY above it. -->
The policy verdict tells you exactly what it found and what it changed:
Field	Value
Decision	MODIFY
Reasoning	Redacted PII: ssn: 1, credit_card: 1, email: 1, phone_us: 1
Policy	redact-pii
Target	output
Part 3: Budget Limiter — Stopping Runaway Sessions
PII is one class of problem. Another is cost. LLM API calls cost money, and a single runaway loop can burn through your monthly budget in minutes.
The budget limiter policy fires before the LLM call:
# policies/budget_limiter.py

from apl import PolicyServer, PolicyEvent, Verdict

server = PolicyServer("budget-limiter", version="1.0.0")

@server.policy(
    name="token-budget",
    events=["llm.pre_request"],
    context=["metadata.token_count", "metadata.token_budget"],
)
async def check_token_budget(event: PolicyEvent) -> Verdict:
    used   = event.metadata.token_count
    budget = event.metadata.token_budget or 100_000
    ratio  = used / budget if budget > 0 else 0

    if ratio >= 1.0:
        return Verdict.deny(
            reasoning=f"Token budget exceeded: {used:,} / {budget:,} tokens used",
        )
    if ratio >= 0.8:
        return Verdict.observe(
            reasoning=f"Warning: {budget - used:,} tokens remaining",
        )
    return Verdict.allow()

if __name__ == "__main__":
    server.run()

<!-- SCREENSHOT: The budget limiter code. -->
Notice the three tiers:
Under 80% → ALLOW — no intervention
80–100% → OBSERVE — log a warning, let it proceed
Over 100% → DENY — block the call entirely
When the session hits its limit:
┌──────────────┬──────────────────────────────────────────────────────┐
│ Decision     │ DENY                                                 │
│ Reasoning    │ Token budget exceeded: 102,000 / 100,000 tokens used │
│ Policy       │ token-budget                                         │
└──────────────┴──────────────────────────────────────────────────────┘

<!-- SCREENSHOT: Capture Part 3, Scenario B from the demo showing the DENY verdict in red. -->
The LLM call never happens. APL raises a PolicyDenied exception that your agent can catch and handle gracefully — e.g., by telling the user their session limit has been reached.
Part 4: Confirm Destructive — Human-in-the-Loop
The scariest agent failures aren't data leaks — they're actions. An agent with tool access can delete databases, send emails, modify infrastructure. One wrong tool call and you have a production incident.
The confirm-destructive policy intercepts tool calls before execution:
# policies/confirm_destructive.py

from apl import PolicyServer, PolicyEvent, Verdict
import re

server = PolicyServer("confirm-destructive", version="1.0.0")

DESTRUCTIVE_TOOLS = [
    r".*delete.*", r".*remove.*", r".*drop.*",
    r".*destroy.*", r".*purge.*", r".*truncate.*",
]

@server.policy(
    name="confirm-delete",
    events=["tool.pre_invoke"],
    context=["payload.tool_name", "payload.tool_args"],
)
async def confirm_delete(event: PolicyEvent) -> Verdict:
    tool_name = event.payload.tool_name or ""
    tool_args = event.payload.tool_args or {}

    for pattern in DESTRUCTIVE_TOOLS:
        if re.match(pattern, tool_name.lower()):
            target = tool_args.get("target") or tool_args.get("path") or str(tool_args)
            return Verdict.escalate(
                type="human_confirm",
                prompt=f"Destructive action: {tool_name} on '{target}'",
                reasoning=f"Tool '{tool_name}' is destructive",
                options=["Proceed", "Cancel"],
            )
    return Verdict.allow()

if __name__ == "__main__":
    server.run()

<!-- SCREENSHOT: The confirm-destructive code. -->
When the agent tries to execute delete_database, remove_storage, or drop_table, APL returns an ESCALATE verdict instead of letting the call proceed:
┌──────────────┬─────────────────────────────────────────────────────────┐
│ Decision     │ ESCALATE                                                │
│ Reasoning    │ Tool 'delete_database' is destructive                   │
│ Policy       │ confirm-delete                                          │
│ Escalation   │ Destructive action: delete_database on 'staging_orders' │
└──────────────┴─────────────────────────────────────────────────────────┘

<!-- SCREENSHOT: Capture Part 4 from the demo, showing all four ESCALATE verdicts stacked vertically. -->
Your application receives a PolicyEscalation exception with the prompt text and options. You can surface this to the user as a confirmation dialog, send it to a Slack channel for approval, or route it through whatever approval workflow your org uses.
The critical point: the tool never executes until a human says yes.
The Architecture
Here's what the full lifecycle looks like with all three policies active:
                        ┌───────────────────────────────┐
                        │   budget-limiter               │
                        │   event: llm.pre_request       │
  User Query            │   verdict: ALLOW / DENY        │
       │                └───────────┬───────────────────┘
       ▼                            │
  ┌─────────────┐          if ALLOW ▼
  │  APL Layer  │ ──────────► LLM Call (watsonx.ai)
  └─────────────┘                   │
       │                            ▼
       │                ┌───────────────────────────────┐
       │                │   pii-filter                   │
       │                │   event: output.pre_send       │
       │                │   verdict: ALLOW / MODIFY      │
       │                └───────────┬───────────────────┘
       │                            │
       │                   if MODIFY ▼ (rewritten output)
       │                ┌───────────────────────────────┐
       ▼                │   confirm-destructive          │
   User Response        │   event: tool.pre_invoke       │
                        │   verdict: ALLOW / ESCALATE    │
                        └───────────────────────────────┘

Each policy server is an independent process. They can be:
Local (stdio://./policy.py) — runs as a subprocess
Remote (https://policies.corp.com/pii) — HTTP microservice
Hot-swapped — update a policy without redeploying your agent
The Five Verdict Types
APL policies don't just return yes/no. The verdict model is richer:
Verdict	What It Does	Example
ALLOW	Let it through unchanged	Clean output, budget OK
DENY	Block the operation entirely	Budget exceeded, forbidden content
MODIFY	Rewrite the content before it proceeds	PII redaction, prompt injection removal
ESCALATE	Pause and request human intervention	Destructive tool call, high-cost operation
OBSERVE	Allow but log for audit	Approaching budget limit, unusual patterns
This is what makes APL more than a content filter. MODIFY means your agent still provides a useful response — just a safe one. ESCALATE means you get human-in-the-loop without building it into every tool handler.
Running the Demo Yourself
The repository includes a self-contained demo script that runs without API keys:
git clone https://github.com/nimonkaranurag/agent_policy_layer.git
cd agent_policy_layer
pip install -e ".[dev]"

python demo_watsonx_agent.py

You'll see rich CLI output walking through all four parts: the unprotected agent, PII filter, budget limiter, and destructive action confirmation.
<!-- SCREENSHOT: The final summary panel from the demo script. -->
To test with your own watsonx.ai instance, replace FakeWatsonXModel in the script with a real ModelInference — the rest of the code stays identical.
What's Next
APL is in early beta. Here's what's on the roadmap:
HTTP transport — deploy policy servers as standalone microservices
YAML policies — define simple rules without writing Python
LangGraph adapter — native integration with LangGraph's state machine
Policy composition modes — configure how multiple verdicts combine (deny-overrides, unanimous, weighted)
If you're building agents in production and want to add guardrails without rewriting your stack, give APL a try. It's ~30 lines to your first policy.
GitHub: github.com/nimonkaranurag/agent_policy_layer
APL supports OpenAI, Anthropic, LiteLLM, LangChain, and IBM watsonx.ai out of the box. The instrumentation is provider-agnostic — if your LLM client has a .chat() or .create() method, APL can wrap it.
