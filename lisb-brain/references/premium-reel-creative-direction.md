# Premium Reel Creative Direction (Motion and Composition)

Purpose: lift the visual quality of LISB reels from plain fade transitions to
premium, elegant motion design, so the videos look like what we sell. This is a
motion and composition upgrade only. The brand identity does not change.

## Hard constraints (do not touch)
- Palette stays navy #0D1B2A, white #FFFFFF, gold #C9A84C. Gold is the accent
  for motion highlights only (underlines, label chips, hairlines). Never flood
  a frame with gold.
- Headings stay Cormorant Garamond. Body stays DM Sans.
- Slide structures stay as defined in content-pipeline.md. Reveals are 8 slides,
  educational reels are 7 slides. We are changing how slides move, not what they
  say or how many there are.
- Output stays 1080 by 1920.

## Frame-rate note
All frame counts below assume 30 fps, which matches the project's current
"45-frame tail buffer" (1.5 seconds). If the project renders at 60 fps, double
every frame number here. Confirm the project fps before building.

---

## The Remotion motion toolkit (verified API)

- useCurrentFrame() returns the current frame. useVideoConfig() returns
  { fps, width, height, durationInFrames }.
- interpolate(input, inputRange, outputRange, options). Options:
  - easing: an easing function from the Easing module.
  - extrapolateLeft and extrapolateRight: 'extend' (default), 'clamp',
    'identity', or 'wrap'. For entrances always set extrapolateRight: 'clamp'
    so values do not drift past their end state.
- spring({ fps, frame, config, from, to, durationInFrames, delay, reverse }).
  - config is SpringConfig: damping (default 10), mass (default 1), stiffness
    (default 100), overshootClamping (default false, so springs overshoot a
    little by default).
  - delay holds the spring at its start value for N frames, which is the
    cleanest way to stagger springs.
- Easing module: Easing.bezier(x1, y1, x2, y2) is a CSS cubic-bezier. Easing.in,
  Easing.out, Easing.inOut wrap a base curve (for example Easing.out(Easing.cubic)).
  Base curves include linear, quad, cubic, poly(n), sin, circle, exp, plus
  bounce, elastic, back which we mostly avoid (see below).
- interpolateColors(input, inputRange, ['#0D1B2A', '#C9A84C']) for tweening
  brand colors.
- Sequencing: <Sequence from durationInFrames>, <Series>, and for slide-to-slide
  transitions the @remotion/transitions package: <TransitionSeries>,
  springTiming({ config }), linearTiming({ durationInFrames }), and presentations
  fade(), slide(), wipe().
- Fonts: @remotion/google-fonts/CormorantGaramond and /DMSans, loaded with
  loadFont() so renders are deterministic.

## The LISB easing vocabulary (use these three, not raw linear)

Define these once and reuse everywhere. Consistency of easing is most of what
makes motion feel designed rather than default.

- BRAND_OUT = Easing.bezier(0.16, 1, 0.3, 1)
  A strong decelerating curve (an easeOutExpo feel). Fast on entry, long soft
  settle. This is the default for every element entrance.
- BRAND_IN_OUT = Easing.bezier(0.65, 0, 0.35, 1)
  Symmetrical ease for things that move continuously on screen (parallax,
  slow push-ins).
- BRAND_SETTLE = spring with config { damping: 26, stiffness: 120, mass: 1 }
  A controlled settle with a barely-there overshoot. Use for logo and hero
  scale. For a zero-overshoot settle set overshootClamping: true or raise
  damping to about 200.

Banned motion (reads cheap, kills the premium feel): Easing.bounce,
Easing.elastic, high-overshoot springs (low damping), spinning logos, fast zooms,
linear fades on text, anything that moves more than it needs to.

---

## Technique 1: Easing curves

What it is: the acceleration profile of a moving value over time. Linear motion
(the implicit default if you only pass start and end) moves at a constant speed
and looks robotic. Eased motion accelerates and decelerates like physical objects.

Why it elevates: luxury motion is almost always decelerating. Elements arrive
quickly, then ease into a long, gentle stop. The eye reads that slow settle as
calm, expensive, and deliberate. A single shared curve across every element is
what ties a video together.

How in Remotion:
```
const frame = useCurrentFrame();
const y = interpolate(frame, [0, 18], [40, 0], {
  easing: BRAND_OUT,            // Easing.bezier(0.16, 1, 0.3, 1)
  extrapolateRight: 'clamp',
});
const opacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: 'clamp' });
```
Rule of thumb: entrances run 12 to 20 frames. Never animate position without an
easing curve, and never use the same duration for opacity and movement (opacity
should finish slightly before the slide settles).

