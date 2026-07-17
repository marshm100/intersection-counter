# Plan — §3-E Miovision-parity deliverables, completion (2026-07-16)

Item 8 closed (see its plan doc); this is the next build lane. Recon says E
is PARTIALLY BUILT already — the roadmap row understates it:

- `backend/services/excel_export.py`: Miovision-format helpers (bound-name
  approaches, L/T/R/U columns), peak-hour + PHF analysis, L/M/A class
  groups via `fhwa_to_class_group`.
- `backend/services/pdf_report.py` (Phase 3E.3): letterhead + peak-hour
  summary + paginated 15-min TMC pages via matplotlib PdfPages (no new
  dependency).
- `backend/routers/export.py`: `/export/gate` (spot-check QA gate),
  `/export/preview`, `/export/download`, `/export/report.pdf` — gated,
  override-able. All PROJECT-level.
- `backend/services/v3_excel_export.py`: the v3 intersection-day export —
  but a DIFFERENT, simpler format (TMC Summary / Per-Camera / Dedup Audit),
  not Miovision parity.

So the real work is (a) PROVEN parity against the example deliverable and
(b) v3 unification — the operator's flow is intersection-day cards, and the
Miovision-format artifacts must come from there.

The reference artifacts (in hand): `docs/historic data/26097 TIA for Wise
County, TX/Cam 1 FM51-CORD4699/405051_*.xlsx` + the `.pdf` beside it.

## Stages (each shippable; audit first, it redirects the rest)

1. **Parity audit (no code).** Script-diff our generated xlsx against the
   example: sheet inventory, header rows, column sets (incl. class rows:
   Lights/Mediums/Articulated/Total), interval labeling, peak-hour block,
   PHF cells, grand totals; same visual pass for the PDF page-by-page.
   Deliverable: a gap table in this doc — what matches, what differs, what
   Miovision has that we don't (and explicitly what we will NOT copy, e.g.
   branding). Everything below re-scopes from this table.
2. **v3 Miovision-format export.** One shared data loader for the v3
   intersection-day (merged, cross-camera-deduped events — reuse
   `v3_aggregator`) feeding BOTH the Miovision-format workbook builder and
   the PDF renderer (today's builders read the legacy project shape via
   `_load_export_data`; refactor to accept the v3 frame, do not fork the
   format code). Card UI gets Export buttons wired to new
   intersection-day endpoints; the §3-A export gate (bank + classification
   + QA) applies per intersection-day.
3. **Gap closure from the audit** (unknown until stage 1; likely: exact
   header/label strings, class-row ordering, u-turn presentation, the
   PDF's approach diagram block if we choose to match it).
4. **End-to-end verify** (the /verify discipline): generate both artifacts
   for the corridor intersection-day through the UI, diff key cells against
   the DB aggregates, open in Excel (no repair prompts), and pin a
   regression test on sheet structure + a handful of cell values. Hard
   constraints hold throughout: integers only, no formulas; ASCII-safe
   labels; NEVER a runtime GT dependency (the example file is a FORMAT
   reference only).

## STAGE-1 AUDIT RESULT (2026-07-16) — the gap table

Generated ours from the corridor project (`audit_ours.xlsx/pdf`, scratchpad)
and diffed against the example (4 sheets / 13 PDF pages).

**Excel:**

| aspect | example | ours | verdict |
|---|---|---|---|
| sheets | Contents, "(date) Summary", TMV Table, TMV Data | Contents, Summary, TMC Summary, Time Series, TMV Data, Raw Events | rename/merge; TMV Table ("Road Volumes" pivot) MISSING; our extras (Raw Events, Time Series) keep as QA sheets |
| Summary layout | approaches as COLUMN GROUPS w/ leg-specific movement letters (T-junction: SB=L/T/U, WB=L/R/U, NB=T/R/U) + In/Out cols + Total; class ROWS Lights/%/Mediums/%/Articulated/%/Total/PHF/Approach %; TWO peak blocks (AM+PM) | long-format rows (Approach x Mvt), classes as columns, PHF col | REBUILD the Summary sheet layout: transposed, geometry-aware columns, % rows, I/O, two peak blocks |
| sheet headers | Study Name / Start / End / Site Code block on EVERY sheet (+ Contents has Overview, Classification Categories, peak listings) | Study Name + Date only | extend header block |
| TMV Data | long rows Interval/Approach/Movement/Class/Volume @15 min | SAME columns ✓ | structure matches; fix interval granularity + timestamps (below) |
| leg names | road names ("SB FM 51") | present in TMC Summary | carry into Summary column groups |

**PDF:** the example is 13 pages: OPERATOR-FIRM letterhead (Deshazo block —
our client's OWN brand, so a configurable letterhead IS in scope, revising
the plan's "no branding" line), then per-approach grouped columns with road
names + App. Total + Int. Total at PER-MINUTE rows, then 15-min pages. Ours
is 4 pages of long-format tables. REBUILD: letterhead config (name/address/
tagline), grouped-column layout, per-minute + 15-min page sets.

**Data-level findings (the v3-unification case, proven):** project-level
export on the corridor MIXES all five cameras (duplicate "SB N Belt Line
Rd" rows, "Leg 1/2/3" placeholders from unlabeled legs), Time Series is
junk at project scope, and TMV Data shows year-2000 intervals (events
missing timestamp_real fall back to epoch — must derive from
video_start_time or be excluded with a warning). Stage 2's shared v3
loader (aggregated, deduped, one intersection-day) fixes the data layer;
the format work above sits on top of it.

**Re-scoped build order:** 2a v3 loader + data fixes → 2b Summary sheet
rebuild + TMV Table + headers → 2c PDF rebuild (letterhead config,
grouped columns, minute+15-min pages) → 3 endpoint/card wiring + gate →
4 end-to-end verify + structure regression test.

## STAGES 2–4: SHIPPED (2026-07-16)

- **2a** shared v3 frame (`_load_export_data_v3`): deduped intersection-day,
  per-event wall-clock, unstamped counted never epoch-binned, legs merged by
  road, exits + per-minute frames; legacy loader's missing rejected filter
  fixed. **2b** `generate_miovision_xlsx`: Contents / Summary (geometry-aware
  approach column groups, I/O, class+% rows, PHF, Approach %, dual peaks) /
  TMV Table / TMV Data / Raw Events QA — no-formulas test-pinned.
  **2c** PDF rebuilt: REPORT_LETTERHEAD config (empty = omitted), per-minute
  + 15-min Turning Movement Data pages with road-named column groups and
  App./Int. totals, peak summary. **3** per-intersection-day endpoints
  (gate / tmc.xlsx / report.pdf; blocking from the project gate's own
  entries; 409 + explicit draft override) + card Excel/PDF buttons.
- **4 VERIFY (live drive, corridor project):** cards render the buttons,
  the gate dialog fires, override downloads BOTH artifacts through the real
  endpoints; the downloaded workbook's TMV grand total (13,856) exactly
  matches the deduped DB frame. Screenshot:
  `screenshots/e3_intersection_export_buttons_2026-07-16.png`. Fix from the
  drive: a QA-fail block now names its reason (the dialog showed an empty
  list). 16 structure/endpoint tests pin the formats.

Residual polish (not blocking): Summary %-rows render as fractions (example
formats as percents); TMV Table pivot approximates the example's unreadable
cached layout; per-minute PDF pages could group hours like the example's
page breaks. Revisit only if the operator asks.

## Out of scope

Report branding/logos; multi-intersection combined reports; any accuracy
work (that's §3-D). The XML sidecar Miovision ships is not a deliverable
our clients consume — skip unless the audit says otherwise.
