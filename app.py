"""
Validation Council — FastAPI backend.
Run: uvicorn app:app --reload  (from the council/ directory)
"""

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from typing import AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prompts import (
    STAGE1_SYSTEM,
    STAGE1_USER_TEMPLATE,
    STAGE2_SYSTEM,
    STAGE2_USER_TEMPLATE,
    STAGE3_SYSTEM,
    STAGE3_USER_TEMPLATE,
    FOLLOWUP_STAGE1_SYSTEM,
    FOLLOWUP_STAGE1_USER_TEMPLATE,
    FOLLOWUP_STAGE2_SYSTEM,
    FOLLOWUP_STAGE2_USER_TEMPLATE,
    FOLLOWUP_STAGE3_SYSTEM,
    FOLLOWUP_STAGE3_USER_TEMPLATE,
    DISCOVER_STAGE1_SYSTEM,
    DISCOVER_STAGE1_USER_TEMPLATE,
    DISCOVER_STAGE2_SYSTEM,
    DISCOVER_STAGE2_USER_TEMPLATE,
    DISCOVER_STAGE3_SYSTEM,
    DISCOVER_STAGE3_USER_TEMPLATE,
    DISCOVER_FOLLOWUP_STAGE1_SYSTEM,
    DISCOVER_FOLLOWUP_STAGE1_USER_TEMPLATE,
    DISCOVER_FOLLOWUP_STAGE3_SYSTEM,
    DISCOVER_FOLLOWUP_STAGE3_USER_TEMPLATE,
)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_raw_models = os.getenv(
    "COUNCIL_MODELS",
    "openai/gpt-4.1,anthropic/claude-sonnet-4-5,google/gemini-2.5-pro-preview,x-ai/grok-3",
)
COUNCIL_MODELS = [m.strip() for m in _raw_models.split(",") if m.strip()]

CHAIRMAN_MODEL = os.getenv(
    "CHAIRMAN_MODEL",
    "anthropic/claude-opus-4-5",
)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "90"))

app = FastAPI(title="Validation Council")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── OpenRouter call ──────────────────────────────────────────────────────────

