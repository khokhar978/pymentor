/**
 * Shared Practice Streak Module (streak.js)
 * Automatically injects and synchronizes the active fire streak badge across all pages.
 */

import { getCurrentStudent } from './auth.js';
import { apiFetch } from './api.js';

let _cachedStreak = null;

export function updateNavbarStreakBadge(streak) {
    if (!streak) return;
    _cachedStreak = streak;

    let badge = document.getElementById('streakBadge');
    if (!badge) {
        badge = document.createElement('div');
        badge.id = 'streakBadge';
        badge.className = 'streak-badge';

        const studentBadge = document.getElementById('studentBadge');
        const header = document.querySelector('.site-header') || (studentBadge ? studentBadge.parentNode : null);
        if (header && studentBadge) {
            header.insertBefore(badge, studentBadge);
        } else if (header) {
            header.appendChild(badge);
        }
    }

    const count = streak.current_streak || 0;
    const isSolvedToday = Boolean(streak.solved_today);

    if (count > 0) {
        badge.className = isSolvedToday ? 'streak-badge active-streak solved-today' : 'streak-badge active-streak';
        badge.innerHTML = `
            <span class="streak-fire" aria-hidden="true">🔥</span>
            <span class="streak-count">${count}</span>
        `;
    } else {
        badge.className = 'streak-badge zero-streak';
        badge.innerHTML = `
            <span class="streak-ice" aria-hidden="true">❄️</span>
            <span class="streak-count">0</span>
        `;
    }

    badge.title = streak.message || (count > 0 ? `${count}-day solve streak!` : 'Solve a problem today to ignite your streak!');

    try {
        localStorage.setItem('pymentor_streak_cache', JSON.stringify(streak));
    } catch (_) {}
}

export async function initNavbarStreak() {
    const student = getCurrentStudent();
    if (!student || !student.token) return;

    // Fast render from localStorage cache if available
    try {
        const cached = JSON.parse(localStorage.getItem('pymentor_streak_cache') || 'null');
        if (cached && typeof cached.current_streak === 'number') {
            updateNavbarStreakBadge(cached);
        }
    } catch (_) {}

    // Fetch live streak from backend
    try {
        const res = await apiFetch('/api/student/streak');
        if (res.ok) {
            const data = await res.json();
            updateNavbarStreakBadge(data);
        }
    } catch (_) {
        // Fall back gracefully
    }
}
