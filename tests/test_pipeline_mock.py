"""
Offline pipeline test using mocked HTTP calls.
Tests the full 3-stage flow without a real API key.
"""

import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


MOCK_STAGE1_RESPONSE = """
1. THE PROBLEM
Hair-on-fire: small restaurant owners lose 30% revenue to no-shows.
2. CUSTOMER & WILLINGNESS TO PAY
Restaurant managers; they already pay OpenTable $249/mo.
3. RISKIEST ASSUMPTION
Restaurants will pay for SMS reminders when they already have manual calls.
4. MARKET & COMPETITION
Resy, OpenTable, simple Google Calendar reminders.
5. HOW IT MAKES MONEY
$29/mo SaaS; break-even at 50 customers.
6. CHEAPEST TEST
Cold-call 20 restaurants, offer a free 2-week trial, measure no-show rate delta.
7. KILL CRITERIA
< 3 out of 20 restaurants activate after trial.

GUT CALL: PIVOT — confidence 55%
"""

MOCK_STAGE2_RESPONSE = """
Response A was specific about the riskiest assumption but weak on competition.
Response B gave generic advice and missed the pricing pressure from OpenTable.

FINAL RANKING:
1. Response A
2. Response B
"""

MOCK_VERDICT = """
VERDICT: PIVOT — confidence 62%
ONE-LINE WHY: The SMS reminder space is crowded and restaurants rarely add new SaaS without clear differentiation.

STRONGEST CASE FOR
- Real problem with measurable impact (no-shows)
- Clear willingness-to-pay signal (OpenTable exists)

STRONGEST CASE AGAINST
- Commodity feature; OpenTable already offers reminders
- Unit economics only work at scale
- No clear moat

RISKIEST ASSUMPTIONS (most likely to kill it first)
1. Restaurants will pay separately for what incumbents bundle
2. 50 paying customers reachable in reasonable time
3. No-show rate meaningfully reducible via SMS alone

THE NEXT EXPERIMENT
- What to do in 2 weeks cheaply: Cold-email 50 restaurants, offer free pilot, measure activation
- Result = PROCEED: 5+ restaurants activate and track no-shows with your tool
- Result = STOP: < 2 activations or no measurable no-show improvement

WHERE THE COUNCIL DISAGREED
- Council split on whether differentiation through AI reminders is enough vs. incumbents bundling the feature.
"""


@pytest.mark.asyncio
async def test_pipeline_mock():
    """Full pipeline with all HTTP mocked — no real API key needed."""
    # We need to set env vars before importing app
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"
    os.environ["REQUEST_TIMEOUT"] = "10"

    # Reload app with test env
    import importlib
    import app as app_module
    importlib.reload(app_module)

    call_count = [0]

    async def mock_call_model(client, model, system, user, temperature=0.7):
        call_count[0] += 1
        if "chairman" in model or "claude" in model.lower():
            return MOCK_VERDICT
        if "FINAL RANKING" in system or "peer reviewer" in system.lower():
            return MOCK_STAGE2_RESPONSE
        return MOCK_STAGE1_RESPONSE

    events = []

    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        from fastapi.testclient import TestClient
        # Use async generator manually
        req = app_module.ValidateRequest(idea="SMS reminder app for restaurants to reduce no-shows")

        async def collect():
            async for chunk in (await app_module.validate(req)).body_iterator:
                line = chunk.decode() if isinstance(chunk, bytes) else chunk
                for part in line.split("\n"):
                    if part.startswith("data: "):
                        events.append(json.loads(part[6:]))

        await collect()

    event_types = [e["event"] for e in events]
    assert "stage1_result" in event_types, "Stage 1 results missing"
    assert "rankings" in event_types, "Rankings missing"
    assert "verdict" in event_types, "Verdict missing"
    assert "done" in event_types, "Done event missing"
    assert "error" not in event_types, f"Unexpected errors: {[e for e in events if e['event']=='error']}"

    verdict_ev = next(e for e in events if e["event"] == "verdict")
    assert "PIVOT" in verdict_ev["content"]
