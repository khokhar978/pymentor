# PyMentor — Re-Audit (Round 6): Production-Readiness Pass

Pulled the latest commit (`fix: resolve Audit Round 5 findings (admin IP validation, bfcache restoration, cache busting, and smoke test alignment)`) and went through it with production deployment specifically in mind — not just "does it work," but "is this safe to leave running unattended with real students on it." Verified the two open bugs from last round first, then read every changed file, ran the (now 11-test) smoke suite, and added a dedicated production-readiness pass at the end since that's the actual goal now.

## Verifying the two bugs from last round

**The Pyodide namespace fix: done, and actually better than what I suggested.** `pyodide-worker.js` now runs every execution in a fresh, isolated global dictionary and destroys it afterward. What I want to call out specifically: instead of a bare empty dict (`pyodide.toPy({})`, which is what I'd proposed), the implementation builds the fresh namespace with `__name__='__main__'` and `__builtins__` explicitly set — which matters, because a bare dict would silently break any student code using the extremely common `if __name__ == "__main__":` pattern. On top of that, there's now a defensive sweep that purges anything unexpected from the shared interpreter globals both before and after each run, as a second line of defense. This is more thorough than my original suggestion, not just "implemented as spec'd." I'm confident this resolves what your screenshots showed.

**The theme.js flash-of-light-mode bug: still not fixed.** I checked directly — `theme.js` is still loaded as `<script type="module">` on every page, which still means dark-mode users get a flash of the light theme before it switches on every load. Nothing in this commit touched that (the "bfcache restoration" work was a different, also-legitimate fix — see below — but it's not the same issue). Still an easy fix: drop `type="module"` and the now-unused `export` keywords from `theme.js`, and move its `<script>` tag to be the very first thing in `<head>`. Worth doing before this is genuinely "shipped," since it's the kind of thing a first-time visitor notices immediately.

## New: found a real, well-executed security fix I hadn't asked for

The admin IP-lockout now validates *where* the `CF-Connecting-IP` header is coming from before trusting it — it checks the actual TCP peer address against Cloudflare's officially published IP ranges, and only uses the header-provided IP if the connection genuinely came through Cloudflare's edge. If it didn't, it falls back to the raw peer address instead of blindly trusting a header anyone could set. This is exactly the right way to handle this, and it also explains something from last round: I'd take a bet that before this fix, every request was probably showing up as `127.0.0.1` (since `cloudflared` connects to your app locally), meaning the IP-based admin lockout was likely tracking *all* visitors as one shared bucket rather than individual IPs. This fix resolves that properly, with real spoofing protection built in rather than just trusting the header outright.

One tiny operational note, not urgent: Cloudflare's published IP list can change occasionally. It's hardcoded here, which is fine for now — just something to glance at [cloudflare.com/ips](https://www.cloudflare.com/ips/) for every so often if you ever notice legitimate traffic being misclassified.

## New: a small inconsistency in the cache-busting work

The commit added version query strings (`?v=2.1`, `?v=3.6`, etc.) to force browsers to fetch updated JS after a deploy — good instinct, and `pyodide-worker.js` itself is versioned (`?v=3.1`), which matters a lot given the fix above. But it's inconsistently applied: `index.html` references `theme.js?v=2.1`, while `login.html`, `profile.html`, and `problems.html` all still reference a bare `theme.js` with no version. If you update `theme.js` again later (e.g., to fix the FOUC issue above), students who've already visited the login/profile/problems pages may keep getting a stale cached copy there even after the fix ships. Worth bumping all four to match once you touch this file next.

## Confirmed: the modularization work is fully carried through, not half-done

I specifically checked whether the shared frontend modules from two rounds ago were actually adopted everywhere, not just created and left unused — they are. `shared/api.js`, `shared/auth.js`, `shared/utils.js`, and `shared/theme.js` all exist, and every page script (`app.js`, `admin.js`, `problems.js`, `profile.js`, `login.js`) imports from them instead of duplicating logic. The `formatDuration()` duplication and the four-times-repeated localStorage auth check from a few rounds ago are both genuinely gone now, not just relocated.

The backend split is holding up the same way: `config.py`, `deps.py`, `state.py`, and the router split are all intact and correctly extended (the new Cloudflare IP-validation logic went into `deps.py` exactly where it belongs, not bolted onto `main.py`).

## Confirmed: your own smoke test suite caught up

It's grown from 8 to 11 tests, and the three new ones are exactly the right additions: `test_code_submit_and_cooldown`, `test_cross_student_idor` (an explicit regression test for the IDOR class of bug from early rounds — good instinct to lock that down permanently), and `test_admin_lockout_and_rate_limiting`. All 11 pass. This is a genuinely solid safety net at this point, and it's the reason I can move faster and trust incremental changes more than I could three rounds ago.

## Smaller things reviewed and cleared

- **`psutil.cpu_percent(interval=0.1)` → `interval=None`**: this fixes the minor blocking-call efficiency note from an earlier report (the old version deliberately paused for 100ms on every admin dashboard load to sample CPU; the new version doesn't block at all). Correct fix.
- **New `default_help_level` student setting**: reviewed the new endpoint (`/api/student/settings`) — properly authenticated, properly range-validated (`ge=1, le=3`) via Pydantic, no issues.
- **New resizable editor/terminal panels**: checked the drag-handle JS specifically for the classic mistake here (mousemove/mouseup listeners that never get cleaned up, silently accumulating over a long session) — it's implemented correctly, removing both listeners on every `mouseup`. No leak.
- **Heartbeat timing retuned** (10–45s/25s cap → 14–60s/30s cap, matching a 20-second client interval) and **heartbeats now stop crediting time once a session is already marked solved** — both are sensible, deliberate improvements, not regressions.
- I noticed you (or your coding agent) already have a `PyMentor_Feature_Discussion.md` in the repo scoping out responsive/mobile design — correctly identifying that `style.css` currently has zero `@media` queries. I won't duplicate that analysis since it's already been thought through there; just flagging that it's a real gap worth closing before wide deployment if students might use the app on phones or tablets, since right now it's desktop-only by construction, not by graceful degradation.

---

## Production-readiness checklist (the new focus for this round)

These aren't bugs in the current code — they're the difference between "runs correctly when I'm watching it" and "safe to leave running unattended for a semester."

1. **Don't add more uvicorn workers for "performance."** It'll be tempting, once this is in real production use, to scale up with `uvicorn ... --workers 4` thinking that helps under load. Don't, not without more changes first — your rate limiting, admin lockout, and submission cooldowns all live in plain Python dicts in `state.py`, which are per-process memory. Multiple workers means multiple independent copies of that state, silently breaking all of your lockout/rate-limit guarantees (a student could get 5 attempts against worker 1 and 5 more against worker 2 with no shared memory of either). At your actual scale (a handful of students), one worker is completely fine and is what you're already running — just flagging this so a future "let's make it faster" instinct doesn't quietly reopen every rate-limiting fix you've built up over five rounds.
2. **`logs.txt` has no rotation and will grow forever.** Fine for a few weeks of testing; not fine left running for a semester unattended. Swap `logging.FileHandler` for `logging.handlers.RotatingFileHandler(config.LOG_FILE_PATH, maxBytes=5_000_000, backupCount=3)` — same interface, just caps the file size and keeps a few rolled-over backups instead of one unbounded file.
3. **There's no backup of `pymentor.db`.** It's the only copy of every student's progress, submissions, and account data, sitting on one PC with no redundancy. A simple scheduled copy (Windows Task Scheduler running `copy pymentor.db backups\pymentor_%date%.db` daily, or the equivalent cron job if you're on the Linux launcher) is a 10-minute task that saves you from a single disk hiccup wiping out a semester of data.
4. **Nothing restarts the app if it crashes.** Right now, if the process dies for any reason (an unhandled exception outside what the global handler catches, an out-of-memory event, a power blip that doesn't reboot the PC cleanly), it just stays down until you notice and manually restart it. Consider `nssm` (Windows) or a small watchdog/scheduled task that checks the process is alive and restarts it if not — doesn't need to be fancy, just something other than "you happen to notice students can't log in."
5. **No health-check endpoint.** A trivial `GET /healthz` returning `{"status": "ok"}` costs almost nothing to add and gives you (or an external uptime monitor, even a free one) something to poll instead of guessing whether the app is actually up.
6. **`requirements.txt` uses open-ended version bounds** (`fastapi>=0.110.0`, etc.), not exact pins. That's fine for active development, but for a production install, run `pip freeze > requirements.txt` once you're happy with the current working set, so a fresh install six months from now doesn't silently pull in a newer, potentially breaking version of FastAPI or Pydantic. Keep a copy of today's exact versions before you consider this "shipped."
7. **Confirm nothing else reaches port 8000 directly.** This is presumably already true given the Cloudflare Tunnel setup, but worth a one-time check: make sure your router/firewall isn't also port-forwarding 8000 directly, and that it's only reachable through the tunnel. Redundant redundancy is cheap; an accidentally-exposed raw HTTP port is not.

None of these are urgent in the sense of "fix today" — they're the checklist for "before I stop thinking about this as a class project and start thinking about it as something running unattended for a semester."

---

## Efficiency notes (as requested — happy to dig into any of these further)

- The `psutil` fix above is the only actual blocking-call issue I found this round.
- SQLite connections are still opened and closed per-query rather than pooled (noted a couple of rounds ago) — genuinely not worth touching at your current scale (a handful of students, low request volume); flagging again only because you're explicitly asking about efficiency, not because it's actually costing you anything measurable right now.
- The admin dashboard polls every 10 seconds while open, each hitting 6+ queries plus the now-non-blocking `psutil` calls — fine for one admin tab open occasionally, would be worth lengthening the interval or switching to manual refresh only if you ever leave the dashboard open continuously for hours.
- `logs.txt`'s unbounded growth (point 2 above) is as much an efficiency concern as an ops one — a multi-gigabyte log file eventually makes every `tail`/grep/text-editor open on it slower, on top of the disk space.

## Recap: intentionally deferred, not forgotten

- **C3 — AI grading trust boundary** (client-reported output trusted, prompt injection surface) — still open, still your call on timing, not touched this round.
- **M3 — no per-student daily AI quota cap** — still just the 3-second burst cooldown, nothing further needed unless you want it.

Both are noted here per your instruction and I haven't spent further effort on either this round.
