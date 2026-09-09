# PyMentor — Audit Round 8 (Pre-Production, 183 Real Students)

**Scope note:** `seed_production_students.py` in this commit imports a real attendance sheet and enrolls 183 actual students, plus your own account. This is no longer a "will this work" audit in the abstract — you're about to run this for real. Weighted accordingly.

Six new commits since last audit, one of them huge (`b7c09bc`, 5,180 lines: a full admin CMS — Problem Studio, student management, raw SQL console, rate-limit config — plus a GitHub-backed backup/restore system). Ran the full test suite, read every new backend file, and live-verified the two things that turned out to matter most.

**27/28 tests pass. One regression, confirmed both by the test suite and by reproducing it live.**

---

## 🔴 1. The per-request submit cooldown is gone — confirmed regression

Your own `test_code_submit_and_cooldown` now fails:
```
Expected 429 cooldown, got 400
```
Not a stale test — `tests/` wasn't touched in this commit; `session.py` was. Here's what happened: the cooldown *stamp* was moved to the end of `submit_code()` ("so student has full cooldown window after reading hint" — a reasonable UX intent), but the actual *check* that reads the stamp and rejects a too-fast request was dropped in the process. `state.submit_cooldowns[student_id] = time.time()` still runs — nothing ever reads it back. `SUBMIT_COOLDOWN_SECONDS` is still imported and now unused.

I confirmed live: 5 back-to-back submits, zero delay between them, all return `200`.
```python
for i in range(5):
    r = client.post('/api/session/submit', ...)
    # all 5: status 200
```

**Impact:** the new per-student **daily** quota (50/day, see the good news below) still catches a sustained spammer, just much later — a script with no delay could burn a student's entire daily allowance in well under a second instead of the ~2.5 minutes the old cooldown enforced, and a burst like that can knock other students onto the lower-quality Gemma fallback for that same minute since it's a shared pool. Not catastrophic given the daily cap exists as a backstop, but worth restoring — it's a one-line fix, the logic already exists in the codebase from before, it's just not being called.

**Fix — add back near the top of `submit_code`, before the expensive work:**
```python
last = state.submit_cooldowns.get(student_id, 0)
if time.time() - last < SUBMIT_COOLDOWN_SECONDS:
    raise HTTPException(status_code=429, detail=f"Please wait {SUBMIT_COOLDOWN_SECONDS - (time.time()-last):.1f}s before requesting guidance again.")
```
If you want the "clock starts after they've read the hint" behavior specifically, keep the stamp where it is now (at completion) — just add the check back at the entry point too. Both can coexist.

---

## 🔴 2. New raw-SQL admin endpoint — know what you're carrying

`POST /admin/sql` executes **any SQL text you send it** against the live database — no allowlist, no read-only restriction, no confirmation step. Gated by `verify_admin` only, same as everything else.

To be clear about what this is and isn't: it's not reachable by students, and `verify_admin` itself is solid (fail-closed secret, real lockout, Cloudflare IP validated since Round 5). This isn't a "someone will exploit this" finding. It's a **blast-radius** finding: every other admin action in this app — even the scary-sounding ones (delete a student, bulk-reset passwords) — is at worst reversible or scoped. This one is `rm -rf` for your database. If your admin secret is ever guessed, phished, or read out of `localStorage` via some future XSS, the attacker doesn't get "read access to the roster" anymore, they get **the whole database**, including the ability to drop it. And the more mundane risk: a mistyped `WHERE` clause on a `DELETE` or `UPDATE`, run by *you*, during a live class, with no undo.

You now also have the machinery to make this much safer for basically free, since it's in the same commit:
- **Block destructive statements by default.** Reject anything that isn't `SELECT`/`PRAGMA`/`EXPLAIN` unless a second field (e.g. `"confirm": true`) is explicitly set — turns "oops" into "you'd have had to mean it."
- **Auto-backup before any write.** You already have `create_local_hot_backup()` sitting right there — call it at the top of `execute_sql` whenever the statement isn't a `SELECT`. Costs nothing, means the worst case becomes "restore from 30 seconds ago" instead of "gone."

