# PyMentor — Security, Robustness & Efficiency Audit

**Scope reviewed:** `backend/main.py`, `backend/ai_mentor.py`, `backend/quota_manager.py`, `backend/database.py`, `run.py`, frontend JS (`app.js`, `problems.js`, `pyodide-worker.js`), the committed `pymentor.db`, and your student-testing `logs.txt`, cross-referenced against the code paths that produced each log line.

**Deployment context:** Self-hosted on your own PC, bound to `0.0.0.0:8000`, exposed to the internet via a Cloudflare Tunnel, used by a handful of BCA students.

---

## 1. Executive Summary

PyMentor works — the logs show real students logging in, solving problems, and getting AI feedback successfully. But right now the app has **no real authorization layer** (anyone who can reach it can act as anyone else) and **no protection against its own users gaming the AI grader**. Combined with public internet exposure, a handful of unauthenticated admin-ish endpoints, and a database file that's already sitting in your public GitHub repo, this needs attention before you scale up usage — but none of it requires a rewrite.

There are effectively **two different problems to solve**, and they need different fixes:

- **Threat A — random internet traffic.** Your logs show generic bots scanning for `.env`, `.git/HEAD`, `wp-admin`, SSH keys, etc. (all harmless 404s), plus one clearly *targeted* automated probe (tagged `__CODEX_AUDIT_NONEXISTENT_ROLL__` / `__AUDIT_INVALID_ROLL__` in your logs) that specifically brute-forced login, fuzzed problem IDs, and hit `/docs` and `/api/status` — the latter actually crashed the server. **Worth confirming: did you run that probe yourself?** If not, someone already deliberately security-tested your live app. Either way, this class of threat is best solved by not exposing the app to the whole internet in the first place — see Phase 0 below.
- **Threat B — your own students.** They have legitimate logins. The risk isn't them breaking in, it's them (a) seeing/overwriting each other's work, since there's no real per-user boundary, and (b) gaming the AI grader into marking incorrect work "solved." Cloudflare-level fixes do nothing for this — it needs app-level fixes.

---

## 2. Findings

### 2.1 Critical

**C1. Anyone can overwrite your Gemini API key — no auth at all.**
`POST /api/config/key` takes any string and writes it straight into your `.env` file and process environment. It's public, unauthenticated, and reachable from the internet.
- *Impact:* Trivial denial-of-service (break the key, app stops giving AI feedback to every student), or someone routes their own traffic through your quota/billing.
- *Where:* `backend/main.py`, `set_api_key()`.

