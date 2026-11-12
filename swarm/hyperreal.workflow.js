export const meta = {
  name: 'hyperreal-swarm',
  description: 'Build, verify and repair hyper-realism work items from swarm/manifest.json, sized to the probed Windows hardware',
  phases: [
    { title: 'Build', detail: 'one agent per work item: research sources, write code + tests in its lane' },
    { title: 'Verify', detail: 'two skeptics per item: refute the build (licence/provenance, gate honesty)' },
    { title: 'Repair', detail: 'one repair attempt per rejected item' },
  ],
}

// args: { items: [...manifest slice], budget: <hardware_budget.budget() dict>, wave: 'w1' }
// Run the manifest in waves of <=200 items (about 500 agents per wave, under the 1000-agent cap).
const items = args.items
const hw = args.budget
const RULES = `Project rules you must obey (CLAUDE.md, docs/VALIDITY.md): named sources only, sha256 and licence on every fetched asset, no non-commercial licences, no placeholder airframes, visual-only work labelled visual-only. Google tiles are the ground of every terrain render. You are in a Linux container: you cannot render or run UE. Anything that needs the Windows GPU is written, source-tested where possible, and marked UNMEASURED with the exact Windows command that would measure it. Never claim a visual result you did not measure. Write ONLY inside your lane directory (plus a test file tests/test_swarm_<id with dots as underscores>.py). Never touch another lane.`

const BUILD = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    sources: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, licence: { type: 'string' } }, required: ['name', 'licence'] } },
    measured: { type: 'array', items: { type: 'string' } },
    unmeasured_needs_windows: { type: 'array', items: { type: 'string' } },
    tests_pass: { type: 'boolean' },
  },
  required: ['files', 'sources', 'measured', 'unmeasured_needs_windows', 'tests_pass'],
}
const VERDICT = {
  type: 'object',
  properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } },
  required: ['refuted', 'reason'],
}

const buildPrompt = (it) => `${RULES}

Work item ${it.id}: ${it.component} for ${it.domain}, scenario "${it.scenario}" (${it.scenario_note}).
Gate: ${it.gate}.
Lane directory: ${it.lane_dir}
Hardware budget (starting point, unmeasured): tier ${hw.tier}, ${hw.usable_vram_mb} MB usable VRAM, hardware RT ${hw.hardware_ray_tracing}, max capture width ${hw.max_capture_width}.
Source classes to look for third-party components in: ${it.source_classes.join('; ')}.

1. Read the code that already exists for this component (grep core/, ue/Source, docs/) before adding anything.
2. Find the best third-party component or dataset for this scenario within the licence rule, or state that none exists.
3. Implement it as a small, tested module in your lane, with a PROVENANCE.json (source, url, licence, sha256).
4. Write a test for what is checkable here and run it. Report honestly.`

const verifyPrompt = (it, b, lens) => `Try to REFUTE this finished work item. Default to refuted=true if uncertain. Lens: ${lens}.
Item ${it.id}, lane ${it.lane_dir}. Builder report: ${JSON.stringify(b)}.
Read the actual files. For "licence": is every source real, named, and not non-commercial? For "honesty": does any file or report claim a visual or hardware result that was not measured here, or does the test pass vacuously?`

const results = await pipeline(
  items,
  (it) => agent(buildPrompt(it), { label: `build:${it.id}`, phase: 'Build', schema: BUILD }),
  async (b, it) => {
    if (!b) return { it, b, ok: false, why: 'builder died' }
    const votes = (await parallel(['licence', 'honesty'].map((lens) => () =>
      agent(verifyPrompt(it, b, lens), { label: `verify:${lens}:${it.id}`, phase: 'Verify', schema: VERDICT, effort: 'low' })))).filter(Boolean)
    const refutes = votes.filter((v) => v.refuted)
    return { it, b, ok: refutes.length === 0, why: refutes.map((v) => v.reason).join(' | ') }
  },
  async (r) => {
    if (r.ok || !r.b) return r
    const fixed = await agent(`${RULES}\n\nRepair work item ${r.it.id} in ${r.it.lane_dir}. Skeptics said: ${r.why}\nFix the files, or delete the claim that cannot be supported. Report in the same shape.`,
      { label: `repair:${r.it.id}`, phase: 'Repair', schema: BUILD })
    return { ...r, b: fixed || r.b, repaired: !!fixed }
  },
)

const done = results.filter(Boolean)
const passed = done.filter((r) => r.ok)
log(`wave ${args.wave}: ${passed.length} verified, ${done.length - passed.length} still rejected or failed, ${items.length - done.length} dropped`)
return {
  wave: args.wave,
  verified: passed.map((r) => r.it.id),
  rejected: done.filter((r) => !r.ok).map((r) => ({ id: r.it.id, why: r.why })),
  needs_windows: done.flatMap((r) => (r.b ? r.b.unmeasured_needs_windows.map((u) => `${r.it.id}: ${u}`) : [])),
}
