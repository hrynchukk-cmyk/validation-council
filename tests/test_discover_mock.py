"""
Offline test for the discover endpoint (council in reverse) using mocked HTTP.
Exercises the full 3-stage idea-generation flow without a real API key.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch


MOCK_PROPOSAL = """
IDEA: A done-for-you VAT filing service for UA sole proprietors on the simplified tax system.
WHO PAYS & PAYMENT SIGNAL: FOPs already pay accountants 1,500–3,000 UAH/mo for exactly this.
WHY NOW: Diia.City and frequent tax-rule changes make DIY filing risky.
RISKIEST ASSUMPTION: FOPs will switch from a trusted human accountant to software.
CHEAPEST TEST: Sell 10 manual filings via a landing page before building anything.
"""

MOCK_REVIEW = """
Response A had the strongest money trail; Response B was vaguer on the payer.

FINAL RANKING:
1. Response A
2. Response B
"""

MOCK_TOP3 = """
IDEA 1: Done-for-you VAT/tax filing for UA sole proprietors on the simplified system.
PAYMENT SIGNAL: FOPs already pay accountants 1,500–3,000 UAH/mo for this exact task.
WHY NOW: Frequent tax-rule changes make DIY risky and accountants expensive.
RISKIEST ASSUMPTION: They will trust software over a human accountant.
CHEAPEST TEST: Pre-sell 10 manual filings via a landing page in a week.

IDEA 2: Reactivation-as-a-service for dental clinics with idle patient lists.
PAYMENT SIGNAL: Clinics already pay agencies for recall SMS campaigns.
WHY NOW: Cheap messaging APIs make per-clinic automation viable.
RISKIEST ASSUMPTION: Clinics will share patient data with a third party.
CHEAPEST TEST: Run one paid recall campaign for a single clinic, revenue-share.

IDEA 3: Compliance-doc generator for EU-bound UA freelancers.
PAYMENT SIGNAL: Freelancers pay lawyers €150+ per contract template today.
WHY NOW: Surge in UA→EU remote contracts post-2022.
RISKIEST ASSUMPTION: Generated docs are trusted enough to replace a lawyer.
CHEAPEST TEST: Sell 5 paid template packs before automating generation.
"""


@pytest.mark.asyncio
async def test_discover_mock():
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"
    os.environ["REQUEST_TIMEOUT"] = "10"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    async def mock_call_model(client, model, system, user, temperature=0.7):
        if "chairman" in model:
            return MOCK_TOP3
        if "peer reviewer" in system.lower():
            return MOCK_REVIEW
        return MOCK_PROPOSAL

    req = app_module.DiscoverRequest(constraints="UA market, B2B, solo founder")

    events = []
    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        async for chunk in (await app_module.discover(req)).body_iterator:
            line = chunk.decode() if isinstance(chunk, bytes) else chunk
            for part in line.split("\n"):
                if part.startswith("data: "):
                    events.append(json.loads(part[6:]))

    event_types = [e["event"] for e in events]
    assert "stage1_result" in event_types, "Stage 1 proposals missing"
    assert "rankings" in event_types, "Rankings missing"
    assert "ideas" in event_types, "Top-3 ideas missing"
    assert "done" in event_types, "Done event missing"
    assert "error" not in event_types, f"Unexpected errors: {[e for e in events if e['event']=='error']}"

    ideas_ev = next(e for e in events if e["event"] == "ideas")
    assert "IDEA 1:" in ideas_ev["content"]
    assert ideas_ev["content"].count("PAYMENT SIGNAL:") == 3


@pytest.mark.asyncio
async def test_discover_empty_constraints_ok():
    """Discover works with no constraints (broad scan)."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    async def mock_call_model(client, model, system, user, temperature=0.7):
        if "chairman" in model:
            return MOCK_TOP3
        if "peer reviewer" in system.lower():
            return MOCK_REVIEW
        return MOCK_PROPOSAL

    req = app_module.DiscoverRequest()

    events = []
    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        async for chunk in (await app_module.discover(req)).body_iterator:
            line = chunk.decode() if isinstance(chunk, bytes) else chunk
            for part in line.split("\n"):
                if part.startswith("data: "):
                    events.append(json.loads(part[6:]))

    assert any(e["event"] == "ideas" for e in events)
    assert not any(e["event"] == "error" for e in events)
