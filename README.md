# AutoCodabench

**Author and pre-launch test [Codabench](https://www.codabench.org) competition bundles — the way you test software.**

[![PyPI](https://img.shields.io/badge/pypi-autocodabench-blue)](https://pypi.org/project/autocodabench)
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
pip install autocodabench

# Catch the bugs & missing best practices a checklist can catch.
autocodabench validate ./my-competition.zip

# Or go from idea to uploadable bundle (needs an LLM backend).
autocodabench plan-build-validate "Plankton image classification, balanced \
    accuracy, two phases" --data ./sample_data/
```

<!-- > **Note:** this `README.md` is also the Hugging Face Spaces metadata file —
> the YAML header above configures the Space (Docker SDK, port 7860). Don't
> delete it; the prose below it is free to edit. -->

## Requirements

`pip install autocodabench` covers the Python side. Two phases also need tools
pip can't install:

- **Docker** (daemon running) — for `build` and `validate --execute`, which run
  the bundle inside its `docker_image` exactly as Codabench does. Get
  [Docker Desktop](https://www.docker.com/products/docker-desktop/) or
  [Docker Engine](https://docs.docker.com/engine/install/).
- **Node/`npx`** (OpenAlex research) and **git** (Agent SDK) — optional.

Run `autocodabench doctor` to check all three. Phase-1 planning and the keyless
validator need none of it.

## Quick start
### Validation
```bash
pip install autocodabench        # or: pip install -e . from a checkout

# Validate any bundle — including one you wrote by hand.
autocodabench validate /path/to/bundle.zip

# See exactly what gets checked, by tier, with citations.
autocodabench checks list
```

We use a combination of deterministic and LLM-as-a-judge for validation:

| Type                    | What it does                                                  | Pass/fail?      |
| ----------------------- | ------------------------------------------------------------- | ----------- |
| **Deterministic** | Code computes PASS/FAIL (schema, splits, scoring round-trips) | ✅ Yes      |
| **LLM-judged**    | An LLM grades a rubric → advisory findings with rationale    | ❌ Advises  |
| **Attestation**   | Launch criteria only a human can certify                      | ❌ Surfaces |

When a fact is missing it reports *skipped, with instructions*. Every
check cites its source (Pavão et al. or the Codabench schema). The full
catalogue is in [`docs/autocodabench_checks.md`](docs/autocodabench_checks.md).

**Executable checks with Docker container.** autocodabench *executes* the bundle's baseline and starting-kit notebook inside the competition's declared `docker_image`, mounted the way Codabench's
worker mounts it, and iterates until both run.

**Bring your own backbone.** The agent runs on Claude by default, but every
agentic command takes `--backend` — local Ollama, OpenAI-compatible endpoints,
or any `URL#model`:

```bash
autocodabench validate bundle.zip                     # Claude (default)
autocodabench validate bundle.zip --model claude-opus-4-8
autocodabench validate bundle.zip --backend ollama:llama3.1     
autocodabench validate bundle.zip --judged --backend openai:gpt-4o
```

### The pipeline

Authoring runs in three phases you can chain or run on their own:

```bash
autocodabench plan  "<idea>" [--pdf proposal.pdf] [--data DIR]  # → implementation_plan.md
autocodabench build --run-dir <dir>                             # plan → bundle + .zip
autocodabench validate <bundle>                                 # pre-launch checks (keyless)
```

`plan-build-validate` (alias: `create`) runs all three as isolated agent
sessions joined only by a locked, human-editable `implementation_plan.md`. The
build agent acts exclusively through a typed MCP tool surface, so every action
is logged and the finished run is replayable.

## Authentication

For the agentic commands, in order of preference for local use:

1. **Claude subscription** — if Claude Code is installed and logged in (Pro/Max),
   nothing else is needed; usage draws on the plan's Agent SDK credit.
2. **API key** — export `ANTHROPIC_API_KEY`.

`autocodabench auth status` shows which path is active. Hosted multi-user
deployments **must** use an API key (Anthropic ToS) — see
[`docs/INSTRUCTION_FOR_USER.md`](docs/INSTRUCTION_FOR_USER.md).

## Web UI

A Chainlit chat UI (`web/`) wraps the library in a guided plan → build →
validate workspace.

**Host it yourself** — copy `.env.example` to `.env`, set `SHARED_PASSWORD` and
a Claude auth path, then:

```bash
pip install -e . && pip install -r web/requirements.txt
cd web && chainlit run app.py --host 127.0.0.1 --port 8500 -h
```

Open [http://127.0.0.1:8500](http://127.0.0.1:8500). See
[`web/README.md`](web/README.md) for the operator guide.

**Or try the hosted demo** — email
[autocodabench@googlegroups.com](mailto:autocodabench@googlegroups.com) for an
account (with a little free credit) at the
[hosted Space](https://ktgiahieu-autocodabench-alpha.hf.space/login), no install
required.

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
