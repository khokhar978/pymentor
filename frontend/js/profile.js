/**
 * Python Practice — Profile Page (profile.js)
 * Displays student stats, topic mastery, and handles password changes/logout.
 */

document.addEventListener('DOMContentLoaded', () => {
    const studentData = localStorage.getItem('pymentor_student');
    if (!studentData) {
        window.location.href = '/login?next=/profile';
        return;
    }

    const student = JSON.parse(studentData);
    
    // Set Header UI
    document.getElementById('navNameDisplay').textContent = student.name;
    document.getElementById('navSecDisplay').textContent = 'Sec ' + student.section;
    document.getElementById('headerName').textContent = student.name;
    document.getElementById('headerRoll').textContent = `Roll: ${student.roll_no} | Sec: ${student.section}`;

    // Setup Logout
    document.getElementById('logoutBtn').addEventListener('click', () => {
        localStorage.removeItem('pymentor_student');
        window.location.href = '/login';
    });

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
                localStorage.removeItem('pymentor_student');
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
        document.getElementById('loadingOverlay').style.display = 'none';
    }
}

function renderStats(data) {
    document.getElementById('statCompleted').textContent = data.stats.completed_problems;
    document.getElementById('statAttempts').textContent = data.stats.total_attempts;
    document.getElementById('statSessions').textContent = data.stats.total_sessions;
    
    let rate = 0;
    if (data.stats.total_sessions > 0) {
        rate = Math.round((data.stats.completed_problems / data.stats.total_sessions) * 100);
    }
    document.getElementById('statRate').textContent = `${rate}%`;
}

function renderTopicMastery(mastery) {
    const container = document.getElementById('topicMasteryContainer');
    if (!mastery || mastery.length === 0) return;

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
        const date = new Date(act.updated_at);
        const timeStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
    const alertBox = document.getElementById('pwdAlert');
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
        
        showAlert('Password successfully updated!', 'success');
        document.getElementById('pwdForm').reset();
        
    } catch (err) {
        showAlert(err.message, 'error');
    } finally {
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

function esc(str) {
    return String(str)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
