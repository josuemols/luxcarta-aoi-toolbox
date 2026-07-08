# Design

Visual system of the AOI Toolbox, captured from the live code
(`engine/branding.py`, `.streamlit/config.toml`, `streamlit_app.py`).
Inherited from **luxcarta-quote-app** — changes here should be mirrored there
or deliberately diverge.

## Theme

Light only. Used at a desk, in an office, usually next to email or the quote
app in another tab. White content surface, cool light-gray sidebar, one warm
accent. Color strategy: **restrained** — tinted neutrals plus the orange
accent on actions and the header rule; blue reserved for headings and key
values.

## Colors

| Token | Value | Role |
|---|---|---|
| `--lux-blue` | `#206294` | Headings, metric values, links — identity color |
| `--lux-orange` | `#FF8300` | Primary buttons, header underline, map AOI stroke/fill, focus of attention |
| `--lux-green` | `#71BF49` | Success / positive only. Rare. |
| `--lux-gray` | `#72808A` | Secondary text, captions, metric labels. ~4.1:1 on white — large/secondary text only, never body copy |
| `--lux-ink` | `#333333` | Body text |
| `--lux-bg` | `#F4F7F9` | Sidebar, secondary panels |
| white | `#FFFFFF` | Content surface |
| hover orange | `#e57600` | Primary button hover |

Streamlit theme (`config.toml`): `primaryColor #FF8300`, background white,
secondary `#F4F7F9`, text `#333333`. Semantic states come from Streamlit's
built-ins (`st.success`/`st.warning`/`st.error`/`st.info`) — do not restyle
them per-tool.

## Typography

- **One family**: Jost (Google Fonts), weights 400/500/600/700; fallback
  `'Century Gothic', sans-serif`. No second family, ever.
- Headings: Jost 600, `--lux-blue`.
- Header block: title 1.5rem/600 blue; subtitle .88rem gray.
- Body: Streamlit default sizing (≈16px), `--lux-ink`.
- Captions/help text: `st.caption` (gray) — one line per tool, plain language.

## Layout

- App shell: Streamlit wide layout; sidebar = tool switcher (radio with
  one-line captions), content = one tool at a time.
- Brand header on every page: 44px logo + title block, 3px `--lux-orange`
  bottom border, 14px margin below.
- Tool anatomy (fixed order, every tool): subheader → one-line caption →
  input(s) → options → folium map preview (420px) → km² metric → download row
  (KMZ primary, KML secondary, optional cloud-link button).
- Download rows use `st.columns([1, 1, 2])`.

## Components

- **Primary button**: orange bg, white text 600, radius 8px, padding
  `.55rem 1.4rem`, hover `#e57600`. One primary per tool (the KMZ download).
- **Metric**: `st.metric` — value blue 600, label gray. km² always formatted
  `{:,.1f} km²`.
- **Map preview**: folium + OpenStreetMap tiles, AOI drawn `#FF8300` stroke
  2px / fill opacity 0.25, auto-fit bounds with 20px padding.
- **File inputs**: `st.file_uploader` with explicit `type=` lists; plain-word
  labels ("Files to convert", "KMZ or KML file").
- **Errors**: `st.error` with a plain sentence + next step. Stack traces only
  inside an expander labeled "Technical details (for support)".
- **Login gate**: single password form, same as quote app.

## Motion

None beyond Streamlit defaults (spinners during network work). This is
correct for the register — do not add entrance animations or decorative
motion. Long operations (Tool 5 lookups) get `st.spinner` with a sentence
that sets time expectations.

## Anti-patterns (this project)

- No metric-card grids or dashboard styling — one metric at the moment of
  truth, not a stats row.
- No GIS vocabulary in labels, captions, or errors.
- No per-tool color themes; every tool uses the same restrained palette.
- No new fonts, no gradients, no glass effects.
