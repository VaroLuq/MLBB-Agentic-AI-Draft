---
name: Draft Copilot
description: An MLBB draft copilot built as the game's own pick/ban screen, blue-black stage, chamfered steel panels, gold only where the decision is.
colors:
  stage-950: "#0a1017"
  stage-900: "#101820"
  stage-850: "#131d28"
  stage-800: "#16212d"
  stage-700: "#1d2b3a"
  stage-600: "#263749"
  edge: "#2a3646"
  steel: "#3a4a5c"
  steel-hi: "#5d7188"
  ink: "#e8edf3"
  ink-2: "#b4bfcb"
  ink-3: "#8d9aa9"
  ink-4: "#6f7c8b"
  gold: "#e8c547"
  gold-hi: "#f4dc7e"
  gold-lo: "#b8912b"
  gold-deep: "#3d3110"
  ally: "#4a90d9"
  ally-ink: "#7fbaf5"
  ally-tint: "#12233a"
  enemy: "#c0392b"
  enemy-ink: "#f28577"
  enemy-tint: "#2b1518"
  ok: "#58c48a"
  warn: "#f0a93b"
  danger: "#ff7a7a"
typography:
  display:
    fontFamily: "Barlow Condensed, Arial Narrow, ui-sans-serif, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 700
    lineHeight: 0.95
    letterSpacing: "0.03em"
  headline:
    fontFamily: "Barlow Condensed, Arial Narrow, ui-sans-serif, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.06em"
  title:
    fontFamily: "Barlow Condensed, Arial Narrow, ui-sans-serif, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.06em"
  body:
    fontFamily: "Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.07em"
  caption:
    fontFamily: "Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.25
rounded:
  none: "0"
  field: "2px"
  lamp: "50%"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button:
    backgroundColor: "{colors.stage-700}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 16px"
    height: "40px"
  button-hover:
    backgroundColor: "{colors.stage-600}"
  button-primary:
    backgroundColor: "{colors.gold}"
    textColor: "#1a1405"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 26px"
    height: "48px"
  button-quiet:
    backgroundColor: "{colors.stage-900}"
    textColor: "{colors.ink-2}"
    height: "40px"
  button-danger:
    backgroundColor: "{colors.stage-700}"
    textColor: "{colors.danger}"
  panel:
    backgroundColor: "{colors.stage-800}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "18px"
  panel-ally:
    backgroundColor: "{colors.ally-tint}"
    textColor: "{colors.ally-ink}"
    padding: "16px"
  panel-enemy:
    backgroundColor: "{colors.enemy-tint}"
    textColor: "{colors.enemy-ink}"
    padding: "16px"
  field:
    backgroundColor: "{colors.stage-950}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "0 12px"
    height: "42px"
  seg-face:
    backgroundColor: "{colors.stage-850}"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    height: "36px"
    padding: "0 14px"
  seg-face-checked:
    backgroundColor: "{colors.gold-deep}"
    textColor: "{colors.gold-hi}"
  tag:
    backgroundColor: "{colors.stage-850}"
    textColor: "{colors.ink-2}"
    typography: "{typography.caption}"
    padding: "5px 9px"
  hero-tile:
    backgroundColor: "{colors.stage-850}"
    textColor: "{colors.ink}"
    padding: "9px 4px 8px"
  slot:
    backgroundColor: "#173151"
    textColor: "{colors.ink}"
    height: "60px"
    padding: "8px 12px"
  lead-pick:
    backgroundColor: "{colors.stage-800}"
    textColor: "{colors.ink}"
    padding: "22px"
  banner-warn:
    backgroundColor: "#2a2313"
    textColor: "{colors.ink}"
    padding: "12px 16px"
---

# Design System: Draft Copilot

## Overview

**Creative North Star: "The Pick/Ban Screen"**

The interface is Mobile Legends' own draft screen rebuilt as a working tool. It sits on a blue-black stage with a faint hex lattice. Two teams face each other across a hero pool, and the recommendation arrives as the next pick locking in. It is a dark, low-light-room product: dense enough to read a full draft at a glance, quiet enough that the one gold thing on screen is always the thing to act on.

The world has one shape and one color rule. The shape is the chamfer: every panel, button, tile, chip and badge is cut at the top-left and bottom-right corners and edged with a thin steel line. The color rule is that gold is reserved for the primary action, the current selection, and the lead recommendation. Ally slate-blue and enemy red tint entire side panels, so the ally/enemy split is readable from across the room. Stripped of all content, the chamfers, the gold and the blue/red split still identify it.

