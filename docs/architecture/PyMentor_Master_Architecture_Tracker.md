# PyMentor — Master Architecture, API & Implementation Tracker

This document serves as the **single source of truth** for PyMentor's system architecture, live implementation status, REST API master specifications, AI mentorship pipeline, security posture, and developmental roadmap.

**Status Legend:**
* ✅ **IMPLEMENTED & VERIFIED LIVE** — Fully built, tested, and running in production.
* 🟡 **PARTIALLY IMPLEMENTED** — Core functionality exists; extensions or related endpoints pending.
* ⏳ **PLANNED BACKLOG** — Designed and specified; scheduled for upcoming phases.
* ❌ **PENDING ACTION / BUG** — Specific issue, regression, or missing dependency requiring resolution.

---

## 1. Master System Status Matrix

| Subsystem / Feature | Category | Status | Primary Code Locations | Notes |
| :--- | :--- | :---: | :--- | :--- |
| **Problem Studio CMS** | Admin API | ✅ Live | `backend/routers/admin.py` | Full CRUD, reordering, soft/hard deletion, rubric viewing. |
| **Topic / Module Management** | Admin API | ✅ Live | `backend/routers/admin.py` | List with live stats, creation, renaming with DB cascade. |
| **Student Account Management** | Admin API | ✅ Live | `backend/routers/admin.py` | Roster pagination, manual creation, edit, single & bulk password reset. |
| **Session Overrides** | Admin API | ✅ Live | `backend/routers/admin.py` | `POST /admin/sessions/{id}/reset`, `POST /admin/sessions/{id}/override-pass`. |
| **Data Exports (CSV)** | Admin API | ✅ Live | `backend/routers/admin.py` | `GET /admin/export/grades.csv`, `GET /admin/export/submissions.csv`. |
| **Rate Limit CMS** | Admin API | ✅ Live | `backend/routers/admin.py` | Per-student and global daily quota control stored in DB. |
| **Failover & GitHub Backup** | Ops / Infra | ✅ Live | `backend/github_backup.py` | Recency-checked SQLite hot backup, gzip push to GitHub, startup sync. |
| **Pre-Run Guidance Gate** | AI Pipeline | ✅ Live | `app.js`, `session.py` | Block guidance if code was not executed or output is empty. |
| **Deterministic Crash Gate** | AI Pipeline | ✅ Live | `backend/ai_mentor.py` | Pattern-matching override (`detect_crash`) blocks false "SOLVED". |
| **Similarity Scoring** | AI Pipeline | ✅ Live | `backend/ai_mentor.py` | Normalizes and scores student stdout against `sample_output`. |
| **Reference Solution Context** | AI Pipeline | ✅ Live | `backend/ai_mentor.py` | Supplies hidden reference solution to LLM as grading context. |
| **Level Word Budgets** | AI Pipeline | ✅ Live | `backend/ai_mentor.py` | Level 1 ($\le 70$ words), Level 2 ($\le 45$ words), Level 3 ($\le 25$ words). |
| **Model Quota Management** | AI Pipeline | ✅ Live | `backend/quota_manager.py` | Priority cascade (`3.5-flash-lite` $\rightarrow$ Flash premium $\rightarrow$ Gemma). |
| **Resizable Panels** | UI / Frontend | ✅ Live | `index.html`, `style.css` | Drag gutters (`#gutterProblem`, `#gutterOutput`) with Monaco sync. |
| **Responsive Design** | UI / Frontend | ✅ Live | `frontend/css/style.css` | Media breakpoints at 900px, 768px, 640px, 480px. |
| **Active Practice Timer** | UI / Frontend | ✅ Live | `frontend/js/app.js` | Starts on first keystroke/run (Option C), pauses on hidden/idle. |
| **Learning Reports** | AI / Feature | ✅ Live | `reports.py`, `session.py` | Background generation on attempt $\ge 2$, sync fallback, modal viewer. |
| **Open Redirect Vulnerability** | Security | ✅ Live | `frontend/js/login.js` | Protected against protocol-relative redirects (`!targetUrl.startsWith('//')`). |
| **Student Hard-Delete FK Order** | Data Integrity| ✅ Live | `backend/routers/admin.py` | Complete cascading deletion across all 6 child tables and in-memory overrides. |
| **`openpyxl` Dependency** | Environment | ✅ Live | `requirements.txt` | Added `openpyxl>=3.1.0` for spreadsheet parsing on fresh server deployments. |
| **Silent Auth Token Refresh** | Security | ⏳ Planned | `backend/routers/auth.py` | Background token refresh around day 5 to avoid mid-session 401s. |
| **Hint Friction Step-Down** | Pedagogy | ✅ Live | `backend/hint_friction.py`, `session.py` | Enforces 3:2:1 -> 6:4:2 doubling ratio cycle; editor dropdown replaced with read-only badge. |
| **Leaderboard** | Engagement | ✅ Live | `backend/routers/leaderboard.py`, `problems.html` | Top 10 rankings (All vs Section toggle), 5-min in-memory cache, private student rank footer. |
| **Milestone Badges** | Engagement | ⏳ Planned | `frontend/js/profile.js` | Badges for 1st solve, 10 solves, topic mastery, and streaks. |
| **Concept-Linking in Prompts** | Pedagogy | ⏳ Planned | `backend/ai_mentor.py` | Link back to previously solved problems in the same topic. |
| **In-App Plagiarism Checker** | Pedagogy | ⏳ Planned | `backend/routers/admin.py` | AST-normalized pairwise similarity batch analyzer. |

