# Build Spec: The Rebuild, Auto Detailer Test (North Shore Details)

This is the hand-off spec for the Remotion session to build the first Rebuild test.
Format rules: content-pipeline.md (The Rebuild). Concept: flagship-reel-concept.md.
Motion primitives: premium-reel-creative-direction.md, retuned fast. Do not change
the brand system or the no-price rule.

## Goal
Test whether kinetic plus educational plus owner-framed actually converts. One
instance, the detailer Rebuild. North Shore Details is the after, a representative
weak brand is the before.

## Composition specs
- 1080 by 1920, 30 fps (confirm the project fps before building; all frames below
  assume 30). Total about 38 seconds, roughly 1140 frames.
- Music-first. A single continuous music track drives timing. No per-slide voiceover.
- Two fonts only, loaded via @remotion/google-fonts: Cormorant Garamond (the lesson
  and any serif framing) and DM Sans (all kinetic callouts and the CTA).
- Our framing color: navy #0D1B2A background, white #FFFFFF text, gold #C9A84C accent.
  The after content uses the client palette: matte black and electric blue.

## Music spec (the spine)
- One track with a clear build and one big drop. Licensed (NCS.io per pipeline).
- The drop must land at about 22 seconds. Usable length about 38 seconds.
- Set the track BPM as a constant and derive a beat grid:
  beatFrame(i) = round(i * (60 / BPM) * fps). Every cut and text hit lands on a beat.
- Example at 120 BPM and 30 fps: one beat = 15 frames, one bar = 60 frames, the drop
  at beat 44 (frame 660, 22s). Adjust to the real track.

## Assets needed
Before (representative, must be generated as a generic typical weak detailer brand,
not a real competitor's actual brand and not implying North Shore Details looked like
this):
- before-logo.png: a deliberately generic, homemade-looking detailer logo (default
  font name plus clipart car).
- before-bio.png or text: a near-empty, vague bio.
- before-grid.png: a messy, mismatched, low-quality 9-tile grid.
- before-profile.png: the three above composed into one weak IG profile, plus
  separate close-up crops of the logo, bio, and grid for the teardown whips.

After (North Shore Details, real assets):
- nsd-logo.png: the real logo, matte black and electric blue.
- nsd-bio: strong copy we write. Example, number-free and price-free: "North Shore
  Details. Long Island auto detailing. Ceramic coatings, paint correction, interior
  resets. Book in bio."
- nsd-grid: 9 post tiles in matte black and electric blue (our grid templates),
  delivered as 9 separate tiles so they can assemble on screen.
- phone-nsd-feed.png: the phone-in-hand mockup showing the NSD feed (the phone-plus-
  grid surface from mockup-pipeline-spec.md).

Framing: the LISB mark for the CTA. Music track file.

## Shot by shot

HOOK, 0.0 to 2.5s (before profile on screen)
- 0.0s: hard cut to the weak before profile.
- Beat near 0.5s: "TOP-TIER WORK." punches in (DM Sans bold caps, white).
- Beat near 1.0s: "SIDE-HUSTLE BRAND." punches in below it (gold).
- Hold to 2.5s.
- Build: each line is its own Sequence from a beatFrame. Punch-in is a fast spring
  (config damping 14, stiffness 220, mass 0.7) on scale 0.85 to 1 plus opacity 0 to 1
  over about 6 frames, landing on the beat.

TEARDOWN, 2.5 to 10.0s (three problems, whip between each)
- 2.5 to 5.0s, whip to the weak logo close-up. Text hits on consecutive beats:
  "LOGO LOOKS HOMEMADE." then "CUSTOMERS ASSUME CHEAP." (DM Sans caps, white, the
  consequence word in gold).
- 5.0 to 7.5s, whip to the weak bio: "BIO SAYS NOTHING." then "NO REASON TO CALL."
- 7.5 to 10.0s, whip to the messy grid: "RANDOM POSTS." then "LOOKS CLOSED."
- Build: whip transition is outgoing translateX 0 to -110% and incoming 110% to 0
  over about 5 frames, with a horizontal motion blur peaking mid-whip (filter blur via
  interpolate). Text punches as above. Tension rises, cuts stay on the beat.

