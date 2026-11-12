---
name: Luminous Kinetic
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#464554'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#767586'
  outline-variant: '#c7c4d7'
  surface-tint: '#494bd6'
  primary: '#4648d4'
  on-primary: '#ffffff'
  primary-container: '#6063ee'
  on-primary-container: '#fffbff'
  inverse-primary: '#c0c1ff'
  secondary: '#b90538'
  on-secondary: '#ffffff'
  secondary-container: '#dc2c4f'
  on-secondary-container: '#fffbff'
  tertiary: '#006c49'
  on-tertiary: '#ffffff'
  tertiary-container: '#00885d'
  on-tertiary-container: '#000703'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e1e0ff'
  primary-fixed-dim: '#c0c1ff'
  on-primary-fixed: '#07006c'
  on-primary-fixed-variant: '#2f2ebe'
  secondary-fixed: '#ffdadb'
  secondary-fixed-dim: '#ffb2b7'
  on-secondary-fixed: '#40000d'
  on-secondary-fixed-variant: '#92002a'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  headline-xl:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-xl-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 38px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-lg:
    fontFamily: Space Grotesk
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 18px
    letterSpacing: 0.02em
  label-md:
    fontFamily: Space Grotesk
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.03em
  label-sm:
    fontFamily: Space Grotesk
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-md: 1.25rem
  gutter-lg: 1.5rem
  margin: 1rem
  margin-md: 1.5rem
  margin-lg: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system reimagines smart surveillance and computer vision away from ominous surveillance tropes into a warm, human-centric visual assistant. Targeted at modern tech-forward homeowners, collaborative operations teams, and smart facilities managers, the interface feels like an intelligent, friendly companion rather than a cold panopticon. 

The aesthetic blends **Playful Modernism** with the precision of contemporary creator tools. It prioritizes:
- **Optimistic Clarity:** Clean, airy, warm-white surfaces paired with crisp structural keylines.
- **Micro-Delight:** Vivid contextual accents (electric indigo, bright watermelon, sunny amber, and mint) that transform status monitoring, spatial camera grids, and AI detection tags into visually engaging visual events.
- **Tactile Softness:** Generous radii, subtle elevation shifts, and springy interactive micro-states that convey approachability without sacrificing data density or analytical authority.

## Colors

The palette trades heavy dark mode canvases for layered, high-key surfaces accented with vibrant chromatic cues.

- **Canvas & Containers:** Base canvas rests at `#f8fafc` with subtle structural grouping panels at `#f1f5f9`. Foreground cards, camera viewport containers, and active drawers sit on pure crisp `#ffffff` to establish positive contrast.
- **Primary (`#6366f1` - Electric Indigo):** Anchors core interactions, primary CTAs, active timeline scrubbers, AI search suggestions, and focal selection boundaries.
- **Secondary (`#f43f5e` - Watermelon Pink):** Flags critical motion alerts, optical tripwire triggers, live stream recording indicators, and high-priority anomalies.
- **Tertiary (`#10b981` - Minty Green):** Signals operational health, verified face matches, clear zones, active streams, and safe status indicators.
- **Accent Sunny Amber (`#f59e0b`):** Highlights pending detections, ambient motion buffers, low-confidence tags, and notification badges.
- **Neutrals & Borders:** Subdued typography sits on `#0f172a` (slate-900) for headlines and `#475569` (slate-600) for metadata. Border systems leverage `#e2e8f0` to keep element separation crisp, airy, and soft.

## Typography

The type system blends friendly, geometric clarity with analytical precision:
- **Headings & Body (Plus Jakarta Sans):** Selected for its humanist geometry, gentle counters, and optimistic tone. It renders camera names, dashboard titles, natural language query bars, and event narratives with an approachable, clean voice.
- **Labels, Telemetry & Timecodes (Space Grotesk):** Provides structured geometric rigor for bounding box tags, AI recognition metrics, timestamps, coordinates, and stream bitrates without feeling sterile.
- **Scale Behavior:** Mobile adaptations tighten display sizes by 4-10px while retaining line-height proportionality to safeguard telemetry readout density in portrait viewports.

## Layout & Spacing

