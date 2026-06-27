"""
Offline test for the follow-up chat endpoint using mocked HTTP calls.
Exercises the full 3-stage follow-up flow (answer → peer review → synthesis)
without a real API key.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch


MOCK_FOLLOWUP_ANSWER = """
Your follow-up doesn't change the riskiest assumption. You still haven't shown a
psychologist will pay for between-session task assignment when notes apps already exist.
Narrowing to CBT helps, but test demand before building AI analytics.
"""

MOCK_FOLLOWUP_REVIEW = """
Response A directly answered and held the line on the riskiest assumption.
Response B was vaguer about the test.

FINAL RANKING:
1. Response A
2. Response B
"""

MOCK_CHAT_SYNTHESIS = """
Narrowing to CBT is a reasonable wedge, but it does not de-risk the core bet:
that a CBT psychologist will pay for structured between-session assignments plus
analytics. Before building the AI layer, run a 2-week test — get 5 CBT therapists
to manually assign tasks to clients through a stripped-down prototype and measure
whether clients complete them and therapists keep using it.
"""


@pytest.mark.asyncio
async def test_chat_mock():
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"
    os.environ["REQUEST_TIMEOUT"] = "10"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    async def mock_call_model(client, model, system, user, temperature=0.7):
        if "chairman" in model:
            return MOCK_CHAT_SYNTHESIS
        if "peer reviewer" in system.lower():
            return MOCK_FOLLOWUP_REVIEW
        return MOCK_FOLLOWUP_ANSWER

    req = app_module.ChatRequest(
        idea="Platform for psychologists to assign between-session tasks to patients.",
        verdict="VERDICT: CONDITIONAL GO — confidence 55%",
        analyses=[
            app_module.ChatAnalysis(letter="A", model="model-a", content="Original analysis A"),
            app_module.ChatAnalysis(letter="B", model="model-b", content="Original analysis B"),
        ],
        history=[],
        question="If I narrow it to just CBT therapists first, does that fix the riskiest assumption?",
    )

    events = []
    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        async for chunk in (await app_module.chat(req)).body_iterator:
            line = chunk.decode() if isinstance(chunk, bytes) else chunk
            for part in line.split("\n"):
                if part.startswith("data: "):
                    events.append(json.loads(part[6:]))

    event_types = [e["event"] for e in events]
    assert "chat_stage1_result" in event_types, "Stage 1 answers missing"
    assert "chat_rankings" in event_types, "Peer-review rankings missing"
    assert "chat_answer" in event_types, "Synthesized answer missing"
    assert "done" in event_types, "Done event missing"
    assert "error" not in event_types, f"Unexpected errors: {[e for e in events if e['event']=='error']}"

    answer_ev = next(e for e in events if e["event"] == "chat_answer")
    assert "CBT" in answer_ev["content"]


@pytest.mark.asyncio
async def test_chat_requires_context():
    """With no council analyses provided, the endpoint errors cleanly."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    req = app_module.ChatRequest(idea="x", verdict="", analyses=[], history=[], question="why?")

    events = []
    async for chunk in (await app_module.chat(req)).body_iterator:
        line = chunk.decode() if isinstance(chunk, bytes) else chunk
        for part in line.split("\n"):
            if part.startswith("data: "):
                events.append(json.loads(part[6:]))

    assert any(e["event"] == "error" for e in events)
