/**
 * Python Practice — Problems Page (problems.js)
 * Collapsible accordion topics with per-topic progress and per-question status markers.
 * Displays time elapsed for attempted questions and time taken for solved questions.
 */

import { getCurrentStudent } from './shared/auth.js';
import { formatDuration, escapeHtml as esc } from './shared/utils.js';

let progressMap = {};       // { [problem_id]: { status, time_spent_seconds } }
let allTopicsData = [];     // Array of topic objects
let areAllExpanded = false; // Toggle all state

document.addEventListener('DOMContentLoaded', () => {
    setupStudentUI();
    setupToggleAll();
    loadAll();
});

// ── STUDENT AUTHENTICATION ────────────────────────
function setupStudentUI() {
    const student = getCurrentStudent();
    updateStudentDisplay(student);

    const handleAuthClick = () => {
        if (getCurrentStudent()) {
            window.location.href = '/profile';
        } else {
            window.location.href = '/login';
        }
    };

    const studentBadge = document.getElementById('studentBadge');
    if (studentBadge) studentBadge.addEventListener('click', handleAuthClick);

    const switchStudentBtn = document.getElementById('switchStudentBtn');
    if (switchStudentBtn) switchStudentBtn.addEventListener('click', handleAuthClick);
}

function updateStudentDisplay(student) {
    const nameEl = document.getElementById('studentNameDisplay');
    const secEl  = document.getElementById('studentSecDisplay');
    const btnEl  = document.getElementById('switchStudentBtn');

    if (!student || !student.name) {
        if (nameEl) nameEl.textContent = 'Not Logged In';
        if (secEl)  secEl.textContent  = 'Click to Log In';
        if (btnEl)  btnEl.textContent  = 'Log In';
        return;
    }

    if (nameEl) nameEl.textContent = student.name + ` (Roll ${student.roll_no})`;
    if (secEl)  secEl.textContent  = 'Sec ' + student.section;
    if (btnEl)  btnEl.textContent  = 'Profile';

    if (student.needs_password_change) {
        let banner = document.getElementById('pwdWarningBanner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'pwdWarningBanner';
            banner.style.cssText = 'background:#fef3c7;border:1px solid #fde68a;color:#92400e;padding:12px 16px;border-radius:8px;font-size:13.5px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;gap:12px;';
            banner.innerHTML = `
                <span>⚠️ <strong>Security Notice:</strong> You are currently using the default password. Please change your password to secure your account.</span>
                <a href="/profile?force_change=1" style="background:#d97706;color:#fff;padding:6px 14px;border-radius:6px;text-decoration:none;font-weight:600;font-size:12.5px;white-space:nowrap;">Change Password &rarr;</a>
            `;
            const hero = document.querySelector('.page-hero');
            if (hero && hero.parentNode) {
                hero.parentNode.insertBefore(banner, hero.nextSibling);
            }
        }
    }
}

// ── EXPAND / COLLAPSE ALL ─────────────────────────
function setupToggleAll() {
    const btn  = document.getElementById('toggleAllBtn');
    const icon = document.getElementById('toggleAllIcon');
    const text = document.getElementById('toggleAllText');
    if (!btn) return;

    btn.addEventListener('click', () => {
        areAllExpanded = !areAllExpanded;
        if (text) text.textContent = areAllExpanded ? 'Collapse All' : 'Expand All';
        if (icon) icon.textContent = areAllExpanded ? '▴' : '▾';

        const accordions = document.querySelectorAll('.topic-accordion');
        accordions.forEach(acc => {
            const header = acc.querySelector('.accordion-header');
            const body   = acc.querySelector('.accordion-body');
            if (header && body) {
                if (areAllExpanded) {
                    acc.classList.add('open');
                    header.classList.add('open');
                    header.setAttribute('aria-expanded', 'true');
                    body.classList.add('open');
                } else {
                    acc.classList.remove('open');
                    header.classList.remove('open');
                    header.setAttribute('aria-expanded', 'false');
                    body.classList.remove('open');
                }
            }
        });
    });
}

// ── LOAD TOPICS + PROGRESS ────────────────────────
async function loadAll() {
    const container = document.getElementById('topicsContainer');

    // 1. Fetch student progress if authenticated
    const student = getCurrentStudent();
    if (student && student.token) {
        try {
            const progRes = await fetch('/api/student/progress', {
                headers: { 'Authorization': 'Bearer ' + student.token }
            });
            if (progRes.ok) {
                const progData = await progRes.json();
                progressMap = progData.progress || {};
            }
        } catch (_) {
            // Unauthenticated or network error — gracefully fallback
        }
    }

    // 2. Fetch topics
    try {
        const res = await fetch('/api/topics');
        const data = await res.json();
        allTopicsData = data.topics || [];

        if (!allTopicsData.length) {
            container.innerHTML = '<p style="color:var(--text-faint); padding: 20px;">No problems found.</p>';
            return;
        }

        // 3. Render accordion list
        container.innerHTML = '';
        allTopicsData.forEach((t, idx) => {
            container.appendChild(renderTopicAccordion(t, idx));
        });
    } catch (err) {
        container.innerHTML = '<p style="color:var(--error);font-size:13px; padding: 20px;">Failed to load problems: ' + esc(err.message) + '</p>';
    }
}

