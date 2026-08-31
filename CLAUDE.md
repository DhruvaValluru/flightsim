# CLAUDE.md

Project context for Claude Code sessions in this repository.

## Platform branches — IMPORTANT

This repo has two long-lived branches for two platform states:

- **`master`** — the current, cross-platform version (works on Windows, Linux,
  and macOS). All new development happens here. The cross-platform work landed
  in commit `7bd98b7`.
- **`macos-original`** — a frozen snapshot of the last pure-macOS version from
  *before* any Windows compatibility changes (commit `e8fdd2d`). Never commit
  new work to this branch; it exists as a known-good fallback for the owner's
  MacBook.

### What the owner means by these phrases

- "switch it to mac" / "switch to the mac version" / "use the macbook one"
  → `git checkout macos-original`
- "switch it to windows" / "switch back" / "use the normal/current version"
  → `git checkout master`
- "make the mac version permanent" or similar → STOP and ask; that would mean
  discarding the cross-platform work on `master`, which is destructive.

Both are branches of this same clone — switching is a checkout, not a separate
download. If the owner wants both versions on disk at once, use
`git worktree add ../flightsim-mac macos-original`.
