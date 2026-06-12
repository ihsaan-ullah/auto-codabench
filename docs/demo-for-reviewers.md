# autocodabench — evaluator's guide

A self-contained guide for evaluating this software: a **zero-install web
demo** (Part A), a **five-minute local evaluation** that needs no accounts
or API keys (Part B), and a **guided tour of the repository** with the
engineering and scientific standards to check it against (Part C).

The scientific companion — what the software claims, how each claim is
tested, and how to reproduce every test — is
[`scientific-validation.md`](./scientific-validation.md). If you read only
one document, read that one.

---

## Part A — Web demo (browser only, ~10 minutes)

You need: the Space URL and the shared password (provided by the
maintainer). Nothing is installed on your machine; sessions are
cost-capped server-side.

1. **Open the Space URL** and sign in — any username, plus the shared
   password.
2. You land in **Phase 1 (Plan)**. Type a competition idea, e.g.:
   > *Design a competition on detecting AI-generated text.*
3. The agent drafts the seven design dimensions (task framing, data,
   metric, baselines, phases, rules, schedule) and asks **1–2 scoping
   questions**. Answer them (or say "use your defaults"). Note that
   design proposals carry **citations** — the design rules come from
   Pavão et al. (2024), *AI Competitions and Benchmarks*, not from model
   improvisation.
4. When the agent saves `implementation_plan.md`, the right-hand
   workspace panel shows the rendered plan. **This document is the
   entire interface between phases** — Phase 2 starts with no memory of
   the chat, only this file. That is the auditability mechanism, not a
   UI quirk.
5. Click **▶ Advance to Phase 2 — Competition Creation** in the phase
   bar. A fresh agent reads the plan and writes the bundle; you'll see
   one chip per tool call (`init_bundle`, `write_scoring_program`,
   `write_competition_yaml`, …). Each chip expands to the exact input
   and output JSON of that call — the audit trail, live.
6. When it finishes, the workspace footer offers **📦 competition bundle
   (.zip)** (the uploadable artifact) and **workspace.zip** (the full
   session record: plan, transcript, every tool call).
7. *(Optional)* The **Publish to Codabench** form uploads the zip with
   credentials you type; it goes straight to codabench.org, never
   through the model. Skip unless you want a live competition under
   your account.

Each turn's footer shows the running cost against the session cap.

**What the web demo does and doesn't show.** It demonstrates the
plan→build flow, phase isolation, and the per-action audit trail. The
validator (the scientific core) is better exercised locally — Part B.

---

## Part B — Local evaluation, keyless (~5 minutes)

Needs Python ≥ 3.10. No Anthropic account, no API key, no network after
install.

```bash
git clone <repo-url> && cd auto-codabench
pip install -e '.[dev]'

# 1. The unit suite: 41 tests, < 1 s, keyless by policy.
python -m pytest tests/

# 2. Offline end-to-end: a recorded agent run is REPLAYED against the
#    real authoring layer — the bundle is genuinely rebuilt on your
#    machine, then validated and zipped. Deterministic; no model access.
autocodabench demo --out /tmp/demo

# 3. The validator on the result (also works on any hand-written bundle).
codabench-validate /tmp/demo/demo-ai-text-detection.zip

# 4. The executable checklist: every check, its tier, its citation.
autocodabench checks list
```

Read the validation report's four sections deliberately — they encode the
project's epistemics: **Gate failures** (code-computed, blocking),
**Findings** (advisory design risks, each with a citation), **Attestations
required** (human-only criteria the tool refuses to pretend to verify),
**Skipped** (checks whose declared facts are missing — loud, not silent).

If you have Claude auth available (a Claude Pro/Max login via Claude
Code, or `ANTHROPIC_API_KEY`), two more probes are worthwhile:

```bash
codabench-validate /tmp/demo/demo-ai-text-detection --judged
# → the LLM-judged tier. Then plant a contradiction and re-run:
#   edit pages/overview.md to claim "max 20 submissions/day"
#   (the config enforces 5) — the judge should flag exactly that line.

autocodabench create "Iris species classification from tabular \
    measurements, balanced accuracy, result submission" --verbose
# → the full live pipeline (~10–20 min, ~$2–4): plan → build →
#   self-validation (the bundle's own baseline + notebook must execute)
#   → validation report.
```

---

## Part C — Reading the repository

### Suggested order (~1 hour)

| # | Read | What it answers |
|---|------|-----------------|
| 1 | `README.md` | What the tool is, the friction it removes |
| 2 | [`docs/scientific-validation.md`](./scientific-validation.md) | The claims, every test type with exact procedure and oracle, designed experiments, threats to validity |
| 3 | [`docs/architecture.md`](./architecture.md) | Layering, the backend seam, design rationale, invariants |
| 4 | `src/autocodabench/checks/` (start at `base.py`, then `deterministic.py`) | The check contract in code — compare against what §3.4 of the scientific doc promises |
| 5 | `tests/` | What is actually asserted (note `tests/conftest.py`: the test fixture **is** the replay demo) |
| 6 | `experiments/bundle_creation_test/README.md` | The ground-truth experiment design, incl. the data-leakage/blinding protocol |
| 7 | `src/autocodabench/skills/*/SKILL.md` + sibling READMEs | The agents' behavioral contracts and their provenance |

### Engineering standards checklist (verify, don't trust)

| Standard | Where to verify |
|---|---|
| OSI license | `LICENSE` / `pyproject.toml` (MIT) |
| Installable package | `pip install -e .`; console scripts `autocodabench`, `codabench-validate` |
| Test suite, keyless, fast | `python -m pytest tests/` |
| CI on every push (3.10–3.13, Linux+macOS, incl. offline E2E and wheel-content check) | `.github/workflows/ci.yml` |
| Versioning + changelog | `CHANGELOG.md`, `autocodabench --version` |
| Docs beyond a README | `docs/` (user guide, architecture, this guide, scientific validation) |
| Reproducible runs | any run dir: `tool_calls/`, `events.jsonl`, `meta.json` (model + git SHA recorded) |
| Honest limitations | `scientific-validation.md` §5; the attestation tier itself |

### Questions a skeptical reviewer should ask — and where the answer lives

- *"Isn't this just a wrapper around a chatbot?"* — The contribution is
  the scaffolding, inspectable in code: the typed tool surface the agent
  is confined to (`mcp/tools/`), phase isolation through a locked plan
  (`agent/pipeline.py`), execution oracles independent of the agent
  (`runner/execution.py`), the three-tier check registry (`checks/`),
  and record/replay (`backends/replay.py`). The keyless demo runs the
  entire stack minus the model.
- *"How can a non-deterministic generator be tested?"* — §2 and §3.3 of
  `scientific-validation.md`: artifact-level oracles, repeated-run
  success rates, and a deterministic sub-model layer proven by replay.
- *"Does the LLM grade its own homework?"* — No: generation verdicts
  come from code (linter, sandbox exit codes, parsed scores). The one
  LLM-judged check is advisory by construction and degrades to SKIPPED
  when unparseable (`checks/judged.py`, ~30 lines of policy).
- *"What's the evidence so far vs. planned?"* — Status tags throughout
  `scientific-validation.md`: implemented (with commands), piloted
  (N=1, artifacts retained), designed (E1–E4 protocols).