// ── TOPIC ACCORDION COMPONENT ─────────────────────
function renderTopicAccordion(topic, idx) {
    const wrapper = document.createElement('div');
    wrapper.className = 'topic-accordion';
    wrapper.id = 'accordion-' + idx;

    const problems = topic.problems || [];
    let solved = 0;
    let attempted = 0;
    let topicTimeSpent = 0;

    problems.forEach(p => {
        const prog = progressMap[p.id];
        const st = (typeof prog === 'object' && prog !== null ? prog.status : prog) || 'not_started';
        const timeSec = (typeof prog === 'object' && prog !== null ? prog.time_spent_seconds : 0) || 0;
        topicTimeSpent += timeSec;

        if (st === 'solved') solved++;
        else if (st === 'attempted') attempted++;
    });

    const total = problems.length;
    const pct = total > 0 ? Math.round((solved / total) * 100) : 0;

    // Determine status class
    let statusClass = 'not-started';
    let badgeHtml = `<span class="topic-status-badge not-started">0%</span>`;

    if (total > 0 && solved === total) {
        statusClass = 'complete';
        badgeHtml = `<span class="topic-status-badge complete">✓ Completed</span>`;
    } else if (solved > 0 || attempted > 0) {
        statusClass = 'in-progress';
        badgeHtml = `<span class="topic-status-badge in-progress">${pct}%</span>`;
    }

    const topicTimeHtml = topicTimeSpent > 0
        ? `<span class="topic-time-label" title="Total active practice time on this topic">⏱ ${formatDuration(topicTimeSpent)}</span>`
        : '';

    // ── Header (Topic summary, progress bar) ──
    const header = document.createElement('div');
    header.className = 'accordion-header';
    header.setAttribute('role', 'button');
    header.setAttribute('aria-expanded', 'false');
    header.setAttribute('tabindex', '0');
    header.setAttribute('aria-controls', 'body-' + idx);

    header.innerHTML = `
        <div class="accordion-left">
            <span class="accordion-chevron">▶</span>
            <div class="accordion-topic-title-group">
                <span class="accordion-topic-name">${esc(topic.topic)}</span>
                <span class="topic-count-pill">${total} problem${total !== 1 ? 's' : ''}</span>
            </div>
        </div>
        <div class="accordion-right">
            ${topicTimeHtml}
            <div class="topic-stats-wrapper">
                <span class="topic-progress-label">${solved}/${total} Solved</span>
                <div class="topic-progress-bar" title="${pct}% completed">
                    <div class="topic-progress-fill ${statusClass}" style="width: ${pct}%"></div>
                </div>
            </div>
            ${badgeHtml}
        </div>
    `;

    // ── Body (Questions list — Collapsed by default) ──
    const body = document.createElement('div');
    body.className = 'accordion-body';
    body.id = 'body-' + idx;

    problems.forEach(p => {
        body.appendChild(renderProblemRow(p));
    });

    // ── Toggle action ──
    const toggleAccordion = () => {
        const isOpen = wrapper.classList.toggle('open');
        header.classList.toggle('open', isOpen);
        header.setAttribute('aria-expanded', String(isOpen));
        body.classList.toggle('open', isOpen);
    };

    header.addEventListener('click', toggleAccordion);
    header.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggleAccordion();
        }
    });

    wrapper.appendChild(header);
    wrapper.appendChild(body);
    return wrapper;
}

// ── PROBLEM ROW COMPONENT ─────────────────────────
function renderProblemRow(p) {
    const diff   = (p.difficulty || 'easy').toLowerCase();
    const prog   = progressMap[p.id];
    const status = (typeof prog === 'object' && prog !== null ? prog.status : prog) || 'not_started';
    const timeSec = (typeof prog === 'object' && prog !== null ? prog.time_spent_seconds : 0) || 0;
    const concepts = (p.concepts || []).slice(0, 3);

    const row = document.createElement('div');
    row.className = 'problem-row';

    const { icon, pillLabel, pillCls, btnLabel, btnCls } = getProblemStatusMeta(status);

    let timeBadgeHtml = '';
    if (timeSec > 0) {
        if (status === 'solved') {
            timeBadgeHtml = `<span class="problem-time-badge solved" title="Time taken to solve">⏱ ${formatDuration(timeSec)}</span>`;
        } else if (status === 'attempted') {
            timeBadgeHtml = `<span class="problem-time-badge attempted" title="Time elapsed so far">⏱ ${formatDuration(timeSec)} elapsed</span>`;
        }
    }

    row.innerHTML = `
        <div class="problem-row-left">
            <span class="problem-status-icon ${pillCls}" title="${pillLabel}">${icon}</span>
            <div class="problem-row-info">
                <span class="problem-row-title">${esc(p.title)}</span>
                <div class="problem-row-meta">
                    <span class="difficulty-badge ${diff}">${esc(p.difficulty)}</span>
                    ${concepts.map(c => `<span class="concept-tag">${esc(c)}</span>`).join('')}
                </div>
            </div>
        </div>
        <div class="problem-row-right">
            ${timeBadgeHtml}
            <span class="problem-status-pill ${pillCls}">${pillLabel}</span>
            <a href="/practice?problem=${p.id}" class="btn-practice ${btnCls}">${btnLabel}</a>
        </div>
    `;

    return row;
}

function getProblemStatusMeta(status) {
    switch (status) {
        case 'solved':
            return {
                icon: '✓',
                pillLabel: '✓ Solved',
                pillCls: 'status-solved',
                btnLabel: 'Review →',
                btnCls: 'solved-btn'
            };
        case 'attempted':
            return {
                icon: '◐',
                pillLabel: '◐ Attempted',
                pillCls: 'status-attempted',
                btnLabel: 'Continue →',
                btnCls: ''
            };
        default:
            return {
                icon: '○',
                pillLabel: 'Not Started',
                pillCls: 'status-not-started',
                btnLabel: 'Start Practice →',
                btnCls: ''
            };
    }
}