async def call_model(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/validation-council",
        "X-Title": "Validation Council",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    resp = await client.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ── Ranking parser ───────────────────────────────────────────────────────────

def parse_ranking(text: str, letters: list[str]) -> dict[str, int]:
    """
    Parse FINAL RANKING block. Returns {letter: position} (1-based).
    Falls back to alphabetical order if parsing fails.
    """
    match = re.search(r"FINAL RANKING:(.*?)(?:\n\n|\Z)", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return {l: i + 1 for i, l in enumerate(letters)}

    block = match.group(1)
    ranking: dict[str, int] = {}
    for line in block.strip().splitlines():
        m = re.match(r"\s*(\d+)\.\s+Response\s+([A-Z])", line, re.IGNORECASE)
        if m:
            pos, letter = int(m.group(1)), m.group(2).upper()
            ranking[letter] = pos

    # fill missing
    for i, l in enumerate(letters):
        if l not in ranking:
            ranking[l] = len(letters)
    return ranking


def aggregate_rankings(
    all_rankings: list[dict[str, int]], letters: list[str]
) -> dict[str, float]:
    """Average rank per letter across all reviewers (lower = better)."""
    totals: dict[str, list[int]] = defaultdict(list)
    for ranking in all_rankings:
        for letter, pos in ranking.items():
            totals[letter].append(pos)
    return {l: sum(totals[l]) / len(totals[l]) if totals[l] else 999.0 for l in letters}


# ── SSE helpers ──────────────────────────────────────────────────────────────

def sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


# ── Main pipeline ────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    idea: str


@app.post("/validate")
async def validate(req: ValidateRequest):
    async def stream() -> AsyncGenerator[str, None]:
        idea = req.idea.strip()
        if not idea:
            yield sse("error", {"message": "No idea provided."})
            return
        if not OPENROUTER_API_KEY:
            yield sse("error", {"message": "OPENROUTER_API_KEY not set."})
            return

        letters = [chr(ord("A") + i) for i in range(len(COUNCIL_MODELS))]

        # ── Stage 1 ──────────────────────────────────────────────────────────
        yield sse("stage", {"stage": 1, "status": "start", "models": COUNCIL_MODELS})

        stage1_results: dict[str, str | None] = {}  # letter → content or None

        async with httpx.AsyncClient() as client:

            async def fetch_stage1(model: str, letter: str):
                try:
                    content = await call_model(
                        client,
                        model,
                        STAGE1_SYSTEM,
                        STAGE1_USER_TEMPLATE.format(idea=idea),
                    )
                    stage1_results[letter] = content
                    return letter, model, content, None
                except Exception as exc:
                    stage1_results[letter] = None
                    return letter, model, None, str(exc)

            tasks = [
                fetch_stage1(model, letter)
                for model, letter in zip(COUNCIL_MODELS, letters)
            ]
            for coro in asyncio.as_completed(tasks):
                letter, model, content, error = await coro
                if error:
                    yield sse(
                        "stage1_result",
                        {"letter": letter, "model": model, "error": error},
                    )
                else:
                    yield sse(
                        "stage1_result",
                        {"letter": letter, "model": model, "content": content},
                    )

        # drop failed models
        valid_letters = [l for l in letters if stage1_results.get(l)]
        if len(valid_letters) < 2:
            yield sse("error", {"message": "Too few models responded (need ≥ 2)."})
            return

        yield sse("stage", {"stage": 1, "status": "done"})

        # ── Stage 2 ──────────────────────────────────────────────────────────
        yield sse("stage", {"stage": 2, "status": "start"})

        # Build anonymous block — NO model names, only letters
        anon_block = "\n\n---\n\n".join(
            f"Response {l}:\n{stage1_results[l]}" for l in valid_letters
        )

        stage2_results: list[dict[str, int]] = []

        async with httpx.AsyncClient() as client:

            async def fetch_stage2(reviewer_model: str, reviewer_letter: str):
                try:
                    content = await call_model(
                        client,
                        reviewer_model,
                        STAGE2_SYSTEM,
                        STAGE2_USER_TEMPLATE.format(idea=idea, analyses=anon_block),
                        temperature=0.4,
                    )
                    ranking = parse_ranking(content, valid_letters)
                    return reviewer_letter, reviewer_model, content, ranking, None
                except Exception as exc:
                    return reviewer_letter, reviewer_model, None, {}, str(exc)

            tasks = [
                fetch_stage2(model, letter)
                for model, letter in zip(COUNCIL_MODELS, letters)
                if stage1_results.get(letter)  # only use models that answered stage 1
            ]
            for coro in asyncio.as_completed(tasks):
                reviewer_letter, reviewer_model, content, ranking, error = await coro
                if error:
                    yield sse(
                        "stage2_result",
                        {"reviewer": reviewer_letter, "model": reviewer_model, "error": error},
                    )
                else:
                    stage2_results.append(ranking)
                    yield sse(
                        "stage2_result",
                        {
                            "reviewer": reviewer_letter,
                            "model": reviewer_model,
                            "content": content,
                            "ranking": ranking,
                        },
                    )

        avg_ranks = aggregate_rankings(stage2_results, valid_letters)
        yield sse("rankings", {"avg_ranks": avg_ranks, "letters": valid_letters})
        yield sse("stage", {"stage": 2, "status": "done"})

        # ── Stage 3 ──────────────────────────────────────────────────────────
        yield sse("stage", {"stage": 3, "status": "start", "chairman": CHAIRMAN_MODEL})

        # Build ranked analyses for chairman (still anonymous letters)
        sorted_letters = sorted(valid_letters, key=lambda l: avg_ranks.get(l, 999))
        analyses_with_ranks = "\n\n---\n\n".join(
            f"Response {l} (avg rank: {avg_ranks.get(l, '?'):.1f}):\n{stage1_results[l]}"
            for l in sorted_letters
        )

        try:
            async with httpx.AsyncClient() as client:
                verdict = await call_model(
                    client,
                    CHAIRMAN_MODEL,
                    STAGE3_SYSTEM,
                    STAGE3_USER_TEMPLATE.format(
                        idea=idea, analyses_with_ranks=analyses_with_ranks
                    ),
                    temperature=0.3,
                )
            yield sse("verdict", {"content": verdict})
        except Exception as exc:
            yield sse("error", {"message": f"Chairman failed: {exc}"})
            return

        yield sse("stage", {"stage": 3, "status": "done"})
        yield sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Follow-up chat ───────────────────────────────────────────────────────────
# The council continues the conversation after the verdict. Stateless: the
# frontend sends back the full context (idea, verdict, original analyses, and the
# running Q/A history) with every question. Same 3-stage method as /validate:
# each member answers → anonymous peer review → chairman synthesizes one reply.


class ChatAnalysis(BaseModel):
    letter: str
    model: str
    content: str


class ChatTurn(BaseModel):
    question: str
    answer: str


class ChatRequest(BaseModel):
    idea: str
    verdict: str = ""
    analyses: list[ChatAnalysis] = []
    history: list[ChatTurn] = []
    question: str


def format_history(history: list[ChatTurn]) -> str:
    if not history:
        return "(no prior follow-up questions yet)"
    parts = []
    for i, turn in enumerate(history, 1):
        parts.append(f"Q{i} (founder): {turn.question}\nA{i} (council): {turn.answer}")
    return "\n\n".join(parts)


async def _followup_pipeline(
    participants: list[tuple[str, str]],   # (letter, model)
    stage1_system: str,
    stage1_user: str,
    stage2_system: str,
    make_stage2_user,                      # (anon_block: str) -> str
    stage3_system: str,
    make_stage3_user,                      # (analyses_with_ranks: str) -> str
) -> AsyncGenerator[str, None]:
    """Shared 3-stage follow-up flow used by both the validate and discover chats.

    Each council member answers the same prompt → anonymous peer review ranks the
    answers → chairman synthesizes one reply. Emits the same chat_* SSE events
    regardless of which chat invoked it.
    """
    # ── Stage 1 — each member answers ────────────────────────────────────────
    yield sse("chat_stage", {"stage": 1, "status": "start"})

    answers: dict[str, str] = {}        # letter → content
    member_models: dict[str, str] = {}  # letter → model

    async with httpx.AsyncClient() as client:

        async def fetch_answer(letter: str, model: str):
            try:
                content = await call_model(
                    client, model, stage1_system, stage1_user, temperature=0.5
                )
                return letter, model, content, None
            except Exception as exc:
                return letter, model, None, str(exc)

        tasks = [fetch_answer(l, m) for l, m in participants]
        for coro in asyncio.as_completed(tasks):
            letter, model, content, error = await coro
            if error:
                yield sse("chat_stage1_result", {"letter": letter, "model": model, "error": error})
            else:
                answers[letter] = content
                member_models[letter] = model
                yield sse("chat_stage1_result", {"letter": letter, "model": model, "content": content})

    valid_letters = list(answers.keys())
    if not valid_letters:
        yield sse("error", {"message": "All council members failed to answer."})
        return
    yield sse("chat_stage", {"stage": 1, "status": "done"})

    # ── Stage 2 — anonymous peer review (only with ≥ 2 answers) ──────────────
    avg_ranks: dict[str, float] = {l: 1.0 for l in valid_letters}
    if len(valid_letters) >= 2:
        yield sse("chat_stage", {"stage": 2, "status": "start"})

        anon_block = "\n\n---\n\n".join(
            f"Response {l}:\n{answers[l]}" for l in valid_letters
        )
        stage2_rankings: list[dict[str, int]] = []

        async with httpx.AsyncClient() as client:

            async def review(letter: str, model: str):
                try:
                    content = await call_model(
                        client, model, stage2_system, make_stage2_user(anon_block),
                        temperature=0.4,
                    )
                    return parse_ranking(content, valid_letters), None
                except Exception as exc:
                    return {}, str(exc)

            tasks = [review(l, member_models[l]) for l in valid_letters]
            for coro in asyncio.as_completed(tasks):
                ranking, error = await coro
                if not error and ranking:
                    stage2_rankings.append(ranking)

        if stage2_rankings:
            avg_ranks = aggregate_rankings(stage2_rankings, valid_letters)
        yield sse("chat_rankings", {"avg_ranks": avg_ranks, "letters": valid_letters})
        yield sse("chat_stage", {"stage": 2, "status": "done"})

    # ── Stage 3 — chairman synthesizes one reply ─────────────────────────────
    yield sse("chat_stage", {"stage": 3, "status": "start", "chairman": CHAIRMAN_MODEL})

    sorted_letters = sorted(valid_letters, key=lambda l: avg_ranks.get(l, 999))
    analyses_with_ranks = "\n\n---\n\n".join(
        f"Response {l} (avg rank: {avg_ranks.get(l, 999.0):.1f}):\n{answers[l]}"
        for l in sorted_letters
    )

    try:
        async with httpx.AsyncClient() as client:
            answer = await call_model(
                client, CHAIRMAN_MODEL, stage3_system, make_stage3_user(analyses_with_ranks),
                temperature=0.3,
            )
        yield sse("chat_answer", {"content": answer})
    except Exception as exc:
        yield sse("error", {"message": f"Chairman failed: {exc}"})
        return

    yield sse("chat_stage", {"stage": 3, "status": "done"})
    yield sse("done", {})


@app.post("/chat")
async def chat(req: ChatRequest):
    async def stream() -> AsyncGenerator[str, None]:
        question = req.question.strip()
        if not question:
            yield sse("error", {"message": "No question provided."})
            return
        if not OPENROUTER_API_KEY:
            yield sse("error", {"message": "OPENROUTER_API_KEY not set."})
            return

        participants = [(a.letter, a.model) for a in req.analyses if a.content and a.model]
        if not participants:
            yield sse("error", {"message": "No council context provided."})
            return

        history_str = format_history(req.history)
        verdict = req.verdict or "(verdict unavailable)"
        stage1_user = FOLLOWUP_STAGE1_USER_TEMPLATE.format(
            idea=req.idea, verdict=verdict, history=history_str, question=question
        )

        async for ev in _followup_pipeline(
            participants,
            FOLLOWUP_STAGE1_SYSTEM,
            stage1_user,
            FOLLOWUP_STAGE2_SYSTEM,
            lambda block: FOLLOWUP_STAGE2_USER_TEMPLATE.format(question=question, analyses=block),
            FOLLOWUP_STAGE3_SYSTEM,
            lambda awr: FOLLOWUP_STAGE3_USER_TEMPLATE.format(
                idea=req.idea, verdict=verdict, history=history_str,
                question=question, analyses_with_ranks=awr,
            ),
        ):
            yield ev

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Discover follow-up chat ──────────────────────────────────────────────────
# Same shared pipeline, framed around the proposed top-3 ideas instead of a verdict.


class DiscoverChatRequest(BaseModel):
    constraints: str = ""
    ideas: str = ""
    proposals: list[ChatAnalysis] = []
    history: list[ChatTurn] = []
    question: str


@app.post("/discover_chat")
async def discover_chat(req: DiscoverChatRequest):
    async def stream() -> AsyncGenerator[str, None]:
        question = req.question.strip()
        if not question:
            yield sse("error", {"message": "No question provided."})
            return
        if not OPENROUTER_API_KEY:
            yield sse("error", {"message": "OPENROUTER_API_KEY not set."})
            return

        participants = [(p.letter, p.model) for p in req.proposals if p.content and p.model]
        if not participants:
            yield sse("error", {"message": "No council context provided."})
            return

        history_str = format_history(req.history)
        constraints = req.constraints.strip() or "(none given)"
        ideas = req.ideas or "(ideas unavailable)"
        stage1_user = DISCOVER_FOLLOWUP_STAGE1_USER_TEMPLATE.format(
            constraints=constraints, ideas=ideas, history=history_str, question=question
        )

        async for ev in _followup_pipeline(
            participants,
            DISCOVER_FOLLOWUP_STAGE1_SYSTEM,
            stage1_user,
            FOLLOWUP_STAGE2_SYSTEM,
            lambda block: FOLLOWUP_STAGE2_USER_TEMPLATE.format(question=question, analyses=block),
            DISCOVER_FOLLOWUP_STAGE3_SYSTEM,
            lambda awr: DISCOVER_FOLLOWUP_STAGE3_USER_TEMPLATE.format(
                constraints=constraints, ideas=ideas, history=history_str,
                question=question, analyses_with_ranks=awr,
            ),
        ):
            yield ev

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Discover mode (the council in reverse) ───────────────────────────────────
# Same 3-stage method, but the council PROPOSES ideas with a real payment signal
# instead of validating one. Stage 1: each member proposes 3 ideas. Stage 2:
# anonymous peer review ranks the sets. Stage 3: chairman picks the top 3 overall.


class DiscoverRequest(BaseModel):
    constraints: str = ""


@app.post("/discover")
async def discover(req: DiscoverRequest):
    async def stream() -> AsyncGenerator[str, None]:
        if not OPENROUTER_API_KEY:
            yield sse("error", {"message": "OPENROUTER_API_KEY not set."})
            return

        constraints = req.constraints.strip()
        constraints_for_prompt = constraints or (
            "(none given — scan broadly for the strongest payment signals)"
        )
        letters = [chr(ord("A") + i) for i in range(len(COUNCIL_MODELS))]

        # ── Stage 1 — each member proposes ideas ─────────────────────────────
        yield sse("stage", {"stage": 1, "status": "start", "models": COUNCIL_MODELS})

        stage1_results: dict[str, str | None] = {}

        async with httpx.AsyncClient() as client:

            async def propose(model: str, letter: str):
                try:
                    content = await call_model(
                        client,
                        model,
                        DISCOVER_STAGE1_SYSTEM,
                        DISCOVER_STAGE1_USER_TEMPLATE.format(constraints=constraints_for_prompt),
                        temperature=0.8,
                    )
                    stage1_results[letter] = content
                    return letter, model, content, None
                except Exception as exc:
                    stage1_results[letter] = None
                    return letter, model, None, str(exc)

            tasks = [propose(m, l) for m, l in zip(COUNCIL_MODELS, letters)]
            for coro in asyncio.as_completed(tasks):
                letter, model, content, error = await coro
                if error:
                    yield sse("stage1_result", {"letter": letter, "model": model, "error": error})
                else:
                    yield sse("stage1_result", {"letter": letter, "model": model, "content": content})

        valid_letters = [l for l in letters if stage1_results.get(l)]
        if len(valid_letters) < 2:
            yield sse("error", {"message": "Too few models responded (need ≥ 2)."})
            return
        yield sse("stage", {"stage": 1, "status": "done"})

        # ── Stage 2 — anonymous peer review of the idea sets ─────────────────
        yield sse("stage", {"stage": 2, "status": "start"})

        anon_block = "\n\n---\n\n".join(
            f"Response {l}:\n{stage1_results[l]}" for l in valid_letters
        )
        stage2_results: list[dict[str, int]] = []

        async with httpx.AsyncClient() as client:

            async def review(model: str, letter: str):
                try:
                    content = await call_model(
                        client,
                        model,
                        DISCOVER_STAGE2_SYSTEM,
                        DISCOVER_STAGE2_USER_TEMPLATE.format(
                            constraints=constraints_for_prompt, proposals=anon_block
                        ),
                        temperature=0.4,
                    )
                    return parse_ranking(content, valid_letters), None
                except Exception as exc:
                    return {}, str(exc)

            tasks = [
                review(m, l)
                for m, l in zip(COUNCIL_MODELS, letters)
                if stage1_results.get(l)
            ]
            for coro in asyncio.as_completed(tasks):
                ranking, error = await coro
                if not error and ranking:
                    stage2_results.append(ranking)

        avg_ranks = (
            aggregate_rankings(stage2_results, valid_letters)
            if stage2_results
            else {l: 1.0 for l in valid_letters}
        )
        yield sse("rankings", {"avg_ranks": avg_ranks, "letters": valid_letters})
        yield sse("stage", {"stage": 2, "status": "done"})

        # ── Stage 3 — chairman picks the top 3 ───────────────────────────────
        yield sse("stage", {"stage": 3, "status": "start", "chairman": CHAIRMAN_MODEL})

        sorted_letters = sorted(valid_letters, key=lambda l: avg_ranks.get(l, 999))
        proposals_with_ranks = "\n\n---\n\n".join(
            f"Response {l} (avg rank: {avg_ranks.get(l, 999.0):.1f}):\n{stage1_results[l]}"
            for l in sorted_letters
        )

        try:
            async with httpx.AsyncClient() as client:
                ideas = await call_model(
                    client,
                    CHAIRMAN_MODEL,
                    DISCOVER_STAGE3_SYSTEM,
                    DISCOVER_STAGE3_USER_TEMPLATE.format(
                        constraints=constraints_for_prompt,
                        proposals_with_ranks=proposals_with_ranks,
                    ),
                    temperature=0.4,
                )
            yield sse("ideas", {"content": ideas})
        except Exception as exc:
            yield sse("error", {"message": f"Chairman failed: {exc}"})
            return

        yield sse("stage", {"stage": 3, "status": "done"})
        yield sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "models": COUNCIL_MODELS,
        "chairman": CHAIRMAN_MODEL,
    }
