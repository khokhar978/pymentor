# PyMentor — Feature Discussion & Roadmap

Covers the items that involve a real design decision or more than one reasonable way to build them. Each section: current state → options → recommendation. Nothing here is implemented yet — pick a direction and I'll build it.

---

## 1. Resizable Editor / Terminal Panels

**Current state:** `practice-layout` is a flexbox row; panel widths are fixed via CSS custom properties (`--problem-panel-width` etc.), not user-adjustable. No drag handles exist anywhere.

**Feasibility: straightforward — easier than usual, in fact.** Normally Monaco needs an explicit `editor.layout()` call after its container is resized, or the text area clips until something else forces a relayout. You've already got `automaticLayout: true` set in `initMonaco()`, which makes Monaco watch its own container size and relayout on its own — so a drag-resize just needs to change the container's width/height (CSS), and Monaco keeps up by itself. One minor note: `automaticLayout` checks on a short interval rather than instantly, so calling `state.editor.layout()` once on `mouseup` (end of drag) still makes the final resize feel snappier than waiting for the next poll — worth doing, not strictly required.

**Options:**
| Approach | Effort | Notes |
|---|---|---|
| **A. Custom drag-handle** (thin `<div>` between panels, `mousedown`→track `mousemove`→update a CSS var, `mouseup` to stop, persist final width to `localStorage`) | Low-Medium | No new dependency. ~60-80 lines of vanilla JS + a bit of CSS for the handle's hover/active state. Full control over feel and mobile behavior. |
| **B. CSS `resize: horizontal` on the panel** | Trivial | Only works per-element with `overflow: auto`, gives an ugly native browser resize-corner, can't resize two panels symmetrically from one handle, no persistence without extra JS anyway. Not worth it here. |
| **C. A library** (Split.js, or similar) | Low | Handles the drag math and min/max sizing for you; adds one small dependency (~4KB) and a CDN `<script>` tag, consistent with how you already pull in `marked`/`confetti`/Monaco from CDN. |

**Recommendation:** **A**, unless you'd rather not hand-roll the drag math — in which case **C** (Split.js) gets you there faster for one extra CDN script. Either way: call `state.editor.layout()` on every drag tick (or at minimum on `mouseup`), and persist the chosen widths to `localStorage` so it's remembered per student per device. Do the same for a horizontal split between the editor and the output/terminal panel if you want that resizable too — same pattern, just a vertical handle instead of a horizontal one.

---

## 2. Screen Adaptability / Responsive Design

**Current state:** `style.css` has **zero `@media` queries**. The whole app — practice page, problems list, profile, admin — is built for one fixed desktop layout.

**The real constraint isn't CSS, it's Monaco + Pyodide.** A full VS Code-style editor and a WASM Python runtime are both genuinely heavy and cramped below ~768px width; most serious "student practice IDE" products (Replit, LeetCode) either degrade gracefully to a stacked single-column view on mobile or explicitly tell mobile users to switch to desktop for the coding view. Trying to make the *editor itself* comfortable on a phone is a much bigger effort-to-value trade than making everything *else* mobile-friendly.

**Recommendation, in priority order:**
1. **Problems list, login, profile, admin dashboard → make these properly responsive first.** These are just cards/tables/forms; standard flexbox-to-column breakpoints at ~768px close most of the gap for a student checking their progress from a phone.
2. **Practice/editor page → stack panels vertically below ~900px** (problem description on top, collapsed by default or in an accordion; editor below; output below that) rather than trying to shrink three side-by-side panels into a phone screen. This is "adaptable," not "optimized" — a student can use it in a pinch, but you're not chasing feature-parity with desktop.
3. Skip trying to make Monaco's own minimap/gutter/etc. touch-friendly — not worth the effort for a lab tool primarily used on lab PCs.

This is a CSS-heavy, low-architectural-risk task — mostly `@media` breakpoints plus a JS toggle to switch the practice-layout `flex-direction` from `row` to `column`. Say the word and I'll do a pass on `style.css` for this.

---

## 3. Practice Timer: Auto-Start vs. Manual Start

**Current behavior (confirmed in code):** the timer starts the instant a problem loads — `startActiveTimer()` fires immediately when `/api/session/start` resolves, before the student has read the problem or written a single character.

