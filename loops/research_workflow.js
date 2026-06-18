export const meta = {
  name: 'equity-research-loop',
  description: 'Loop 3: screen + gate equity candidates against the trading rules; stop at first approved or 5 evaluated. Generates research only -- never places orders.',
  phases: [
    { title: 'Screen', detail: 'web-screen a candidate pool' },
    { title: 'Gate', detail: 'evaluate each candidate against the rule gates (real-data R:R)' },
    { title: 'Dossier', detail: 'full research for the approved candidate only' },
  ],
}

// === LOOP_CONFIG (guardrail G1: all caps are named constants, never inline) ===
const LOOP_CONFIG = {
  MAX_CANDIDATES: 5,                       // hard iteration cap -> guarantees termination
  MIN_RR: 3.0,                             // reward:risk gate at Target 1
  CANDIDATE_TIMEOUT_SECONDS: 300,          // documented per-candidate budget (see note below)
  OVERALL_TIMEOUT_SECONDS: 1200,           // documented overall budget
  DETERMINISTIC_OP_TIMEOUT_SECONDS: 60,    // applies to technicals.py / research_inputs.py
  PRICE_MIN: 5, PRICE_MAX: 50,
  EXCLUDED_SECTORS: ['packaged food', 'ad-tech / digital advertising', 'consumer footwear'],
}
// NOTE on G2: the Workflow JS sandbox has no clock (Date.now is unavailable), so
// CANDIDATE/OVERALL_TIMEOUT_SECONDS are documented budgets enforced at the
// orchestrator level (TaskStop) + on the deterministic Python ops (60s via
// run_subprocess). The HARD in-sandbox termination guarantee is MAX_CANDIDATES.

const A = args || {}
const excludedTickers = (A.excluded_tickers || []).map(t => String(t).toUpperCase())
const balanceNote =
  `Live balance: Net Liq ${A.net_liq}, deployed ${A.deployed_pct}%, ` +
  `headroom to 70% = ${A.headroom_to_70pct}, 2% risk budget = ${A.two_pct_budget}. ` +
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

const GATE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    ticker: { type: 'string' },
    // From loops/technicals.py (REAL Schwab levels -- must be copied verbatim, not invented):
    entry: { type: 'number', description: 'technicals.py "last"' },
    stop: { type: 'number', description: 'technicals.py "suggested_stop"' },
    nearest_resistance: { type: 'number', description: 'technicals.py "nearest_resistance_40d"' },
    technicals_ran: { type: 'boolean', description: 'true only if loops/technicals.py was run via Bash and its JSON used' },
    // Web-verified rule inputs:
    price_in_range: { type: 'boolean' },
    fcf_positive: { type: 'boolean' },
    catalyst_within_60d: { type: 'boolean' },
    excluded_sector: { type: 'boolean' },
    no_moat: { type: 'boolean' },
    declining_revenue: { type: 'boolean' },
    sizing_conflict: { type: 'boolean' },
    notes: { type: 'string' },
    sources: { type: 'array', items: { type: 'string' } },
  },
  required: ['ticker', 'entry', 'stop', 'nearest_resistance', 'technicals_ran',
             'price_in_range', 'fcf_positive', 'catalyst_within_60d', 'excluded_sector',
             'no_moat', 'declining_revenue', 'sizing_conflict', 'notes'],
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

// --- Screen a candidate pool (more than MAX_CANDIDATES so the gate has options) ---
phase('Screen')
const screen = await agent(
  `Screen US-listed common stocks as equity-trade candidates. Constraints: price ` +
  `$${LOOP_CONFIG.PRICE_MIN}-$${LOOP_CONFIG.PRICE_MAX}, FCF-positive, a clear catalyst within 60 days, ` +
  `NOT in ${LOOP_CONFIG.EXCLUDED_SECTORS.join(' / ')}, and NOT these held tickers: ` +
  `${excludedTickers.join(', ') || '(none)'}. Use live web search. Favor names near support with ` +
  `room to a real resistance (so a 3:1 reward:risk is plausible). Return 8-12 tickers ranked by conviction.`,
  { label: 'screen', phase: 'Screen', schema: SCREEN_SCHEMA }
)

