export const meta = {
  name: 'equity-research-loop',
  description: 'Loop 3: screen -> deterministic technical prefilter -> web-gate survivors; stop at first approved or MAX_CANDIDATES gated. Generates research only -- never places orders.',
  phases: [
    { title: 'Screen', detail: 'web-screen a candidate pool' },
    { title: 'Prefilter', detail: 'ONE technicals.py pass over the whole pool; deterministic R:R/knife/liquidity/sizing filter (P4)' },
    { title: 'Gate', detail: 'web-verify survivors only (FCF, catalyst, sector, revenue numbers, moat)' },
    { title: 'Dossier', detail: 'full research for the approved candidate only' },
  ],
}

// === LOOP_CONFIG (guardrail G1: all caps are named constants, never inline) ===
const LOOP_CONFIG = {
  MAX_CANDIDATES: 5,                       // cap on web-gated SURVIVORS -> guarantees termination
  MIN_RR: 3.0,                             // reward:risk gate at Target 1
  MIN_AVG_VOLUME: 300000,                  // P3 liquidity floor (30-day avg shares/day)
  CANDIDATE_TIMEOUT_SECONDS: 300,          // documented per-candidate budget (see note below)
  OVERALL_TIMEOUT_SECONDS: 1200,           // documented overall budget
  DETERMINISTIC_OP_TIMEOUT_SECONDS: 60,    // applies to technicals.py / research_inputs.py
  PRICE_MIN: 5, PRICE_MAX: 50,
  MIN_POSITION_USD: 150, MAX_POSITION_USD: 200,
  MIN_SHARES: 3,
  EXCLUDED_SECTORS: ['packaged food', 'ad-tech / digital advertising', 'consumer footwear'],
}
// NOTE on G2: the Workflow JS sandbox has no clock (Date.now is unavailable), so
// CANDIDATE/OVERALL_TIMEOUT_SECONDS are documented budgets enforced at the
// orchestrator level (TaskStop) + on the deterministic Python ops (60s via
// run_subprocess). The HARD in-sandbox termination guarantee is MAX_CANDIDATES
// plus the single bounded prefilter pass.

// Robust args intake: accept an object OR a JSON string, then FAIL FAST if the
// live-balance fields are missing -- a sizing-blind run must never happen.
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch { A = null } }
A = A || {}
for (const field of ['net_liq', 'deployed_pct', 'headroom_to_70pct', 'two_pct_budget']) {
  if (typeof A[field] !== 'number' || !isFinite(A[field])) {
    throw new Error(`research_workflow: required balance arg '${field}' missing/non-numeric -- refusing to run sizing-blind`)
  }
}
// C1 (2026-08-12): sector cap needs the sectors of CURRENT holdings. Fail fast if
// absent -- a sector-blind run allowed 3x consumer discretionary and two of the
// three stopped out in 16 minutes on one macro move (2026-08-12).
if (typeof A.held_sectors !== 'object' || A.held_sectors === null || Array.isArray(A.held_sectors)) {
  throw new Error("research_workflow: required arg 'held_sectors' missing (object ticker->GICS sector) -- refusing to run sector-blind")
}
const excludedTickers = (A.excluded_tickers || []).map(t => String(t).toUpperCase())

// --- C1: GICS normalization (deterministic; agents report, code judges) --------
const GICS_SECTORS = ['Energy', 'Materials', 'Industrials', 'Consumer Discretionary',
  'Consumer Staples', 'Health Care', 'Financials', 'Information Technology',
  'Communication Services', 'Utilities', 'Real Estate']
