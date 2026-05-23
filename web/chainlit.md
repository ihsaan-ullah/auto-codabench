# AutoCodabench

A scientific-friend chat assistant for designing **Codabench** competitions.

---

## How this app works — 2 phases

The phase bar at the top of the page (three black pills next to **Readme**
and **New chat**) is your navigation surface. Each phase has its own
fresh agent and the chat history is dropped between phases — that's how
we keep cost predictable.

### 1. 📝 Plan *(you start here)*

Short roadmap conversation. The agent saves a one-page
`implementation_plan.md` covering all 7 design sections of a Codabench
competition (task, data, metric, baseline, rules, ethics, schedule).
Pure prose, no code.

Review the plan in the **workspace panel on the right** (📝
`implementation_plan.md` tab). When it looks right, click the
**▶ Advance to Phase 2** pill at the top.

### 2. 📦 Competition Creation

A *fresh* agent reads the locked plan and packages a Codabench `.zip`
directly:

- `competition.yaml`
- `scoring_program/score.py` — implements your metric
- `solution/sample_code_submission/model.py` — the baseline class from
  the plan
- four standard pages (overview, evaluation, terms, data)

After validation + zip, a 📦 `bundle.zip` tab appears in the
workspace panel for download. A one-click **⬆️ Upload to Codabench**
button also shows up in chat — clicking it publishes the competition
and surfaces the Codabench URL.

### Back-navigation

Once you're in Phase 2, the Phase 1 pill turns into a 🔒 lock. Click
it to **revise the plan** — that discards the bundle (regenerated when
you advance again) but preserves the plan itself. The plan is the
locked artifact; you can edit it, then advance forward to rebuild from
the updated version.

### Live telemetry

The end of each assistant turn shows a one-line footer:

```
turn ≈ $0.012 · session $0.34 / $5.00 · ctx 4.2% (8,415 tok)
```

That's your context-window usage and session-cost readout — same place
the Claude Code CLI puts them.

---

## Internal note — operator checklist

(_This block is for the project maintainer / internal testers. End
users can ignore it._)

### How to start

Sign in with the shared password (given to you out-of-band). The bot
will greet you and ask for your competition idea — a sentence is enough.

### Trial-account ground rules

This is a **private alpha** for invited collaborators. By signing in
you agree that:

- Your conversation lands in a per-session directory and is visible to
  the maintainer for postmortems (logs upload to a private HF Dataset
  repo named `autocodabench-runs`).
- The session has a hard Anthropic API budget cap (default **$5.00**;
  configurable via `MAX_USD_PER_SESSION`).
- The publish-to-Codabench step uses a **shared organizer account**
  (`ihsanchalearn`). Please don't publish silly or inappropriate
  competitions — they'll appear under that account.

### Backup branch

The 3-phase flow with an intermediate `starting_kit.ipynb` step lives
on branch `try-web-ui-with-starting-kit`. v1 web (this deploy) is
intentionally simpler — 2 phases, no notebook — for time-to-bundle.

### Known limitations

- Phase 2 picks sensible sklearn defaults if the plan doesn't fully
  specify a baseline / metric. If you want exact control, write those
  fields concretely in Phase 1 before advancing.
- HF Spaces is CPU-only, ≤16 GB RAM. Curated package whitelist:
  `numpy`, `pandas`, `scikit-learn`, `matplotlib`, `seaborn`, `scipy`,
  `pillow`.
- The Codabench upload step requires `CODABENCH_USERNAME` /
  `CODABENCH_PASSWORD` configured as Space Repository Secrets.
