export const meta = {
  name: 'max-push',
  description: 'Maximise visual hyper-realism per component for the Windows laptop (Intel iGPU, D3D11) on branch max-push',
  phases: [
    { title: 'Research', detail: 'one researcher per item: sources, prior art, failure risks' },
    { title: 'Build', detail: 'one agent per component x scenario: best visuals the laptop can sustain' },
    { title: 'Verify', detail: 'three skeptics: licence, honesty, laptop budget' },
    { title: 'Repair', detail: 'one repair per rejected item' },
    { title: 'Deepen', detail: 'args.rounds improve-then-verify rounds per verified item' },
    { title: 'Integrate', detail: 'one integrator per domain wires verified lanes into shared files, serially' },
  ],
}

// args: { items: [...manifest shard], budget: {...hardware_budget dict}, wave: 'm0_s0' }
// Shards run as separate Workflow calls in the same turn; integration is done after all shards, see swarm/MAXPUSH.md.
const items = args.items
const hw = args.budget
const ROUNDS = args.rounds === undefined ? 2 : args.rounds

const LAPTOP = `THE TARGET MACHINE (the Windows test laptop): Intel integrated GPU, Direct3D 11 / Shader Model 5 only (no D3D12, no Lumen, no hardware ray tracing, no Nanite assumptions), shared memory, display 1536x960, RAM unmeasured and tight (one UE render process used 3.8 GB and background jobs were OOM-killed), C: has about 60 GB free, and it hit 12 "device lost" crashes on scene 9. Starting budget: ${JSON.stringify(hw)}.
YOUR GOAL: the most photorealistic result this machine can SUSTAIN for your component, focused on what is seen in the rendered frames. Not the prettiest idea: the best frame that renders without device loss.
THE KEY MOVE: the Mac (where you run) has 64 GB and an M1 Max and the render machine does not. Move cost out of the render: precompute offline on the Mac and ship baked results (atmosphere/sky LUTs, baked AO and lightmaps, normal and roughness maps, flipbook and impostor sprites, texture atlases, mip-chains compressed to BC, distance-field-free fake shadows, precomputed wave/cloud/rain textures, tiled detail maps). The render path should only sample them.
Deliver TIERS for your component: tier 0 must be stable on this laptop; tiers 1-3 are progressively heavier for the stress ladder to try. Each tier is a cvar/param set plus asset set, with its estimated VRAM and per-frame cost stated as ESTIMATES. The stress ladder on the laptop (hardware_perf items) decides which tier is real; never claim one is sustained.`

const RULES = `Project rules (CLAUDE.md, docs/VALIDITY.md): named sources only, sha256 and licence on every fetched asset, no non-commercial licences, no placeholder airframes, visual-only work labelled visual-only. Google tiles are the ground of every terrain render and are ON unless FLIGHTSIM_GOOGLE_TILES=off; the web app's weather defaults stay on. You run on a MacBook: you cannot run the pinned Windows UE build or the laptop GPU, so anything that needs it is written, source-tested here where possible, and marked UNMEASURED with the exact Windows command to measure it. Never claim a visual result you did not measure. Write ONLY inside your lane directory, plus tests/test_swarm_<id with dots as underscores>.py. Never edit shared files (ue/Source, core/scene, core/render, webapp): put the proposed change in <lane>/INTEGRATION.md as an exact patch description for the domain integrator.`

const BUILD = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    sources: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, licence: { type: 'string' } }, required: ['name', 'licence'] } },
    tiers: { type: 'array', items: { type: 'object', properties: { tier: { type: 'integer' }, est_vram_mb: { type: 'number' }, summary: { type: 'string' } }, required: ['tier', 'est_vram_mb', 'summary'] } },
    baked_offline: { type: 'array', items: { type: 'string' } },
    measured: { type: 'array', items: { type: 'string' } },
    unmeasured_needs_windows: { type: 'array', items: { type: 'string' } },
    tests_pass: { type: 'boolean' },
  },
  required: ['files', 'sources', 'tiers', 'baked_offline', 'measured', 'unmeasured_needs_windows', 'tests_pass'],
}
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['refuted', 'reason'] }

const RESEARCH = {
  type: 'object',
  properties: {
    candidates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, licence: { type: 'string' }, why: { type: 'string' } }, required: ['name', 'licence', 'why'] } },
    existing_defects: { type: 'array', items: { type: 'string' } },
    risks_on_igpu: { type: 'array', items: { type: 'string' } },
    plan: { type: 'string' },
  },
  required: ['candidates', 'existing_defects', 'risks_on_igpu', 'plan'],
}

const researchPrompt = (it) => `${LAPTOP}

${RULES}

RESEARCH ONLY, write no code. Work item ${it.id}: ${it.component} for ${it.domain}, scenario "${it.scenario}" (${it.scenario_note}). Gate: ${it.gate}.
Search the repo (core/, ue/Source, docs/, docs/visual, git log) for the real current defects, then the web for the best open techniques, papers, datasets and CC0/CC-BY assets. Rank candidates by realism gain per unit of iGPU cost. Name what will crash a D3D11 Intel iGPU.`