const GICS_SYNONYMS = {
  'consumer cyclical': 'Consumer Discretionary', 'consumer defensive': 'Consumer Staples',
  'technology': 'Information Technology', 'tech': 'Information Technology',
  'information tech': 'Information Technology', 'healthcare': 'Health Care',
  'telecom': 'Communication Services', 'telecommunications': 'Communication Services',
  'communications': 'Communication Services', 'financial': 'Financials',
  'financial services': 'Financials', 'basic materials': 'Materials',
}
function normalizeSector(raw) {
  const s = String(raw || '').trim().toLowerCase()
  for (const g of GICS_SECTORS) if (g.toLowerCase() === s) return g
  if (GICS_SYNONYMS[s]) return GICS_SYNONYMS[s]
  for (const g of GICS_SECTORS) if (s.includes(g.toLowerCase())) return g
  return null  // unmappable -> caller fails closed
}
const heldSectorCounts = {}
for (const [tkr, sec] of Object.entries(A.held_sectors)) {
  const n = normalizeSector(sec)
  if (!n) throw new Error(`research_workflow: held_sectors['${tkr}']='${sec}' does not map to a GICS sector`)
  heldSectorCounts[n] = (heldSectorCounts[n] || 0) + 1
}
const balanceNote =
  `Live balance: Net Liq $${A.net_liq}, deployed ${A.deployed_pct}%, ` +
  `headroom to 70% = $${A.headroom_to_70pct}, 2% risk budget = $${A.two_pct_budget}. ` +
  `Held/excluded tickers: ${excludedTickers.join(', ') || '(none)'}.`

const SCREEN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          ticker: { type: 'string' }, sector: { type: 'string' },
          approx_price: { type: 'number' }, catalyst: { type: 'string' },
          catalyst_date: { type: 'string' }, why: { type: 'string' },
        },
        required: ['ticker', 'sector', 'approx_price', 'catalyst', 'catalyst_date', 'why'],
      },
    },
  },
  required: ['candidates'],
}

// P4: ONE deterministic technicals pass over the whole pool, copied VERBATIM.
const PREFILTER_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          ticker: { type: 'string' },
          error: { type: 'string' },
          last: { type: 'number' },
          suggested_stop: { type: 'number' },
          risk_per_share: { type: 'number' },
          nearest_resistance_40d: { type: 'number' },
          rr_to_resistance: { type: ['number', 'null'] },
          valid_setup: { type: 'boolean' },
          falling_knife: { type: 'boolean' },
          avg_volume_30d: { type: ['number', 'null'] },
          support_anchor: { type: ['number', 'null'] },
          support_floor: { type: ['number', 'null'] },
          // P2 breakout mode RETIRED 2026-08-12: full-population replay showed a
          // 20% hit rate against ~20% breakeven with all positive R from 2 of 10
          // trades, and none of the motivating escapes were base-and-confirm
          // breakouts. technicals.py still computes breakout_* fields solely for
          // loops/breakout_replay.py (research harness); the live pipeline
          // neither consumes nor logs them.
        },
        required: ['ticker'],
      },
    },
  },
  required: ['results'],
}

// P5: web gate returns NUMBERS and sourced assessments; the orchestrator applies
// the thresholds (no more LLM flip-flop on "declining revenue" / "no moat").
const GATE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    ticker: { type: 'string' },
    sector: { type: 'string' },
    fcf_positive: { type: 'boolean' },
    catalyst: { type: 'string' },
    catalyst_date: { type: 'string' },
    catalyst_within_60d: { type: 'boolean' },
    excluded_sector: { type: 'boolean' },
    ttm_revenue_growth_pct: { type: ['number', 'null'], description: 'TTM revenue growth %, cited; null only if unfindable' },
    latest_fy_revenue_growth_pct: { type: ['number', 'null'], description: 'latest full fiscal-year revenue growth %, cited' },
    moat_assessment: { type: 'string', description: "'none' | 'narrow' | 'wide'" },
    moat_source: { type: 'string', description: 'where the moat call comes from (e.g. Morningstar rating, own assessment)' },
    // C1: GICS sector -- agents REPORT it, the orchestrator judges the cap.
    gics_sector: { type: 'string', description: 'one of the 11 GICS sectors, best classification' },
    sector_source: { type: 'string', description: 'where the sector classification comes from' },
    // C3: insider BUYING signal (surfaced, not gated) -- Form 4 open-market purchases.
    insider_buys_90d: { type: ['number', 'null'], description: 'count of open-market insider BUY transactions, trailing 90 days; null if undeterminable' },
    insider_buyers_90d: { type: ['number', 'null'], description: 'distinct insiders who bought in the trailing 90 days' },
    insider_buy_total_usd: { type: ['number', 'null'], description: 'aggregate $ value of those purchases; null if undeterminable' },
    insider_data_note: { type: 'string', description: 'source + caveats (e.g. foreign private issuer -> no Form 4s)' },
    notes: { type: 'string' },
    sources: { type: 'array', items: { type: 'string' } },
  },
  required: ['ticker', 'sector', 'fcf_positive', 'catalyst', 'catalyst_date', 'catalyst_within_60d',
             'excluded_sector', 'ttm_revenue_growth_pct', 'latest_fy_revenue_growth_pct',
             'moat_assessment', 'moat_source', 'gics_sector', 'sector_source',
             'insider_buys_90d', 'insider_buyers_90d', 'insider_buy_total_usd', 'insider_data_note',
             'notes'],
}

