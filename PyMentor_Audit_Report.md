# PyMentor — Audit Round 4 (Bug-Focused)

**HEAD unchanged since Round 3** (`3c1bcf0`, no new commits). All Round 3 findings still stand as reported — this round is scoped to the two things you flagged: the dashboard-refresh bug and the online-students section, plus whatever else turned up while tracing them.

---

## 1. Bug: "Dashboard not updated automatically after solving a problem"

**Root cause found — it's the student-facing problems list, not the admin dashboard.**

`problems.js` fetches `/api/student/progress` exactly once, on `DOMContentLoaded` (line 111-120), and builds `progressMap` from that single snapshot. There is no `pageshow` listener and no re-fetch trigger anywhere else in the file.

Sequence that reproduces it:
1. Student opens `/problems`, sees a problem as "Not Started"/"Attempted".
2. Clicks into it, solves it (the practice page itself updates correctly in real time — confirmed: `app.js` flips the status pill, stops the timer, and fires confetti the moment `is_correct` comes back true).
3. Clicks "← Problems" to go back.
4. If the browser restores the page from **back-forward cache (bfcache)** instead of doing a fresh navigation — which Chrome/Firefox do by default for a plain same-origin `<a href>` navigation — `DOMContentLoaded` never fires again. The page shows exactly the DOM it had *before* the student solved anything. Only a manual hard refresh fixes it.

This is a well-known class of bug (stale JS-rendered state surviving in bfcache) and is browser/session dependent, which is why it can look intermittent — worth confirming on your end, but the code has no defense against it either way, so the fix is worth making regardless of which exact browser path triggers it.

**Fix — `frontend/js/problems.js`:** wrap the progress-loading logic in a named function and re-run it on `pageshow`, not just `DOMContentLoaded`:

```js
// At the top level of problems.js, wrap the existing fetch+render logic:
async function loadProgressAndRender() {
    // ...move the existing "1. Fetch student progress" block (lines ~111-120)
    // and whatever re-renders the topic/problem list here...
}

document.addEventListener('DOMContentLoaded', loadProgressAndRender);

// Add this: covers bfcache restores (back/forward navigation)
window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
        loadProgressAndRender();
    }
});
```
`event.persisted === true` specifically means "this page came from bfcache, not a fresh load" — so this only does extra work on the exact path that's currently broken, with zero cost on normal loads (which already run `DOMContentLoaded`).

---

## 2. Admin Panel — Online Students Section

Reviewed the query, the rendering, and the escaping again specifically for this section. **No bug found — it's solid:**

- The "most recent session per student, only if heartbeat < 120s old" query (`routers/admin.py`) is correctly correlated and returns exactly one row per online student.
- `admin.js` re-renders this table on every poll with no stale-diffing logic, so it does reflect new activity — just not instantly.
- Escaping is consistent with the rest of the dashboard (`escapeHtml()` applied).

**What might read as "not automatic" here, and isn't actually a bug:**
- The dashboard polls every **10 seconds** (`setInterval(fetchDashboardData, 10000)`), so there's up to a 10s lag between a student solving something and the roster/counts reflecting it. A "Refresh Now" button already exists in `admin.html` for anyone who doesn't want to wait.
- Online status has an inherent **120-second tail**: a student who solves a problem and immediately closes the tab still shows "online, working on X" for up to 2 minutes, because that's how long the heartbeat window is before they're considered gone. This is a deliberate trade-off (heartbeat interval is 15s, grace window is 8x that to tolerate a couple of missed beats) — tightening it risks false "offline" flickers on a slow network instead.

If 10s actually feels too slow in practice, the cheap fix is lowering `setInterval(..., 10000)` to `5000` — no other changes needed. Real-time (sub-second) push updates would need Server-Sent Events or a WebSocket, which is a bigger lift — I've put that under "Live Dashboard Updates" in the feature discussion doc as an option rather than assuming you want it.

---

## 3. One More Thing Found While Tracing This: Unused Logo Asset

Not a bug, but worth a two-minute fix. `frontend/favicon.svg` is a genuinely well-made mark (two Python-style snakes, blue/yellow gradient, dark squircle background) — but every page header (`index.html`, `login.html`, `problems.html`) uses a plain 🐍 emoji as `.brand-icon` instead of it. You already have a good logo; it's just not being used anywhere but the browser tab. Concrete fix is in the minor-features implementation file — this is a two-line change per page.
