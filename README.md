# AutoCodabench

**Author and pre-launch test [Codabench](https://www.codabench.org) competition bundles — the way you test software.**

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

</div>

---

A Codabench competition is a comlicated set of YAML configs, scoring
programs, and data splits. Small mistakes shipped can fail miserably for your live participants.
AutoCodabench helps organizers in two ways:

- **Validate** any bundle, generated or hand-written, against an executable
  checklist *before* you launch.
- **Plan and build** a validated, uploadable bundle from a one-line idea or a proposal
  PDF, with an LLM agent guiding you.

```bash
git clone https://github.com/ihsaan-ullah/auto-codabench.git
cd auto-codabench
pip install -e .          # editable install; add '[dev]' to run the tests

# Catch the bugs & missing best practices a checklist can catch.
autocodabench validate ./my-competition.zip

# Or go from idea to uploadable bundle (needs an LLM backend).
autocodabench plan-build-validate "Plankton image classification, balanced \
    accuracy, two phases" --data ./sample_data/
```

<!-- > **Note:** this `README.md` is also the Hugging Face Spaces metadata file —
> the YAML header above configures the Space (Docker SDK, port 7860). Don't
> delete it; the prose below it is free to edit. -->

## Prerequisites

- **Docker** (daemon running) — for `build` and `validate --execute`. Get
  [Docker Desktop](https://www.docker.com/products/docker-desktop/) or
  [Docker Engine](https://docs.docker.com/engine/install/).
- **Node/`npx`** for OpenAlex research

## Quick start

## Installation

``bash
git clone https://github.com/ihsaan-ullah/auto-codabench.git
cd auto-codabench
pip install -e .
``

### Validating competition bundle

```bash
autocodabench validate /path/to/bundle.zip
```

We use a combination of deterministic and LLM-as-a-judge for validation:

| Type                    | What it does                                                  |
| ----------------------- | ------------------------------------------------------------- |
| **Deterministic** | Code computes PASS/FAIL (schema, splits, scoring round-trips) |
| **LLM-judged**    | An LLM grades a rubric → advisory findings with rationale    |
| **Attestation**   | Criteria only a human can certify                             |

If a fact required for verification is missing, autocodabench reports *skipped*. 
The full checklist can be found in [`docs/autocodabench_checks.md`](docs/autocodabench_checks.md), or by running:
```bash
autocodabench checks list
```

**Choose another LLM:** 
The agent runs on Claude by default, but you can change LLM backbone with `--backend`:

```bash
autocodabench validate bundle.zip                     # Claude (default)
autocodabench validate bundle.zip --backend claude:claude-opus-4-8
autocodabench validate bundle.zip --backend ollama:llama3.1   
autocodabench validate bundle.zip --backend openai:gpt-4o
```

### Planning & creating competition bundle

```bash
autocodabench plan  "<idea>" [--pdf proposal.pdf] [--data DIR]  # → implementation_plan.md
autocodabench build --run-dir <dir>                             # plan → bundle + .zip

```
You can also run:
`plan-build-validate`: to execute all three commands at once.

## Claude authentication

Run this command to set up authentication if you are using Claude Code:
``bash
autocodabench auth status
``

The package currently supports 2 options:
1. **Claude subscription** — if Claude Code is installed and logged in (Pro/Max), usage draws on the plan's Agent SDK credit.
2. **Claude API key** — export `ANTHROPIC_API_KEY` before running.

`autocodabench auth status` shows which option is active.

## Web UI

A web UI that wraps the library is available in (`web/`). You can either:

1. **Host it yourself**: copy `.env.example` to `.env`, set `SHARED_PASSWORD` and a Claude auth path, then:

```bash
pip install -e . && pip install -r web/requirements.txt
cd web && chainlit run app.py --host 127.0.0.1 --port 8500 -h
```

You can then open [http://127.0.0.1:8500](http://127.0.0.1:8500). See
[`web/README.md`](web/README.md) for more details.

2. ** Try our hosted demo** — email
[autocodabench@googlegroups.com](mailto:autocodabench@googlegroups.com) for an
account (with a little free credit) at the
[hosted Space](https://ktgiahieu-autocodabench-alpha.hf.space/login), no installation required.

## Documentation

| If you want to…                             | Read                                                            |
| -------------------------------------------- | --------------------------------------------------------------- |
| Evaluate the software (demo + repo tour)     | [`docs/demo-for-reviewers.md`](docs/demo-for-reviewers.md)       |
| Know what `validate` checks, by tier       | [`docs/autocodabench_checks.md`](docs/autocodabench_checks.md)   |
| Understand what's scientifically tested      | [`docs/scientific-validation.md`](docs/scientific-validation.md) |
| Use the CLI or library                       | [`docs/INSTRUCTION_FOR_USER.md`](docs/INSTRUCTION_FOR_USER.md)   |
| Work on the package internals                | [`docs/architecture.md`](docs/architecture.md)                   |
| Run the end-to-end benchmarks (any backbone) | [`benchmark/README.md`](benchmark/README.md)                     |

## Repository layout

| Path                   | Contents                                                                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/autocodabench/` | The library: core authoring, check framework, agent backends, plan→build pipeline, MCP server, CLI.                                                            |
| `web/`               | Chainlit chat UI — a consumer of the library, deployed by the Space.                                                                                           |
| `benchmark/`         | Pure-SDK end-to-end benchmarks (any backbone): create-bench and validate-bench, with ground-truth competitions and a reproducible, leakage-controlled pipeline. |
| `tests/`             | Unit suite — fast and fully keyless.                                                                                                                           |
| `Dockerfile`         | Builds the HF Spaces image.                                                                                                                                     |

## License

MIT.
`</content>`
`</invoke>`
