---
title: AutoCodabench
emoji: 🧪
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Chat assistant for designing Codabench competitions.
---

# autocodabench

Agentic authoring and pre-launch validation of [Codabench](https://www.codabench.org)
competition bundles.

Organizing an ML competition on Codabench means hand-writing an interlocking
set of YAML configs, scoring programs, and data splits — and a single
inconsistency ships silently and fails on live participants. autocodabench
turns a one-line idea (or a proposal PDF) into a validated, uploadable
bundle, and tests bundles — generated *or* hand-written — the way software
is tested: against an executable checklist before launch.

> **This `README.md` is also the Hugging Face Spaces metadata file** — the
> YAML header above configures the Space (Docker SDK, port 7860). Don't
> delete it on the HF side; edit prose freely below.

## Quickstart (no API keys needed)

```bash
pip install -e .            # (PyPI release pending — install from a checkout)

# Watch the full pipeline offline: a recorded agent run is replayed against
# the real authoring layer, then validated and zipped.
autocodabench demo --out ./demo

# Validate ANY bundle — including one you wrote by hand.
codabench-validate ./demo/demo-ai-text-detection.zip

# What gets checked, by tier, with citations.
autocodabench checks list
```

The validator's checks come in three tiers with different standing:
**deterministic** checks gate (code computes pass/fail), **LLM-judged**
checks advise (findings with rationale, never gates), and **attestations**
surface launch criteria only a human can certify. Checks that need context
the bundle can't carry (anticipated error rate, unit of generalization)
read a declared `competition_facts.yaml` — and report *skipped, here's how
to enable me* rather than silently passing.

## Agentic authoring (Claude auth required)

```bash
autocodabench auth status     # which auth path is active
autocodabench create "Plankton image classification, balanced accuracy, \
    two phases" --data ./plankton_sample/
```

`create` runs two isolated agent sessions — plan, then build — joined only
by a locked, human-editable `implementation_plan.md`. The build agent acts
exclusively through a typed MCP tool surface, so every authoring action is
logged and the finished run is replayable.

**Auth, friendliest first:** if you have Claude Code installed and logged
in (Pro/Max), it just works — usage draws from your plan's monthly Agent
SDK credit. Otherwise export `ANTHROPIC_API_KEY`. Hosted multi-user
deployments (like the HF Space) must use an API key — see
[`docs/INSTRUCTION_FOR_USER.md`](docs/INSTRUCTION_FOR_USER.md).

## Where to look

| You are… | Read |
|----------|------|
| **Evaluating this software** (demo walkthrough + repo tour) | [`docs/demo-for-reviewers.md`](docs/demo-for-reviewers.md) |
| Asking what's scientifically tested, and how | [`docs/scientific-validation.md`](docs/scientific-validation.md) |
| Using the CLI or library | [`docs/INSTRUCTION_FOR_USER.md`](docs/INSTRUCTION_FOR_USER.md) |
| Trying the Web UI (Space or local `chainlit run`) | [`docs/INSTRUCTION_FOR_USER.md`](docs/INSTRUCTION_FOR_USER.md) §Web UI, then [`web/README.md`](web/README.md) to operate it |
| Hacking on the package | [`docs/architecture.md`](docs/architecture.md) |
| Skill provenance (where each `SKILL.md` came from) | [`src/autocodabench/skills/<name>/README.md`](src/autocodabench/skills/) |
| The end-to-end test harness | [`experiments/bundle_creation_test/README.md`](experiments/bundle_creation_test/README.md) |

## What's where

| Path | What it is |
|------|------------|
| `src/autocodabench/` | The library: core authoring, check framework, agent backends, plan→build pipeline, MCP server, CLI. |
| `web/` | Chainlit chat UI — a consumer of the library, deployed by this Space. |
| `experiments/` | The bundle-creation test harness (ground-truth competitions + leakage-controlled pipeline). |
| `tests/` | Unit suite — fast and fully keyless. |
| `Dockerfile` | Used by HF Spaces to build the image. |

## License

MIT.
