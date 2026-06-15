# Agent eval — intent routing & calendar-slot extraction

The email-extraction layer has a field-level P/R/F1 eval (`docs/EVAL_REPORT.md`).
This document covers the **LLM-in-the-loop** paths added later: the intent
**router** and the conversation-driven calendar **slot extractor**. The model is
now genuinely in the loop on these surfaces, so they get measured, not assumed.

## What's measured

- **Routing** (`eval agent-routing`) — does a phrasing reach the right intent? The
  router is keyword-first with a model fallback, so the harness runs in two modes:
  - *keyword-only* (`--provider local`, no model): the deterministic layer. This is
    the **CI regression gate** — keyword-clear cases must score 1.0
    (`tests/test_agent_eval.py`).
  - *with model* (`--provider ollama`): the full path, including the cases only the
    model can place (paraphrases, cross-language, search intent).
- **Slot extraction** (`eval calendar-slots`) — from "add X to my calendar", does it
  extract the right `{title, date, time}`? Entirely model-driven, so it always needs
  a model (a live eval). `date` is the load-bearing field and is scored separately.

Golden sets: `evals/golden/agent/agent_routing.jsonl`,
`evals/golden/agent/calendar_slots.jsonl`. Each routing case carries a
`needs_model` flag so the CI gate and the live run can be separated.

> The model paths are **non-deterministic** — numbers move run-to-run. Treat a
> single run as a snapshot, not a fixed score. The keyword-only gate is the
> deterministic invariant.

## Run (qwen2.5:7b, local Ollama)

**Routing — 24 cases**

| metric | accuracy |
|---|---|
| overall (with model) | **1.00** |
| keyword-clear (no model, CI gate) | **1.00** |
| model-dependent (paraphrase/search/follow-up) | **1.00** |

By category: keyword 7/7, paraphrase 8/8, follow-up 4/4, search 2/2, greeting 3/3.
Keyword-only (no model) over the model-dependent cases is **0.29** — i.e. the model
is doing real work on the phrasings the keyword lists miss; the deterministic layer
alone only catches the continuation/greeting cases.

**Calendar slots — 12 cases**

| metric | accuracy |
|---|---|
| overall (all fields) | 0.75 |
| **date** | **0.67** |
| abstention (no-event → propose nothing) | 1.00 |

By category: absolute 2/3, english 1/1, range 1/1, no_event 3/3, relative 2/3,
**weekday_relative 0/1**.

## Finding → motivates the deterministic date resolver

Abstention and absolute/range dates are solid; **relative dates are the weak spot.**
Concretely, "下周三上午十点开组会" (today = Sunday 2026-06-14) was extracted as
**2026-06-20** — the correct next-Wednesday is **2026-06-17**. The prompt *does*
include "Today is 2026-06-14", so this isn't a missing-context problem: the model
has the date and botches the weekday arithmetic. "三天后" was dropped entirely.

That's the empirical case for resolving relative dates **deterministically**
(anchor on today, compute 明天/后天/N天后/下周X in code) rather than asking the model
to do calendar math — the user still confirms the date on the proposal card, so this
raises the default-correct rate without changing the trust model.

## Run it

```sh
# CI-safe deterministic gate (keyword router)
python -m sentineldesk eval agent-routing                       # --provider local

# Live, with the local model
python -m sentineldesk eval agent-routing  --provider ollama
python -m sentineldesk eval calendar-slots --provider ollama
python -m sentineldesk eval agent-routing  --provider ollama --json   # full report
```