---

## 2. Master Admin REST API Specification

All administrative endpoints require the `X-Admin-Secret` request header matching `ADMIN_SECRET` in `.env`.

### Group 1: Problem Management (✅ Live)
* **`GET /api/admin/problems`**: List all problems with metadata, difficulty, topic, order, and active flag.
* **`POST /api/admin/problems`**: Create a new problem.
  * **Payload**: `topic`, `title`, `difficulty`, `description`, `sample_input`, `sample_output`, `concepts`, `starter_code`, `ai_rubric`, `reference_solution`, `teacher_instructions`.
* **`GET /api/admin/problems/{id}/full`**: Retrieve complete problem details including internal rubrics, teacher instructions, and reference solution.
* **`PUT /api/admin/problems/{id}`**: Update any subset of problem fields.
* **`DELETE /api/admin/problems/{id}?hard=false`**: Soft-delete (`is_active=0`) or hard-delete (if no student submissions exist).
* **`POST /api/admin/problems/reorder`**: Reorder display sequence. Payload: `[{"id": 1, "order_index": 10}, ...]`.
* **`GET/POST/DELETE /api/admin/problems/{id}/instructions`**: Live teacher instructions for a specific problem.

### Group 2: Topic Management (✅ Live)
* **`GET /api/admin/topics`**: List all topics with live aggregated counts (questions count, active count, attempts, solves).
* **`POST /api/admin/topics`**: Create a new topic category. Payload: `{"name": "...", "description": "..."}`.
* **`PUT /api/admin/topics/{topic_identifier}`**: Rename a topic and automatically cascade changes across all problems in `problems.topic`.

### Group 3: Student Account Management (✅ Live)
* **`GET /api/admin/students`**: Paginated student search with `section` and `search` query parameters.
* **`POST /api/admin/students`**: Manually register a late student (`roll_no`, `name`, `section`, `password`, `needs_password_change`).
* **`PUT /api/admin/students/{id}`**: Edit student profile (fix typos, update section, modify email).
* **`POST /api/admin/students/{id}/reset-password`**: Reset specific student password (defaults to `'123'`).
* **`POST /api/admin/students/bulk-reset-passwords`**: Bulk reset an entire section or whole class.
* **`DELETE /api/admin/students/{id}?hard=false`**: Soft deactivation or permanent deletion.