## Technique 2: Staggered element reveals

What it is: the elements on a slide enter one after another with a small offset,
instead of all at once. Label, then headline, then supporting line, then hairline.

Why it elevates: simultaneous reveals feel like a slide deck. A 2 to 4 frame
stagger creates a sense of choreography and guides the eye in reading order. It
is the single highest-impact change from the current plain look.

How in Remotion: offset each element's spring with delay, or shift its interpolate
input range.
```
const elements = [labelRef, headlineRef, bodyRef, ruleRef];
const STAGGER = 3; // frames between elements at 30fps
const enter = (i) => spring({
  fps, frame, delay: i * STAGGER,
  config: { damping: 26, stiffness: 120, mass: 1 },
});
// element i: opacity = enter(i); translateY = interpolate(enter(i), [0,1], [28, 0]);
```
Keep total stagger under about 12 frames so the slide is fully settled well before
the voiceover for that slide ends.

## Technique 3: Typographic animation

What it is: animating the type itself, not just fading the text box. Two premium
moves that suit Cormorant Garamond and DM Sans:
- Fade-up with a settle: each line rises 24 to 40px into place on BRAND_OUT.
- Letter-spacing settle on headlines: start the Cormorant heading slightly wide
  (for example 0.06em) and let it close to its final tracking. This subtle
  contraction reads as refined.
- Optional line-by-line mask reveal for the hero headline: each line sits in a
  container with overflow hidden and slides up from 100 percent, so words appear
  to rise from behind a hairline.

Why it elevates: editorial brands animate type with restraint. A serif headline
that eases into its tracking feels typeset rather than dropped in. Avoid
per-letter bounces or typewriter effects, which read as cheap.

How in Remotion:
```
const tracking = interpolate(frame, [0, 22], [0.06, 0], {
  easing: BRAND_OUT, extrapolateRight: 'clamp',
}); // style: letterSpacing: `${tracking}em`
// Masked line: wrap line in div{ overflow:hidden }, inner div translateY 100% -> 0
```
DM Sans body lines fade-up only, no tracking animation, to keep hierarchy.

## Technique 4: Depth and parallax

What it is: separating a frame into layers (background, mid, foreground) that move
at different speeds and scales, plus soft depth cues (a faint vignette, a gentle
blur-in on entry).

Why it elevates: flat frames feel like slides. A background that drifts or scales
slightly slower than the foreground creates the illusion of a camera and a room,
which feels produced and high-end.

How in Remotion:
```
// Slow background push-in across the whole slide
const bgScale = interpolate(frame, [0, durationInFrames], [1.06, 1.0], {
  easing: BRAND_IN_OUT,
});
// Foreground enters faster and from a larger offset than mid layer
const blurIn = interpolate(frame, [0, 16], [10, 0], { extrapolateRight: 'clamp' });
// style: filter: `blur(${blurIn}px)`
```
Keep parallax tiny: 3 to 8 percent of scale, a few pixels of drift. Overdone
parallax looks like a template. Add a fixed radial vignette over the navy to give
the background depth without motion cost.

## Technique 5: Pacing and holds

What it is: deliberately designing the still moments. After an element settles, it
should hold, motionless, while the viewer reads, before anything else changes.

Why it elevates: amateur motion never stops moving, which feels anxious. Premium
motion is mostly stillness punctuated by short, confident transitions. The hold is
where the content lands and where the brand feels confident.

How in Remotion: structure each slide as ENTER (12 to 20 frames), HOLD (the bulk
of the slide, matched to the voiceover line), EXIT (8 to 12 frames, only if not
using a cross-slide transition). Drive timing off the per-slide audio clip length
already in the pipeline, so motion and voiceover settle together.
```
// On a 90-frame slide: enter 0-18, hold 18-78, exit 78-90.
const exit = interpolate(frame, [78, 90], [0, 1], { extrapolateLeft: 'clamp' });
```
Replace the current uniform 6-frame fade between slides with a TransitionSeries
using springTiming for the hero beats and a short fade for quieter cuts, so cuts
have intention instead of one mechanical dissolve everywhere.

## Technique 6: The logo reveal moment (reveals only)

What it is: the opening of a brand reveal, where the client logo is the full
visual with no text overlay. This is the signature 2 seconds and deserves bespoke
motion.

Why it elevates: this single beat is the proof that we do premium work. It should
feel like a logo sting, not a fade-in.

The recommended sequence (about 60 frames):
1. Frames 0 to 8: navy field holds, a faint gold hairline grows from center
   (scaleX 0 to 1 on BRAND_OUT) as an anchor.