### Option A — Keep auto-start (current)
**Pros:** Simplest, zero UI change. Captures true "time from opening the problem," which is arguably the more honest metric of total engagement (reading + thinking + coding all count). Nothing for the student to forget to click.
**Cons:** Penalizes slow readers / students who open a problem, get distracted, and come back later — inflated "time spent" that doesn't reflect actual work. Can feel like being watched from the moment you look at a problem, which is exactly the discomfort your student flagged.

### Option B — Manual start (student clicks "Start")
**Pros:** Timer reflects actual working time, not reading/idle time. Gives the student a sense of control — psychologically, an opt-in timer feels like a tool, an always-on one feels like surveillance. Matches how most competitive-programming judges behave (Codeforces/LeetCode: clock starts on your action, not on page load).
**Cons:** A student can "game" the number by reading the whole problem, planning the solution mentally, then hitting Start only once they're ready to type — so "time to solve" stops being comparable to Option A's number, and stops being a reliable proxy for how hard a problem actually was. Also one more UI element to design/place well, and one more thing a student can simply never click (do you then fall back to something? probably to "no time recorded" — need to decide).

### Option C — Auto-start, but only on first *keystroke or Run*, not on page load
This is the middle ground and — the one worth taking, given the tracking already exists: the `lastUserActivityTime`/`markActive()` idle-detection you already built for the heartbeat system is 90% of what this needs. Right now activity-tracking only *pauses* an already-running timer; flipping it to *start* the timer on first real interaction (keydown in the editor, or first Run/Submit) is a small change, not a new subsystem.
**Pros:** No extra button, no extra step for the student — it just quietly starts counting the moment they actually begin, which is what both Option A and B are each half-solving. Removes the "being watched while reading" feeling without needing an opt-in click.
**Cons:** Still doesn't solve the "student reads and plans in their head for 10 minutes before typing anything" case — but arguably that's *fine* to not count, more so than either A or B.

