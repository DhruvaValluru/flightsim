#!/usr/bin/env bash
# Phase 3 integrator, the mechanical half (owner's rule 2026-11-04: the model
# reviews fit; this script merges, tests, checks guards, cleans up).
#   [BRANCH=p3-<box>r] bash scripts/phase3_integrate.sh <box> <pytest paths...>
# Runs from the MAIN checkout on phase-2-final. Merges branch p3-<box> with
# --no-ff, runs the given tests (never the suite), checks the mutation guards
# whose target files the merge touched (--check-targets), runs the diff guard,
# removes ../p3-<box>, and records stage=integrated. Exit 0 only when all pass;
# on a failing step the merge is left in place for the integrator to read, and
# the step is named.
set -u
box="${1:?box}"; shift
tests=("$@")
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
py="$root/.venv/bin/python"
log() { python3 scripts/phase3_event.py log --agent integrator --box "$box" --stage build --note "$1" >/dev/null; }
step() { echo "== $1"; }
branch="${BRANCH:-p3-$box}"
git rev-parse --verify -q "$branch" >/dev/null || { echo "FAIL no branch $branch"; exit 2; }
[ "$(git branch --show-current)" = "phase-2-final" ] || { echo "FAIL not on phase-2-final"; exit 2; }
if ! git diff --quiet -- docs/phase3 || ! git diff --cached --quiet -- docs/phase3; then
  git add docs/phase3 && git commit -qm "Phase 3: bookkeeping before merging $branch

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TYf9hdwcEyKovqfAJKwdzh" >/dev/null
fi
if ! git diff --quiet || ! git diff --cached --quiet; then echo "FAIL dirty working tree outside docs/phase3"; git status --short; exit 2; fi
base="$(git merge-base HEAD "$branch")"
step "merge $branch --no-ff"
if ! git merge --no-ff "$branch" -m "Merge $branch: $box

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TYf9hdwcEyKovqfAJKwdzh" >/dev/null 2>&1; then
  # bookkeeping conflicts resolve to MAIN's copy; anything else is the model's call
  conflicts="$(git diff --name-only --diff-filter=U)"
  others="$(echo "$conflicts" | grep -v '^docs/phase3/' || true)"
  if [ -n "$others" ]; then echo "FAIL merge conflicts outside docs/phase3:"; echo "$others"; exit 3; fi
  for f in $conflicts; do git checkout --ours -- "$f" && git add -- "$f"; done
  git -c core.editor=true commit --no-edit >/dev/null || { echo "FAIL could not finish the merge"; exit 3; }
  echo "   bookkeeping conflicts resolved to MAIN: $conflicts"
fi
merge="$(git rev-parse --short HEAD)"
changed="$(git diff --name-only "$base" "$branch" -- . ':!docs/phase3')"   # the branch's own side only
step "diff guard"
if git diff "$base" "$branch" -- . ':!docs/phase3' | grep -n "GOOGLE_TILES\|WEATHER_BACKEND\|subscribe"; then echo "FAIL diff guard hit (review the lines above)"; exit 4; fi
step "tests: ${tests[*]:-none}"
if [ "${#tests[@]}" -gt 0 ]; then
  if ! "$py" -m pytest -q -p no:cacheprovider --durations=5 "${tests[@]}"; then echo "FAIL tests"; log "integrate.sh $box: tests FAILED after merge $merge"; exit 5; fi
fi
step "mutation guard targets for touched files"
labels="$(bash scripts/mutation_check.sh --list 2>/dev/null | while IFS= read -r line; do
  f="$(echo "$line" | sed -n 's/.*(\(.*\))$/\1/p')"; [ -n "$f" ] || continue
  echo "$changed" | grep -qx "$f" && echo "$line" | sed -n 's/^ *\[[0-9]*\/[0-9]*\] \(.*\)  (.*$/\1/p' | sed 's/[][\.*^$+?(){}|\\]/\\&/g'; done | paste -sd'|' -)"
if [ -n "$labels" ]; then
  if ! bash scripts/mutation_check.sh --check-targets --match "$labels"; then echo "FAIL a guard target no longer matches; retarget it in scripts/mutation_check.sh"; exit 6; fi
else echo "   no guards target the touched files"; fi
step "cleanup"
git worktree remove --force "../${branch}" 2>/dev/null || true
python3 scripts/phase3_state.py set "$box" stage=integrated integrated_commit="\"$merge\"" >/dev/null
log "integrate.sh $box: merged $merge, tests exit 0, guard targets ok, diff guard clean"
echo "OK $box integrated as $merge"
