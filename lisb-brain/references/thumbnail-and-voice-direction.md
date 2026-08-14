# Thumbnail Formula and Voice-to-Pillar Mapping

Two specs. The thumbnail formula is ready to lock. The voice mapping is the logic
only, ready to finalize once Brian picks a voice from samples.

---

# PART 1: The thumbnail formula

PROMOTED. The operative rules now live in the Reel Thumbnails section of
.claude/rules/brand-system.md, which is authoritative. This part is kept as the
reasoning behind them. If the two ever disagree, brand-system.md wins and this
section should be corrected to match.

## What a thumbnail is for here
The cover image is what a profile visitor sees in the grid, which is the exact
audience we are failing to convert. Strong reach with weak follower conversion means
people arrive at the profile and do not commit. A grid that reads as one system is a
trust signal before a single reel is played.

Key technical point that makes this work: the reel cover is chosen separately from
frame one. So a reveal can still open on the pure logo with no text overlay (the
brand-system rule) while its grid cover carries our branded treatment. Thumbnail and
first frame are different jobs for different audiences. The first frame serves the
scroller, the cover serves the profile visitor.

## The fixed signature (identical on every thumbnail, no exceptions)
This is what makes the grid read as one system:
- A gold hairline running the full width, with the LISB mark centered directly below
  it, locked to the same position and size on every cover. It reads as a masthead
  footer, the way a publication signs every page.
- The same outer margin on every cover.
- Only two typefaces ever: Cormorant Garamond for the hook, DM Sans small caps for
  the kicker.
- Palette is navy, white, and gold only. Client color never enters our framing.

Everything above the hairline can change. The hairline and mark never do. That single
persistent element is what lets reveal covers show client work and still belong to the
same grid.

## The variable zone (above the hairline)
1. Ground. Navy #0D1B2A by default. Every third reel uses gold #C9A84C to break the
   pattern, which is the existing grid rhythm rule and is where that rhythm now lives.
   Aesthetic niches may use the warm dark register.
2. Kicker. Small DM Sans caps, wide tracking, gold on navy or navy on gold. Names the
   value the post gives, in owner language, never internal pillar terms. Never the
   words pillar, equity, or content.
3. Hook. Cormorant Garamond, weighted cut, three to six words, maximum two lines.
   A compressed version of the reel's own hook, never a different message.

## Per-pillar treatment
- Branding Tips: kicker BRAND TIP with a running number, for example BRAND TIP 12.
  Numbering implies a series, which is a direct follow trigger, and it makes the grid
  legible as an ongoing resource. Highest-value use of the kicker slot.
- Brand Equity: kicker names the stake in owner terms, for example WHAT IT COSTS YOU
  or WHAT YOU CAN CHARGE. Hook carries the tension.
- Business Mindset: no kicker. Type-only, centered, the most whitespace of any cover.
  The quiet ones should look quiet in the grid.
- Brand Reveals: the client's mark or a hero surface fills the frame above the
  hairline, kicker is the brand name and niche, for example GARRISON DETAIL CO.
  AUTO DETAILING. No hook line. This is the designed exception: the work is the
  message, and the hairline and mark keep it inside the system.
- The Rebuild: kicker THE REBUILD. Hook is the before-state tension. Ground stays navy
  so the flagship reads consistently every week.

## Legibility rules
- Design at 1080 by 1920 but keep the kicker, hook, hairline, and mark inside the
  central safe area, since grid crops change and the sides are the first thing lost.
- The hook must be readable at thumbnail scale. If it cannot be read on a phone at
  grid size, it is too long or too small. Three to six words is the discipline that
  prevents this.
- High contrast only. White on navy, navy on gold. No gold text on navy at small size,
  it goes muddy.
- On reveal covers, if the client work is busy, the hairline and mark sit on a solid
  navy band so the signature never fights the image.

## Why this holds together
The grid varies by ground color, kicker, and content, so it does not look repetitive.
It unifies through the hairline, mark, margins, and two typefaces, so it never looks
like a different account each post. That is the difference between a grid that reads
as a system and one that reads as a folder.

---

# PART 2: Voice-to-pillar mapping logic

The register mapping below is final in logic. Only the voice itself is open. Once
Brian picks, these map onto the chosen voice's settings.

## The governing principle
Register follows what the viewer is being asked to do, not what the topic is.
Content that asks someone to face a cost gets a level, serious read. Content that
hands someone a tool gets a brisk, useful read. Content that shows proof gets a
quiet, underplayed read, because overselling proof undercuts it.

The through-line across all four: confident, never hyped. The brand sells durability.
A voice that oversells reads as the cheap version of what we are selling.

## The mapping

| Pillar | Register | Pace | Why |
|---|---|---|---|
| Brand Reveals | Quiet authority, understated, warm | Slowest | The work is the proof. Underplay it. Selling hard over a strong visual makes it look like it needs the help. |
| Brand Equity | Serious, level, consequential | Measured | This is money and loss framing. It needs weight without alarm. A peer telling you something you need to hear, not a warning. |
| Branding Tips | Lighter, brisk, useful | Fastest | Instructional. Energy and clarity carry it. Helpful, not heavy. This is the most approachable register we use. |
| Business Mindset | Warmest, most personal, reflective | Slow, with room to breathe | The trust register. Small pauses earn more here than emphasis does. Closest to one person talking to another. |

Suspense sits in one place only: Brand Equity, and only mildly. It comes from the
stakes and the pacing, never from a dramatic read. Reveals are the opposite of
suspenseful, they are settled and certain. If a voice sounds like a movie trailer on
any pillar, it is wrong for this brand.

## Parameter direction (starting points, tune after the voice is chosen)
Current baseline is stability 0.80, similarity 0.90, speed 0.85. Similarity stays at
0.90 throughout. Stability and speed move by register:
- Reveals: stability 0.85, speed 0.85. Controlled and calm.
- Brand Equity: stability 0.80, speed 0.88. Level and direct.
- Branding Tips: stability 0.72, speed 0.95. More expression, more momentum.
- Business Mindset: stability 0.68, speed 0.80. Most expressive, most room.

Lower stability buys warmth and variation, higher stability buys control. The spread
across pillars should be audible but never sound like four different people.

## How to judge the samples
Have every candidate voice read the same three lines, one per register extreme, so
the differences surface instead of the delivery of one nice line:
1. Equity, serious: "Nobody can judge your work before they hire you."
2. Tips, brisk: "Line one names exactly who you serve."
3. Mindset, warm: "Show up looking like the business you already are."

Judge on three things:
- Does it sound like a confident peer, or like an ad? Peer wins.
- Can it do warm and serious without sounding like two different people? A voice that
  only does one register will fight half the content.
- Does it sound expensive at slow speed? Cheap voices fall apart when slowed down, and
  our slowest registers are reveals and mindset, the two that carry the most trust.

Reject any voice that sounds like a hype narrator, a radio ad, or a customer service
line, however clean the audio is.

## Open structural question to resolve alongside the voice pick
The kinetic standard is currently text-driven over one continuous music track, with no
voiceover, while the 7-slide educational format uses per-slide voiceover clips. Before
this mapping goes into production, decide which of the two the chosen voice is for:
- Voiceover returns to the kinetic reels, layered over the music bed, which means the
  music mix has to duck under the voice and the beat-locked timing has to accommodate
  read length.
- Or voiceover stays with the 7-slide format only, and the kinetic reels remain text
  and music.
The mapping above holds either way. Only the surface it applies to changes.
