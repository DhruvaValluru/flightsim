export const meta = {
  name: 'max-push',
  description: 'Competing builders per component, judged, skeptic-checked, deepened, then reconciled per scenario, for the Windows laptop',
  phases: [
    { title: 'Research', detail: 'sources, existing defects, adoptable niche repos from discoveries.json' },
    { title: 'Panel', detail: 'three competing builders from different angles on priority items' },
    { title: 'Judge', detail: 'one judge picks the winner and grafts the best ideas from the others' },
    { title: 'Verify', detail: 'skeptics: licence, honesty, laptop budget' },
    { title: 'Repair', detail: 'one repair per rejected item' },
    { title: 'Deepen', detail: 'critic names what a trained eye would call fake, then closes it' },
    { title: 'Coherence', detail: 'one agent per scenario reconciles every component into one consistent look' },
  ],
}

// args: { items, budget, wave, rounds?, priority?: [item ids], discoveries?: [ranked candidates] }
const items = args.items
const hw = args.budget
const ROUNDS = args.rounds === undefined ? 2 : args.rounds
const PRIORITY = new Set(args.priority || [])
const DISC = args.discoveries || []
// Cost controls: skipResearch reuses discoveries instead of a research agent; lenses overrides the skeptic set;
// verifyModel runs skeptics on a cheaper model; coherence:false skips the scenario pass; reserve is the
// output-token floor below which no new agent is started (needs a "+Nk" token target in the prompt).
const SKIP = !!args.skipResearch
const VMODEL = args.verifyModel
// The token pool is shared with the main session, so it may already be partly spent at launch.
// The floor therefore scales with what was available at the start (never more than 15% of it),
// and the numbers are logged so a stopped run says why.
const R0 = budget.total ? budget.remaining() : Infinity
const FLOOR = Math.min(args.reserve || 60000, Math.floor(R0 * 0.15))
log(`token target ${budget.total}, remaining at start ${R0}, floor ${FLOOR}`)
if (budget.total && R0 < 150000) log(`WARNING: only ${R0} tokens left under the target; raise it (e.g. +1M) or this wave will be cut short`)
const out = () => !!budget.total && budget.remaining() < FLOOR
const vopt = (o) => (VMODEL ? { ...o, model: VMODEL } : o)

const LAPTOP = `THE TARGET MACHINE (the Windows test laptop): Intel integrated GPU, Direct3D 11 / Shader Model 5 only (no D3D12, no Lumen, no hardware ray tracing, no Nanite assumptions), shared memory, display 1536x960, RAM unmeasured and tight (one UE render process used 3.8 GB and background jobs were OOM-killed), C: has about 60 GB free, and it hit 12 "device lost" crashes on scene 9. Starting budget: ${JSON.stringify(hw)}.
GOAL: the most photorealistic result this machine can SUSTAIN for your component, judged on rendered frames. Not the prettiest idea: the best frame that renders without device loss.
KEY MOVE: the Mac (64 GB, M1 Max) precomputes what the laptop cannot: atmosphere/sky LUTs, baked AO and lightmaps, normal and roughness maps, flipbooks and impostors, texture atlases, BC-compressed mip chains, fake shadows, precomputed wave/cloud/rain textures, tiled detail maps. The render path only samples them.
TIERS: tier 0 must be stable on this laptop; tiers 1-3 are heavier for the stress ladder to try. State VRAM/cost as ESTIMATES. Never claim a tier is sustained.
ADOPT BEFORE WRITING: a small niche third-party repo, shader or dataset that already does the job beats writing it yourself. Vendor it with a pinned commit, licence file and sha256 in PROVENANCE.json; downloaded code is untrusted, read it, do not execute it.`

const RULES = `Project rules (CLAUDE.md, docs/VALIDITY.md): named sources only, sha256 and licence on every fetched asset, no non-commercial licences, no placeholder airframes, visual-only work labelled visual-only. Google tiles are the ground of every terrain render and are ON unless FLIGHTSIM_GOOGLE_TILES=off; the web app's weather defaults stay on. You run on a MacBook: you cannot run the pinned Windows UE build or the laptop GPU, so anything that needs it is written, source-tested here where possible, and marked UNMEASURED with the exact Windows command. Never claim a visual result you did not measure. Write ONLY inside your lane directory plus tests/test_swarm_<id with dots as underscores>.py. Never edit shared files (ue/Source, core/scene, core/render, webapp): put the exact proposed change in <lane>/INTEGRATION.md for the integrator.`

