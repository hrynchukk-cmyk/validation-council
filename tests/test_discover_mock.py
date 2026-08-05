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
WHY THIS MIGHT FAIL: The accountant is also the trusted advisor; the fee buys reassurance, not filing.
MOST LIKELY FAILURE MODE: FOPs try it once, hit an edge case, and go back to their accountant.
POSSIBLE SOLUTION: Sell to the accountants as a throughput tool instead of replacing them.
RISKIEST ASSUMPTION: FOPs will switch from a trusted human accountant to software.
CHEAPEST TEST: Sell 10 manual filings via a landing page before building anything.
"""

MOCK_REDTEAM = """
RESPONSE A — IDEA 1: VAT filing for FOPs
FATAL FLAWS: The 1,500 UAH is a relationship fee, not a filing fee. Liability for a wrong filing sits
with the accountant today — software cannot absorb it.
SURVIVES?: WOUNDED — the payment signal is real but points at the accountant, not the FOP.
IF SAVEABLE: Sell to accounting firms as capacity tooling, not to FOPs direct.
"""

MOCK_REVIEW = """
Response A had the strongest money trail and had already named the liability flaw itself.
Response B was vaguer on the payer and its self-criticism was token.

FINAL RANKING:
1. Response A
2. Response B
"""

MOCK_TOP3 = """
IDEA 1: Done-for-you VAT/tax filing for UA sole proprietors on the simplified system.
PAYMENT SIGNAL: FOPs already pay accountants 1,500–3,000 UAH/mo for this exact task.
WHY NOW: Frequent tax-rule changes make DIY risky and accountants expensive.
WHY THIS MIGHT FAIL: The fee buys liability cover and reassurance, which software cannot absorb.
HOW TO DE-RISK IT: Sell to accounting firms as capacity tooling rather than replacing them.
RISKIEST ASSUMPTION: They will trust software over a human accountant.
CHEAPEST TEST: Pre-sell 10 manual filings via a landing page in a week.
SURVIVAL ODDS: MEDIUM — hinges on selling to firms, not to FOPs direct.

IDEA 2: Reactivation-as-a-service for dental clinics with idle patient lists.
PAYMENT SIGNAL: Clinics already pay agencies for recall SMS campaigns.
WHY NOW: Cheap messaging APIs make per-clinic automation viable.
WHY THIS MIGHT FAIL: Patient data access is a hard legal and trust barrier for a new vendor.
HOW TO DE-RISK IT: Start revenue-share on one clinic, never holding the data yourself.
RISKIEST ASSUMPTION: Clinics will share patient data with a third party.
CHEAPEST TEST: Run one paid recall campaign for a single clinic, revenue-share.
SURVIVAL ODDS: HIGH — the budget already exists and is agency-shaped.

IDEA 3: Compliance-doc generator for EU-bound UA freelancers.
PAYMENT SIGNAL: Freelancers pay lawyers €150+ per contract template today.
WHY NOW: Surge in UA→EU remote contracts post-2022.
WHY THIS MIGHT FAIL: One-off purchase with no repeat; free templates are already good enough.
HOW TO DE-RISK IT: Attach it to a recurring compliance need rather than selling templates once.
RISKIEST ASSUMPTION: Generated docs are trusted enough to replace a lawyer.
CHEAPEST TEST: Sell 5 paid template packs before automating generation.
SURVIVAL ODDS: LOW — no recurring payment and weak differentiation from free templates.
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

    seen_prompts = []

    async def mock_call_model(client, model, system, user, temperature=0.7):
        seen_prompts.append((system, user))
        if "chairman" in model:
            return MOCK_TOP3
        if "red-team" in system.lower():
            return MOCK_REDTEAM
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
    assert "redteam_result" in event_types, "Red-team pass did not run"
    assert "rankings" in event_types, "Rankings missing"
    assert "ideas" in event_types, "Top-3 ideas missing"
    assert "done" in event_types, "Done event missing"
    assert "error" not in event_types, f"Unexpected errors: {[e for e in events if e['event']=='error']}"

    # Every council member should have red-teamed the pooled ideas.
    assert sum(1 for e in events if e["event"] == "redteam_result") == 2

    # Discover runs 4 stages once the red-team pass is in play.
    stages_done = {e["stage"] for e in events if e["event"] == "stage" and e.get("status") == "done"}
    assert stages_done == {1, 2, 3, 4}, f"Unexpected stage numbering: {stages_done}"

    # The peer review and the chairman must both be handed the red-team findings.
    review_users = [u for s, u in seen_prompts if "peer reviewer" in s.lower()]
    chairman_users = [u for s, u in seen_prompts if "chairman" in s.lower()]
    assert review_users and chairman_users, "No review/chairman calls recorded"
    assert all("Red-team review 1:" in u for u in review_users), "Peer review did not see red-team findings"
    assert all("Red-team review 1:" in u for u in chairman_users), "Chairman did not see red-team findings"

    ideas_ev = next(e for e in events if e["event"] == "ideas")
    assert "IDEA 1:" in ideas_ev["content"]
    assert ideas_ev["content"].count("PAYMENT SIGNAL:") == 3
    # The self-criticism must survive into the final top 3.
    assert ideas_ev["content"].count("WHY THIS MIGHT FAIL:") == 3
    assert ideas_ev["content"].count("HOW TO DE-RISK IT:") == 3
    assert ideas_ev["content"].count("SURVIVAL ODDS:") == 3


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
