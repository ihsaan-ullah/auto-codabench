# AutoCodabench

A scientific-friend assistant for designing and validating **Codabench** competitions.

---

## Pick what you want to do (at the start of every chat)

When a chat begins you choose one of two paths. To switch later, start a **New Chat** and choose again.

- **🛠 Create a bundle from scratch** — go through Plan → Build → Validate. Optionally drop a PDF/markdown proposal to seed the plan.
- **✅ I have a bundle — validate it** — skip straight to validation. The composer locks to *attach-only*: drop your bundle `.zip` and press send.

The **phase bar** at the top shows progress only (● in progress · ✓ done · ⤼ skipped). You move forward with the **▶ Proceed** buttons that appear in chat — clicking a pill just flashes this Readme.

---

## Path A — Create a bundle from scratch

**1. 📝 Plan.** Chat with the agent until it converges on a one-page `implementation_plan.md` covering the 7 design sections (task, data, metric, baseline, rules, ethics, schedule). Review it in the **workspace panel** on the right. When ready, click **▶ Proceed to Phase 2**.

**2. 📦 Build.** A fresh agent (no memory of the chat) reads the plan and writes the Codabench bundle — `competition.yaml`, `scoring_program/score.py`, the baseline `solution/`, and the standard pages — then validates and zips it. It also **builds and runs the bundle in Docker** using the `docker_image` from `competition.yaml` (**~5–10 min** for a verified bundle; longer on first run while the image pulls). You get a `bundle.zip` download and an **⬆️ Upload to Codabench** button. Click **▶ Proceed to Phase 3**.

**3. ✅ Validate.** See below — same as Path B, plus a **design scorecard** (Table A) comparing your plan against best practice.

---

## Path B — Validate an existing bundle

Attach your bundle `.zip` and press send. AutoCodabench runs the full check framework, **executing the baseline in Docker** (it pulls the `docker_image` if needed), and writes a report.

---

## What validation produces

A **✅ PASS / ❌ FAIL** verdict in chat plus two colorful tables, and a downloadable `validation_report.md`:

- **Table A — design scorecard** *(create-path only)*: each of the 7 design sections marked ✅ / ⚠️ / ❌ against best practice.
- **Table B — checks**: every check with ✅ pass / ❌ fail / ⚠️ finding / 📋 attestation / • skipped.
  - **Gate failures (❌)** must be fixed before upload (e.g. missing `competition.yaml` keys, broken file refs, a baseline that crashes in Docker).
  - **Findings (⚠️)** are advisory design risks (with citations) — they don't block upload.
  - **Attestations (📋)** are criteria only a human can certify.

After the report, you'll be offered an optional **✨ LLM-judged** pass: an LLM reads your participant-facing pages and flags **contradictions** against `competition.yaml` (e.g. a page promises a metric or submission limit the config doesn't declare). It's advisory only and needs Claude auth.

Everything is downloadable from the workspace panel: `implementation_plan.md`, `bundle.zip`, `validation_report.md`, and a combined `workspace.zip`.

---

## Internal note — operator checklist

(_For the project maintainer / internal testers._) This is a **private alpha**:

- Logs are uploaded to a private HF Dataset (`ktgiahieu/autocodabench-runs`).
- Each session has a hard Anthropic budget cap (default **$5.00**, via `MAX_USD_PER_SESSION`).
- HF Spaces is CPU-only, ≤16 GB RAM; if Docker isn't available, Phase 2 skips the runtime check and Phase 3's Docker execution checks report as *skipped* rather than failing.
