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

HIS LINES (saved 2026-09-11, live project 0acb12c0, camera 405051):
  W   gate (354,190)-(317,196)   38 px   heading 144.5 (unchanged)
  E   gate (399,426)-(625,276)  271 px   heading 299.1 (unchanged)
  S   gate (295,199)-(235,209)   61 px   heading 120.5 (unchanged)
  SE  gate ( 35,324)-(297,422)  279 px   heading  40.8 (unchanged)
The far legs W and S are short lines at the far mouths (38 / 61 px).
Interim B2 on the fine-tune basis (b2ft): the same dumps as B0, with
his lines — the effect of the lines alone under the site's mode.

b2ft (his lines, fine-tune basis): am 87.5 / 66.7, cov 0.111 OFF;
pm 67.8 / 33.3, cov 0.13 OFF — IDENTICAL to B0. The lines change
nothing because the channel never activates.

CENSUS (ftv2n_am, 2,024 tracks, median box 17 px, both corners vs
the drawn lines +25%): machine tags no_crossing 1,156 / entry_only
404 / exit_only 330 / full 134. 1,463 tracks (72%) are BORN inside
all four lines and 1,553 (77%) DIE inside them. Raw corner crossings:
W in 476, E in 396, S in 97, E out 753, SE out 12, W out 77.
THE BLANK-SITE LESSON: the operator draws the lines at the physical
mouths (W 38 px and S 61 px in the far field, E/SE 271/279 px near
the camera), and on this basis detection begins after the far lines
and ends before the near ones. The evidence the counting default
acts through — a track witnessed at a line — does not exist for most
tracks here. The corridor never showed this because its lines were
drawn where its tracks already ran. Two candidate responses, for his
ruling after B1: (a) an operating rule — draw the lines where vehicles
are reliably TRACKED, inside the physical mouth; or (b) the software
treats a track born inside every line as having entered over the line
nearest its birth, in the direction of travel (the born-across idea
extended from one corner to the whole box). B1 (large detector) may
move the detection boundary outward first.

B1 / B2, morning, large detector (l1_study_0700: 52,227 rows vs the
fine-tune's 67,884 — the large model finds FEWER far-field boxes on
this site):
  B1 as found (snapshot, derived gates)   movement 79.6   approach 58.3   cov 0.119 OFF   events 1,450 (673 dropped)
  B2 with his lines (live project)        movement 79.6   approach 58.3   cov 0.122 OFF   identical
Against B0 / b2ft on the fine-tune: 87.5 / 87.5. On FM 51 the site's
chosen mode ("balanced") beats the new-project default ("accurate")
by 7.9 on the morning, and the lines are inert on both bases for the
same reason (tracks born inside the lines). Afternoon pending.

CORRIDOR CENSUS of the same class (tracks born inside every drawn
line, bottom centre, per window): cam1 35% / 26%, cam2 8% / 6% / 14%,
cam3 14%, cam4 35% / 20% / 38%, cam5 32% / 19% / 23% — against FM51's
72%. A rule for born-inside tracks is a FLEET candidate with real
stake on cam1/cam4/cam5, not an FM51 special case; FM51 is the
extreme of a common condition (detection begins inside the lines).

B1 / B2, afternoon, large detector (l1_study_1600, 58,462 rows):
  B1 as found       movement 72.7   approach 45.8   cov 0.147 OFF   events 1,767 (942 dropped)
  B2 with his lines movement 72.7   approach 45.8   cov 0.146 OFF   identical

## G-BLANK-1 RESULT (recorded 2026-09-11)

                          morning 07-09        afternoon 16-18
  fine-tune (site mode)   87.5 / 66.7          67.8 / 33.3      B0 and b2ft, identical
  large (new-project)     79.6 / 58.3          72.7 / 45.8      B1 and B2, identical
  corridor default, for scale: fleet 77.08 (12 windows); site best-ever 87.5.

1. HIS LINES CHANGE NOTHING ON THIS SITE, on either basis: the
   evidence channel never activates (coverage 0.11-0.15 against the
   0.45 bar) because 72% of tracks are born inside every line and 77%
   die inside them. Every counting default shipped this week acts
   THROUGH that channel, so on a site drawn at its physical mouths the
   week's work is inert. The corridor could not show this: its lines
   were drawn where its tracks already ran (born-inside 6-38% there).
2. THE TWO BASES SPLIT BY WINDOW: the site's chosen fine-tune wins the
   morning by 7.9; the new-project large detector wins the afternoon
   by 4.9. Neither is a default the other window agrees with — the
   same non-separability G-DEF-5/6 found on the corridor.
3. The site scores 68-88 on the posterior path alone, which is the
   pre-2026-09 machinery.

WHAT GENERALISES: the counting defaults do not reach a blank site
unless its lines sit where its tracks are. Two responses, his call:
  (a) OPERATING RULE — draw each line where vehicles are reliably
      tracked (inside the physical mouth), judged on moving video;
      cheap; puts a judgment on the operator the corridor never asked.
  (b) SOFTWARE RULE — a track born inside every line has ENTERED over
      the line nearest its birth, in its direction of travel (the
      born-across ruling extended from a corner to the whole box); and
      symmetrically a track dying inside every line has EXITED over
      the line nearest its death. A fleet candidate: 6-38% of corridor
      tracks and 72% of FM51's; measured on the corridor's 12 windows
      against 77.08 AND on FM51's two windows against this table.
Nothing on FM51 is shipped. The as-found snapshot project fm51asfd
(display name "FM51 AS-FOUND SNAPSHOT (agent) - do not edit") is
scratch and can be deleted after this.

## OPERATOR RULING (2026-09-11): "software"

## G-DEF-7 (declared before any scoring): BORN INSIDE EVERY LINE

Built: BORN_INSIDE_NEAREST_LINE (default OFF) inside classify_pair.
A track with no valid inward crossing whose first bottom-centre point
is inside every gate ENTERED over the nearest gate whose inward
direction agrees with its first 1 s of travel; a track with an origin
and no legitimate exit whose last point is inside every gate EXITED
over the nearest gate its last 1 s of travel points at (same leg only
past the u-turn tests). Six tests.

Arms: d11 = the default + the rule on the corridor's 12 windows
(letter against 77.08); b3 = the rule on FM51 with his lines, both
bases (fine-tune ftv2n_am/pm and large l1_study_0700/1600), against
the G-BLANK-1 table. PASS = the corridor letter holds AND FM51 does
not fall on either basis; the evidence channel's coverage on FM51 is
reported (the rule's purpose is to make his lines count there).

b3 (the born-inside rule, FM51 with his lines):
  fine-tune  am  87.5 / 66.7   cov 0.111 -> 0.355  OFF   (identical score)
  fine-tune  pm  67.8 / 33.3   cov 0.130 -> 0.423  OFF   (identical)
  large      am  79.6 / 58.3   cov 0.122 -> 0.428  OFF   (identical)
  large      pm  72.7 -> 74.5 / 45.8   cov 0.146 -> 0.453  ON   (+1.8)
The rule does what it was built for — the lines now witness 36-45%
of tracks instead of 11-15% — but three of four windows land just
UNDER the 0.45 activation bar, a corridor-tuned constant, so the
channel stays off and the counts do not move; the one window that
clears it gains 1.8. The bar itself is the next question on a blank
site (it was set on the corridor's coverage distribution, 0.45 = the
census-definition gap midpoint).
