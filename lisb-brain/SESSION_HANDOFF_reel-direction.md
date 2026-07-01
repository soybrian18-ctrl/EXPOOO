# Session Handoff: Reel Direction

Job of this session: stand up the LISB content brain and establish the reel creative
direction, culminating in The Rebuild flagship format and tonight's launch batch.
All rule and reference files are committed and pushed to branch
claude/gifted-lovelace-tr7xg4 (latest commit b0d2ddd). Reel scripts are chat
deliverables and are not in git.

## Completed
- Built the whole lisb-brain content brain, isolated from the trading project at the
  repo root (never touch the Schwab files):
  - Root CLAUDE.md (Master Operating Brief): identity, Phase 1, non-negotiable copy
    rules, banned words, platform safety, rules manifest, session management.
  - Rules: brand-system.md, copy-rules.md, outreach.md, content-pipeline.md, loops.md.
- Iterated the rules heavily:
  - copy-rules.md: split Pillar 1 and 3 CTAs, then retuned Pillar 1 to "brand rebuild
    every week" and added a Pillar 5 follow CTA. Removed the price from all public
    content (the $175 is never shown publicly, only in direct conversation on request).
    Reveal CTA is now price-free. Cold DM Voice rewritten.
  - content-pipeline.md: expanded Hook Rule to five structure types with word caps,
    added the Viral Hook Framework, added the Content Theme Tracker (the
    judged-before-contact theme is fully covered by Reels 27, 31, 33). Reel Structure
    evolved from labeled cards to Concept B to The Rebuild as flagship, with reveals
    repositioned as secondary. Music sources switched to premium libraries
    (Musicbed, Artlist, Epidemic Sound, Soundstripe), NCS deprecated as wrong fit.
    Audio rule carved out so The Rebuild can use one continuous music track.
  - outreach.md: Cold DM Voice rewrite, Profile Credibility Standards (follower to
    following ratio, unfollow non-followers after 30 days, all manual per platform
    safety), Tracker section (lisb_outreach.db via db.py, stages S0 to S8), warm-lead
    to Apex mapping.
  - brand-system.md: added Apex Studios anchor brand (boutique fitness and pilates,
    palette still a placeholder), warm-lead portfolio mapping.
- Reference docs in lisb-brain/references/: premium-reel-creative-direction.md,
  brand-reveal-concepts.md, mockup-pipeline-spec.md, flagship-reel-concept.md,
  rebuild-detailer-test-spec.md, rebuild-music-direction.md.
- Generated reel scripts (chat only, not committed): Reels 27 to 34 across pillars,
  and tonight's kinetic batch: the locked Pillar 3 five-second profile audit, Reel A
  (Pillar 1 Brand Equity), Reel B (Pillar 4 kinetic reveal, North Shore Details),
  Reel C (Pillar 5 Business Mindset). All four approved for scheduling.

## Current state and in progress
- Tonight's batch: four kinetic reels across Pillars 3, 1, 4, 5. Scripts done and
  approved. Production, rendering, and scheduling are the user's to do tonight.
- The Rebuild is defined end to end in the brain (format rules, concept, shot-by-shot
  test spec, motion language, music direction, music sources, audio structure) but not
  yet built. The detailer Rebuild test in references/rebuild-detailer-test-spec.md is
  the first build target, waiting on production (track pick plus before and after
  assets).
- Apex Studios has palette and style TBD, so we cannot produce Apex brand content until
  the palette is provided.

## Next actions
- Production and design side (separate from this brain): build the detailer Rebuild
  test. Pick a track per the music direction, produce a representative weak before plus
  the North Shore Details after assets, render per the shot spec. Build the
  phone-plus-grid mockup surface first, it is the cheapest and most on-message.
- Reel 2 (Pillar 1 Brand Equity, already rendered with the old "brand reveal every
  week" CTA baked on screen): ship Tuesday as-is. Do not update the caption, it would
  mismatch the baked video. The new "brand rebuild every week" CTA governs future
  Pillar 1 reels.
- Provide the Apex Studios palette and style to finish its anchor-brand entry.
- Optional: decide "brand rebuild" vs "brand breakdown" for the Pillar 1 CTA wording.
  Currently "rebuild."

## Decisions made
- The content brain lives in lisb-brain/, fully isolated from the trading project.
- No public price ever. The $175 only comes up in direct conversation when a prospect
  asks.
- The Rebuild (kinetic, music-first, educational teardown and rebuild, owner-framed) is
  the flagship acquisition format. Brand reveals are secondary proof and case-study
  content, strongest once we have a real client, and even then they borrow The Rebuild's
  kinetic energy rather than running slow and elegant.
- Reveal concept direction: Concept B (brand in the wild) when we do reveals, Concept A
  (before and after) reserved for the first real client, Concept C (built live) in the
  back pocket.
- Music: premium libraries not NCS, groove-driven energy, a drop that arrives rather
  than explodes at about 22 seconds, with a pull-back after for the payoff line.
  Premium is precision, not slowness.
- Voice: we and us only, no banned words, no em dashes, number-free, no
  criticism-framing that could trip pre-flight. Owner-framed, customer and outcome
  language, never design terms.
- Platform safety: every Instagram action is manual and human-confirmed. Loops only
  prepare and organize, including the unfollow list. The human sends.

## Open flags to carry forward
- Reel 2 caption stays as-is to match its baked on-screen CTA. Lock the on-screen CTA
  last before any future render so a late CTA change costs only a caption edit.
- Apex Studios palette is pending.
- Pillar 1 CTA wording ("rebuild" vs "breakdown") is the user's call, currently rebuild.
- Reels are chat deliverables and are not committed. Rule and reference files are
  committed to branch claude/gifted-lovelace-tr7xg4.