const BUILD = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    sources: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, licence: { type: 'string' } }, required: ['name', 'licence'] } },
    tiers: { type: 'array', items: { type: 'object', properties: { tier: { type: 'integer' }, est_vram_mb: { type: 'number' }, summary: { type: 'string' } }, required: ['tier', 'est_vram_mb', 'summary'] } },
    baked_offline: { type: 'array', items: { type: 'string' } },
    pixel_gate: { type: 'object', properties: { windows_command: { type: 'string' }, metric: { type: 'string' }, threshold: { type: 'string' } }, required: ['windows_command', 'metric', 'threshold'] },
    shared_params: { type: 'object', description: 'look parameters other components in this scenario must agree with: exposure_ev, sun_elevation_deg, haze_density, ground_albedo, colour_temperature_k, etc' },
    measured: { type: 'array', items: { type: 'string' } },
    unmeasured_needs_windows: { type: 'array', items: { type: 'string' } },
    tests_pass: { type: 'boolean' },
  },
  required: ['files', 'sources', 'tiers', 'baked_offline', 'pixel_gate', 'measured', 'unmeasured_needs_windows', 'tests_pass'],
}
const RESEARCH = {
  type: 'object',
  properties: {
    candidates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, licence: { type: 'string' }, why: { type: 'string' } }, required: ['name', 'licence', 'why'] } },
    existing_defects: { type: 'array', items: { type: 'string' } },
    reference_truth: { type: 'array', items: { type: 'string' }, description: 'real measurements, photos or datasets this component can be compared against' },
    risks_on_igpu: { type: 'array', items: { type: 'string' } },
    plan: { type: 'string' },
  },
  required: ['candidates', 'existing_defects', 'reference_truth', 'risks_on_igpu', 'plan'],
}
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['refuted', 'reason'] }

const ANGLES = [
  ['physical', 'derive it from the physics and published radiometry; correctness first, then bake it'],
  ['data', 'drive it from real measured data, scans, photographs and open datasets; fidelity to reality first'],
  ['cheat', 'the cheapest convincing fake: maximum offline precomputation, minimum render cost, adopt a niche repo'],
]

const discFor = (it) => DISC.filter((d) => d.domain === it.domain).slice(0, 8)

const researchPrompt = (it) => `${LAPTOP}\n\n${RULES}\n\nRESEARCH ONLY, write no code. Item ${it.id}: ${it.component} for ${it.domain}, scenario "${it.scenario}" (${it.scenario_note}). Gate: ${it.gate}.
Already-discovered candidates for this domain (verify them, then go beyond them): ${JSON.stringify(discFor(it))}.
Find the real current defects (core/, ue/Source, docs/visual, git log), then the best open techniques, papers, tiny repos and CC0/CC-BY assets. Name the real-world reference this component should be compared against. Name what will crash a D3D11 Intel iGPU.`

const buildPrompt = (it, research, angle) => `${LAPTOP}\n\n${RULES}\n\nRESEARCH (use it, do not trust it blindly): ${JSON.stringify(research)}\n
Item ${it.id}: ${it.component} for ${it.domain}, scenario "${it.scenario}" (${it.scenario_note}). Gate: ${it.gate}.
${angle ? `YOUR ANGLE: ${angle[0]}: ${angle[1]}. Write only in ${it.lane_dir}/${angle[0]}/.` : `Lane directory: ${it.lane_dir}`}
Deliver: the offline generator on the Mac, tiered render-side description, PROVENANCE.json, INTEGRATION.md, a test for what is checkable here, and a pixel_gate: the exact Windows command, the numeric metric and the threshold that would show your change improved the frame against the reference. Fill shared_params with the look parameters other components of this scenario must match.`

const verifyPrompt = (it, b, lens) => {
  const what = {
    licence: 'Is every source real, named, and not non-commercial? Is sha256/licence/pinned commit recorded for anything vendored?',
    honesty: 'Does any file or report claim a visual or hardware result that was not measured here, or does a test pass vacuously? Is the pixel_gate a real measurable command?',
    budget: `Would tier 0 plausibly run on an Intel iGPU, D3D11 SM5, ~${hw.usable_vram_mb} MB texture pool, no Lumen/HWRT, under 4 GB process RAM? Refute if tier 0 needs D3D12, Nanite, Lumen, hardware RT, or more memory.`,
  }[lens]
  return `Try to REFUTE this finished work item. Default to refuted=true if uncertain. Lens: ${lens}. ${what}\nItem ${it.id}, lane ${it.lane_dir}. Builder report: ${JSON.stringify(b)}. Read the actual files.`
}

