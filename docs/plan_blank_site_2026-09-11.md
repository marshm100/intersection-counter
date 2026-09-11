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

(to be recorded)