### Group 4: Live Lab Session Overrides (✅ Live)
* **`POST /api/admin/sessions/{session_id}/reset`**: Clear submissions and code for an active problem session, allowing a student to start fresh.
* **`POST /api/admin/sessions/{session_id}/override-pass`**: Manually mark a student's session as `SOLVED` with an instructor note (e.g. oral verification or alternate valid algorithm).

### Group 5: Data Exports & Analytics (🟡 Partially Live)
* **`GET /api/admin/export/grades.csv`** (✅ Live): Stream CSV containing Roll No, Name, Section, Solved Count, Active Seconds, Submission Count, and Last Active timestamp.
* **`GET /api/admin/export/submissions.csv`** (✅ Live): Stream complete historical attempts, student code, AI feedback, verdicts, and model used.
* **`GET /api/admin/analytics/problem-stats`** (⏳ Backlog): Aggregated breakdown of problem failure rates and common error categories across sections.

### Group 6: System, Rate Limits & Logs (✅ Live)
* **`GET /api/admin/config/ratelimit` & `POST /api/admin/config/ratelimit`**: Global daily student guidance quota control.
* **`GET/POST/DELETE /api/admin/students/{id}/ratelimit`**: Per-student daily quota exemptions or overrides.
* **`GET /api/admin/logs` & `GET /api/admin/logs/download` & `POST /api/admin/logs/clear`**: Live server log inspection and download.
* **`POST /api/config/key`**: Live Gemini API key update without server restart.

---

## 3. AI Mentorship & Grading Pipeline

### Evaluation Flow (Four-Stage Pipeline)
```text
1. PRE-RUN GATE: Was current code executed in Pyodide?
   ├── No  ─► REJECT: "Run your code first so I can see what it actually does."
   └── Yes ─► Continue to Step 2
2. HARD CRASH GATE: Deterministic regex scan of simulated_output
   ├── Crash detected (Traceback, SyntaxError, ValueError, etc.)
   │   └─► FORCE VERDICT: [STATUS: IN_PROGRESS] (AI cannot mark solved)
   └── No crash ─► Continue to Step 3
3. STRUCTURAL SIMILARITY: Compare simulated_output vs sample_output
   └── Computes normalized match percentage (0–100%) as evidence for LLM
4. LLM EVALUATION: Evaluates code + reference solution + similarity + current attempt
   ├── Output starts with [STATUS: SOLVED]       ──► Solved + short praise
   └── Output starts with [STATUS: IN_PROGRESS]  ──► Feedback based on Help Level
```

### Guidance Levels & Word Budgets (`ai_mentor.py`)
* **Level 1 (Baby Steps) — Budget: $\le 70$ words:**
  * Quotes exact line numbers and expected vs. actual values.
  * Breaks the fix into one tiny, concrete next action.
  * Explains the practical real-world screen effect of the error.
  * Explicitly prohibited from printing the complete solution code.
* **Level 2 (Guided) — Budget: $\le 45$ words:**
  * Identifies the concept or section that is off without quoting line numbers or exact values.
  * Prompts the student with one guiding diagnostic question.
* **Level 3 (Challenge) — Budget: $\le 25$ words:**
  * States only general category (input handling, arithmetic logic, or formatting).
  * Forces the student to rely on test output and terminal evidence.

### Prompt Tone & Safety Guardrails
* Standard encouraging college lab instructor voice.
* **Strict Rule 1:** Zero Romanized Hindi / Hinglish filler words (`achha`, `arre`, `shabash`, `bilkul`). Standard English only.
* **Strict Rule 2:** No addressing the student by name in feedback text (starts directly with encouragement).
* **Failure Handling:** Temporary API errors are caught and recorded as `_FAILED_ATTEMPT_PLACEHOLDER` so raw stack traces never pollute future prompt histories.