**Recommendation: Option C.** It directly answers the objection your student raised (timer shouldn't start the second the page loads) without introducing a manual step that most students would find mildly annoying or just forget. It also reuses code you've already written for a different purpose (idle detection), so it's cheap.

### Other timing-model ideas worth considering (independent of the above)
- **Pause-on-tab-switch is already partially there** (heartbeat requires `!document.hidden`) — worth making sure the *visible countdown* freezes in the UI too when hidden, not just the server-side credit, so what the student sees always matches what gets saved.
- **Per-attempt time** vs. **cumulative time** — right now time accumulates across all attempts on a problem forever (even across days). If you ever want a "how long did THIS attempt take" stat, that's a different, currently-uncaptured metric — worth deciding if you want both.
- **A soft, optional "focus timer"** (Pomodoro-style, purely client-side, no bearing on grading) is a very different feature from the current tracking-for-analytics timer — don't conflate them if a student asks for "a timer" meaning this instead.

---

## 4. Leaderboard

**What you already have that's usable for this:** `submissions.is_correct`, `sessions.status`, `sessions.time_spent_seconds`, all per-student. No new schema needed for a basic version.

**Ranking metric options:**
| Metric | Pros | Cons |
|---|---|---|
| **Problems solved (count)** | Simple, intuitive, hard to game meaningfully | Doesn't reward speed or efficiency; ties are common |
| **Solved + tiebreak on total time** | Rewards efficiency too | "Total time" penalizes students who take breaks between sessions — not a fair speed proxy given time tracking spans days |
| **Points per problem, weighted by difficulty** | Rewards tackling harder problems, not just volume | Needs you to assign point values per difficulty — a small design/config task, not just a query |
| **Streak (consecutive days practiced)** | Encourages consistency over raw skill | A different axis entirely — works well as a *second* leaderboard, not a replacement for a solve-count one |

**The part that matters more than the metric: whether a public ranking is a good idea at all.** A leaderboard is a strong motivator for students near the top and a genuine demotivator for students who are struggling — worth deciding deliberately rather than defaulting to "rank everyone publicly by name." Options that soften this:
- **Top-N + "your rank"**: show the top 5-10 publicly, and privately tell each student their own rank/percentile without exposing the bottom of the list.
- **Opt-in**: a profile toggle ("show me on the leaderboard") — respects students who don't want to participate.
- **Anonymized-but-comparable**: show ranks without names ("#3 — 8 solved") plus "you are #7" — keeps the competitive/motivational element without the public-shaming risk.

**Recommendation:** solved-count as the primary metric, **top-N + private "your rank"** display, admin-configurable on/off (you may want it off during the first weeks while students are still building confidence). This is a genuinely small backend addition (one query, similar shape to the admin roster query you already have) plus one new page/section — happy to build the full thing once you pick the display model.

---

## 5. Evaluation Integrity & Plagiarism Detection

Two related but separate problems: **(a)** is the "SOLVED" verdict actually trustworthy (this is the C1 finding from Round 2/3 — still open, still deferred by you), and **(b)** are two students submitting the same code.

### (a) Grading trust — recap
Real server-side execution (sandboxed subprocess or a pooled headless-Pyodide, comparing actual stdout to `sample_output`) is still the correct long-term fix, independent of plagiarism. Flagging again here because plagiarism detection is much more useful *once grading is trustworthy* — right now it's plausible for two students to submit similarly-forged `simulated_output` and both "solve" a problem neither of them wrote, which a similarity checker wouldn't even need to catch since the grader missed it first.

### (b) Plagiarism / similarity detection — options by effort
| Tier | Method | Effort | Catches |
|---|---|---|---|
| **1. Naive** | `difflib.SequenceMatcher` ratio on raw submitted code, pairwise, per problem | Trivial (stdlib only, ~20 lines) | Verbatim copies. Misses renamed-variable copies; false-positives on boilerplate/starter code everyone shares |
| **2. Normalized** | Strip comments/whitespace, canonicalize via `tokenize`/`ast` (rename all identifiers to generic placeholders, drop literals or bucket them), *then* diff | Low-Medium | Renamed-variable copies, reformatted copies. Still misses logic-equivalent-but-restructured code |
| **3. External tool** | Integrate `copydetect` (open-source Python package, AST-aware) or submit to Stanford MOSS (free, but sends code to a third-party server — a real consideration if any submission contains anything you wouldn't want leaving your infrastructure) | Medium | Much more robust structural similarity, industry-standard approach |

**Recommendation:** start with **Tier 2** — it's still just a Python script (no new dependency, no external network call, no data leaving your server), and normalized-AST comparison closes the "just renamed my variables" case, which is the overwhelmingly common form of copying in a beginner class. Run it as an **admin-triggered batch job per problem** (a button: "Check submissions for Problem X"), not as something that runs automatically on every submission — plagiarism review needs a human to look at flagged pairs and use judgment, not an automatic penalty. Output: a similarity matrix / flagged-pairs list surfaced in the admin dashboard, admin decides what to do with it.

If Tier 2's false-positive rate turns out too high in practice (very possible in an intro class where everyone's code looks similar because there's only one obvious way to solve a given exercise), that's the signal to move to Tier 3.

---

## 6. Guidance Level Content & Amount (Levels 1-3)

Read through `build_prompt()` in `ai_mentor.py` in detail. Current design is reasonable overall — each level correctly escalates from "very explicit" to "minimal nudge" — but one thing stood out:

**The response length cap is the same for every level: under 80 words, no exceptions.** That's backwards for what Level 1 is trying to do. Baby-steps guidance for an absolute beginner often *needs* more words to be gentle and step-by-step (breaking one mistake into two or three small sentences) — capping it at the same 80 words as the "minimal nudge" Level 3 forces the model to either skip steps or rush the explanation, undermining the "very gentle" instruction elsewhere in the same prompt.

**Recommendation:** make the word budget level-dependent instead of fixed:
- **Level 1 (Baby Steps):** ~120-150 words — room for a full explain-the-symptom-then-ask-a-leading-question flow.
- **Level 2 (Guided):** ~80 words — current default, works fine here.
- **Level 3 (Challenge):** ~40-50 words — actively *tighter* than now, so "minimal nudge" is enforced rather than just requested.

This is a one-line change in `build_prompt()` (compute the word limit from `help_level` instead of hardcoding 80) plus updating the instruction text per level to state its own limit. Low effort, and it's the one part of the guidance system where the current design works against its own stated intent.

**Separately, worth deciding:** full submission `history` (every previous attempt's code + full feedback) is sent to the model on every single request, for every level, growing every attempt. For a student on their 6th attempt, that's 6 full code blocks + 6 feedback blocks in every subsequent prompt — rising token cost per request as a session goes on, independent of help level. If you want to cap this (e.g., last 3 attempts only, or a summary of earlier ones instead of full text), that's a separate, easy change and ties into the per-student quota discussion from Round 3.