2. Frames 6 to 26: the logo fades up and scales from 0.96 to 1.0 on BRAND_SETTLE
   (spring, damping 26), with a 6 to 0 px blur-in so it resolves into focus.
3. Frames 22 to 40: a soft gold shimmer sweeps once across the mark (a masked
   gradient translated left to right via interpolate), then never repeats.
4. Frames 30 to 60: everything holds dead still on the settled logo. Stillness
   sells it.
```
const sLogo = spring({ fps, frame, delay: 6, config: { damping: 26, stiffness: 120, mass: 1 }});
const logoScale = interpolate(sLogo, [0, 1], [0.96, 1]);
const logoBlur  = interpolate(frame, [6, 26], [6, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
const shimmerX  = interpolate(frame, [22, 40], [-1, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: BRAND_IN_OUT });
const rule      = interpolate(frame, [0, 8], [0, 1], { easing: BRAND_OUT, extrapolateRight: 'clamp' }); // scaleX of gold hairline
```
For med-spa and aesthetic reveals, run this same sequence on the warm-dark
editorial background allowed by brand-system.md instead of navy, with the client
palette. The motion language does not change, only the canvas.

---

# OUTPUT 1: Upgraded brand reveal template spec (8 slides)

Canvas 1080x1920, 30fps. Shared: navy base with a fixed radial vignette, the three
LISB easing tokens, a 4-element max stagger of 3 frames, slow background push-in
(scale 1.06 to 1.0) running under every slide. Slide-to-slide via TransitionSeries:
springTiming for hero cuts (into slide 1, into the closing, into the DM CTA), a
10-frame fade elsewhere. Gold used only for the kicker label chip, hairlines, and
the logo shimmer.

- Slide 1 — Logo reveal (no text): the 60-frame logo sequence in Technique 6.
  Client palette and mark only. This is the longest-held slide.
- Slides 2 to 5 — Brand slides (gold label + asset): the asset (logo, flyers,
  social set, full pack) scales in from 0.97 with a blur-in on BRAND_SETTLE; the
  gold kicker chip draws in (scaleX 0 to 1) then the label fades; any caption line
  fades-up after a 3-frame stagger. Hold still for the bulk of the slide. A subtle
  parallax between the asset (foreground) and its drop shadow (mid) adds depth.
- Slide 6 — Closing statement: Cormorant line enters with the letter-spacing
  settle, masked line reveal if two lines. Long hold. This is the emotional beat,
  so give it the most stillness.
- Slide 7 — Follow CTA ("Follow us for next week's reveal"): text fades-up, a gold
  hairline draws under it. Calm, short.
- Slide 8 — DM CTA ("Want this for your business? DM us to get started"): the only
  slightly more active slide. The CTA line settles, then a gold underline draws on
  BRAND_OUT to push the action. No price anywhere (per the pricing rule).

Per-slide timing is driven by the existing per-slide ElevenLabs audio clips, so the
ENTER, HOLD, EXIT envelope is matched to each voiceover line. Keep the 45-frame
tail buffer on slide 8.

# OUTPUT 2: Educational reel template — same motion language (7 slides)

The educational template (Hook, 4 body slides with gold labels, closing, CTA)
inherits the exact same easing tokens, stagger system, parallax, and pacing
envelope. Differences are scope, not language:

- No logo-reveal sting. The hook is text, so it uses the typographic treatment:
  the Cormorant hook enters with the letter-spacing settle and a masked line
  reveal, over the navy base with the slow background push-in. That gives the hook
  the same premium open without a client logo.
- Body slides 2 to 5 reuse the brand-slide motion exactly: gold kicker chip draws
  in, headline fades-up, optional supporting line staggered behind it, long hold.
  This is where the two templates look most alike, which is the point.
- Closing and CTA reuse slides 6 and 8 of the reveal verbatim in motion. The CTA
  underline-draw is the same gold accent.

Because the body and closing motion are shared, once the reveal template is proven
we port the same components (the EasedText, KickerChip, SlideShell, and the
transition config) into the educational template with almost no new motion work.
Build the shared motion components first, prove them on a reveal, then the
educational rollout is mostly composition.

---

## What this changes in the rule set (for later, not now)
- content-pipeline.md Production Tools currently says "FADE at 6 frames." Once this
  is adopted, that line should evolve into a reference to this transition language
  (springTiming for hero cuts, short fade elsewhere). The 45-frame tail buffer and
  per-slide audio clips stay as written.
- Nothing in brand-system.md changes. The palette, fonts, and the warm-dark med-spa
  register are all preserved and reused by the motion spec.