const DOSSIER_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    ticker: { type: 'string' },
    financials: { type: 'string' }, valuation: { type: 'string' },
    business_moat: { type: 'string' }, growth: { type: 'string' },
    management: { type: 'string' }, risks: { type: 'string' },
    catalyst_market: { type: 'string' }, analyst_pt: { type: 'string' },
    data_gaps: { type: 'string' }, sources: { type: 'array', items: { type: 'string' } },
  },
  required: ['ticker', 'financials', 'valuation', 'business_moat', 'growth',
             'management', 'risks', 'catalyst_market', 'analyst_pt', 'data_gaps'],
}

// P6: FULLY deterministic sizing -- single source of truth in the orchestrator.
function sizingCheck(entry, risk) {
  if (!(risk > 0) || !(entry > 0)) return { ok: false, buyable: 0 }
  const buyable = Math.min(
    Math.floor(LOOP_CONFIG.MAX_POSITION_USD / entry),
    Math.floor(A.two_pct_budget / risk),
    Math.floor(A.headroom_to_70pct / entry),
  )
  return { ok: buyable >= LOOP_CONFIG.MIN_SHARES && buyable * entry >= LOOP_CONFIG.MIN_POSITION_USD, buyable }
}

// Deterministic technical verdict for one prefilter row (P1/P3/P4 + sizing P6).
function technicalFails(r) {
  const fails = []
  if (r.error) { fails.push(`data_error(${String(r.error).slice(0, 40)})`); return fails }
  if (r.falling_knife) fails.push('falling_knife_fresh_40d_low')
  if (r.valid_setup === false) fails.push('invalid_technical_setup')
  if (!(r.last >= LOOP_CONFIG.PRICE_MIN && r.last <= LOOP_CONFIG.PRICE_MAX)) fails.push('price_band')
  if (r.rr_to_resistance == null || r.rr_to_resistance < LOOP_CONFIG.MIN_RR) fails.push(`rr_below_3to1(${r.rr_to_resistance})`)
  if ((r.avg_volume_30d || 0) < LOOP_CONFIG.MIN_AVG_VOLUME) fails.push(`liquidity(${r.avg_volume_30d})`)
  const s = sizingCheck(r.last, r.risk_per_share)
  if (!s.ok) fails.push(`sizing_conflict_deterministic(buyable=${s.buyable})`)
  return fails
}

// --- Screen a candidate pool (more than MAX_CANDIDATES so the gate has options) ---
phase('Screen')
const screen = await agent(
  `Screen US-listed common stocks as equity-trade candidates. Constraints: price ` +
  `$${LOOP_CONFIG.PRICE_MIN}-$${LOOP_CONFIG.PRICE_MAX}, FCF-positive, a clear catalyst within 60 days, ` +
  `avg daily volume >= ${LOOP_CONFIG.MIN_AVG_VOLUME.toLocaleString()} shares, ` +
  `NOT in ${LOOP_CONFIG.EXCLUDED_SECTORS.join(' / ')}, and NOT these held tickers: ` +
  `${excludedTickers.join(', ') || '(none)'}. Use live web search. Favor names basing above tested ` +
  `support with room to real overhead resistance (3:1 reward:risk plausible) -- NOT names collapsing ` +
  `to fresh lows. Return 8-12 tickers ranked by conviction.`,
  { label: 'screen', phase: 'Screen', schema: SCREEN_SCHEMA }
)