### Quota Management & Model Cascades (`quota_manager.py`)
1. **Normal Code Guidance (Submissions):**
   * Primary: `gemini-3.5-flash-lite` (500 RPD, 15 RPM).
   * Secondary: `gemini-3.1-flash-lite` (500 RPD, 15 RPM).
   * Emergency Fallback: `gemma-4-31b-it` / `gemma-4-26b-a4b-it` (14,400 RPD).
2. **Learning Reports:**
   * Restricted to high-quality Flash models: `gemini-3.8-flash` $\rightarrow$ `3.7` $\rightarrow$ `3.6` $\rightarrow$ `3.5` $\rightarrow$ `2.5`.
   * **Recommendation:** Update `gemini-3.5-flash-lite` to `"uses": "both"` to prevent report starvation on free tiers.

---

## 4. UI/UX & Practice Environment Subsystems

### 1. Resizable Workspace Panels (✅ Live)
* Thin vertical gutter (`#gutterProblem`) between Problem Description and Code Editor.
* Thin horizontal gutter (`#gutterOutput`) between Code Editor and Terminal/Guidance Console.
* Drag handlers listen to `mousedown` $\rightarrow$ `mousemove` $\rightarrow$ `mouseup` updating flex basis CSS variables.
* Monaco editor automatically synchronizes layouts upon drag release.

### 2. Responsive Adaptability (✅ Live)
* Fixed desktop layout degrades cleanly to column-stacked layout on viewports $\le 900\text{px}$.
* Cards, headers, and admin tables collapse gracefully for mobile inspection down to $480\text{px}$.

### 3. Practice Timer — Option C (✅ Live)
* Timer does **not** count up passively on problem load.
* Initialized via `startTimerOnActivity()` in `app.js` upon the student's first keystroke in Monaco or first code execution.
* Automatically halts ticks whenever `document.hidden` is true or if user activity ceases for $>60$ seconds.
* Heartbeats credit actual server-authoritative elapsed seconds every 20 seconds.

---

## 5. Security, Audit & Hardening Tracker

### Resolved Audit Items
* ✅ **Per-Request Submit Cooldown Restored:** `SUBMIT_COOLDOWN_SECONDS = 3.0` actively checked at the top of `/session/submit` to prevent automated spamming.
* ✅ **Raw SQL Console Removed:** Unrestricted `POST /admin/sql` endpoint was deleted from the backend, eliminating blast-radius risks.
* ✅ **Backup Recency Check:** `is_candidate_db_newer()` verifies that the remote backup has a higher `MAX(id)` or greater submission count before overwriting the local database upon startup or peer sync.

* ✅ **Open Redirect Guarded:** Added protocol-relative redirect protection (`!targetUrl.startsWith('//')`) in `frontend/js/login.js`.
* ✅ **Hard-Delete Foreign Key Cascade:** `DELETE /admin/students/{id}?hard=true` cascades deletions through `student_rate_limits`, `learning_reports`, `events`, `submissions`, `sessions`, and `auth_tokens` before removing the student record.
* ✅ **`openpyxl` Dependency Added:** Included `openpyxl>=3.1.0` in `requirements.txt` for Excel parsing support.

---

## 6. Pedagogical & Engagement Roadmap (Next Phases)

### Phase 1: Ground-Truth Grading Integrity
* **Status:** Soft similarity scoring + deterministic crash gate active.
* **Next Step:** Introduce headless server-side execution against hidden test cases as the ground truth boolean for `is_correct`, reserving the LLM strictly for natural-language feedback.

