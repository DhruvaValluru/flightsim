#!/usr/bin/env bash
# Try ruflo (github.com/ruvnet/ruflo) in a throwaway copy of this repository.
#
# docs/RUFLO_EVALUATION.md explains why it is kept out of the main checkout:
# `ruflo init` writes ~90 files, a settings.json with hooks on every tool
# call, memory databases and an MCP server, and its --dry-run flag is not a
# dry run. This script runs init in a sibling clone so CLAUDE.md, settings
# and the Phase 3 state here are never touched.
#
# Usage: bash scripts/ruflo_sandbox.sh [target-dir]
# Needs: git, node >= 20, npm (npx). Network for the npm download.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
target="${1:-$here/../flightsim-ruflo-sandbox}"
branch="$(git -C "$here" rev-parse --abbrev-ref HEAD)"

if [ -e "$target" ]; then
  echo "ruflo_sandbox: $target already exists; remove it or pass another path" >&2
  exit 1
fi
command -v node >/dev/null || { echo "ruflo_sandbox: node is not installed" >&2; exit 1; }
command -v npx  >/dev/null || { echo "ruflo_sandbox: npx is not installed" >&2; exit 1; }

echo "ruflo_sandbox: cloning $here ($branch) into $target"
git clone --quiet --branch "$branch" "$here" "$target"

echo "ruflo_sandbox: running ruflo init inside the sandbox only"
echo "  note: init also registers the ruvnet/ruflo marketplace and installs"
echo "  ruflo-mods, ruflo-swarm and ruflo-console under ~/.claude/plugins for"
echo "  this account; remove them with 'claude plugin uninstall <name>@ruflo'."
echo "  --no-global keeps it from appending to ~/.claude/CLAUDE.md."
(cd "$target" && npx -y ruflo@latest init --no-global)

cat <<EOF

ruflo_sandbox: done. Open Claude Code in
  $target
to try it. Rules that still apply there (CLAUDE.md): no scheduled check-ins,
no /loop, no PR subscriptions, so do not start 'ruflo daemon' or the
ruflo-loop-workers plugin. Delete the directory to undo everything except
the plugins named above.
EOF