The layout operates on an adaptive 8-point base grid within a responsive fluid multi-column matrix:
- **Desktop (1024px+):** 12-column layout with 24px (`margin-lg`) canvas margins and 24px (`gutter-lg`) gutters. Video stream feeds can be dynamically toggled across 1-, 2-, 3-, or 4-column modules. Search intelligence panels and event rails dock along a persistent 360px side pane.
- **Tablet (768px - 1023px):** 8-column layout with 20px gutters and margins; camera feeds auto-reflow into an adaptive 2-column card stack.
- **Mobile (<768px):** 4-column layout with 16px gutters and margins. Side panels collapse into layered bottom sheets with gesture-driven swipe handles.
- **Component Flow:** Padding stays modular using `space-xs` (4px) for inline metadata pills, `space-sm` (8px) for input gaps and thumbnail lists, up to `space-xl` (24px) for card body interiors.

## Elevation & Depth

Visual hierarchy uses crisp boundary keylines, layered tonal levels, and soft ambient shadows:
- **Surface Tiers:** 
  - Base background: `#f8fafc`
  - Grouping trays & rails: `#f1f5f9`
  - Cards, modal surfaces, and stream tiles: `#ffffff` with a crisp `1px solid #e2e8f0` outline.
- **Ambient Lighting & Soft Shadows:** Shadows are warm, widely diffused, and non-directional:
  - *Resting Card:* `0 2px 8px -2px rgba(15, 23, 42, 0.04), 0 1px 3px 0 rgba(15, 23, 42, 0.02)`
  - *Active / Hover:* `0 12px 24px -6px rgba(99, 102, 241, 0.08), 0 4px 8px -2px rgba(15, 23, 42, 0.03)` with a border tint transition to `#c7d2fe`.
  - *Floating Search Bar & Popovers:* `0 20px 32px -8px rgba(15, 23, 42, 0.08), 0 8px 16px -4px rgba(99, 102, 241, 0.06)`
- **Over-Video HUD Depth:** Video stream annotations and detection markers use translucent frosted glass (`rgba(255, 255, 255, 0.85)` with `backdrop-filter: blur(8px)`) with crisp `rgba(255, 255, 255, 0.6)` inner rims, preventing live feeds from feeling cluttered.

## Shapes

The design adopts a distinct, friendly **Rounded** shape language (`roundedness: 2`):
- **Base Components:** Standard inputs, buttons, and alert strips feature `8px` (`0.5rem`) corner radii.
- **Containers & Feeds:** Stream viewports, event cards, and filter cards utilize `16px` (`rounded-lg` / `1rem`) corner radii to maintain a soft, friendly hardware-inspired enclosure.
- **Modals & Command Center:** Large floating prompt sheets and global AI search dialogs use `24px` (`rounded-xl` / `1.5rem`).
- **Telemetry Pills & Status Badges:** Fully circular (`rounded-full` / `9999px`) badges provide high-contrast visual rhythm alongside rectangular camera viewports.

## Components

- **Buttons:**
  - *Primary:* Solid Electric Indigo (`#6366f1`) with pure white text, subtle shadow, and 8px radius. Active state scales down to `0.98` with a spring transition.
  - *Secondary / Ghost:* Pure white card background, `#e2e8f0` border, `#0f172a` text, shifting on hover to `#f1f5f9` with an indigo border highlight.
  - *Destructive / Live Tag:* Watermelon red (`#f43f5e`) base with high-visibility white text.
- **Search & Query Input Bar:**
  - Designed as the central conversational engine. Centered, elevated pure white container with a 16px corner radius, featuring a leading spark icon, quick-token pills (e.g., `[Person]`, `[Backyard]`, `[09:00 AM]`), and a shortcut prompt (`⌘K`).
- **Detection Chips & Badges:**
  - Capsule-shaped with Space Grotesk typography.
  - *Motion:* Background `#fef3c7`, text `#b45309`, dot `#f59e0b`.
  - *Verified Safe:* Background `#d1fae5`, text `#065f46`, dot `#10b981`.
  - *Critical Event:* Background `#ffe4e6`, text `#9f1239`, pulse dot `#f43f5e`.
- **Camera Stream Cards:**
  - Pure white base with `rounded-lg` (16px) bounding frames. The video sits inside with a seamless 12px inner corner offset. Top overlay contains live signal status and optical FPS readouts; bottom bar reveals swift PTZ (pan-tilt-zoom) controls and snapshot shortcuts on hover.
- **Timeline Scrubber:**
  - Low-profile horizontal track in `#e2e8f0` with colored segment ribbons indicating detected events (watermelon for motion, amber for pet recognition, mint for package delivery). Playhead is an electric indigo pill with a glowing anchor ring.
- **Checkboxes & Toggles:**
  - Toggles are pill-shaped with smooth sliding thumb animations; checked state defaults to electric indigo.
  - Checkboxes use 6px rounded squares with custom white checkmarks against solid indigo or emerald when selected.