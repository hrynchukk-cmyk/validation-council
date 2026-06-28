"""
Offline test for the discover follow-up chat endpoint using mocked HTTP calls.
Exercises the shared 3-stage follow-up pipeline framed around the proposed ideas.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch


MOCK_MEMBER_ANSWER = """
Idea 2 has the clearest payer: dental clinics already buy recall SMS from agencies,
so you can revenue-share on a single clinic before building anything. The riskiest
part is data access, not demand.
"""

MOCK_REVIEW = """
Response A answered the question and kept the payment signal central.
Response B drifted into features.

FINAL RANKING:
1. Response A
2. Response B
"""

MOCK_SYNTHESIS = """
Go with idea 2 first. The payer is proven — clinics already pay agencies for recall
campaigns — so the cheapest test is to run one paid, revenue-share recall for a single
clinic this week and measure booked appointments.
"""


@pytest.mark.asyncio
async def test_discover_chat_mock():
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["COUNCIL_MODELS"] = "model-a,model-b"
    os.environ["CHAIRMAN_MODEL"] = "model-chairman"
    os.environ["REQUEST_TIMEOUT"] = "10"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    async def mock_call_model(client, model, system, user, temperature=0.7):
        if "chairman" in model:
            return MOCK_SYNTHESIS
        if "peer reviewer" in system.lower():
            return MOCK_REVIEW
        return MOCK_MEMBER_ANSWER

    req = app_module.DiscoverChatRequest(
        constraints="UA market, B2B",
        ideas="IDEA 1: ...\nIDEA 2: Reactivation-as-a-service for dental clinics.\nIDEA 3: ...",
        proposals=[
            app_module.ChatAnalysis(letter="A", model="model-a", content="proposal set A"),
            app_module.ChatAnalysis(letter="B", model="model-b", content="proposal set B"),
        ],
        history=[],
        question="Which of the three should I start with and why?",
    )

    events = []
    with patch.object(app_module, "call_model", side_effect=mock_call_model):
        async for chunk in (await app_module.discover_chat(req)).body_iterator:
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
    assert "idea 2" in answer_ev["content"].lower()


@pytest.mark.asyncio
async def test_discover_chat_requires_context():
    os.environ["OPENROUTER_API_KEY"] = "test-key"

    import importlib
    import app as app_module
    importlib.reload(app_module)

    req = app_module.DiscoverChatRequest(constraints="", ideas="", proposals=[], history=[], question="why?")

    events = []
    async for chunk in (await app_module.discover_chat(req)).body_iterator:
        line = chunk.decode() if isinstance(chunk, bytes) else chunk
        for part in line.split("\n"):
            if part.startswith("data: "):
                events.append(json.loads(part[6:]))

    assert any(e["event"] == "error" for e in events)
