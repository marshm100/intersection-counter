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

## Out of scope

Report branding/logos; multi-intersection combined reports; any accuracy
work (that's §3-D). The XML sidecar Miovision ships is not a deliverable
our clients consume — skip unless the audit says otherwise.
