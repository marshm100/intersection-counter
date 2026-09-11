# THE BLANK SITE — FM 51 (2026-09-11) — G-BLANK-1 declared

Operator: "Sure lets do it, is that one properly pre calibrated?"

## The site as found (project 0acb12c0, camera 2, FM51 at CORD 4699, Wise County)

  video     405051_0029_20260430 FM51-CORD4699.mp4, 10 fps, 864,038 frames
  reference Miovision XML (v2_score_dev --project 0acb12c0), windows
            ftv2n_am 07-09 and ftv2n_pm 16-18; leg -> approach map
            {W: NB, E: SB, S: WB, SE: none}
  legs      4 (W, E, S, SE) with mouth points + headings from a May
            calibration; NO gate lines drawn
  paths     3 gt-free anchors (W<->E throughs, S->E right) + 6 hand-
            drawn channels
  tracker   no per-camera calibration (defaults)
  dumps     ftv2n_am / ftv2n_pm only — the July fine-tune (yolo26s_ft2
            OpenVINO @640), the basis G-DEF-6 just showed collapsing
            under the default on the corridor
  best-ever 87.5 movement-bar on an older basis (MASTER_ACCURACY_ROADMAP)

The defaults shipped this week were tuned on the corridor's five
cameras. This site has never seen them. It is the first honest test
of the prime directive: a blank, untested intersection.

## G-BLANK-1 (declared before any scoring; three numbers, no window chosen)

  B0  the default over the EXISTING fine-tune dumps, derived gates —
      reference only (that basis is known-bad under these rules).
  B1  AS FOUND: pass-1 at the production mode (yolo26l@1280, default
      tracker) on both windows, then pass-2 under the default with the
      derived gates. What a new site gets before its operator draws.
  B2  WITH HIS LINES: he draws the four gate lines and aims the arrows
      along the through direction in the calibration editor (the
      G-DEF-3 operating rule), pass-2 again on the B1 dumps.
Reported: movement and approach bars per window, cell tables, the
corridor's fleet bar (77.08) alongside for scale, and the site's
best-ever (87.5). No pass/fail letter: this is a measurement of
generalisation, and the operator's reading of B1 -> B2 is the result.
Nothing on FM51 is shipped by it.

## Results

B0 (the default over the July fine-tune dumps, derived gates, no lines):
  ftv2n_am 07-09   movement 87.5   approach 66.7   coverage 0.089 OFF   events 1,595 (827 dropped)
  ftv2n_pm 16-18   movement 67.8   approach 33.3   coverage 0.120 OFF   events 2,035 (959 dropped)
The morning equals the site's best-ever (87.5). With no drawn lines
the derived gates witness under 12% of tracks, so the evidence
channel — the whole of what this week's rules act through — is OFF
on both windows: B0 is the non-evidence path alone. Scratch
_replay_scratch/blank_20260911, stems b0_*.

FINDING while setting up B1: the detector is a PER-PROJECT processing
mode. FM51 is set to "balanced" = yolo26s_ft2 @ 640, the product's own
recommended mode for full-day footage ("FM51-validated", 07-21); the
corridor project is set to "counted_path" = yolo26l @ 1280 (the G-CP-1
recipe every counting default was tuned on); a brand-new project gets
DEFAULT_PROCESSING_MODE = "accurate" = yolo26l @ 1280 at conf 0.08.
So B0 is not merely a reference: it is what THIS site produces under
the mode its operator chose. B1 runs the new-project default
("accurate") on the as-found snapshot project fm51asfd, so the live
project stays free for his lines. The first re-detect attempt ran
under "balanced" and was discarded (misnamed dump removed).
