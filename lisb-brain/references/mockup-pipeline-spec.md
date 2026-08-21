# Brand Mockup Pipeline Spec

Concept B lives or dies on mockup quality. A reveal that shows the brand on
fake-looking surfaces is worse than the old slideshow. This is the real dependency.

## The one rule that separates professional from fake
The applied logo is always the real vector or PNG, composited onto a realistic base
with correct perspective, lighting integration, and shadow. Never let an image model
render the logo or any text. Diffusion models mangle marks and type. AI may generate
the empty scene; the brand is always composited in afterward.

## The surface set per reveal: 3 universal plus 1 niche-specific
Every reveal uses four surfaces. Three are universal, the fourth is the niche hero.

Universal:
1. Business card in hand, close, shallow depth. The most relatable "this is a real
   business" cue.
2. Signage. Form varies by niche (storefront, window, yard, truck).
3. Phone screen showing the new Instagram grid. We already render the grid, so this
   is the highest-value and easiest surface. Build it first.

Niche-specific fourth surface (the hero):

| Niche | Signage form | Niche hero surface |
|---|---|---|
| Auto detailing | shop banner or window | vehicle door decal or magnet |
| Med spa | reception sign or window lettering | treatment menu card or product label |
| Landscaping or hardscaping | yard sign | truck door decal or polo embroidery |
| Boutique fitness or pilates (Eastlight) | studio window or wall | water bottle, tote, or schedule card |
| Boutique boxing (Callahan) | exterior club sign or window | gloves on a hook or the wrapped-hands detail |
| Wedding or portrait photo | A-frame or booth sign | welcome guide cover or print box |
| Masonry | yard sign | truck decal or banner |

Note: on a med spa treatment menu, keep prices off-frame. The no-price rule is about
our $175, but a price-free menu also reads more premium. That is a menu-specific
preference, not a blanket ban: client-side pricing may appear on promo and offer
artwork, and our own price never appears anywhere.

## How to produce each surface convincingly

Business card:
- Best: a photographic smart-object card mockup (card in hand or on a textured
  surface). Drop the logo into the smart object. Good templates apply paper
  displacement so the ink sits in the stock and picks up the light.
- Keep a soft-focus background and a real shadow under the card. Slight depth of
  field sells it.

Signage:
- Smart-object signage mockup matching the niche. The logo must follow the surface
  plane (perspective) and pick up the scene light. Lit signs get a subtle screen or
  glow blend, vinyl gets a matte multiply.

Phone screen (IG grid):
- Composite our rendered IG grid into a device-frame mockup (hand holding a phone).
  Add a faint screen reflection and a realistic status bar. This is mostly
  compositing our own asset, so it is the cheapest and most on-message surface.

Niche hero surface:
- If a good smart-object template exists (vehicle, apparel, menu), use it. If not,
  AI-generate the blank scene (no logo), then composite the real logo with a
  perspective warp, a multiply or screen blend, a displacement or grain pass so it
  wraps to the material, and a soft contact shadow.

## Recommended pipeline (primary and fallback)
Primary: premium photographic smart-object mockup templates (Envato Elements, Yellow
Images, Pixelbuddha, Mockup World) plus the real logo dropped into the smart object.
This is the fastest path to professional because the realism (lighting, shadow,
texture) is baked into the photography. Edit in Photoshop or Photopea (free, supports
smart objects and is scriptable for batch).

Fallback for surfaces with no good template: AI-generate the empty scene with a
current image model, then composite the real logo programmatically (Python Pillow
plus OpenCV warpPerspective for the plane, a blend mode for material integration, a
displacement or grain pass, and a soft shadow). Node with sharp works too.

Always finish with one consistent color grade or LUT across all four surfaces so the
reveal reads as a single shoot.

## What makes a mockup look fake (avoid all of these)
- Logo sitting flat on top of the surface instead of integrated into its texture and
  light. Fix with multiply or displacement so paper grain and shadows show through.
- Wrong perspective. The logo must lie on the surface plane.
- No shadow, or a shadow whose direction fights the scene light.
- Mismatched color temperature across surfaces. Fix with one grade.
- AI-rendered logo or text. Never. Composite the real vector.
- Sterile, too-perfect frames. Keep photographic depth of field, slight grain, and
  real backgrounds.

## Output specs
- Render each surface at about 2x the frame (roughly 2160 px on the short side) so the
  reveal can push in and parallax without softening.
- Bake the final mockup as a flat PNG with the logo already applied, so Remotion only
  animates images. Keep the transparent logo separate for the logo sting.
- Per reveal deliver: the logo (for the sting), four baked surface PNGs, and the
  client palette. The assembly payoff can be composed in Remotion from the four
  surfaces or pre-composed as one image.

## Build order
1. Phone-plus-grid surface first. We already have the grid, it is the easiest and most
   on-message.
2. Business card and signage from smart-object templates.
3. The niche hero surface. Template if available, AI-scene-plus-composite if not.
4. Lock a single grade and a reusable template set per niche so future reveals are
   fast.

## Boundary
Producing these mockups (image generation and compositing) is execution and design
work, outside this content brain. This spec defines what to build and the quality
bar. The actual asset production happens on the design and render side.