### Phase 2: Hint Friction & Socratic Scaffolding (✅ Live)
* **Status:** Implemented & Verified.
* **Goal:** Prevent learners from staying permanently parked on Level 1 (Baby Steps) through automatic pedagogical scaffolding.
* **Architecture (`backend/hint_friction.py` & `session.py`):**
  * **Ratio Progression Cycle:**
    * Cycle 1: 3 Baby Steps (L1) $\rightarrow$ 2 Guided (L2) $\rightarrow$ 1 Challenge (L3) (Total: 6 hints).
    * Cycle 2: 6 Baby Steps (L1) $\rightarrow$ 4 Guided (L2) $\rightarrow$ 2 Challenge (L3) (Total: 12 hints).
    * Cycle $k$: $3 \times 2^{k-1}$ L1 $\rightarrow$ $2 \times 2^{k-1}$ L2 $\rightarrow$ $1 \times 2^{k-1}$ L3 (doubles each cycle).
  * **Student Profile Independence:**
    * If student sets `default_help_level = 2` (Guided) in profile: Baby Steps is zeroed out ($0:2:1 \rightarrow 0:4:2$).
    * If student sets `default_help_level = 3` (Challenge): strictly kept at Challenge mode.
  * **Database Tracking:** `submissions.help_level` column records the exact level utilized on each attempt.
  * **UI/UX:** Editor dropdown removed to avoid student tampering; replaced with read-only `.hint-level-badge` displaying the active band icon, name, and progress tag (e.g. `🟢 Baby Steps (1/3)`). Transitions trigger a visual glow alert.

### Phase 3: Engagement & Gamification
1. **Leaderboard (✅ Live):**
   * **Endpoint:** `GET /api/leaderboard?section={sec}` with 5-minute (300s) server-side thread-safe in-memory cache.
   * **Metric:** Solved problem count (`COUNT(DISTINCT problem_id)` where `status = 'solved'`), with tiebreaker on lower total active time (`SUM(time_spent_seconds)`).
   * **Privacy:** Publicly displays Top 10 with rank medals (🥇, 🥈, 🥉); displays the requesting student's rank privately in the footer (`Your Rank (Overall): #X of Y`) to prevent bottom-roster demotivation.
   * **UI/UX:** Sticky sidebar card on `/problems` with instant toggle between "All" (class-wide) and "Section" views. Displays active streak flame pills (`🔥 N`). Responsive layout collapses below problem list on viewports $\le 960\text{px}$.

2. **Practice Streak System 🔥 (✅ Live):**
   * **Engine (`backend/streak.py`):**
     * Tracks consecutive calendar days based strictly on verified problem solves (`is_correct = 1` in `submissions`).
     * Current streak remains alive if the student solved a problem today OR yesterday (allowing day-of practice without premature streak reset).
     * Tracks all-time `longest_streak` and `solved_today` boolean status.
     * High-performance batch evaluation (`compute_all_students_current_streaks`) integrated into the 5-minute leaderboard cache.
   * **API Endpoints:**
     * Dedicated: `GET /api/student/streak`
     * Enriched: `GET /api/student/profile` includes full `streak` payload.
     * Enriched: `GET /api/leaderboard` attaches `streak` to each top 10 solver.
   * **UI/UX Integration:**
     * **Site-Wide Header Badge (`#streakBadge` via `shared/streak.js`):** Displays animated fire badge `🔥 N` with pulse effect when solved today, or ice `❄️ 0` if broken. Instantly refreshes on problem solve.
     * **Profile Streak Hero Card (`#profileStreakCard` in `profile.html`):** Large flame display with current vs. all-time best streak counts and motivational call-to-action.
     * **Leaderboard Streak Badges:** Distinctive flame pills next to student usernames on the problem sidebar.

3. **Milestone Badges:**
   * Computed dynamically in profile view:
     * *First Solve*
     * *10 Problems Solved*
     * *Topic Master* (100% completion of any module)
     * *7-Day Streak Master*
   * Triggers celebration confetti upon unlock.

4. **Concept-Linking in Guidance:**
   * Query if the student previously solved an earlier problem in the same topic.
   * If found, prompt injects: *"The student previously solved '{title}' in this module. If relevant, reference that concept rather than re-explaining from scratch."*

### Phase 4: Integrity & Plagiarism Review Engine
* **Status:** Backlog.
* **Implementation:** An admin-triggered batch analysis tool running AST normalization (`ast.parse`, renaming variables to generic tokens, stripping comments) and computing pairwise similarity matrices across student solutions for any selected problem. Flags suspicious clusters for instructor review.
