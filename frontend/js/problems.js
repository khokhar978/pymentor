/**
 * Python Practice — Problems Page (problems.js)
 * Enforces authorized student login (Sections E, F, G; Roll 1-4)
 * Loads topic/problem data and renders card grid.
 */

document.addEventListener('DOMContentLoaded', () => {
    setupStudentUI();
    loadTopics();
});

// ── STUDENT AUTHENTICATION ────────────────────────
function setupStudentUI() {
    const saved = localStorage.getItem('pymentor_student');
    if (saved) {
        try {
            const student = JSON.parse(saved);
            updateStudentDisplay(student);
        } catch (e) {
            openModal(true);
        }
    } else {
        openModal(true);
    }

    document.getElementById('studentBadge')?.addEventListener('click', () => openModal(false));
    document.getElementById('switchStudentBtn')?.addEventListener('click', () => {
        localStorage.removeItem('pymentor_student');
        openModal(true);
    });
    document.getElementById('studentForm')?.addEventListener('submit', onStudentSubmit);
}

function openModal(reset = false) {
    const alertEl = document.getElementById('loginAlert');
    if (alertEl) alertEl.classList.add('hidden');

    if (reset) {
        document.getElementById('studentRollInput').value = '';
        document.getElementById('studentPwdInput').value  = '';
        document.getElementById('studentSecInput').value  = 'E';
    } else {
        const saved = localStorage.getItem('pymentor_student');
        if (saved) {
            try {
                const s = JSON.parse(saved);
                document.getElementById('studentRollInput').value = s.roll_no || '';
                document.getElementById('studentSecInput').value  = s.section || 'E';
                document.getElementById('studentPwdInput').value  = '';
            } catch (e) {}
        }
    }

    document.getElementById('studentModal').classList.remove('hidden');
    setTimeout(() => document.getElementById('studentRollInput').focus(), 150);
}

function showLoginError(msg) {
    const alertEl = document.getElementById('loginAlert');
    if (alertEl) {
        alertEl.textContent = msg;
        alertEl.classList.remove('hidden');
    }
}

function hideLoginError() {
    const alertEl = document.getElementById('loginAlert');
    if (alertEl) alertEl.classList.add('hidden');
}

async function onStudentSubmit(e) {
    e.preventDefault();
    const section = document.getElementById('studentSecInput').value;
    const roll_no = document.getElementById('studentRollInput').value.trim();
    const password = document.getElementById('studentPwdInput').value.trim();
    const submitBtn = document.getElementById('loginSubmitBtn');

    if (!roll_no || !password) {
        showLoginError('Please enter both Roll Number and Password.');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Verifying...';
    hideLoginError();

    try {
        const res = await fetch('/api/student/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section, roll_no, password })
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || 'Login failed. Please check your credentials.');
        }

        localStorage.setItem('pymentor_student', JSON.stringify(data));
        updateStudentDisplay(data);
        document.getElementById('studentModal').classList.add('hidden');
    } catch (err) {
        showLoginError(err.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Log In to Lab';
    }
}

function updateStudentDisplay(student) {
    const nameEl = document.getElementById('studentNameDisplay');
    const secEl  = document.getElementById('studentSecDisplay');
    if (!student) {
        nameEl.textContent = 'Not Logged In';
        secEl.textContent  = 'Login Required';
        return;
    }
    nameEl.textContent = student.name + ` (Roll ${student.roll_no})`;
    secEl.textContent  = 'Sec ' + student.section;
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
