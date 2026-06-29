"""
Offline tests for the requirements-audit endpoints using mocked HTTP calls.
Covers the audit pipeline and the audit follow-up chat (incl. dev-prompt request).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch


MOCK_AUDIT = """
1. DOMAIN READ
A B2B booking platform with payments — PCI scope applies.
2. AMBIGUITIES
"Users can pay" — card, invoice, or both? Refund policy unspecified.
5. EFFORT ESTIMATE
Auth: 5-8 person-days (med). Payments: 10-15 (low). Cannot estimate reporting until clarified.

PRICING RISK: HIGH — confidence 70%
"""

MOCK_REVIEW = """
Response A caught the PCI obligation and was honest about the unestimable parts.
Response B padded without reasoning.

FINAL RANKING:
1. Response A
2. Response B
"""

MOCK_REPORT = """
PRICING RISK: HIGH — confidence 72%
ONE-LINE: Not safe to fix-price as-is — payment scope and refunds are undefined.

TOP AMBIGUITIES
1. Payment methods (card vs invoice) are unspecified.
2. Refund/chargeback flow is missing.

MISSING / INCOMPLETE
- Non-functional: expected scale and uptime.

KEY IMPLEMENTATION RISKS
- PCI compliance scope — high impact on effort.

EFFORT ESTIMATE (ranged, with assumptions)
- Auth: 5-8 person-days (med)
- Payments: 10-15 person-days (low)
- TOTAL: 30-50 person-days
- Estimate assumes: a single payment provider; clarify refunds to tighten.

MUST-ASK BEFORE PRICING
1. Which payment methods and providers?
2. What is the refund policy?

RECOMMENDATION
- Clarify first — the payment scope can swing the total by 40%.
"""

MOCK_DEV_PROMPT = """
DEVELOPMENT PROMPT — Email/password authentication

GOAL: Let users register and sign in securely.
SCOPE: Registration, login, logout, password reset. OUT OF SCOPE: SSO, 2FA.
DATA MODEL: User(id, email unique, password_hash, created_at).
API: POST /auth/register, POST /auth/login, POST /auth/logout, POST /auth/reset.
ACCEPTANCE CRITERIA: Passwords hashed with bcrypt; lockout after 5 failed attempts.
EDGE CASES: duplicate email, expired reset token.
ASSUMPTION (spec ambiguous): email verification is required before first login.
"""


@pytest.mark.asyncio
async def test_audit_mock():
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"
    os.environ["REQUEST_TIMEOUT"] = "10"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    async def mock_call_model(client, model, system, user, temperature=0.7):
        if "chairman" in model:
            return MOCK_REPORT
        if "peer reviewer" in system.lower():
            return MOCK_REVIEW
        return MOCK_AUDIT

    req = app_module.AuditRequest(
        requirements="Build a B2B booking platform where users can pay and manage reservations.",
        context="Stack: Django + React. Team of 3. Deadline 3 months.",
    )

    events = []
    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        async for chunk in (await app_module.audit(req)).body_iterator:
            line = chunk.decode() if isinstance(chunk, bytes) else chunk
            for part in line.split("\n"):
                if part.startswith("data: "):
                    events.append(json.loads(part[6:]))

    event_types = [e["event"] for e in events]
    assert "stage1_result" in event_types, "Stage 1 audits missing"
    assert "rankings" in event_types, "Rankings missing"
    assert "audit" in event_types, "Consolidated audit missing"
    assert "done" in event_types, "Done event missing"
    assert "error" not in event_types, f"Unexpected errors: {[e for e in events if e['event']=='error']}"

    audit_ev = next(e for e in events if e["event"] == "audit")
    assert "PRICING RISK: HIGH" in audit_ev["content"]
    assert "EFFORT ESTIMATE" in audit_ev["content"]


@pytest.mark.asyncio
async def test_audit_requires_requirements():
    os.environ["OPENROUTER_API_KEY"] = "test-key"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    req = app_module.AuditRequest(requirements="   ", context="")

    events = []
    async for chunk in (await app_module.audit(req)).body_iterator:
        line = chunk.decode() if isinstance(chunk, bytes) else chunk
        for part in line.split("\n"):
            if part.startswith("data: "):
                events.append(json.loads(part[6:]))

    assert any(e["event"] == "error" for e in events)


@pytest.mark.asyncio
async def test_audit_chat_generates_dev_prompt():
    """The audit chat can be asked to produce a development prompt."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    async def mock_call_model(client, model, system, user, temperature=0.7):
        if "chairman" in model:
            return MOCK_DEV_PROMPT
        if "peer reviewer" in system.lower():
            return MOCK_REVIEW
        return "Here is a draft development prompt for authentication..."

    req = app_module.AuditChatRequest(
        requirements="Build a B2B booking platform.",
        context="Django + React.",
        report=MOCK_REPORT,
        audits=[
            app_module.ChatAnalysis(letter="A", model="model-a", content="audit A"),
            app_module.ChatAnalysis(letter="B", model="model-b", content="audit B"),
        ],
        history=[],
        question="Write a precise development prompt for the authentication feature.",
    )

    events = []
    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        async for chunk in (await app_module.audit_chat(req)).body_iterator:
            line = chunk.decode() if isinstance(chunk, bytes) else chunk
            for part in line.split("\n"):
                if part.startswith("data: "):
                    events.append(json.loads(part[6:]))

    event_types = [e["event"] for e in events]
    assert "chat_answer" in event_types
    assert "done" in event_types
    assert "error" not in event_types

    answer = next(e for e in events if e["event"] == "chat_answer")["content"]
    assert "ACCEPTANCE CRITERIA" in answer