REBUILD, 10.0 to 22.0s (three fixes, accelerating into the drop)
- 10.0 to 14.0s, the new NSD logo snaps in (matte black, electric blue):
  "NOW IT LOOKS LIKE A REAL SHOP." then "ONE YOU'D TRUST YOUR CAR WITH."
- 14.0 to 18.0s, the new bio hits: "NOW IT SAYS WHAT THEY DO." then "AND WHY TO BOOK."
- 18.0 to 22.0s, the new grid assembles: "NOW IT LOOKS BUSY." then "BOOKED AND REAL."
- Build: logo and bio snap with a fast spring (scale 0.9 to 1 plus opacity). The grid
  assembles as 9 tiles, each a fast spring with delay tileIndex times 1 to 2 frames.
  Tighten the cut spacing slightly across the three fixes so it accelerates into 22s.

PAYOFF SNAP, 22.0 to 27.0s (on the drop)
- 22.0s, the drop: a hard before-to-after flip of the whole profile. Optional 1 to 2
  frame white flash on the cut for impact. Text: "SAME SHOP. NEW EVERYTHING." (DM Sans
  caps, white with gold).
- 24.0 to 27.0s: the phone showing the new NSD feed pushes in (phone-nsd-feed.png),
  scale 1.06 to 1.0 over about 14 frames with a slight upward parallax.
- Build: place the flip exactly on the drop frame (a Sequence boundary). The flip can
  be a hard cut or a 4-frame split-screen wipe. This is the visual peak on the audio
  peak.

LESSON, 27.0 to 33.0s (music pulls back, navy framing, the one breath)
- Navy background. Text in Cormorant Garamond, white: "A customer judges your business
  by your brand before they ever call." A gold underline draws under it. Hold.
- Build: this is the only slower beat. Fade-up over about 18 frames on BRAND_OUT, the
  underline is a gold rule with scaleX 0 to 1 on BRAND_OUT. Let it sit. This breath is
  what separates premium from hype-edit.

DM CTA, 33.0 to 38.0s (navy, gold accent)
- Text in DM Sans, white: "DM us your niche." then "We'll show you what your brand
  could look like." with a small gold accent and the LISB mark. No price.
- Build: punch-in on a beat, hold to the end. Keep a short tail so the last frame is
  not cut off.

## Remotion build approach (overall)
- Drive everything off the beat grid. Keep a constants map of beat index to event so
  the whole edit is locked to the track. The drop frame is an explicit constant.
- Kinetic text: a reusable PunchText component, fast spring on scale plus opacity,
  caps DM Sans, optional gold keyword. Each is a Sequence placed on a beatFrame.
- Whips: a reusable Whip transition, translateX plus a peaking motion blur over about
  5 frames. Or @remotion/transitions slide() with a very short springTiming plus a
  blur overlay.
- Grid assemble: map 9 tiles to staggered fast springs.
- Before-after flip: a hard Sequence boundary on the drop frame, optional white flash.
- Lesson and CTA: navy AbsoluteFill, the lesson is the one slower fade-up with a gold
  underline draw, the CTA punches in.
- Audio: a single Audio of the music track spanning the whole composition. No per-slide
  voiceover. This is the format's audio exception.
- Motion retune: reuse the easing tokens from premium-reel-creative-direction.md but
  fast, durations cut to one half or one third, punchier springs (lower damping for
  the snaps), everything beat-locked. Premium is precision plus the single lesson hold,
  not slowness.

## Honesty caveat on the before
The before must read as a generic, representative weak detailer brand. Do not use a
real competitor's actual brand, and do not imply North Shore Details literally looked
like this before. The honest frame is what a weak detailer brand looks like versus what
we build.

## What we are testing
Does kinetic energy plus a demonstrated, owner-framed teardown and rebuild stop the
scroll and drive DM intent. Ship this one, watch retention and DMs, then decide whether
The Rebuild becomes the repeatable weekly format across niches.
