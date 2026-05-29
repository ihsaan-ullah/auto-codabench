#!/usr/bin/env bash
# Symlink the experiment's agent definitions and required skills into
# .claude/ so Claude Code picks them up under its standard discovery paths.
# Idempotent: re-running is safe.
#
# .claude/ itself is gitignored — the source of truth for these agents and
# skills lives in experiments/bundle_creation_test/ (tracked). Symlinks
# are local only.

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

mkdir -p .claude/agents .claude/skills

echo "=== linking stage-agent definitions into .claude/agents/ ==="
# The 5 step-agents the orchestrator skill spawns via Task. The
# orchestrator itself is a SKILL (see next section), not an agent — it
# needs the Task tool, which is unavailable inside subagents.
for f in experiments/bundle_creation_test/agents/*.md; do
    name="$(basename "$f")"
    target="../../experiments/bundle_creation_test/agents/${name}"
    link=".claude/agents/${name}"
    ln -sfn "${target}" "${link}"
    printf "  %-44s -> %s\n" "${link}" "${target}"
done

# Sweep up any stale .claude/agents/ symlinks whose source dir no longer
# exists. Without this, removing a tracked agent file leaves a dangling
# symlink in .claude/agents/.
echo
echo "=== sweeping stale agent symlinks ==="
for link in .claude/agents/*.md; do
    [ -L "$link" ] || continue
    target_abs="$(readlink "$link" 2>/dev/null || true)"
    [ -e ".claude/agents/${target_abs}" ] || {
        echo "  removing stale symlink: ${link} -> ${target_abs}"
        rm -f "${link}"
    }
done

echo
echo "=== linking the orchestrator skill + autocodabench skills into .claude/skills/ ==="
# Two sources:
#   1. The bundle-creation-test orchestrator skill lives inside this experiment.
#   2. The autocodabench-* / competition-design / codabench-bundle skills
#      live in auto_codabench/ and are loaded by the stage agents via Skill(...).
#
# Each entry is "<skill_name>:<src_dir_relative_to_repo_root>".
SKILLS=(
    "bundle-creation-test:experiments/bundle_creation_test/skills/bundle-creation-test"
    "autocodabench-plan:auto_codabench/skills/plan"
    "autocodabench-implement:auto_codabench/skills/autocodabench-implement"
    "competition-design:auto_codabench/skills/competition-design"
    "codabench-bundle:auto_codabench/skills/codabench-bundle"
)
for entry in "${SKILLS[@]}"; do
    skill_name="${entry%%:*}"
    src="${entry#*:}"
    target="../../${src}"
    link=".claude/skills/${skill_name}"
    if [[ ! -d "${src}" ]]; then
        echo "  SKIP ${skill_name}: ${src} not found on disk"
        continue
    fi
    if [[ -e "${link}" || -L "${link}" ]]; then
        # If it's already a symlink to the right place, leave it.
        if [[ "$(readlink "${link}" 2>/dev/null || true)" == "${target}" ]]; then
            printf "  %-40s (already linked)\n" "${link}"
            continue
        fi
        # Otherwise replace.
    fi
    ln -sfn "${target}" "${link}"
    printf "  %-40s -> %s\n" "${link}" "${target}"
done

echo
echo "=== done ==="
echo "Verify with:  ls -la .claude/agents/ .claude/skills/"
echo
echo "Then in Claude Code top-level session, ask:"
echo '  "Run the bundle-creation experiment on <competition_sample_name>"'
echo "and Claude will load the bundle-creation-test skill, which then"
echo "spawns bundle-planner, bundle-implementer, bundle-validator-runner,"
echo "submission-reformatter, and submission-runner via the Task tool."
