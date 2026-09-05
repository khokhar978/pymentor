# PyMentor — Re-Audit (Round 4) + Improvement Suggestions

Pulled the latest commit (`feat: live online students tracking, admin heartbeat log filtering, local timezone alignment, and student run logging`) and reviewed it two ways this time: line-by-line diff against the last audited version, **and actually running the app** to exercise the endpoints end-to-end. That second part caught something the diff alone wouldn't have.

## 🚨 Critical — login is completely broken right now

I don't say this lightly: I set up a local copy, installed the dependencies, and ran the actual server against the current code. **Every single login attempt — right password or wrong — returns `500 Internal Server Error`.** Nobody can log into the app in its current state on GitHub.

**Root cause:** the new audit-logging lines added to `login_student()` reference a `client_ip` variable —
```python
logger.warning(f"[STUDENT AUTH] Login FAILED: ... from IP={client_ip} ...")
logger.info(f"[STUDENT AUTH] Login SUCCESS: ... from IP={client_ip}")
```
— but `client_ip` is only ever defined inside `verify_admin()`, a completely different function. `login_student(req: LoginRequest)` never receives the `request` object needed to compute it, so both lines throw `NameError: name 'client_ip' is not defined` the moment they execute, which is on every login, success or failure.

**Proof** (ran directly against your code):
```
FAILURE PATH STATUS: 500   Internal Server Error
SUCCESS PATH STATUS: 500   Internal Server Error
```
with the traceback pointing straight at `main.py`, the `client_ip` reference in `login_student`.

**The fix is small** — give the function access to the request, the same way `verify_admin` already does:
```python
def login_student(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    ...
```
That's it — everything downstream (rate limiting, token issuance, password-change enforcement) is unaffected once this compiles. I verified this fix resolves it by patching a local copy and re-running the full login → change-password → session → submit flow successfully.

This is clearly a "the log line was added but the function signature wasn't updated to match" slip, not a design problem. It's the kind of thing that's genuinely hard to catch by reading a diff, since the added lines look completely reasonable in isolation — you only find it by actually calling the endpoint. More on that in the improvements section below.

---

## ✅ What's new and good this round

- **Cross-browser Pyodide fix (COOP/COEP headers):** you added `Cross-Origin-Opener-Policy`/`Cross-Origin-Embedder-Policy` headers with a Safari-specific branch (`require-corp` for Safari, `credentialless` for everyone else), which is exactly right — Safari genuinely doesn't support `credentialless` the way Chromium/Firefox do, and this is needed for Pyodide's `input()` support via `SharedArrayBuffer`. Good, correct, non-obvious fix.
- **Live "online students" dashboard tile** — I tested this directly (started a session, sent a heartbeat, checked the admin dashboard) and it correctly detected and displayed the active session in real time. Well done.
- **Admin panel's escaping discipline held up** — the new online-students table uses the same `escapeHtml()` treatment as the rest of the dashboard, so this new feature didn't reopen the XSS question I checked carefully in the last round.
- **`start_pymentor.sh`** — a proper Linux/Mac launcher using a venv, which is actually a better pattern than the Windows `.bat` (which installs into the system Python directly). Worth backporting the venv approach to Windows too at some point, but not urgent.
- **The `logs.txt` bug from my last two reports is now actually fixed** — I re-tested it and log entries are landing in the file correctly now (it looks like this happened as a side effect of removing dead code from `ai_mentor.py`, whether intentional or not).

---

## Minor things worth knowing about

**Raw AI-provider error text is returned directly to students.** When every model in the fallback cascade fails, the response includes the literal exception string from the Gemini SDK (in my test: a raw "Host not in allowlist..." message) in both `feedback` and `error` fields. You already log the real error server-side — the student-facing message should probably just say something like "AI guidance is temporarily unavailable, please try again shortly" without the raw internals attached.

**Naive local timestamps everywhere, by design choice.** This round switched every timestamp (Python `datetime.now()` and SQL `datetime('now', 'localtime')`) from UTC to the server's local time, presumably so the admin dashboard shows times that make sense to you directly. That's a reasonable call for a single PC in one timezone with no DST — just flagging it as a known trade-off: naive local timestamps (no stored UTC offset) can get confusing later if you ever move hosting, sync data across machines, or hit a DST change. Not worth fixing now; worth knowing about later.

**`is_run` is currently always `true`.** The new `SessionSaveRequest.is_run` flag defaults to `true`, and the one and only place that calls `/api/session/save` (inside `runCode()`) always sends `is_run: true` explicitly. So right now the flag doesn't actually toggle anything — it's fine, just a bit of unused flexibility rather than a bug.

---

## Recap: still open from before (unchanged)

- **C3 — AI grading trust boundary.** Still deferred, as agreed — nothing in `ai_mentor.py`'s evaluation logic changed.
- **H4 — Cloudflare Access.** Still can't verify from the repo whether the tunnel itself is restricted.
- **M3 — no per-student daily AI quota cap** (still just the 3-second burst cooldown from last round).

---

## Broader improvements worth considering for the app itself

You asked for this beyond just the security angle, so here's what I'd actually suggest, roughly in order of value for the effort:

**1. Add a tiny automated smoke test, and run it before every push.** This is the single highest-value thing I can suggest given what just happened. The login bug above would have been caught in about 5 seconds by a script that logs in, changes password, starts a session, saves, and submits — exactly the sequence I ran manually to verify this report. You're iterating fast (four rounds of real feature work in a couple of days), which is great, but it also means regressions like this will keep slipping through unless something automated checks the core path every time. I'm happy to write this as a small `tests/test_smoke.py` (pytest + FastAPI's `TestClient`, no real server or network needed) if you want it — it would take seconds to run and would have caught today's bug immediately.

**2. Add a global exception handler.** Right now, an unhandled exception anywhere (like the one above) just becomes a bare `500 Internal Server Error` with no useful detail for you to act on from the client side. A simple `@app.exception_handler(Exception)` that logs the full traceback server-side and returns a clean, consistent JSON error to the client would make failures like this easier to notice and diagnose quickly, without changing behavior for anything that's already working.

**3. Sanitize error messages before they reach students** (see above) — small, quick, and prevents internal implementation details from leaking into the UI.

**4. As the admin dashboard grows, plan for pagination.** Fine at 12 students; if you ever add more sections, the roster table and recent-activity feed will want a limit/offset rather than loading everything at once. Not needed yet.

**5. Consider letting the admin dashboard export data (CSV) for the analysis you mentioned wanting to do** — since you're already planning to store AI chat history for prompt-tuning analysis, a simple "export events/submissions as CSV" button on the admin page would save you from writing one-off SQL queries every time you want to look at the data outside the dashboard.

**6. A lightweight problem-management flow.** Right now problems are seeded directly in `database.py`'s `seed_problems()` — fine for a fixed problem set, but if you'll be adding/editing problems over the semester, even a simple admin-only "add problem" form (behind the same `verify_admin` gate) would save you from editing Python and redeploying every time.

If you want, tell me which of these (especially the smoke test) you'd like me to actually build, and I'll write it.
