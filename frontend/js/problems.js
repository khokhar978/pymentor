/**
 * Python Practice — Problems Page (problems.js)
 * Displays topic/problem card grid and manages student authentication status.
 */

document.addEventListener('DOMContentLoaded', () => {
    setupStudentUI();
    loadTopics();
});

// ── STUDENT AUTHENTICATION ────────────────────────
function setupStudentUI() {
    const saved = localStorage.getItem('pymentor_student');
    let student = null;

    if (saved) {
        try {
            student = JSON.parse(saved);
        } catch (e) {
            localStorage.removeItem('pymentor_student');
        }
    }

    updateStudentDisplay(student);

    const handleAuthClick = () => {
        if (localStorage.getItem('pymentor_student')) {
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
}

// ── TOPIC & PROBLEM CARDS ───────────────────
async function loadTopics() {
    const container = document.getElementById('topicsContainer');
    try {
        const res  = await fetch('/api/topics');
        const data = await res.json();
        const topics = data.topics || [];

        if (!topics.length) {
            container.innerHTML = '<p style="color:var(--text-faint);">No problems found.</p>';
            return;
        }

        container.innerHTML = '';
        topics.forEach(t => container.appendChild(renderTopicSection(t)));
    } catch (err) {
        container.innerHTML = '<p style="color:var(--error);font-size:13px;">Failed to load: ' + err.message + '</p>';
    }
}

function renderTopicSection(topic) {
    const sec = document.createElement('div');
    sec.className = 'topic-section';
    sec.innerHTML =
        '<div class="topic-header">' +
            '<h2>' + esc(topic.topic) + '</h2>' +
            '<span class="topic-count">' + topic.problems.length + ' problem' + (topic.problems.length !== 1 ? 's' : '') + '</span>' +
        '</div>' +
        '<div class="problems-grid">' +
            topic.problems.map(renderProblemCard).join('') +
        '</div>';
    return sec;
}

function renderProblemCard(p) {
    const diff     = (p.difficulty || 'easy').toLowerCase();
    const concepts = (p.concepts || []).slice(0, 4);
    return (
        '<div class="problem-card">' +
            '<div class="card-top">' +
                '<div class="card-title">' + esc(p.title) + '</div>' +
                '<span class="difficulty-badge ' + diff + '">' + esc(p.difficulty) + '</span>' +
            '</div>' +
            '<div class="card-concepts">' +
                concepts.map(c => '<span class="concept-tag">' + esc(c) + '</span>').join('') +
            '</div>' +
            '<div class="card-action">' +
                '<a href="/practice?problem=' + p.id + '" class="btn-practice">Start Practice &rarr;</a>' +
            '</div>' +
        '</div>'
    );
}

function esc(str) {
    return String(str)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
