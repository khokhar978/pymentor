# PyMentor — Re-Audit (Round 3)

Pulled the repo twice during this pass — once at commit `admin telemetry dashboard...` and again at the latest, `Fix missing FileResponse/RedirectResponse imports and add resilient fallback imports` — to make sure I was reviewing what's actually live. This was a big round: an admin dashboard was added, and a lot of the "still open" list from Round 2 got closed, including some things I hadn't even asked for yet.

## Scoreboard

| Severity | Fixed | Open (deferred by you) | Open (new/other) |
|---|---|---|---|
| Critical | 3 / 4 | 1 (AI grading trust — deferred) | — |
| High | 3 / 4 | — | 1 (Cloudflare Access — can't verify from code) |
| Medium | 3 / 4 | — | 1 (partial — per-student quota cap) |
| Low | 4 / 5 | — | 1 (logging bug, see below) |

Everything that's still open is either something you explicitly said you're leaving for later (the AI prompt/trust work), or something I genuinely can't verify by reading code (whether Cloudflare Access is actually configured). Nothing security-critical is sitting unaddressed by accident anymore.

---

## 🎯 The most important thing to know about first

**A real data bug got fixed, and it's worth understanding what it was.** In the previous version, `submit_code()` — the endpoint that saves a student's submission and grades it — inserted the submission row and updated the session's status, but never called `conn.commit()` before closing the connection. In Python's `sqlite3` module, an uncommitted write transaction is rolled back on close. That means, as of the version I reviewed last time, **submissions may not have actually been persisting to the database** — the request would still return a normal success response to the student (since the in-memory transaction looked fine until close), but the database itself likely wasn't recording it. The new commit adds the missing `conn.commit()`, and it's now correct.

I'm flagging this clearly for two reasons: first, it's fixed, so no action needed — but second, if you have any submission data from testing done *before* this fix, don't be surprised if it's missing or incomplete in the database. Worth a quick sanity check: pull up `/admin` and see if the submission counts roughly match what you remember testers actually doing.

---

## ✅ What's newly fixed this round

**C1 — `/api/config/key` unauthenticated → Fully closed, and better than asked.** Beyond just gating it: `ADMIN_SECRET` now has no usable default — if it's unset or still the placeholder value, the app refuses to start with a loud critical error, exactly mirroring the bcrypt fail-closed pattern from Round 2. The comparison itself now uses `secrets.compare_digest` (constant-time), and there's a per-IP lockout (5 failed attempts → 15 minutes) on admin auth specifically. This is a genuinely thorough fix.

**H2 — No login rate limiting → Fixed**, exactly as planned: 5 failed attempts on a roll+section locks it for 5 minutes, with periodic cleanup of stale entries so the in-memory dict doesn't grow forever.

**M1 — CORS wildcard → Fully fixed, not just patched.** `allow_origins` is now a real allow-list (localhost/loopback by default, configurable via `ALLOWED_ORIGINS`), plus a sensible regex covering private LAN IPs and your actual tunnel providers (Cloudflare quick tunnels, ngrok, localtunnel). `allow_methods`/`allow_headers` are scoped down to what the app actually uses instead of `*`. This is more careful than the minimum I suggested.

**The default-password problem is now actually enforced, not just suggested.** Round 2 added a client-side redirect nudge; this round adds a server-side `require_password_changed` dependency on every practice endpoint (`session/start`, `save`, `heartbeat`, `submit`) that returns `403` until the password is changed — so a student can't just ignore the frontend redirect and hit the API directly. Password change also now revokes all of that student's existing tokens, so an old leaked token stops working the moment the password changes.

**Token lifecycle is now complete:** 7-day expiry (added Round 2), a working `/api/auth/logout`, automatic revocation on password change (new), and opportunistic cleanup of expired tokens from the table (new) — nothing left half-done here.

**M3 — shared AI quota → Partially fixed.** A 3-second cooldown between submissions per student caps burst spam (previously someone could hammer the endpoint as fast as the network allowed). It doesn't cap total daily usage per student, so a determined student submitting once every 3 seconds for an hour could still eat a large share of the quota — but the worst-case abuse is now bounded rather than unlimited.

**Malformed-header crash → Fixed** (`len(parts) != 2` check before indexing).

**Dead code removed, which is itself a security improvement:** `/api/session/run` and its `simulate_run()` AI call were deleted entirely — it was unused (Pyodide does real execution client-side), so removing it shrinks the attack surface and stops it silently burning AI quota for no reason.

**Input size limits added:** submission code and simulated-output fields now have `max_length` caps — small thing, but it closes off a cheap way to bloat the database or blow up prompt size.

**Dependency cleanup:** `passlib` was dropped since only raw `bcrypt` is actually used; `marked.js` is now version-pinned instead of pulling `@latest`, which avoids the app silently breaking if that library ships a breaking change. A proper `.env.example` and `README.md` were also added — good for anyone (including future you) setting this up fresh.

---

## 🆕 The admin dashboard itself — review

This is a new, fairly substantial feature, so it got a full pass on its own. **Good news: it's well built.** Specifically:
- Every data-bearing endpoint (`/api/admin/dashboard`, `/api/admin/student/{id}`) is properly gated behind the same hardened `verify_admin` check.
- The frontend renders every piece of server-sourced text (student names, problem titles, model names, event types, event data) through a proper `escapeHtml()` before inserting it into the DOM — I specifically checked this because the telemetry event endpoint accepts free-form `event_type`/`event_data` from any logged-in student with no server-side sanitization, which would otherwise be a textbook stored-XSS-into-the-admin-panel setup. It isn't, because the rendering side handles it correctly and consistently everywhere I checked.
- One residual, low-severity gap: `/api/telemetry/event` doesn't verify that the `session_id`/`problem_id` a student sends actually belongs to them, so a student could tag events with fabricated IDs. Since the escaping is solid, this is a data-integrity nuisance (could pollute your analytics) rather than a security hole — worth a light validation pass whenever you're back in this area, not urgent.

---

## ❌ Still open

**C3 — AI grading trust boundary.** Untouched, as agreed — `ai_mentor.py`'s only change this round was removing the dead `simulate_run()` function.

**H4 — Cloudflare Access / tunnel restriction.** Can't verify from the repo. If you haven't set this up yet, it's still your best remaining return-on-effort item.

**M3 — no per-student daily quota cap** (only burst-rate limited now, see above).

**Low — the `logs.txt` file handler still doesn't actually work.** This is the one I flagged last round and it's still there: `ai_mentor.py` calls `logging.basicConfig(level=logging.INFO)` at import time, and since `main.py` imports from `ai_mentor` *before* it runs its own `logging.basicConfig(..., handlers=[FileHandler, StreamHandler])`, Python's `basicConfig()` treats the second call as a no-op (it only takes effect if the root logger has no handlers yet). I confirmed this behavior directly by reproducing the exact import order in a standalone test — the file gets created but never receives any log records. One-line fix: delete the `logging.basicConfig(level=logging.INFO)` line from `ai_mentor.py` entirely (main.py's setup already covers the whole app once it's the only one configuring the root logger).

---

## 🆕 New, minor things worth knowing about

1. **Same "silent fallback" pattern, this time on the frontend.** AI feedback is rendered via `marked.parse()` then `DOMPurify.sanitize()` — good — but if DOMPurify fails to load (CDN blocked, network hiccup), the code falls back to inserting the *unsanitized* parsed markdown directly. Given the AI's response text is influenced by the grading prompt (and you already know that trust boundary isn't hardened yet), this is the same category of issue as the old bcrypt fallback: quietly correct until the one time the dependency isn't there, then quietly insecure. Suggest: if `DOMPurify` isn't available, show a plain-text fallback instead of raw HTML — fail safe, not silent.
2. **Migration edge case on `needs_password_change`.** The new column defaults to `1` for *all* existing rows when the `ALTER TABLE` runs — including any students who, during your earlier testing, already changed their password away from `123`. They'll get incorrectly forced through the "change your password" flow again once. Harmless, but a one-time cleanup query (`UPDATE students SET needs_password_change = 0 WHERE password does not verify against '123'`) would avoid the false positive.
3. **Login lockout is still keyed by roll+section, not IP.** This closes brute-forcing (good), but means anyone — not just an attacker who knows a password — can lock a specific real student out of their own account for 5 minutes just by sending 5 bad logins for their roll/section. This is a common, generally-accepted trade-off in small systems like this (most real login systems have the same tension), so I wouldn't prioritize fixing it, just flagging that it exists.
4. **Minor:** the new README's clone command points to `github.com/Pawan978/pymentor` rather than this repo's actual URL — just a copy-paste leftover, worth a quick fix so it's not confusing for anyone else who reads it.
5. **Minor:** the CORS regex allows *any* subdomain of `trycloudflare.com`/`ngrok-free.app`/`loca.lt`, not just yours specifically — since you're not using cookies, the practical risk is low, but if you want it tighter later, it's an easy one-line narrowing once you know your exact tunnel hostname.

---

## Updated implementation plan (what's actually left)

1. Delete the redundant `logging.basicConfig(level=logging.INFO)` line from `ai_mentor.py` so `logs.txt` actually starts receiving log entries.
2. Give `DOMPurify`'s failure path a safe fallback (plain text) instead of raw HTML.
3. Run the one-time `needs_password_change` backfill for students who already changed their password before this update.
4. Confirm Cloudflare Access is actually in front of the tunnel — if not, it's still the single highest-leverage thing left on the whole list.
5. Whenever you're back in `ai_mentor.py`/`main.py` for the prompt work: add the `session_id`/`problem_id` ownership check on `/api/telemetry/event`, and consider a per-student daily submission cap alongside whatever quota work you do there.

That's genuinely a short list. The core security posture of this app — auth, authorization, password handling, admin access, CORS, input limits — is in solid shape now.
