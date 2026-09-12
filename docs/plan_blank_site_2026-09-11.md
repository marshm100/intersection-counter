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

d11 (corridor, born-inside rule, nearest-line-with-direction-sign):
MISS — fleet 77.08 -> 67.42; cam1 -20/-23, cam4 1600 -17, cam5 -6 to
-17; cam2 1100 +1.2 the only gain. Coverage 0.53-0.76 everywhere (the
rule witnesses most tracks) but the witnessed ENTRIES/EXITS are wrong:
cam5 0700 NB_right 5 -> 904 (Mio 21), NB_thru 2376 -> 1521 (Mio 2379);
cam1 1600 WB_right 0 -> 208 (Mio 2), NB_thru 2119 -> 1897 (Mio 2078).
CAUSE: my shortcut picked the NEAREST gate whose inward normal merely
agreed in sign with the travel direction; near a corner that is the
side street, so throughs dying inside were handed a right-turn exit.
His rule says "the line it points at" — the gate the travel RAY hits.
d12/b4: the same rule with a ray intersection (first extended gate
segment hit by the ray from the birth point backward along the first
second of travel for entries, and from the death point forward along
the last second for exits).

## G-DEF-7 verdict (recorded 2026-09-11): MISS on both halves

d12 (corridor, ray geometry):
  cam1 75.3 / 86.0 (-8.7 / -9.3) | cam2 75.7 / 76.9 / 67.6 (+0.5 / +1.2 / -3.7)
  cam3 83.8 (-3.8) | cam4 71.1 / 71.7 / 81.0 (0 / -2.8 / +3.0, its best ever)
  cam5 65.4 / 70.8 / 62.3 (-6.6 / -0.6 / -6.6)
  FLEET 77.08 -> (see log) — three windows fall > 3; cam1 -9; MISS.
b4 (FM51, ray geometry, his lines, both bases): coverage 0.35-0.45,
all four windows UNDER the 0.45 bar -> scores identical to no rule.

WHAT IT MEANS: a track born inside every line does not reliably tell
the software where it came from; the ray back along its first second
of travel picks the wrong line often enough to cost cam1 9 points and
cam5 7, while it finds cam4 evening 3 (81.0) and cam2 midday 1.2. The
witnessed share rises everywhere (0.53-0.76), but witnessed-and-wrong
is worse than unwitnessed, because a witnessed origin outranks the
posterior. On FM51 the rule cannot even show its effect: the bar
holds the channel off at 0.35-0.45.
The flag stays built and OFF. The blank-site gap stands as measured:
on a site whose lines sit at the physical mouths, the counting
defaults are inert, and neither reading of "the line it came from"
(nearest with direction; the ray) is a safe substitute for a witnessed
crossing. What remains for a blank site is the OPERATING rule (draw
the lines where vehicles are tracked), or an activation bar derived
per site rather than fixed at the corridor's 0.45 — both his call.

## OPERATOR RULING (2026-09-11): "the operating rule"

Instrument: scripts/viz_track_density.py (heat of tracked positions,
births cyan, deaths orange, the drawn lines) — the picture the rule
needs. Page: https://claude.ai/code/artifact/c75661ef-98dd-4518-a57a-25a08658b380

HIS REDRAW (saved): W (392,197)-(318,202) 75 px; S (316,203)-(235,209)
82 px; E (328,293)-(538,239) 217 px — moved UP the road into the
tracked band; SE (123,267)-(312,294) 190 px.

b5 (redrawn lines, no rule flags):
  fine-tune  am 87.5 / 66.7  cov 0.111 -> 0.302 OFF   pm 67.8 / 33.3  cov 0.130 -> 0.303 OFF
  large      am 79.6 / 58.3  cov 0.122 -> 0.240 OFF   pm 72.7 / 45.8  cov 0.146 -> 0.263 OFF
Scores identical again — the channel is still off — but the lines
now WORK: on the large-detector morning, full gate journeys 134 ->
450, born-inside-all 72% -> 52%; on the fine-tune morning full
journeys 783 and born-inside 33%. Raw crossings: W in 748 / 1,543,
E out 1,625 / 1,385, S in 571 / 894. The operating rule does what it
was meant to; the remaining gate between the lines and the counts is
the ACTIVATION BAR (0.45), a corridor constant, with FM51 at
0.24-0.30 under it.

