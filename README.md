# Validation Council

Multiple LLMs validate your business idea — anonymously, anti-sycophantically.
A council of *different* models (different training, different blind spots) each
analyze your idea independently, then **anonymously** peer-review each other's
reasoning, and a chairman model delivers one decisive verdict.

Based on Andrej Karpathy's "LLM Council" method, specialized for business-idea
validation and explicitly biased *against* sycophancy.

> **Disclaimer:** Real validation = people paying or refusing. The council helps
> you decide *what to test first*, not whether the idea is proven.

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: add OPENROUTER_API_KEY and verify model IDs at https://openrouter.ai/models

uvicorn app:app --reload
# Open http://localhost:8000
```

## How it works

**Stage 1 — Independent analysis**
Each council model receives the idea and analyzes it in parallel against a fixed
rubric (Problem / Willingness to pay / Riskiest assumption / Market / Unit
economics / Cheapest test / Kill criteria). Default assumption: the idea fails.

**Stage 2 — Anonymous peer review**
Analyses are stripped of model identities and labeled A/B/C…. Each council member
critiques and ranks the others' reasoning. This surfaces blind spots without
social pressure. The `FINAL RANKING:` block is parsed and aggregated.

**Stage 3 — Chairman verdict**
A senior model weighs the strongest arguments (trusting higher-ranked analyses
more), surfaces disagreements, and delivers one decisive verdict:
GO / CONDITIONAL GO / PIVOT / KILL.

Calls per run: `(council size × 2) + 1`. Nothing is stored between runs (stateless).

**Follow-up chat**
After the verdict you can keep talking to the council. Each follow-up question
re-runs the full method on that question: every council member answers, they
anonymously peer-review each other's answers, and the chairman synthesizes one
reply — anti-sycophantic, and willing to revise the verdict if you give new
information. Expand *Individual council answers* under any reply to see each
model's take before synthesis.

Calls per follow-up: `(council size × 2) + 1`, same as a full run. The session
stays stateless — the browser holds the idea, verdict, and conversation history
and sends them back with each question, so refreshing the page clears it.

## Configuration

All config lives in `.env` — no code changes needed to swap models:

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required. Get at openrouter.ai/keys |
| `COUNCIL_MODELS` | 4 models (see .env.example) | Comma-separated. **Check IDs at openrouter.ai/models** — they go stale. |
| `CHAIRMAN_MODEL` | claude-opus-4-5 | Final verdict model |
| `REQUEST_TIMEOUT` | 90 | Seconds per model call |

## Running tests (no API key needed)

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

Tests cover the `FINAL RANKING:` parser and a fully mocked end-to-end pipeline
run (no network, no real key).

## Tuning prompts

All prompts are in `prompts.py`. Edit `STAGE1_SYSTEM` to tune for your market
(e.g. UA B2B SaaS context, COD e-commerce specifics, etc.).

## Resilience

If one model fails, the council continues with the rest (minimum 2 participants).
Failures are shown in the UI rather than crashing the whole run. Results stream
progressively via SSE so you see each stage as it completes.