Your call whether to keep it as a convenience console — just make sure it's a deliberate choice, not an oversight, given what it's actually capable of.

---

## 🟡 3. Backup restore has no recency check — real risk on this specific setup

`sync_from_github_on_startup()` and `sync_from_peer_host()` both download a backup and restore it if the file passes an integrity check — **neither compares timestamps against the current local database first.** In the clean case (server shuts down gracefully → `backup_to_github()` fires on the `shutdown` event → next startup restores that exact snapshot) this is fine, no gap. The risk is the *unclean* case: a crash, a forced kill, a power cycle, a laptop sleeping mid-session — none of those trigger the shutdown hook, so the next startup silently restores whatever the *last graceful shutdown* backed up, discarding everything since. On a personal computer running live in a classroom, "ungraceful restart" isn't a rare edge case — it's a normal Tuesday.

**Worth adding:** compare a timestamp (or row-count / `MAX(id)` across `submissions`) between local and remote before deciding to overwrite, and only restore if remote is genuinely newer. Also worth an interval-based backup (every 10–15 min) rather than relying solely on the shutdown hook firing — cheap insurance against exactly the scenario that makes the current design's assumption (clean shutdown) not hold.

---

## 🟡 4. `seed_production_students.py` will crash on a fresh install

It does `import openpyxl`, but `openpyxl` isn't in `requirements.txt` — I checked the diff, only a trailing-newline fix was made to that file this round. It happens to be importable in my test environment because something *else* pulled it in as a transitive dependency; on an actual fresh `pip install -r requirements.txt`, this script fails immediately with `ModuleNotFoundError`. This is the script that enrolls your real 183 students — worth catching before you need to run it under time pressure. One-line fix: add `openpyxl` to `requirements.txt`.

(Good news while I was in there: the attendance spreadsheet itself was never committed to the repo — `*.xlsx` is properly gitignored. No student PII exposure from this.)

---

## ✅ Confirmed Good

- **Per-student daily guidance quota is now real** (default 50/day, admin-configurable globally and per-student, properly persisted in a `system_config` / `student_rate_limits` DB table — not just in-memory, survives restarts). This closes the H3 finding I've flagged since Round 3.
- **Every one of the 36 new admin endpoints is gated by `verify_admin`** — I checked each one individually (a naive grep flagged 6 false positives from multi-line function signatures; all 6 turned out to have the dependency correctly, just on a later line).
- **GitHub backup implementation itself is solid**: uses SQLite's real online-backup API (`conn.backup()`, safe on a live, actively-written DB), integrity-checks every downloaded file before trusting it, prunes old local backups, never puts the token anywhere but an outbound `Authorization` header.
- **`ADMIN_SECRET` is sent to `HOST_SERVER_URL` for peer-sync** — only relevant if you're running the two-machine host/laptop setup implied by this feature; make sure that URL is `https://` if you use it, since nothing in the code enforces that and the secret would otherwise cross the network in plaintext.

---

## Updated Go-Live Checklist

| # | Item | Blocks launch? |
|---|---|---|
| 1 | Restore the submit cooldown check | Recommended — daily cap is a real backstop now, so this is lower-stakes than it would've been a round ago, but still a quick fix |
| 2 | Add `openpyxl` to `requirements.txt` | Yes, if you ever re-run the enrollment script on a clean environment |
| 3 | Decide on raw-SQL guardrails (block destructive, or auto-backup-before-write) | Your call, but go in with eyes open |
| 4 | Recency check on backup restore | Recommended, especially given this is a personal computer, not managed infra with graceful drains |

Nothing here is student-facing in the sense of "a student will see an error." The regression and the design questions are all in your direction — which, given 183 real students are about to depend on this, is exactly where you want the remaining risk concentrated.