const pool = (screen?.candidates || [])
  .map(c => String(c.ticker).toUpperCase())
  .filter(t => t && !excludedTickers.includes(t))

// --- P4: one deterministic technicals pass over the ENTIRE pool ---
phase('Prefilter')
const pre = pool.length === 0 ? { results: [] } : await agent(
  `Run this EXACT command via Bash (single call, all tickers at once):\n` +
  `  .venv/bin/python loops/technicals.py ${pool.join(' ')}\n` +
  `Copy each ticker's JSON fields VERBATIM into the schema (ticker, error, last, suggested_stop, ` +
  `risk_per_share, nearest_resistance_40d, rr_to_resistance, valid_setup, falling_knife, ` +
  `avg_volume_30d, support_anchor, support_floor). ` +
  `Do NOT invent or adjust numbers -- this is non-negotiable.\n\n` +
  `Finally log the batch summary:\n` +
  `  .venv/bin/python loops/research_log.py log PREFILTER "pool=${pool.length} tickers=${pool.join(',')}"`,
  { label: `prefilter:${pool.length}`, phase: 'Prefilter', schema: PREFILTER_SCHEMA }
)

const preRows = (pre?.results || []).filter(r => r && r.ticker)
const preEvaluated = preRows.map(r => {
  const fails = technicalFails(r)
  return {
    ticker: String(r.ticker).toUpperCase(), stage: 'prefilter',
    rr: r.rr_to_resistance ?? null, entry: r.last ?? null, stop: r.suggested_stop ?? null,
    t1: r.nearest_resistance_40d ?? null, fails, passed: fails.length === 0,
  }
})
const survivors = preEvaluated.filter(r => r.passed)
log(`Prefilter: ${preRows.length} screened -> ${survivors.length} technical survivors`)

