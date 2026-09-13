# Implementation Plan: Fine-Tuning the AI Integration

Based on a full read of `chat_logs_export.json` (200 real submissions from student testing) and our discussion. Every claim below is backed by specific submission IDs from that export, not general impressions.

## What the data proved, in one place

- **9.4% of "Correct" verdicts were false** (6/64) — actual captured output was a Python crash (`ValueError`, `SyntaxError`, `TypeError`), and the AI's stored response confidently described success anyway. Submissions #159/#160/#162 are the same crash marked "Correct" three separate times.
- **The AI contradicted its own evidence at least once**: submission #92's actual output shows a formatting fix was already made; the AI's response claimed it wasn't, apparently anchored on the previous attempt's quoted text.
- **Help Level 1 and 2 are statistically indistinguishable**: 351 vs 352 average response characters, same Socratic-question style. Root cause found directly in `ai_mentor.py`: a global "under 80 words" cap and a shared response template dominate over the weaker level-specific instructions.
- **49% of submissions have empty `simulated_output`** — for half of all guidance requests, the AI has no real execution evidence at all.

Everything below addresses one of these findings directly. Nothing here is speculative.

---

## Architecture: what changes

Today, correctness is a single LLM opinion. The new pipeline adds two deterministic layers *before* the LLM gets a vote on pass/fail, while keeping the LLM as the sole author of the actual teaching feedback:

```
1. GATE: was this code actually run? ──────► No → reject, ask student to run first
                     │ Yes
                     ▼
2. HARD CHECK: does output contain a crash signature? ──► Yes → verdict FORCED to IN_PROGRESS
                     │ No                                        (AI still explains the crash,
                     ▼                                            but can't override the verdict)
3. SOFT EVIDENCE: similarity score vs sample_output
   (a number, not a gate — handed to the AI as evidence)
                     │
                     ▼
4. AI evaluates: code + reference solution (context only) +
   similarity score + crash-check result + CURRENT attempt only
   (not blended with history) → produces verdict + feedback,
   verdict only takes effect if step 2 didn't already force it
```

The key principle: **the AI can always downgrade a verdict to "not solved," but it can no longer upgrade one past a hard crash detection.** That asymmetry is deliberate — false negatives (marking working code wrong) are annoying; false positives (marking crashed code solved) are the ones the data shows actually happening and actually damaging trust in the tool.

---

## Component 1 — Require a real run before guidance is allowed

**Frontend (`app.js`):** track the exact code string at the moment a run finishes.
```javascript
// after a run completes successfully or with an error:
state.lastRunCode = currentCodeString;

// whenever editor content changes, or before enabling the Guidance button:
function isGuidanceAllowed() {
    return state.lastRunCode !== null && state.lastRunCode === state.editor.getValue();
}
```
Wire this into the editor's change handler so the Guidance button (and its keyboard shortcut, if any) disables the instant the code diverges from what was last run, with a short inline message: *"Run your code first so I can see what it actually does."* Re-enable the moment a fresh run completes against the current content.

**Backend (`routers/session.py`, `submit_code`):** this must also be enforced server-side, since a direct API call could skip the disabled button entirely:
```python
if not req.simulated_output or not req.simulated_output.strip():
    raise HTTPException(status_code=400, detail="Please run your code at least once before requesting guidance.")
```
This one change directly targets the 49% empty-output statistic and guarantees Components 2 and 3 below always have something real to work with.

---

## Component 2 — Deterministic crash detection (hard gate)

