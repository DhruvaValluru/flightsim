# Ruflo (github.com/ruvnet/ruflo) against the Phase 3 workflow

Written 2026-11-09 from a fresh clone of ruflo at commit `29be054e`
(package `ruflo` 3.74.1) and one real `init` run in an empty scratch
repository on Linux. Nothing here was run on the Windows laptop or the Mac.

## Verdict

**Not beneficial for the stated goal, and a poor fit for this repository's
rules. Keep it out of the main checkout.** Try it only in the sandbox that
`scripts/ruflo_sandbox.sh` creates, if at all.

The lacklustre renders are a renderer problem (see the analysis that led to
this: a 960 x 540 scene capture with two warm-up frames, hand-tuned
non-physical lighting, a forced dim storm look, coarse streamed tiles and
untextured hobby airframes, none of which Phase 3 graded). Ruflo is an agent
orchestration layer for Claude Code. It does not render anything, and the
work that would fix the pictures is C++ and material work that has to be
measured on the one machine with Unreal, which is already the bottleneck
Phase 3 ran into. More agents on the Mac do not shorten the queue on the
laptop.

## What ruflo is

An npm package plus Claude Code plugins. `npx ruflo init` writes into a
project:

| What | Measured in the scratch run |
|---|---|
| `CLAUDE.md` | 224 lines of ruflo's own guidance. Skipped when one exists (ours is kept), overwritten with a backup under `--force`. |
| `.claude/settings.json` | Hooks on PreToolUse, PostToolUse, UserPromptSubmit, SessionStart, SessionEnd, Stop, PreCompact, SubagentStop; a status line; `permissions.allow` for `npx claude-flow*` and every `mcp__claude-flow__*` tool; `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`; three plugins enabled. |
| `.claude/helpers/` | 43 shell and Node scripts. |
| `.claude/skills/`, `.claude/agents/`, `.claude/commands/` | 22 skills, 17 agents, 16 commands. |
| `.mcp.json` | An MCP server started with `npx -y ruflo@latest mcp start` (323 tools). |
| `.swarm/`, `.claude-flow/` | SQLite and vector memory databases, 2.2 MB on an empty repo. |
| Outside the project | Registers the `ruvnet/ruflo` marketplace and installs `ruflo-mods`, `ruflo-swarm` and `ruflo-console` into `~/.claude/plugins`; appends a "Ruflo Integration" block to the account-wide `~/.claude/CLAUDE.md`, which then applies to every project on that machine. The npx cache grew to 1.5 GB. |

The hooks are local Node scripts, about 50 ms each, and call no model. The
"routing" hook is keyword matching: the prompt "fix the exposure in the
render" routed to `coder` at 30 % confidence with the reason "Default
routing - no specific keyword matched". The optional daemon's twelve
background workers each spawn a headless `claude` session and, in ruflo's
own words, consume tokens continuously.

## Why it does not fit this repository

1. **It conflicts with CLAUDE.md.** The owner banned scheduled check-ins,
   `/loop`, cron and PR monitoring on 2026-09-25. Ruflo's `ruflo-loop-workers`
   plugin, its daemon and its "background workers" are exactly that. The
   plugin README describes `/loop` with `ScheduleWakeup` and `CronCreate`
   jobs for audit, optimisation and monitoring.
2. **Budget.** The Mac prompt runs in budget mode at 83 % of the weekly
   credit. Every ruflo swarm, worker and memory pass is additional model
   spend with no render in return.
3. **It duplicates what Phase 3 already built, with less control.** The two
   machines already talk through Remote Control and `SendMessage`, builders
   already fan out through `Workflow` (ultracode), state already lives in
   `docs/phase3/state/` and every command is already logged by
   `scripts/phase3_event.py`. Ruflo's swarm tools wrap the same native
   `Agent`, `SendMessage` and `TaskCreate` tools and add a memory database
   and a console pane on top.
4. **The dry run is not a dry run.** `npx ruflo@latest init --dry-run` wrote
   every file above and installed the plugins globally; the `--dry-run`
   flag is honoured only by `init --grok`. A tool that writes 90 files and
   changes `~/.claude` when asked to preview is not one to run in the main
   checkout of a repository whose settings are pinned by tests.
5. **Unsigned plugins that run host commands.** Ruflo's own scanner, printed
   during init, flags `ruflo-swarm` and `ruflo-console` as "runs host
   commands", "makes network requests" and "runs any tool, Bash included",
   and reports all three plugins as unsigned. They run with the account's
   permissions and are not sandboxed.
6. **Per-tool-call hooks on the laptop.** The Windows runner issues
   hundreds of commands per letter through `phase3_event.py`. A Node
   process before every Bash call and after every edit is overhead with no
   benefit to a render.

## What might be worth borrowing

Two ideas, not the package:

- **One addressable agent per role with explicit "message X when done"
  instructions**, spawned in one message. Phase 3 does this by hand through
  the Mac and Windows prompts; it works and needs no framework.
- **Cost per accepted result** as the metric for any multi-agent run.
  Ruflo's own guide says more agents are not automatically cheaper. Phase 3's
  budget stop on 2026-11-04 is the same lesson.

## If you still want to try it

```bash
bash scripts/ruflo_sandbox.sh
```

The script clones this repository into a sibling directory, checks out the
current branch there and runs `npx ruflo@latest init` inside that copy only.
The main checkout, its `CLAUDE.md` and its settings are untouched. Note that
`init` still registers the ruflo marketplace, installs three plugins
under `~/.claude/plugins` and appends a block to `~/.claude/CLAUDE.md`, all
for the whole account; remove the plugins with
`claude plugin uninstall <name>@ruflo` and delete the block by hand when
done (pass `--no-global` to init to skip the global `CLAUDE.md` write). Do not start the daemon on
either Phase 3 machine.

## Sources read

Ruflo `README.md`, `docs/STATUS.md`, `docs/USERGUIDE.md`,
`docs/ruflo-explained.md`, `docs/compare.md`,
`plugins/ruflo-swarm/README.md`, `plugins/ruflo-loop-workers/README.md`,
`v3/@claude-flow/cli/src/init/executor.ts`, `v3/@claude-flow/cli/src/commands/init.ts`,
and the files `init` wrote in the scratch run. This repository:
`CLAUDE.md`, `docs/phase3/PROMPT_MAC.md`, `docs/phase3/PROMPT_WINDOWS.md`,
`docs/phase3/decisions.md`, `docs/phase3/packets/B4-*.md`,
`docs/VISUAL_FIDELITY_PLAN.md`.
