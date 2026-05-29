#!/usr/bin/env bash
# Symlink the experiment's agent definitions and required skills into
# .claude/ so Claude Code picks them up under its standard discovery paths.
# Idempotent: re-running is safe.
#
# .claude/ itself is gitignored — the source of truth for these agents lives
# in experiments/bundle_creation_test/agents/ (tracked). Symlinks are local
# only.

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

mkdir -p .claude/agents .claude/skills

echo "=== linking agent definitions into .claude/agents/ ==="
for f in experiments/bundle_creation_test/agents/*.md; do
    name="$(basename "$f")"
    target="../../experiments/bundle_creation_test/agents/${name}"
    link=".claude/agents/${name}"
    ln -sfn "${target}" "${link}"
    printf "  %-44s -> %s\n" "${link}" "${target}"
done

echo
echo "=== ensuring required skills exist under .claude/skills/ ==="
# Skills the experiment agents load via Skill(...).
# Each entry is "<skill_name>:<on-disk-dir-under-auto_codabench/skills>".
SKILLS=(
    "autocodabench-plan:plan"
    "autocodabench-implement:autocodabench-implement"
    "competition-design:competition-design"
    "codabench-bundle:codabench-bundle"
)
for entry in "${SKILLS[@]}"; do
    skill_name="${entry%%:*}"
    dir_name="${entry#*:}"
    src="auto_codabench/skills/${dir_name}"
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
echo "Then in Claude Code: ask the main session"
echo '  "Run the bundle-creation experiment on <competition_sample_name>"'
echo "and it will delegate to bundle-experiment-runner."