New function in `ai_mentor.py`, pure string pattern-matching, no execution involved:
```python
import re

_CRASH_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"\b\w*Error\b:",          # ValueError:, TypeError:, SyntaxError:, NameError:, etc.
    r"\b\w*Exception\b:",
]

def detect_crash(simulated_output: str) -> bool:
    if not simulated_output:
        return False
    return any(re.search(pattern, simulated_output) for pattern in _CRASH_PATTERNS)
```
In `evaluate_code()`, after the LLM returns its verdict, apply the override:
```python
crashed = detect_crash(simulated_output)
if crashed and is_correct:
    is_correct = False
    # keep the AI's explanatory text — it's usually still a reasonable description
    # of what went wrong — but the stored verdict is now correct regardless of
    # what the model concluded.
    logger.warning(f"AI marked SOLVED on a crashing output; overridden. submission context: problem={problem['id']}")
```
That log line matters — it turns every near-miss into visibility instead of a silent, invisible correction, so you can spot-check whether the LLM's judgment is improving over time even with the safety net in place.

This single ~15-line function would have caught all 6 false positives in the log export, with no per-problem maintenance and no ongoing cost.

---

## Component 3 — Structural similarity score (soft evidence, not a gate)

Every problem already has a `sample_output` field. Compare the student's actual output against it after normalizing whitespace, and hand the *score* to the AI as evidence rather than deciding anything with it directly — because a correct program run with a different name/number than the sample will legitimately differ from the sample text, so this can't be a rigid pass/fail line.

```python
import difflib
import re

def normalize_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[ \t]+', ' ', text)      # collapse repeated spaces/tabs
    text = re.sub(r'\n{2,}', '\n', text)      # collapse repeated blank lines
    return text.lower()

def similarity_score(expected: str, actual: str) -> float:
    a, b = normalize_output(expected), normalize_output(actual)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio() * 100, 1)
```
Feed this into the prompt as a labeled fact, not an instruction to follow blindly:
```python
f"=== OUTPUT SIMILARITY TO SAMPLE (computed, not your judgment) ===\n"
f"{score}% structural match against the expected sample output.\n"
f"(This score ignores exact names/numbers since those legitimately vary — "
f"treat it as one signal among several, not a verdict.)\n\n"
```
This is the piece that directly answers your "spaces gap, decide a percent" request — the percentage exists and is computed, but it's advisory input to the AI's judgment rather than a second hard gate, because unlike a crash (which is unambiguous), "how close is close enough" genuinely benefits from the model's read of the actual code too.

---

## Component 4 — Reference solution as context (not executed)