b6 (his redrawn lines, activation bar lowered to 0.20 by env so the
channel activates at FM51's 0.24-0.30):
                      channel off (b5)     channel ON (b6)
  fine-tune  am        87.5 / 66.7          91.9 / 83.3   (+4.4 / +16.6)  NEW SITE BEST
  fine-tune  pm        67.8 / 33.3          79.3 / 50.0   (+11.5 / +16.7)
  large      am        79.6 / 58.3          79.6 / 54.2   (0 / -4.1)
  large      pm        72.7 / 45.8          80.0 / 50.0   (+7.3 / +4.2)
THE WEEK'S DEFAULTS GENERALISE — once the lines sit where the tracks
are AND the channel is allowed to activate. Three of four windows
gain 4-12 movement points and 4-17 approach points; the site's
best-ever moves from 87.5 to 91.9 on the mode it was set to. The one
thing between a blank site and those numbers is the activation bar,
a corridor constant (0.45) that this site cannot reach at 0.24-0.30.

## G-BAR-1 (declared 2026-09-11, before any corridor scoring)

Candidate default: EVIDENCE_ACTIVATION_COVERAGE 0.45 -> 0.20. On the
corridor only two windows sit under 0.45 (cam4 1600 at 0.424, cam5
0700 at 0.387); every other window is ON already and cannot change.
Arm d13 = those two windows at bar 0.20 (the others carry their d7
scores by construction). PASS = the G-DEF-1 letter on the corridor
(fleet rises or holds within noise; neither window falls > 3.0) AND
FM51's b6 table stands. Ship = the constant changes in config; cam4
1600 / cam5 0700 reprocessed; FM51 stays unshipped (test site).

## G-BAR-1 result (recorded 2026-09-11)

d13, bar 0.20, the corridor's two sub-bar windows now activating:
  cam4 1600   78.0 -> 75.4 (-2.6)   approach 62.5 -> 62.5   NB_thru 2391 -> 2588 (Mio 2439), EB_left 38 -> 14 (Mio 29), SB_right 117 -> 133 (Mio 39)
  cam5 0700   72.0 -> 73.3 (+1.3)   approach 46.9 -> 31.2   SB_thru 1746 -> 2046 (Mio 1868), WB_right 82 -> 11 (Mio 23), EB_right 113 -> 91 (Mio 188)
  the other ten windows are already ON and cannot change.
  FLEET 77.08 -> 76.97 (-0.11): flat within noise; no window falls > 3.
FM51 (b6) with the same bar: +4.4 / +11.5 / 0 / +7.3 movement,
+16.6 / +16.7 / -4.1 / +4.2 approach.

Against the letter: the corridor holds within noise (-0.11) and no
window falls > 3.0; FM51's table stands. PASS on the letter. The
honest shape: a corridor-neutral change whose entire benefit is on
the blank site — which is what the prime directive asks for. Cost on
the corridor: cam4 1600 -2.6 (its SB_right phantom class grows again
117 -> 133 with the channel on) and cam5 0700's approach bar halves
while its movement bar rises 1.3. Ship = EVIDENCE_ACTIVATION_COVERAGE
0.45 -> 0.20 in config; reprocess cam4 1600 and cam5 0700; FM51 stays
a test site (its lines are his, its counts are not shipped).

## SHIPPED — the activation bar 0.45 -> 0.20 (operator go 2026-09-11: "yes plan it out")

backend/config.py EVIDENCE_ACTIVATION_COVERAGE default 0.20 (commit
d8d839b); 1216 green. Backup pre_ship_bar020; cam4 1600 and cam5 0700
reprocessed under the default (force_once, apply); production ==
the d13 arm on both. Corridor standings: cam1 84.0 / 95.3 | cam2
75.2 / 75.7 / 71.3 | cam3 87.6 | cam4 71.1 / 74.5 / 75.4 | cam5 73.3 /
71.4 / 68.9; FLEET 76.97. FM51 stays a held-out test site with his
lines saved; its counts are not shipped. CLAUDE.md carries the blank-
site calibration rule.

## WHERE THIS LEAVES THE PRIME DIRECTIVE (2026-09-11)

A blank intersection now gets: the five counting rules, the state
machine, ruled-quality headings by the operator's arrow, and an
evidence channel that activates once its lines sit where its vehicles
are tracked. On the one site the rules never saw, that is 91.9 / 79.3
against a pre-week 87.5 / 67.8. What a blank site does NOT yet get: a
detection basis chosen with the rules (G-DEF-5/6), the theft class,
or sub-20-px vehicles.