**C2. No authorization boundary — IDOR on almost every stateful endpoint.**
`student_id` and `session_id` are plain integers passed in the request body, and nothing checks that the caller who sends them is actually that student. `app.js` even stores the entire login response (`student_id`, name, roll, section) in `localStorage` and just replays `student_id` on every call.
- *Impact:* Any logged-in student (or anyone who's ever seen the API) can read, overwrite, or submit code into **any other student's session** by changing one number. Combined with the fact every seeded account shares the password `123` (see C3), and that `change-password` also just takes a raw `student_id`, a student could take over a classmate's account outright.
- *Where:* `start_session`, `save_session_code`, `submit_code`, `change_password` in `backend/main.py`.

**C3. The AI grader can be gamed without solving anything.**
Two separate issues compound here:
1. The "terminal output" (`simulated_output`) sent to the grading prompt comes straight from the client — it's not verified against anything server-side. A student can just POST fabricated output that matches the expected sample output.
2. The student's raw code is pasted directly into the LLM prompt with no separation between "code to evaluate" and "instructions." A comment in the submitted code could attempt to instruct the model directly.
- *Impact:* This undermines the entire point of the tool — a student can get marked `[STATUS: SOLVED]` without writing working code.
- *Where:* `backend/ai_mentor.py`, `build_prompt()` / `evaluate_code()`; `backend/main.py`, `submit_code()`.

**C4. `pymentor.db` is committed to your public GitHub repo.**
Good news: right now it only contains the seed data (`User 1..4`, sections E/F/G, password `123`) and the test submissions from your trial run — no real student names. Bad news: your `.gitignore` covers `.env` but not the database, so the *next* time you push after adding real sections/students, their names, roll numbers, passwords, and submitted code go public the same way.
- *Where:* repo root, `.gitignore`.

### 2.2 High

**H1. Passwords are stored and logged in plaintext.**
`logger.info(f"Student login attempt: ... pwd='{password}'")` writes every password attempt to your server logs in cleartext (confirmed directly in the `logs.txt` you gave me), and the `students.password` column stores them unhashed.

**H2. No rate limiting or lockout on login.**
Your own logs show this being exploited live — dozens of sequential single-character password guesses against `section='G', roll='2'` and `section='E', roll='__CODEX_AUDIT...'` with zero throttling or blocking.

**H3. FastAPI's auto-docs are public.**
`/docs` and `/openapi.json` returned `200 OK` to outside requests in your logs — anyone gets a complete map of your API surface, which makes every other issue on this list easier to find.

**H4. The whole app — not just the practice tool — is reachable by anyone on the internet.**
It's meant for 3–4 students, but the Cloudflare Tunnel currently hands access to anyone with the URL. Confirmed by the bot scanning traffic and the CODEX_AUDIT probe from unrelated IPs.

### 2.3 Medium

**M1. CORS is wide open (`allow_origins=["*"]`, `allow_credentials=True`).** This combination is also technically invalid per the CORS spec (browsers reject wildcard origins with credentials), so it's not even doing what it looks like it's doing.

**M2. Login enumerates valid roll numbers.** Non-existent roll → `403`; existing roll + wrong password → `401`. That difference lets someone map out which roll numbers exist per section before guessing passwords.

**M3. Shared, global AI quota with no per-student cap.** `quota_manager.py` tracks usage per *model*, across *all* students combined. One student spamming submissions can burn the whole class's daily Gemini quota.

**M4. A real crash bug is live and publicly reachable:** `GET /api/status` → `500 Internal Server Error`, `NameError: name 'FALLBACK_MODELS' is not defined` — caught directly in your logs. Root cause: `main.py` never imports `FALLBACK_MODELS` from `ai_mentor.py` even though it references it. The traceback in your server log also reveals your local Windows folder structure (`C:\Users\hp\Desktop\lecture\pymentor\...`); worth double-checking your deployment isn't running in a debug mode that would hand that same traceback back to the client.

### 2.4 Low / Robustness & Efficiency

- **No `requirements.txt`** anywhere in the repo — nothing pins `fastapi`, `uvicorn`, `google-genai`, etc. Fragile to set up on any machine other than yours, and future dependency updates could silently break things.
- **Roll-number normalization is fragile:** the regex-based cleanup (stripping "user"/"roll"/"-", extracting first digit run) can misfire on unusual input and is more complexity than the problem needs.
- **Startup banner bug:** `run.py` prints `Network Access: http://127.0.0.1:8000`, which isn't a real network address — cosmetic, but confusing when sharing access info with others.
- **New SQLite connection opened/closed per query**, sometimes multiple times within a single request (e.g. `submit_code` opens/closes twice). Not a problem at this scale, but worth batching if usage grows.
- **Weak password policy on change-password** — only checks length ≥ 3, so a student can "change" their password to `abc`.

---

## 3. What Your Logs Actually Show (cross-check summary)

- **Legitimate use worked fine:** real sessions across sections E, F, G logging in, opening problems 1–10, and getting successful `200 OK` responses from Gemini (`gemini-3.5-flash-lite`) throughout.
- **Generic internet noise:** dozens of automated scans for `.env`, `.git/HEAD`, `id_rsa`, `wp-admin`, `docker-compose.yml`, backup files, etc. — all 404, all completely normal for anything exposed on the open internet, but a good reminder the tunnel is discoverable and being probed constantly.
- **A targeted security probe already ran against your live app.** The `__CODEX_AUDIT_NONEXISTENT_ROLL__` / `__AUDIT_INVALID_ROLL__` markers, combined with parameter fuzzing (`/api/problems/NaN`, `?problem=CODEX_SAFE_PROBE_...`) and hits on `/docs`, `/openapi.json`, and `/api/status` (which crashed it), are the signature of an automated agent specifically testing for the exact weaknesses this report describes. If that wasn't you, someone else already found — and confirmed — several of these issues.

---

## 4. Implementation Plan (pragmatic minimum for a small classroom pilot)

### Phase 0 — Today, ~1 hour, mostly config not code

1. **Put Cloudflare Access in front of the tunnel.** This is the single highest-leverage fix for Threat A and costs you nothing. In the Cloudflare Zero Trust dashboard → Access → Applications → add your tunnel hostname → set a policy allowing only your students' emails (or a shared PIN/one-time code). This alone removes almost the entire random-internet attack surface without touching a line of app code.
2. **Get `pymentor.db` out of the public repo.** Add it to `.gitignore`, then `git rm --cached pymentor.db`. Since the repo currently has a single commit, the cleanest way to fully remove it from GitHub (not just future commits) is to delete and recreate the repo, or force-push a fresh squashed history.
3. **Turn off public API docs:** `FastAPI(title="Python Practice API", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None)`.
4. **Gate `/api/config/key` and `/api/status`** behind a simple shared secret only you know (an env var, checked via a header) — even a minimal check is enough since you're the only admin.

### Phase 1 — This week, core hardening (still scoped to "small classroom app," not enterprise)

5. **Stop logging passwords** — drop `pwd='{password}'` from the login log line entirely.
6. **Hash passwords** (`passlib[bcrypt]` or `bcrypt` directly), compare hashes on login/change-password, and force everyone off the default `123` on first login.
7. **Add basic login rate limiting/lockout** — e.g. `slowapi`, or a simple in-memory counter that blocks an IP+roll combination for a few minutes after 5 failed attempts.
8. **Add a minimal auth token — this is the one change that fixes essentially all the IDOR issues.** On successful login, generate `secrets.token_urlsafe(32)`, store it server-side (in-memory dict or a small table) mapped to `student_id` with an expiry, and require it on every session/save/submit/change-password call, checked against the `student_id`/`session_id` in the request. This doesn't need to be a full JWT/OAuth system to close the gap.
9. **Tighten CORS** to your actual tunnel hostname and drop `allow_credentials=True` (you're not using cookies, so it's not doing anything useful).
10. **Fix the `FALLBACK_MODELS` crash** — import it from `ai_mentor.py` in `main.py` — and confirm the app isn't running with a debug flag that would hand tracebacks to clients.
11. **Close the AI-grading gaming hole:** stop treating client-reported `simulated_output` as verified fact — make the prompt explicitly frame student code/output as untrusted content to *analyze*, never as instructions to follow, and drop the "output exactly matches expected ⇒ lean SOLVED" shortcut, since that's the exact thing a student can fake by hand.
12. **Add `requirements.txt`** (`pip freeze > requirements.txt`) so setup isn't fragile.

### Phase 2 — Optional, only if you scale beyond a handful of students

13. Per-student daily submission cap, so one student can't burn the class's shared Gemini quota.
14. A Cloudflare WAF/rate-limit rule on `/api/student/login` as defense-in-depth alongside the app-level limiter.
15. True server-side sandboxed execution (subprocess with resource limits, or a lightweight container) if you ever need grading correctness that can't be argued with, rather than an LLM's best guess.
16. Structured, rotated logging, with auth endpoints never logging full request bodies.

---

## 5. Quick-Reference Priority Table

| # | Fix | Solves | Effort |
|---|-----|--------|--------|
| 1 | Cloudflare Access on the tunnel | Threat A (internet) | Low |
| 2 | Remove DB from git | C4 | Low |
| 3 | Disable `/docs`, `/openapi.json` | H3 | Trivial |
| 4 | Admin token on config/status routes | C1 | Low |
| 5 | Stop logging passwords | H1 | Trivial |
| 6 | Hash passwords | H1, C2 | Medium |
| 7 | Login rate limit/lockout | H2 | Medium |
| 8 | Auth token on session endpoints | C2 | Medium |
| 9 | Fix CORS | M1 | Trivial |
| 10 | Fix `FALLBACK_MODELS` crash | M4 | Trivial |
| 11 | Untrust client-reported output in grading prompt | C3 | Medium |
| 12 | `requirements.txt` | robustness | Trivial |

Items 1–5 and 9–10 are all quick config/one-line changes you could reasonably do in one sitting; 6–8 and 11 are the ones that actually require writing new logic, and they're the ones that matter most for the "students misusing it" concern specifically.
