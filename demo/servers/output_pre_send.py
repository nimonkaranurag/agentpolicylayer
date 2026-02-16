#!/usr/bin/env python3
"""
Policy Server: OUTPUT_PRE_SEND
==============================
Final filter before output reaches the user.

Output is in: event.payload.output_text

Client: chat.py or tools.py
"""

import re

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="output-pre-send-policy", version="1.0.0"
)


@server.policy(
    name="add-medical-disclaimer",
    events=["output.pre_send"],
)
async def add_medical_disclaimer(
    event: PolicyEvent,
) -> Verdict:
    """Add disclaimer to medical content."""
    output = (
        event.payload.output_text
        if event.payload
        else ""
    )
    if not output:
        return Verdict.allow(reasoning="No output")

    medical_terms = [
        "medication",
        "dosage",
        "symptom",
        "diagnosis",
        "treatment",
        "prescription",
    ]

    if any(
        term in output.lower()
        for term in medical_terms
    ):
        disclaimer = "\n\n---\n⚕️ *Medical Disclaimer: This is for informational purposes only. Consult a healthcare professional.*"
        return Verdict.modify(
            target="output",
            operation="append",
            value=disclaimer,
            reasoning="Medical disclaimer added",
        )

    return Verdict.allow(
        reasoning="No medical content"
    )


@server.policy(
    name="add-financial-disclaimer",
    events=["output.pre_send"],
)
async def add_financial_disclaimer(
    event: PolicyEvent,
) -> Verdict:
    """Add disclaimer to financial advice."""
    output = (
        event.payload.output_text
        if event.payload
        else ""
    )
    if not output:
        return Verdict.allow(reasoning="No output")

    financial_terms = [
        "invest",
        "stock",
        "crypto",
        "portfolio",
        "financial advice",
        "trading",
    ]

    if any(
        term in output.lower()
        for term in financial_terms
    ):
        disclaimer = "\n\n---\n💰 *Financial Disclaimer: Not financial advice. Consult a licensed advisor.*"
        return Verdict.modify(
            target="output",
            operation="append",
            value=disclaimer,
            reasoning="Financial disclaimer added",
        )

    return Verdict.allow(
        reasoning="No financial content"
    )


@server.policy(
    name="add-legal-disclaimer",
    events=["output.pre_send"],
)
async def add_legal_disclaimer(
    event: PolicyEvent,
) -> Verdict:
    """Add disclaimer to legal content."""
    output = (
        event.payload.output_text
        if event.payload
        else ""
    )
    if not output:
        return Verdict.allow(reasoning="No output")

    legal_terms = [
        "legal advice",
        "lawsuit",
        "attorney",
        "court",
        "liability",
        "contract law",
    ]

    if any(
        term in output.lower() for term in legal_terms
    ):
        disclaimer = "\n\n---\n⚖️ *Legal Disclaimer: Not legal advice. Consult a qualified attorney.*"
        return Verdict.modify(
            target="output",
            operation="append",
            value=disclaimer,
            reasoning="Legal disclaimer added",
        )

    return Verdict.allow(reasoning="No legal content")


@server.policy(
    name="enforce-brand-voice",
    events=["output.pre_send"],
)
async def enforce_brand_voice(
    event: PolicyEvent,
) -> Verdict:
    """Block unprofessional language in output."""
    output = (
        event.payload.output_text
        if event.payload
        else ""
    )
    if not output:
        return Verdict.allow(reasoning="No output")

    unprofessional = [
        "lol",
        "lmao",
        "wtf",
        "omg",
        "bruh",
        "gonna",
        "wanna",
        "ya'll",
    ]

    output_lower = output.lower()
    for term in unprofessional:
        if re.search(rf"\b{term}\b", output_lower):
            return Verdict.deny(
                reasoning=f"Unprofessional language: '{term}'"
            )

    return Verdict.allow(
        reasoning="Professional tone OK"
    )


@server.policy(
    name="final-pii-check", events=["output.pre_send"]
)
async def final_pii_check(
    event: PolicyEvent,
) -> Verdict:
    """Final check for any PII that slipped through."""
    output = (
        event.payload.output_text
        if event.payload
        else ""
    )
    if not output:
        return Verdict.allow(reasoning="No output")

    # Comprehensive PII patterns
    pii_patterns = {
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    }

    redacted = output
    found = []
    for pii_type, pattern in pii_patterns.items():
        if re.search(pattern, redacted):
            found.append(pii_type)
            redacted = re.sub(
                pattern,
                f"[{pii_type.upper()} REDACTED]",
                redacted,
            )

    if found:
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted,
            reasoning=f"Final PII redaction: {', '.join(found)}",
        )

    return Verdict.allow(
        reasoning="No PII in final output"
    )


if __name__ == "__main__":
    print("OUTPUT_PRE_SEND server on :8080")
    print("Use with: chat.py or tools.py")
    server.run(
        transport="http", host="0.0.0.0", port=8080
    )