Add one field to the `problems` table:
```sql
ALTER TABLE problems ADD COLUMN reference_solution TEXT;
```
You write these (per your call) — one working Python solution per problem, in whatever style you'd naturally write it. It's never executed; it's included in the prompt purely as grounding:
```python
f"=== REFERENCE SOLUTION (for your understanding only — NEVER show this to the student, "
f"and do not penalize a different but valid approach) ===\n"
f"{problem.get('reference_solution', 'Not provided for this problem.')}\n\n"
```
This gives the AI something concrete to check logic against, especially useful exactly when `simulated_output` is present but ambiguous (e.g., partial output, or output that's hard to judge on structure alone) — while the explicit "don't penalize a different approach" instruction protects the "accept any valid logic" rule you already have.

Not every problem needs one on day one — start with the problems that show up most in the log export with grading trouble (Problem 1, 14, 15, 24 based on what I found) and backfill the rest over time; the system should treat a missing reference solution the same as today (AI reasons from the description and rubric alone), so this degrades gracefully.

---

## Component 5 — Fixing mode differentiation

The current global "under 80 words" cap plus shared template is why levels feel identical. Replace the one-size-fits-all response-style block with per-level rules that actually differ in *what gets revealed*, not just tone:

```python
level_instructions = {
    1: (
        "\nHELP LEVEL 1 INSTRUCTIONS (Baby Steps) — budget: up to 70 words.\n"
        "- Quote the exact line number AND the exact expected-vs-actual value if available.\n"
        "- Break the fix into one tiny, concrete next action.\n"
        "- It is fine to be this explicit — the goal is momentum, not independence.\n"
    ),
    2: (
        "\nHELP LEVEL 2 INSTRUCTIONS (Guided) — budget: up to 45 words.\n"
        "- Name WHICH concept or section is off (e.g. 'your discount calculation'), "
        "but do NOT quote the exact line number or exact expected value.\n"
        "- Ask one question that requires the student to locate the issue themselves.\n"
    ),
    3: (
        "\nHELP LEVEL 3 INSTRUCTIONS (Challenge) — budget: up to 25 words.\n"
        "- State only THAT something is wrong and in which general area (input handling / "
        "logic / output formatting) — no specifics, no line numbers, no line-level hints.\n"
        "- Let the similarity score and their own output be their only real clue.\n"
    ),
}[help_level]
```
The word budgets are deliberately different per level now (70/45/25) instead of one shared 80-word ceiling, and the difference is *structural* (what's revealed) rather than purely stylistic (how nicely it's phrased) — which is the part that actually survives contact with an LLM that's inclined to be helpful regardless of what tone you ask for.

---

## Component 6 — Stop anchoring on history for the verdict

Directly targets what happened in submission #92. Add an explicit instruction separating "what to narrate" from "what to judge":
```python
"=== CRITICAL: VERDICT SOURCE OF TRUTH ===\n"
"Your [STATUS] verdict must be based ONLY on the CURRENT attempt's code and CURRENT "
"simulated output below — never on what a previous attempt looked like. "
"Use the attempt history ONLY to acknowledge progress in your praise/feedback text, "
"never to inform whether this attempt is correct.\n\n"
```
Small change, but it's a direct fix for a real, observed failure mode, not a hypothetical one.

---

## Component 7 — Don't let infrastructure errors pollute future prompts

The log export shows a raw `[Errno 11001] getaddrinfo failed` message stored as if it were real feedback (submissions #98/#99) — and since full history gets replayed into every future prompt for that session, a raw error string becomes permanent context noise for every subsequent attempt on that problem. Fix: when the AI call itself fails (network/quota/API error, not a grading judgment), don't store that failure text as `ai_response` in the history used for future prompts — store a neutral placeholder instead (e.g., `"(A temporary issue prevented feedback on this attempt.)"`), while still showing the student a friendly retry message in the moment.

---

## Testing this against the exact cases that proved the problem

Since you already have `tests/test_smoke.py` as a working pattern, extend it (or add a sibling `tests/test_grading.py`) with the specific failure cases from the log export as permanent regression tests:
- Replay submission #84's exact `student_code` + `simulated_output` (the crash) through the new pipeline and assert `is_correct == False`, regardless of what the LLM call returns.
- Replay #159's exact scenario the same way.
- A synthetic case with genuinely correct code + a sample-output-matching similarity score, to confirm the happy path still works.

Since `detect_crash()` and `similarity_score()` are pure functions with no external calls, these can be unit-tested directly with zero API cost, run on every change.

---

## What's intentionally not in this plan

- **Plagiarism detection** — out of scope per your call, revisit later. Worth noting the reference-solution field and similarity-scoring groundwork here would be directly reusable for that later (comparing student outputs/code against each other rather than against a reference), but nothing plagiarism-specific is being built now.
- **The "6 baby steps / 3 guided / 2 challenge" attempt-budget idea** — also deferred per your call. Fix mode differentiation first; revisit the budget/step-down mechanism once the modes actually feel different from each other.

---

## Suggested order

1. Component 1 (run-required gate) — unblocks everything else by guaranteeing real data.
2. Component 2 (crash detection) — highest-impact, lowest-effort, no per-problem work needed.
3. Component 6 (history anchoring fix) — a prompt-text change, ships alongside #2 easily.
4. Component 5 (mode differentiation) — independent of the others, can go in parallel.
5. Component 3 (similarity score) — needs the normalization function but no schema change.
6. Component 4 (reference solutions) — needs the schema migration plus you authoring content over time; start with the handful of problems the log export flagged as troublesome.
7. Component 7 (error hygiene) — small, low-risk, whenever convenient.

Steps 1–3 alone would have prevented every concrete failure the log export surfaced. 4–5 are the quality/experience layer on top.
