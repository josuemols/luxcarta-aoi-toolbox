# Product

## Register

product

## Users

LuxCarta salespeople — non-technical, time-pressured, often mid-email with a
customer or prospect. French- and English-speaking. They know cities, deals,
and coverage areas; they do not know GIS (CRS, reprojection, dissolve mean
nothing to them). They arrive with a messy file or just a city name, and they
need a clean AOI KMZ to feed the quote tool — without asking the GIS team and
without wondering whether the output is right.

## Product Purpose

The AOI Toolbox is the preparation bench for the LuxCarta Quote Generator.
Five utilities (convert Shapefile/MapInfo → KMZ, fix the city name inside a
KMZ, buffer an AOI by X km, corridor around a line, city name → urban-area
polygon) that all end the same way: a valid KMZ whose name and km² flow
correctly into the quote table. Success = a salesperson gets from "customer
sent me this file" to "quote-ready KMZ downloaded" in under two minutes,
alone, and trusts the number they saw.

## Brand Personality

Effortless and reassuring. "I can't get this wrong." Calm, guided, plain
language; the tool disappears into the task. It shares LuxCarta's corporate
identity with the quote app — the two must feel like one product.

## Anti-references

- **GIS software** (QGIS, ArcGIS): no jargon, no dense toolbars, no
  expert-only affordances, no coordinate-system talk unless the file forces it
  — and then in plain words with a safe default.
- **Generic SaaS dashboard**: no metric-card grids, gradient buttons, or
  landing-page styling. This is a working tool, not a pitch.
- **Raw internal script**: no unstyled Streamlit defaults, no stack traces or
  engineer-facing error text reaching the user, no debug dumps.

## Design Principles

1. **One path per tool.** Input → one or two options → preview → download.
   Never a branching workflow; if a tool needs a decision, it offers a safe
   default and says why.
2. **Prove it before they download it.** Every tool shows the map preview and
   the km² readout before the download button matters. Trust comes from
   seeing the shape in the right place with a number that matches the quote
   tool.
3. **Plain words or nothing.** "Distance in km", not "buffer radius".
   "Which coordinate system was this made in?", not "CRS undefined". Copy
   must read cleanly for non-native English speakers.
4. **Same product as the quote app.** Shared palette, type, header, and
   vocabulary. A salesperson moving between the two apps should feel zero
   seam.
5. **Never a dead end.** Every failure states what happened in plain language
   and what to do next (retry, add the country, upload the missing sidecar).
   A blank screen or raw exception is a bug by definition.

## Accessibility & Inclusion

WCAG AA baseline: ≥4.5:1 body-text contrast, visible focus states,
reduced-motion respected. Copy simple and idiom-free for the FR/EN team.
Known watch-item: the brand gray `#72808A` on white is ~4.1:1 — fine for
large/secondary text, not for body copy; and white-on-orange primary buttons
sit below AA, mitigated by weight/size but worth revisiting.