const results = await pipeline(
  items,
  // A stage that returns null drops the item from the pipeline, so skipping research must return a non-null marker.
  (it) => SKIP ? { skipped: true } : (out() ? null : agent(researchPrompt(it), { label: `research:${it.id}`, phase: 'Research', schema: RESEARCH, effort: 'high' })),
  async (research, it) => {
    if (out()) return null
    const r = SKIP ? { candidates: discFor(it), note: 'from discoveries.json, UNVETTED: verify the licence before use' } : (research || {})
    if (!PRIORITY.has(it.id)) return agent(buildPrompt(it, r, null), { label: `build:${it.id}`, phase: 'Panel', schema: BUILD })
    const panel = (await parallel(ANGLES.map((a) => () =>
      agent(buildPrompt(it, r, a), { label: `panel:${a[0]}:${it.id}`, phase: 'Panel', schema: BUILD })))).filter(Boolean)
    if (panel.length < 2) return panel[0] || null
    return agent(`${LAPTOP}\n\n${RULES}\n\nJUDGE item ${it.id}. ${panel.length} builders competed, each in ${it.lane_dir}/<angle>/. Reports: ${JSON.stringify(panel)}.\nRead all of them. Pick the winner on realism per iGPU cost and honesty of evidence, copy it to ${it.lane_dir}/ as the final lane, graft in the best ideas from the others (with their provenance), and delete the losing subfolders. Report the final lane in the same shape.`,
      { label: `judge:${it.id}`, phase: 'Judge', schema: BUILD, effort: 'high' })
  },
  async (b, it) => {
    if (!b) return { it, b, ok: false, why: 'builder died' }
    const lenses = args.lenses || (PRIORITY.has(it.id) ? ['licence', 'honesty', 'budget'] : ['honesty', 'budget'])
    const votes = (await parallel(lenses.map((lens) => () =>
      agent(verifyPrompt(it, b, lens), vopt({ label: `verify:${lens}:${it.id}`, phase: 'Verify', schema: VERDICT, effort: 'low' }))))).filter(Boolean)
    const refutes = votes.filter((v) => v.refuted)
    return { it, b, ok: refutes.length === 0, why: refutes.map((v) => v.reason).join(' | ') }
  },
  async (r) => {
    if (r.ok || !r.b || out()) return r
    const fixed = await agent(`${LAPTOP}\n\n${RULES}\n\nRepair item ${r.it.id} in ${r.it.lane_dir}. Skeptics said: ${r.why}\nFix the files or delete the claim that cannot be supported. Same report shape.`,
      { label: `repair:${r.it.id}`, phase: 'Repair', schema: BUILD })
    return { ...r, b: fixed || r.b, repaired: !!fixed, ok: !!fixed }
  },
  async (r) => {
    let cur = r
    for (let k = 1; k <= ROUNDS && cur.ok && cur.b && !out(); k++) {
      const next = await agent(`${LAPTOP}\n\n${RULES}\n\nDEEPEN round ${k}/${ROUNDS} for ${cur.it.id} in ${cur.it.lane_dir}. Current report: ${JSON.stringify(cur.b)}.\nAct as a trained observer (pilot, aerial photographer, VFX supervisor): list the 3 things in this component that would still read as fake in a frame, pick the one that matters most, and close it with a better bake, a sharper tier ladder, a missing scenario case, a niche repo you have not tried, or a stronger test. Do not weaken earlier tiers. Same report shape.`,
        { label: `deepen${k}:${cur.it.id}`, phase: 'Deepen', schema: BUILD })
      if (!next) break
      const checks = (await parallel(['honesty', 'budget'].map((lens) => () =>
        agent(verifyPrompt(cur.it, next, lens), { label: `dv${k}:${lens}:${cur.it.id}`, phase: 'Deepen', schema: VERDICT, effort: 'low' })))).filter(Boolean)
      if (checks.every((c) => !c.refuted)) cur = { ...cur, b: next, deepened: k }
      else break
    }
    return cur
  },
)

const done = results.filter(Boolean)
const passed = done.filter((r) => r.ok)

// Cross-item context is needed here, so this is a real barrier.
const byScenario = {}
for (const r of passed) (byScenario[r.it.scenario] = byScenario[r.it.scenario] || []).push(r)
const coherence = args.coherence === false || out() ? [] : await parallel(Object.entries(byScenario).map(([sc, rs]) => () => agent(
  `${RULES}\n\nCOHERENCE for scenario "${sc}". ${rs.length} verified components were built independently: ${JSON.stringify(rs.map((r) => ({ id: r.it.id, shared_params: r.b.shared_params, tiers: r.b.tiers })))}.\nFind where they disagree on the look (exposure, sun elevation, colour temperature, haze density, ground albedo, wetness, snow line, time of day) or where together they exceed the laptop budget at the same tier. Write swarm/coherence/${sc}.md with one authoritative parameter table and, per component, the exact change needed to match it. Do not edit the lanes.`,
  { label: `coherence:${sc}`, phase: 'Coherence', schema: { type: 'object', properties: { conflicts: { type: 'array', items: { type: 'string' } }, budget_overrun_tiers: { type: 'array', items: { type: 'integer' } } }, required: ['conflicts', 'budget_overrun_tiers'] } })))

log(`${args.wave}: ${passed.length} verified, ${done.length - passed.length} rejected, ${items.length - done.length} dropped`)
return {
  wave: args.wave,
  token_target: budget.total, remaining_at_start: R0, floor: FLOOR, remaining_at_end: budget.remaining(),
  verified: passed.map((r) => ({ id: r.it.id, domain: r.it.domain, lane: r.it.lane_dir, tiers: r.b.tiers.length, gate: r.b.pixel_gate })),
  rejected: done.filter((r) => !r.ok).map((r) => ({ id: r.it.id, why: r.why })),
  coherence: coherence.filter(Boolean),
  needs_windows: done.flatMap((r) => (r.b ? r.b.unmeasured_needs_windows.map((u) => `${r.it.id}: ${u}`) : [])),
}