const buildPrompt = (it, research) => `${LAPTOP}

RESEARCH FROM THE PREVIOUS AGENT (use it, do not trust it blindly): ${JSON.stringify(research)}

${RULES}

Work item ${it.id}: ${it.component} for ${it.domain}, scenario "${it.scenario}" (${it.scenario_note}).
Gate: ${it.gate}.
Lane directory: ${it.lane_dir}
Source classes to look for third-party components in: ${it.source_classes.join('; ')}.

1. Read what already exists for this component (grep core/, ue/Source, docs/VISUAL_FIDELITY_PLAN.md, docs/WEATHER.md, assets/) and what the last visual rounds found (git log, docs/visual) so you fix real defects, not imagined ones.
2. Find the best third-party component or dataset for this scenario inside the licence rule, or state that none exists.
3. Build the offline bake/generator on the Mac and the tiered render-side integration description. Include PROVENANCE.json (source, url, licence, sha256).
4. Test what is checkable here; run it; report honestly.`

const verifyPrompt = (it, b, lens) => {
  const what = {
    licence: 'Is every source real, named, and not non-commercial? Is sha256/licence recorded?',
    honesty: 'Does any file or report claim a visual or hardware result that was not measured here, or does a test pass vacuously?',
    budget: `Would tier 0 plausibly run on an Intel iGPU with D3D11 SM5, ~${hw.usable_vram_mb} MB texture pool, no Lumen/HWRT, under 4 GB process RAM? Refute if tier 0 needs D3D12, Nanite, Lumen, hardware RT, or more memory than that.`,
  }[lens]
  return `Try to REFUTE this finished work item. Default to refuted=true if uncertain. Lens: ${lens}. ${what}
Item ${it.id}, lane ${it.lane_dir}. Builder report: ${JSON.stringify(b)}. Read the actual files.`
}

const results = await pipeline(
  items,
  (it) => agent(researchPrompt(it), { label: `research:${it.id}`, phase: 'Research', schema: RESEARCH, effort: 'high' }),
  (research, it) => agent(buildPrompt(it, research || {}), { label: `build:${it.id}`, phase: 'Build', schema: BUILD }),
  async (b, it) => {
    if (!b) return { it, b, ok: false, why: 'builder died' }
    const votes = (await parallel(['licence', 'honesty', 'budget'].map((lens) => () =>
      agent(verifyPrompt(it, b, lens), { label: `verify:${lens}:${it.id}`, phase: 'Verify', schema: VERDICT, effort: 'low' })))).filter(Boolean)
    const refutes = votes.filter((v) => v.refuted)
    return { it, b, ok: refutes.length === 0, why: refutes.map((v) => v.reason).join(' | ') }
  },
  async (r) => {
    if (r.ok || !r.b) return r
    const fixed = await agent(`${LAPTOP}\n\n${RULES}\n\nRepair work item ${r.it.id} in ${r.it.lane_dir}. Skeptics said: ${r.why}\nFix the files or delete the claim that cannot be supported. Report in the same shape.`,
      { label: `repair:${r.it.id}`, phase: 'Repair', schema: BUILD })
    return { ...r, b: fixed || r.b, repaired: !!fixed, ok: !!fixed }
  },
)

const deepened = await pipeline(
  results.filter(Boolean),
  async (r) => {
    let cur = r
    for (let k = 1; k <= ROUNDS && cur.ok && cur.b; k++) {
      const next = await agent(`${LAPTOP}\n\n${RULES}\n\nDEEPEN round ${k} of ${ROUNDS} for ${cur.it.id} in ${cur.it.lane_dir}. Current report: ${JSON.stringify(cur.b)}.\nRead the lane. Critique it against the gate and the laptop budget, find the single biggest remaining realism gap, and close it: a better bake, a sharper tier ladder, a missing scenario case, a stronger test. Do not weaken earlier tiers. Report in the same shape.`,
        { label: `deepen${k}:${cur.it.id}`, phase: 'Deepen', schema: BUILD })
      if (!next) break
      const checks = (await parallel(['honesty', 'budget'].map((lens) => () =>
        agent(verifyPrompt(cur.it, next, lens), { label: `deepen-verify${k}:${lens}:${cur.it.id}`, phase: 'Deepen', schema: VERDICT, effort: 'low' })))).filter(Boolean)
      if (checks.every((c) => !c.refuted)) cur = { ...cur, b: next, deepened: k }
      else break
    }
    return cur
  },
)

const done = deepened.filter(Boolean)
const passed = done.filter((r) => r.ok)
log(`${args.wave}: ${passed.length} verified, ${done.length - passed.length} rejected or failed, ${items.length - done.length} dropped`)
return {
  wave: args.wave,
  verified: passed.map((r) => ({ id: r.it.id, domain: r.it.domain, lane: r.it.lane_dir, tiers: r.b.tiers.length })),
  rejected: done.filter((r) => !r.ok).map((r) => ({ id: r.it.id, why: r.why })),
  needs_windows: done.flatMap((r) => (r.b ? r.b.unmeasured_needs_windows.map((u) => `${r.it.id}: ${u}`) : [])),
}
