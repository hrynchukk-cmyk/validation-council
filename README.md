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

## Discover mode (the council in reverse)

The **💡 Discover ideas** tab runs the same council backwards: instead of judging
your idea, it proposes the **top 3 ideas with a real signal of willingness to
pay** — problems people or companies already spend money on (competitors,
agencies, manual workarounds, lost revenue), not hype.

Discover is deliberately **self-critical** — the council attacks its own ideas
before showing them to you, so it runs one extra stage (and costs more) than the
other modes:

- **Stage 1 — ideas + self-critique.** Each model proposes 3 ideas, each requiring
  a named payer and concrete evidence of existing spend, and must argue *why the
  idea probably does not work* (`WHY THIS MIGHT FAIL`, `MOST LIKELY FAILURE MODE`)
  before offering a fix — including "NO CREDIBLE FIX" when that is the honest answer.
- **Stage 2 — red-team deep dive.** Every model then attacks the *pooled, anonymous*
  ideas with one job: kill them. It audits whether the payment signal is real or
  assumed, who literally signs the cheque, what the incumbent does in response,
  distribution cost, hidden killers (regulation, liability, data access, churn),
  and whether the "cheapest test" is a disguised survey. Each idea gets a verdict:
  SURVIVES / WOUNDED / DEAD, plus what would save it.
- **Stage 3 — anonymous peer review.** Ranks the idea sets by payment signal *and*
  how well they survived the attack, rewarding proposers who named the real
  weakness themselves and penalizing token self-criticism.
- **Stage 4 — chairman's top 3.** Picks the ideas that best survived, and must
  carry the strongest surviving objection into each one: payer & payment signal,
  why now, **why this might fail**, **how to de-risk it**, riskiest assumption,
  cheapest test, and **survival odds** (LOW / MEDIUM / HIGH).

Give optional constraints (market, B2B/B2C, your skills, a domain) or leave it
empty to scan broadly. Calls per run: `(council size × 3) + 1` — one pass more than
the other modes, by design. Expand *Council proposals* and *Red-team findings* to
see the raw ideas and the attacks on them before synthesis.

Like the validate tab, Discover has a **follow-up chat**: after the top 3 are
shown you can ask the council to go deeper on an idea or weigh a variation, and
the same answer → peer review → chairman synthesis runs again — staying anti-hype
and tracing every recommendation back to who pays. The chat is handed the
red-team findings too, so an objection stands until you actually answer it.
Calls per follow-up: `(council size × 2) + 1`.

## Audit mode (pre-contract requirements risk auditor)

The **🔍 Requirements audit** tab is for software agencies pricing **fixed-price**
projects. A PM pastes the client's requirements (and optional delivery context —
domain, stack, team, deadline, budget) and the council audits them for delivery
risk **before** a number is committed — flagging ambiguities and incompleteness
that cause fixed-price disputes.

- **Stage 1** — each model audits the requirements as a senior architect /
  delivery lead: domain read, ambiguities, missing info, implementation risks,
  a **ranged effort estimate** (with confidence and stated assumptions), and the
  questions to ask the client before pricing.
- **Stage 2** — anonymous peer review ranks the audits by how well they surface
  real risk and how realistic the estimates are.
- **Stage 3** — the chairman delivers one consolidated report with a **pricing
  risk level** (LOW / MEDIUM / HIGH / CRITICAL), top ambiguities, key risks, a
  consolidated estimate range, must-ask questions, and a recommendation
  (price now / clarify first / re-scope / walk away).

**Work-with-the-council chat.** After the report you can keep talking to the
council to clarify a risk, **re-estimate a module** given new information, draft
client-facing questions, and — importantly — ask it to **write precise,
implementation-ready development prompts** for a feature (goal, scope, data model,
API, business rules, acceptance criteria, edge cases, non-functional needs),
ready to hand to an engineer or an AI coding tool. Every council answer has a
**Copy** button. Calls per run / per follow-up: `(council size × 2) + 1`.

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