// --- Gate: web verification for SURVIVORS ONLY (bounded by MAX_CANDIDATES) ---
phase('Gate')
let approved = null
const gated = []
for (let i = 0; i < survivors.length && gated.length < LOOP_CONFIG.MAX_CANDIDATES && !approved; i++) {
  const cand = survivors[i]
  const ticker = cand.ticker
  const verdict = await agent(
    `Web-verify candidate ${ticker} (survivor ${gated.length + 1}/${Math.min(survivors.length, LOOP_CONFIG.MAX_CANDIDATES)}) ` +
    `for the trading-rule gates. Technicals already passed deterministically (entry=${cand.entry}, stop=${cand.stop}, ` +
    `T1=${cand.t1}, R:R=${cand.rr}). ${balanceNote}\n\n` +
    `STEP 1 -- log the start (Bash):\n  .venv/bin/python loops/research_log.py log START "gate ticker=${ticker}"\n\n` +
    `STEP 2 -- web-verify with live sources and CITE them: FCF-positive (most recent FY and/or TTM); a real, dated ` +
    `catalyst within 60 days; sector NOT in ${LOOP_CONFIG.EXCLUDED_SECTORS.join(' / ')}; ` +
    `TTM revenue growth % and latest-FY revenue growth % as NUMBERS (cited -- the orchestrator applies the ` +
    `declining-revenue rule, not you); moat_assessment as 'none'/'narrow'/'wide' with moat_source ` +
    `(prefer a published rating; else say 'own assessment'); gics_sector as the company's GICS sector ` +
    `(one of: ${GICS_SECTORS.join(', ')}) with sector_source -- the orchestrator enforces the sector cap, not you; ` +
    `and INSIDER BUYING (Form 4 open-market purchases, trailing 90 days): insider_buys_90d (count), ` +
    `insider_buyers_90d (distinct buyers), insider_buy_total_usd ($ total), insider_data_note (source + caveats; ` +
    `if the company is a foreign private issuer with no Form 4s, return nulls and say so).\n\n` +
    `STEP 3 -- log the result (Bash):\n  .venv/bin/python loops/research_log.py record ${ticker} <PASS-or-FAIL> "<one-line reason>"`,
    { label: `gate:${ticker}`, phase: 'Gate', schema: GATE_SCHEMA }
  )
  if (!verdict) { gated.push({ ticker, stage: 'gate', passed: false, fails: ['agent_error'] }); continue }

  const fails = []
  if (!verdict.fcf_positive) fails.push('not_fcf_positive')
  if (!verdict.catalyst_within_60d) fails.push('no_catalyst_within_60d')
  if (verdict.excluded_sector) fails.push('excluded_sector')
  // P5: deterministic declining-revenue rule -- BOTH the TTM and the latest full
  // fiscal year must be negative to count as declining (kills classification
  // flip-flop; DVN's +7.8% FY / -1.5% TTM reads NOT-declining in both runs).
  const ttm = verdict.ttm_revenue_growth_pct
  const fy = verdict.latest_fy_revenue_growth_pct
  const declining = (typeof ttm === 'number' && ttm < 0) && (typeof fy === 'number' && fy < 0)
  const noMoat = String(verdict.moat_assessment || '').toLowerCase() === 'none'
  if (noMoat && declining) fails.push(`no_moat_and_declining_revenue(ttm=${ttm},fy=${fy})`)
  // C1 (2026-08-12): deterministic GICS sector cap -- max 2 open positions per
  // sector; a would-be 3rd fails regardless of R:R (the 8/12 consumer-disc sweep
  // stopped 2 of 3 same-sector positions in 16 minutes). 2nd-in-sector = soft flag.
  const gics = normalizeSector(verdict.gics_sector)
  let sectorFlag = null
  if (!gics) {
    fails.push(`sector_unclassifiable('${verdict.gics_sector}')`)  // fail closed
  } else {
    const heldInSector = heldSectorCounts[gics] || 0
    if (heldInSector >= 2) fails.push(`sector_concentration_3rd(${gics}: ${heldInSector} held)`)
    else if (heldInSector === 1) sectorFlag = `2nd position in ${gics} (soft flag -- passes, surfaced per C1)`
  }

  const rec = {
    ticker, stage: 'gate', rr: cand.rr, entry: cand.entry, stop: cand.stop, t1: cand.t1,
    catalyst: verdict.catalyst, catalyst_date: verdict.catalyst_date,
    ttm_rev_pct: ttm, fy_rev_pct: fy, moat: verdict.moat_assessment, moat_source: verdict.moat_source,
    gics_sector: gics || verdict.gics_sector, sector_flag: sectorFlag,
    insider_buys_90d: verdict.insider_buys_90d, insider_buyers_90d: verdict.insider_buyers_90d,
    insider_buy_total_usd: verdict.insider_buy_total_usd, insider_data_note: verdict.insider_data_note,
    fails, passed: fails.length === 0, notes: verdict.notes,
  }
  gated.push(rec)
  if (rec.passed) approved = rec
}

if (!approved) {
  return {
    approved: null,
    prefilter: preEvaluated,
    gated,
    reason: pool.length === 0 ? 'no_candidates_screened'
      : survivors.length === 0 ? 'no_technical_survivors' : 'none_of_gated_passed',
  }
}

// --- Full 9-section research dossier for the APPROVED candidate only ---
phase('Dossier')
const dossier = await agent(
  `Produce thoroughly web-verified research for ${approved.ticker} (cite sources + as-of dates; flag data gaps): ` +
  `financials (5y + TTM, FCF), valuation vs 3 peers, business + moat, growth + TAM, management + insider activity, ` +
  `EXACTLY 3 company-specific + 3 systemic risks, the near-term catalyst, and the analyst average price target.`,
  { label: `dossier:${approved.ticker}`, phase: 'Dossier', schema: DOSSIER_SCHEMA }
)

return { approved, dossier, prefilter: preEvaluated, gated }
