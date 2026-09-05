/**
 * Python Practice — Profile Page (profile.js)
 * Displays student stats, topic mastery, and handles password changes/logout.
 */

import { requireAuth, clearAuth } from './shared/auth.js';
import { escapeHtml as esc, formatLocalDateTime } from './shared/utils.js';

document.addEventListener('DOMContentLoaded', () => {
    const student = requireAuth('/login');
    if (!student) return;

    // Set Header UI
    document.getElementById('navNameDisplay').textContent = student.name;
    document.getElementById('navSecDisplay').textContent = 'Sec ' + student.section;
    document.getElementById('headerName').textContent = student.name;
    document.getElementById('headerRoll').textContent = `Roll: ${student.roll_no} | Sec: ${student.section}`;

    // Setup Logout
    document.getElementById('logoutBtn').addEventListener('click', async () => {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${student.token}` }
            });
        } catch (e) {
            console.error('Logout failed:', e);
        }
        clearAuth();
        window.location.href = '/login';
    });

    // Check force_change
    const params = new URLSearchParams(window.location.search);
    if (params.get('force_change') === '1') {
        showAlert('Please change your default password immediately to secure your account.', 'error');
        document.getElementById('currentPwd').focus();
    }

    // Setup Password Form
    const pwdForm = document.getElementById('pwdForm');
    pwdForm.addEventListener('submit', (e) => handlePasswordChange(e, student.token));

    // Fetch Profile Data
    fetchProfileData(student.token);
});

async function fetchProfileData(token) {
    try {
        const res = await fetch('/api/student/profile', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!res.ok) {
            if (res.status === 401 || res.status === 403) {
                // Token invalid or expired
                clearAuth();
                window.location.href = '/login?next=/profile';
                return;
            }
            throw new Error('Failed to load profile data');
        }

        const data = await res.json();
        renderStats(data);
        renderTopicMastery(data.topic_mastery);
        renderActivity(data.activity_history);

    } catch (err) {
        console.error('Error fetching profile:', err);
    } finally {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) overlay.style.display = 'none';
    }
}

function renderStats(data) {
    if (!data || !data.stats) return;
    const statCompleted = document.getElementById('statCompleted');
    const statAttempts = document.getElementById('statAttempts');
    const statSessions = document.getElementById('statSessions');
    const statRate = document.getElementById('statRate');

    if (statCompleted) statCompleted.textContent = data.stats.completed_problems ?? 0;
    if (statAttempts) statAttempts.textContent = data.stats.total_attempts ?? 0;
    if (statSessions) statSessions.textContent = data.stats.total_sessions ?? 0;

    let rate = 0;
    if (data.stats.total_sessions > 0) {
        rate = Math.round((data.stats.completed_problems / data.stats.total_sessions) * 100);
    }
    if (statRate) statRate.textContent = `${rate}%`;
}

function renderTopicMastery(mastery) {
    const container = document.getElementById('topicMasteryContainer');
    if (!container) return;
    if (!mastery || mastery.length === 0) {
        container.innerHTML = '<p style="color:var(--text-faint); font-size: 13px;">No topic data yet.</p>';
        return;
    }

    container.innerHTML = '';
    mastery.forEach(topic => {
        let percent = 0;
        if (topic.total > 0) {
            percent = Math.round((topic.completed / topic.total) * 100);
        }

        const html = `
            <div class="topic-mastery">
                <div class="topic-mastery-header">
                    <span class="topic-mastery-name">${esc(topic.topic)}</span>
                    <span class="topic-mastery-score">${topic.completed}/${topic.total} Solved</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" style="width: ${percent}%"></div>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', html);
    });
}

function renderActivity(activities) {
    const list = document.getElementById('activityList');
    if (!activities || activities.length === 0) return;

    list.innerHTML = '';
    activities.forEach(act => {
        const timeStr = formatLocalDateTime(act.updated_at);
        const badgeClass = act.is_solved ? 'solved' : 'progress';
        const badgeText = act.is_solved ? 'Solved' : 'In Progress';

        const html = `
            <li class="activity-item">
                <div class="activity-info">
                    <span class="activity-title">${esc(act.problem_title)}</span>
                    <span class="activity-time">${timeStr} &bull; ${act.attempts_count} attempt${act.attempts_count !== 1 ? 's' : ''}</span>
                </div>
                <span class="activity-badge ${badgeClass}">${badgeText}</span>
            </li>
        `;
        list.insertAdjacentHTML('beforeend', html);
    });
}

async function handlePasswordChange(e, token) {
    e.preventDefault();

    const currentPwd = document.getElementById('currentPwd').value;
    const newPwd = document.getElementById('newPwd').value;
    const confirmPwd = document.getElementById('confirmPwd').value;
    const submitBtn = document.getElementById('pwdSubmitBtn');

    if (newPwd !== confirmPwd) {
        showAlert('New passwords do not match.', 'error');
        return;
    }
    if (newPwd.length < 6) {
        showAlert('New password must be at least 6 characters.', 'error');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Updating...';

    try {
        const res = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                current_password: currentPwd,
                new_password: newPwd
            })
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || 'Failed to change password.');
        }

        showAlert('Password updated successfully! Redirecting to login...', 'success');
        document.getElementById('pwdForm').reset();

        // Clear stored token since backend revoked all active sessions
        clearAuth();

        setTimeout(() => {
            window.location.href = '/login?msg=password_updated';
        }, 1200);

    } catch (err) {
        showAlert(err.message, 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Update Password';
    }
}

function showAlert(msg, type) {
    const alertBox = document.getElementById('pwdAlert');
    alertBox.textContent = msg;
    alertBox.classList.remove('hidden');

    if (type === 'error') {
        alertBox.style.background = 'var(--error-bg)';
        alertBox.style.color = 'var(--error)';
        alertBox.style.border = '1px solid #fecaca';
    } else {
        alertBox.style.background = 'rgba(16, 185, 129, 0.1)';
        alertBox.style.color = '#10b981';
        alertBox.style.border = '1px solid rgba(16, 185, 129, 0.3)';
    }

    setTimeout(() => {
        alertBox.classList.add('hidden');
    }, 5000);
}
