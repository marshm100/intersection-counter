# Weekly Report — Intersection Counter

### Week of June 27 – July 3, 2026



**HEADLINE: The tool now produces Miovision's exact deliverables — the formatted Excel report, a matching PDF, and the Light/Medium/Heavy-truck breakdown — so a client would receive the same package we currently pay the commercial service for.**

### 

### Summary



A heavy build-and-ship week: the project crossed from "a working research pipeline" into "something an operator can run start-to-finish and hand to a client." We shipped the client-facing Excel and PDF output formats, an automated quality-check that flags likely miscounts, a one-key review screen, ran an honest head-to-head audit against Miovision that pinpointed our remaining 8% gap, and closed part of that gap by fixing a \~700-vehicle miscount on our hardest intersection.

### 

### What got done, by day



**Monday — accuracy audit \& roadmap.** Compared a full overnight run against the Miovision deliverable on the *same* video and found we were **8% low**, then broke that gap into four specific, separately-fixable causes (afternoon-sun detection misses, no semi-truck category, a calibration mismatch, and one over-counted side road). Wrote this and the whole path-to-finished into a single roadmap document, and confirmed the Excel export downloads and formats correctly.



**Tuesday — the accuracy safety net \& review screen.** Built the "flag queue": the tool now automatically surfaces both the counts it's unsure about *and* the intervals that look suspiciously under-counted — the key part, because a vehicle we miss entirely would otherwise leave no trace. Paired it with a keyboard-driven review screen (one keystroke per fix, auto-advance, batch-resolve, a looping video clip per item) and a formal **±5%-per-15-minutes** accuracy bar. Also improved counting on our worst intersection by adding a missing turn path it had been misattributing.



**Wednesday — Miovision-parity outputs \& one-click workflow.** Shipped the Light/Medium/Heavy vehicle-class breakdown, a Miovision-style Excel summary with peak-hour figures, and a matching **PDF report**. Moved the count-building steps out of the command line and into the app so an operator runs them by clicking. Also cut a report-preview delay from **50 seconds to under 1 second** and fixed two multi-minute freezes.



**Thursday — sampling, performance \& a fresh accuracy investigation.** Hardened the spot-check sampling so a good morning sample can't mask a bad afternoon, finished the freeze/performance fixes on the review queue, and investigated the afternoon-lighting miss — determining it's a limit of the source video's resolution, not something more tuning will fix (a useful dead-end to rule out). Started diagnosing a stubborn count error on our hardest camera (finished Friday).



**Friday — closing the count-accuracy gap on our hardest intersection.** Went after the biggest remaining accuracy problem: on our worst camera, \~**700 vehicles** were being credited to the wrong direction because a straight-through and a right-turn movement trace nearly the same path on screen, so the AI kept confusing them. Tried one fix (based on where each vehicle enters the frame), tested it, found it made things *worse*, and ruled it out. Then built and validated a second fix that separates the two movements by each vehicle's **on-screen speed** — it improved the counts on two cameras; on a third it hurt them, so we made it a **per-camera setting** switched on only where a test confirms it helps, rather than a blanket change. Wired it into the tool as an operator toggle. Developed Friday, committed to push this week.

### 

### Time spent (≈29 hrs engaged)



|Area|Hours|
|-|-|
|Count-accuracy fixes \& audits|\~8.5|
|Automated quality-check + acceptance gate|\~4|
|Miovision-format Excel \& PDF outputs|\~3.5|
|One-click processing workflow|\~3|
|Review \& correction screen|\~2.5|
|Planning, roadmap \& handoffs|\~2.5|
|Making the accuracy fix deployable (in-app toggle + tests)|\~2|
|Environment / setup troubleshooting|\~1.5|
|Speed \& performance fixes|\~1.5|

### 

### Where the project stands



The core counting, the one-click operator workflow, the review-and-correct screen, the built-in quality checks, and the Miovision-format Excel/PDF outputs are all now in place — the tool is genuinely usable end-to-end. The remaining work is well-defined: add the semi-truck category, keep closing the pinpointed \~8% afternoon-lighting gap, and validate across more real-world sites before it's ready for daily hands-off use.

