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
const excludedTickers = (A.excluded_tickers || []).map(t => String(t).toUpperCase())
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
          // P2 SHADOW fields (logged only -- NEVER feed the live approval path):
          breakout_valid: { type: 'boolean' },
          breakout_rr: { type: ['number', 'null'] },
          breakout_stop: { type: ['number', 'null'] },
          breakout_t1: { type: ['number', 'null'] },
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
    notes: { type: 'string' },
    sources: { type: 'array', items: { type: 'string' } },
  },
  required: ['ticker', 'sector', 'fcf_positive', 'catalyst', 'catalyst_date', 'catalyst_within_60d',
             'excluded_sector', 'ttm_revenue_growth_pct', 'latest_fy_revenue_growth_pct',
             'moat_assessment', 'moat_source', 'notes'],
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
  `avg_volume_30d, support_anchor, support_floor, breakout_valid, breakout_rr, breakout_stop, breakout_t1). ` +
  `Do NOT invent or adjust numbers -- this is non-negotiable.\n\n` +
  `THEN, for every ticker whose breakout_valid=true AND breakout_rr>=${LOOP_CONFIG.MIN_RR}, log a SHADOW ` +
  `line via Bash (P2 shadow mode -- these are NOT tradeable and never reach approval):\n` +
  `  .venv/bin/python loops/research_log.py record <TICKER> SHADOW-BREAKOUT "would-approve breakout: rr=<breakout_rr> stop=<breakout_stop> t1=<breakout_t1> (shadow only)"\n` +
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
    shadow_breakout: !!(r.breakout_valid && (r.breakout_rr ?? 0) >= LOOP_CONFIG.MIN_RR),
    breakout_rr: r.breakout_rr ?? null,
  }
})
const survivors = preEvaluated.filter(r => r.passed)
const shadowWouldApprove = preEvaluated.filter(r => r.shadow_breakout)
log(`Prefilter: ${preRows.length} screened -> ${survivors.length} technical survivors; ` +
    `${shadowWouldApprove.length} SHADOW breakout would-approves (logged, not tradeable)`)

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
    `(prefer a published rating; else say 'own assessment').\n\n` +
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

  const rec = {
    ticker, stage: 'gate', rr: cand.rr, entry: cand.entry, stop: cand.stop, t1: cand.t1,
    catalyst: verdict.catalyst, catalyst_date: verdict.catalyst_date,
    ttm_rev_pct: ttm, fy_rev_pct: fy, moat: verdict.moat_assessment, moat_source: verdict.moat_source,
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
    shadow_breakouts: shadowWouldApprove,
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

return { approved, dossier, prefilter: preEvaluated, gated, shadow_breakouts: shadowWouldApprove }
