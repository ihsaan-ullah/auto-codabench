# AutoCodabench

A scientific-friend chat assistant for designing **Codabench** competitions.

This is a **private alpha** for invited collaborators. By signing in you
agree that:

- Your conversation lands in a per-session directory and is visible to
  the maintainer for postmortems.
- The session has a hard Anthropic API budget cap.
- The publish-to-Codabench step uses a shared account; please don't
  publish silly or inappropriate competitions.

### How to start

Sign in with the shared password (given to you out-of-band). The bot
will greet you and ask for your competition idea — a sentence is enough.

### Two phases

1. **Phase 1A — proposal crystallization.** The bot will explore your
   idea across motivation, data, evaluation, ethics, schedule, and
   sustainability. Expect many turns. Read papers it cites, push back,
   refine. When you're satisfied, say *"lock the proposal"* and the bot
   writes a NeurIPS-Competition-Track-style proposal to disk.

2. **Phase 1B (optional) — implementation skeleton.** If you also want
   the implementation specs and an executable plan, say *"ready to
   implement"*. Otherwise stop after the proposal.

Bundle building + Codabench publishing happen in **a fresh chat**, since
they benefit from a clean context window.