It rejects the stacked-form dashboard (three selects above a button). Controls sit where the action is: the lane selector lives in the lock-in bar beside the button it parameterizes, not in the hero pool.

**Key Characteristics:**
- Blue-black stage (#101820) with a hex lattice at about 3% white and a soft radial glow at the top.
- One silhouette: chamfered top-left and bottom-right, 1px steel edge, inner fill layer.
- Gold is scarce and semantic: act, selected, lead.
- Ally slate-blue and enemy red tint whole panels, never just accents.
- Condensed uppercase display type for names and headings; Barlow for everything readable.
- Flat by default: depth comes from edge and fill tone, not shadow.
- Motion is short and honest: one authored flip, live loading, nothing decorative.

## Colors

A blue-black steel palette with a single gold accent, two team hues, and three status tones.

### Primary
- **Draft Gold** (#e8c547): the primary action fill, the lead pick's edge, the active nav underline, the busy lamp and the progress arc. Never a decoration.
- **Gold Highlight** (#f4dc7e): focus outlines and edges everywhere, link color, selected-state text, the hover edge of the primary button.
- **Gold Lo** (#b8912b): the edge of a selected chip, segment or note row, and the primary button's resting edge.
- **Gold Deep** (#3d3110): the fill behind any selected control.

### Secondary
- **Ally Slate-Blue** (#4a90d9): ally team edge (mixed 58% into the steel edge), checked ally segment edge. **Ally Ink** (#7fbaf5) is its text tone; **Ally Tint** (#12233a) fills the whole ally panel.

### Tertiary
- **Enemy Red** (#c0392b): enemy team edge and checked enemy segment. **Enemy Ink** (#f28577) is its text tone; **Enemy Tint** (#2b1518) fills the whole enemy panel.
- **Status:** Go Green (#58c48a) for healthy lamps and rising win rates, Amber Warn (#f0a93b) for caution tags, banners and lamps, Alarm Coral (#ff7a7a) for errors, destructive actions, falling rates and the ban hazard band.

### Neutral
- **Stage** ramp: #0a1017 (inputs, code wells, top bar), #101820 (page), #131d28 (tiles and resting controls), #16212d (panels), #1d2b3a (buttons, hovered tiles), #263749 (hover fill, meter rests).
- **Edge** (#2a3646) is the default 1px line; **Steel** (#3a4a5c) and **Steel Hi** (#5d7188) are hover and emphasis edges.
- **Ink** ramp: #e8edf3 (primary text), #b4bfcb (secondary), #8d9aa9 (tertiary and placeholders, still legible), #6f7c8b (disabled text only, deliberately below 4.5:1).

### Named Rules
**The Gold Is a Verb Rule.** Gold appears only on the primary action, the current selection, and the lead recommendation (plus focus, which is always gold-hi). If two golds compete on one screen, one of them is wrong.

**The Whole-Panel Rule.** Team color tints the fill and edge of a whole side panel and its slots. It is never reduced to a small dot or label beside a neutral panel.

**The Disabled-Only Rule.** Ink 4 is for disabled text only. Any text that must be read uses Ink 3 or lighter.

## Typography

**Display Font:** Barlow Condensed (with Arial Narrow, ui-sans-serif, sans-serif), weights 600 and 700, self-hosted
**Body Font:** Barlow (with ui-sans-serif, system-ui, sans-serif), weights 400 to 700, self-hosted
**Mono:** ui-monospace, Cascadia Mono, Consolas (code and diagnostics only)

**Character:** Condensed and uppercase for anything that is a name, a slot or a heading, so it reads like a game HUD; Barlow at modest sizes for labels, controls and data so the tool stays legible. Condensed is never used for running text, controls or data.

### Hierarchy
The scale is fixed rem, never fluid: 0.75, 0.8125, 0.9375, 1.0625, 1.25, 1.5, 1.875, 2.5 rem.
- **Display** (Condensed 700, 2.5rem, 0.95, +0.03em, uppercase): the lead pick's hero name only.
- **Headline** (Condensed 700, 1.875rem, 1, +0.06em, uppercase): page and note-reader titles.
- **Title** (Condensed 700, 1.25rem, 1.1, +0.06em, uppercase): panel and team titles, prose sub-headings, empty-state headings (1.5rem).
- **Body** (Barlow 400, 0.9375rem, 1.5): default text. Rationale and prose run at 1.55 to 1.7 line height, capped at 66 to 72ch.
- **Label** (Barlow 600, 0.8125rem, +0.06 to 0.09em, uppercase): buttons, nav, segments, group labels. Field labels use the same size in sentence case at +0.04em.
- **Caption** (Barlow 500, 0.75rem): tags, hints, hero-tile names, meter labels.
- **Data:** numerals that change or compare use tabular figures (win rates, counts, percentages, deltas).

### Named Rules
**The Names Are Condensed Rule.** Hero names in slots, picks and the lead are Barlow Condensed 700 uppercase; every other hero mention in a list or sentence is Barlow.

## Layout

A single 1440px-max column with 24px side padding. The draft stage is a three-column grid: 272px ally panel, fluid centre column (ban strip, assign control, searchable hero pool), 272px enemy panel, 16px gaps, side panels stretching to the centre column's height and holding five equal-height slots. Below the stage sit the lock-in bar (lane selector left, secondary and primary actions right) and then a two-column lower area: results fluid, Live Intel rail 340px. The Notebook view is a list (300 to 400px) beside a reader.

Spacing is a small hand-set rhythm rather than a strict scale: 6px between chips and rows in dense groups, 8px inside grids and tiles, 12px between elements in a panel header, 16px between panels and inside team panels, 18 to 24px for panel interiors. Density is high but never cramped: rows keep 60px slots, 40 to 48px buttons, 84px minimum hero tiles.

Responsive changes are structural, not fluid. At 1180px the stage drops to two columns with the pool below spanning both, lower and Notebook areas collapse to one column. At 760px the stage is one column, slots become five compact vertical tiles in a row, the ban strip goes from 10 to 5 columns, the lock bar stacks with the primary button full width, and the top bar wraps with status below.

## Elevation & Depth

Flat and tonal. Depth is a stack of fills (stage 950 wells, 900 page, 850 tiles, 800 panels, 700 raised, 600 hover) plus a 1px edge line; hover raises a control by lightening its edge and fill and, on hero tiles, a 1px lift. Nothing glows or floats except the toast, which carries a single soft drop shadow to separate it from the page while it is on top of everything. Status lamps carry a 3px 22% halo ring, which is a state indicator, not a shadow.

### Shadow Vocabulary
- **Toast lift** (`box-shadow: 0 8px 20px rgb(0 0 0 / .35)`): only on toasts.
- **Lamp halo** (`box-shadow: 0 0 0 3px color-mix(in oklab, <tone> 22%, transparent)`): status lamps.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest and use edge and fill tone for hierarchy. A new surface does not get a shadow.

## Shapes

One silhouette rules everything: a rectangle with the top-left and bottom-right corners cut at 45 degrees, edged with a 1px steel line. The cut scales with the object: 4px on tags, 5 to 7px on badges, small tiles and chips, 8 to 10px on buttons, slots and banners, 12 to 14px on picks and panels, 18px on the lead pick, 16px on dialogs.

The edge is built, not bordered: an edge-colored layer clipped to the chamfer sits under an inner fill layer clipped to a slightly inset chamfer, both as pseudo-elements of an unclipped element. This lets real outlines, badges and children overflow the shape. State is expressed by changing the edge and fill values, and keyboard focus is a 2px gold-hi edge that follows the chamfer.

Text inputs, the status chip, kbd and inline code are the exception: plain rectangles with a 2px radius, deliberately un-clever, because they are native controls. Status lamps are circles. Skewed parallelogram cells (skew -18 degrees) form the confidence meter. Banned heroes carry a diagonal hazard band (repeating -45 degree stripes in danger coral) clipped to the chamfer, so the state reads without color. Portraits are chamfered initials badges: two-letter Barlow Condensed on a diagonal gradient from one of eight muted tone pairs (teal, indigo, violet, crimson, amber, forest, slate, plum) chosen by a hash of the hero name, so a hero always looks the same. The lead pick's portrait carries a gold edge.

## Components

### Buttons
- **Shape:** chamfered, 8px cut (10px for primary), 1px edge.
- **Default:** stage 700 fill, steel edge, uppercase Barlow 600 label at 0.8125rem, 40px high, 16px side padding.
- **Primary:** the only gold button. Gold gradient fill, gold-lo edge, near-black text, Barlow 700, 48px high, 26px side padding. One per view.
- **Quiet:** transparent at rest, edge and fill appear on hover. **Danger:** coral text on a red-tinted edge; delete keeps a two-step confirm.
- **Hover / Focus:** hover lightens the edge to steel-hi and fill to stage 600; press moves 1px down; focus is the 2px gold-hi chamfered edge; disabled uses Ink 4 text on stage 850.
- **Icon button:** 34px square, 6px cut.

### Chips and tags
- **Tag:** 4px cut, stage 850 fill, edge line, 0.75rem text; the warn variant swaps to an amber edge and text.
- **Filter chip / segment:** 6 to 7px cut, uppercase label. Selected state is gold-lo edge, gold-deep fill, gold-hi text. The assign control tints its selected state by meaning: ally blue, enemy red, ban muted gold.

### Panels and containers
- **Panel:** 14px cut, stage 800 fill, edge line, 18px padding, Condensed title.
- **Team panel:** whole-panel ally or enemy tint with a matching edge, and slots filled with a deeper tint of the same hue. Empty slots recede; the active empty slot takes the team ink edge.
- **Lead pick:** 18px cut, 2px gold edge, diagonal fill, 96px portrait, 2.5rem name, gold meter and percentage.
- **Pick rows:** 12px cut, rank numeral, 48px portrait, name, rationale.

### Inputs / Fields
- **Style:** stage 950 fill, 1px edge line, 2px radius, 42px high, native controls restyled.
- **Focus:** 2px gold-hi outline offset 1px and a gold-lo border. Hover moves the border to steel.
- **Error:** coral helper text below the field.
- **Search:** field with a 16px left-aligned icon in Ink 3.

### Navigation
Top bar in stage 950 with a 1px edge, sticky on desktop. Wordmark in Condensed with a gold mark, then uppercase label tabs; the current tab is gold-hi text over a 2px gold underline. Status chips sit right and stay at desktop reading order; on narrow screens the bar wraps and is no longer sticky.

### Hero tile, slot and ban
- **Hero tile:** 8px cut, portrait above an ellipsized 0.75rem name; hover takes a gold-lo edge and lifts 1px. A used hero is disabled, greyscaled, and shows a small colored mark (ally, enemy or ban).
- **Slot:** 10px cut, number, portrait, Condensed name, remove icon on hover.
- **Ban cell:** 7px cut in a ten-wide strip; a banned hero shows the hazard band.

### Banners, toasts, dialog
Banners are chamfered with an icon, message and optional actions; warn and error variants tint the edge and fill. Toasts appear bottom-left, 8px cut, tone edge. Dialogs are native `<dialog>` with a 16px chamfered inner panel and a dark scrim.

### Status and loading
Lamps show ok (green), warn (amber), busy (gold, pulsing) and idle. A recommendation request shows a live countdown ring with a gold arc, then shimmering skeleton cards. The lead pick's portrait does the one authored flip.

### Motion
150 to 250ms, ease-out (150ms colors and lifts, 180 to 260ms entrances on cubic-bezier(.16, 1, .3, 1)). The lock-in flip (260ms, portrait rotates in on Y) is the only authored moment. Loading motion (pulse, shimmer, arc) exists because it tells the truth about waiting. prefers-reduced-motion collapses all animation and transition to about 1ms.

## Do's and Don'ts

### Do:
- **Do** cut every surface with the chamfer (top-left and bottom-right) and build its edge with the edge-plus-fill layers; express state by changing the edge and fill values.
- **Do** reserve gold for the primary action, the current selection and the lead recommendation; focus is always a 2px gold-hi edge.
- **Do** tint whole side panels with ally slate-blue or enemy red and let slots inherit a deeper tint of the same hue.
- **Do** mark bans with the diagonal hazard band so the state reads without color.
- **Do** set hero names in Barlow Condensed 700 uppercase, and everything else in Barlow at the fixed rem scale.
- **Do** keep every interactive target at least 32px high (34px for icon buttons, 40 to 48px for buttons).
- **Do** keep motion between 150 and 250ms, and honor prefers-reduced-motion.
- **Do** use Ink 3 or lighter for any text that must be read.

### Don't:
- **Don't** use gold for decoration, for a second competing button, or for ordinary hover.
- **Don't** build the tool as stacked selects above a button; keep parameters beside the action they configure.
- **Don't** use real or scraped MLBB hero art; portraits stay placeholder initials badges on the eight muted tone pairs.
- **Don't** use Barlow Condensed for running text, controls or data, and don't use fluid type.
- **Don't** add shadows to surfaces; depth is edge and fill.
- **Don't** signal ally, enemy or banned by color alone; keep the whole-panel split and the hazard band.
- **Don't** use Ink 4 for readable text.