const pool = (screen?.candidates || [])
  .map(c => String(c.ticker).toUpperCase())
  .filter(t => t && !excludedTickers.includes(t))

// --- Bounded gating loop: stop at first approved OR after MAX_CANDIDATES evaluated ---
phase('Gate')
let approved = null
const evaluated = []
for (let i = 0; i < pool.length && evaluated.length < LOOP_CONFIG.MAX_CANDIDATES && !approved; i++) {
  const ticker = pool[i]
  const n = evaluated.length + 1
  const verdict = await agent(
    `Evaluate candidate ${ticker} (candidate ${n}/${LOOP_CONFIG.MAX_CANDIDATES}) against the trading-rule gates.\n${balanceNote}\n\n` +
    `STEP 1 -- log the start (Bash):\n  .venv/bin/python loops/research_log.py log START "candidate=${n}/${LOOP_CONFIG.MAX_CANDIDATES} ticker=${ticker}"\n\n` +
    `STEP 2 (MANDATORY -- REAL DATA ONLY): run via Bash EXACTLY:\n  .venv/bin/python loops/technicals.py ${ticker}\n` +
    `Copy "last" -> entry, "suggested_stop" -> stop, "nearest_resistance_40d" -> nearest_resistance VERBATIM from its JSON. ` +
    `Set technicals_ran=true only if you actually ran it and used its numbers. Do NOT invent levels -- this is non-negotiable.\n\n` +
    `STEP 3 -- web-verify: price in $${LOOP_CONFIG.PRICE_MIN}-$${LOOP_CONFIG.PRICE_MAX}; FCF-positive; a real catalyst within 60 days; ` +
    `sector NOT in ${LOOP_CONFIG.EXCLUDED_SECTORS.join(' / ')}; whether it has an economic moat; whether revenue is declining; ` +
    `and whether a $150-200 position at the 2% risk budget fits the 60-70% deployment band (sizing_conflict).\n\n` +
    `STEP 4 -- log the result (Bash):\n  .venv/bin/python loops/research_log.py record ${ticker} <PASS-or-FAIL> "<one-line reason>"\n\n` +
    `Return the technicals fields verbatim plus the web findings. The orchestrator computes the final R:R gate.`,
    { label: `gate:${ticker}`, phase: 'Gate', schema: GATE_SCHEMA }
  )

  if (!verdict) { evaluated.push({ ticker, passed: false, fails: ['agent_error'] }); continue }

  // Deterministic R:R from the REAL technicals levels (H4): risk = entry-stop, rr = (T1-entry)/risk.
  const risk = (verdict.entry != null && verdict.stop != null) ? (verdict.entry - verdict.stop) : null
  const rr = (risk && risk > 0 && verdict.nearest_resistance != null)
    ? (verdict.nearest_resistance - verdict.entry) / risk : null

  const fails = []
  if (!verdict.technicals_ran) fails.push('technicals_not_run')
  if (!verdict.price_in_range) fails.push('price_band')
  if (!verdict.fcf_positive) fails.push('not_fcf_positive')
  if (!verdict.catalyst_within_60d) fails.push('no_catalyst_within_60d')
  if (verdict.excluded_sector) fails.push('excluded_sector')
  if (rr == null || rr < LOOP_CONFIG.MIN_RR) fails.push(`rr_below_3to1(${rr})`)
  if (verdict.no_moat && verdict.declining_revenue) fails.push('no_moat_and_declining_revenue')
  if (verdict.sizing_conflict) fails.push('sizing_conflict')

  const rec = {
    ticker, rr: rr == null ? null : Math.round(rr * 100) / 100,
    entry: verdict.entry, stop: verdict.stop, t1: verdict.nearest_resistance,
    fails, passed: fails.length === 0, notes: verdict.notes,
  }
  evaluated.push(rec)
  if (rec.passed) approved = rec
}

if (!approved) {
  return {
    approved: null,
    evaluated,
    reason: pool.length === 0 ? 'no_candidates_screened' : 'none_of_evaluated_passed',
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

return { approved, dossier, evaluated }
