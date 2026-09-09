/**
 * PyMentor Admin Portal Modular Controller
 * Multi-View SPA router, Problem Studio, Student Accounts, Live Lab, Exports & Telemetry
 */

import {
    escapeHtml,
    formatDuration,
    formatLocalTime,
    formatLocalDateTime,
    formatLocalDateOnly
} from './shared/utils.js';

document.addEventListener('DOMContentLoaded', () => {
    // ──────────────────────────────────────────────
    // STATE & ROUTING
    // ──────────────────────────────────────────────
    const state = {
        secret: localStorage.getItem('pymentor_admin_secret') || '',
        activeView: 'viewOverview',
        refreshInterval: null,
        dashboardData: null,
        studentsPage: 1,
        studentsTotalPages: 1,
        studentsSection: '',
        studentsSearch: '',
        topicsList: [],
        problemsList: []
    };

    // DOM References
    const loginOverlay = document.getElementById('adminLoginOverlay');
    const secretInput = document.getElementById('adminSecretInput');
    const loginBtn = document.getElementById('adminLoginBtn');
    const loginError = document.getElementById('loginError');
    const logoutBtn = document.getElementById('adminLogoutBtn');
    const pageTitle = document.getElementById('pageTitle');
    const navLinks = document.querySelectorAll('.sidebar-nav .nav-link');
    const viewSections = document.querySelectorAll('.view-section');

    // Modals & Drawers
    const studentModal = document.getElementById('studentModal');
    const problemDrawer = document.getElementById('problemDrawer');
    const resetPwModal = document.getElementById('resetPasswordModal');
    const bulkResetModal = document.getElementById('bulkResetModal');
    const addStudentModal = document.getElementById('addStudentModal');
    const topicModal = document.getElementById('topicModal');
    const apiKeyModal = document.getElementById('apiKeyModal');

    // ──────────────────────────────────────────────
    // TOAST NOTIFICATIONS
    // ──────────────────────────────────────────────
    function showToast(message, type = 'success') {
        const toast = document.getElementById('adminToast');
        const toastMsg = document.getElementById('adminToastMsg');
        const toastIcon = document.getElementById('adminToastIcon');
        if (!toast || !toastMsg) return;

        toastMsg.textContent = message;
        toast.className = `show ${type}`;
        toastIcon.textContent = type === 'success' ? '✓' : '✕';

        setTimeout(() => {
            toast.className = '';
        }, 3200);
    }

    // ──────────────────────────────────────────────
    // AUTHENTICATION
    // ──────────────────────────────────────────────
    async function verifyAndInitialize(secret) {
        if (!secret) {
            loginOverlay.classList.remove('hidden');
            return;
        }

        try {
            const res = await fetch('/api/status', {
                headers: { 'X-Admin-Secret': secret }
            });
            if (res.ok) {
                state.secret = secret;
                localStorage.setItem('pymentor_admin_secret', secret);
                loginOverlay.classList.add('hidden');
                loginError.style.display = 'none';

                initPortal();
            } else {
                localStorage.removeItem('pymentor_admin_secret');
                state.secret = '';
                loginOverlay.classList.remove('hidden');
                loginError.textContent = "Invalid Admin Secret Key.";
                loginError.style.display = 'block';
            }
        } catch (err) {
            loginOverlay.classList.remove('hidden');
            loginError.textContent = "Cannot connect to PyMentor backend.";
            loginError.style.display = 'block';
        }
    }

    loginBtn.addEventListener('click', () => {
        const key = secretInput.value.trim();
        verifyAndInitialize(key);
    });

    secretInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loginBtn.click();
    });

    logoutBtn.addEventListener('click', () => {
        localStorage.removeItem('pymentor_admin_secret');
        state.secret = '';
        if (state.refreshInterval) clearInterval(state.refreshInterval);
        loginOverlay.classList.remove('hidden');
        secretInput.value = '';
    });

    // ──────────────────────────────────────────────
    // HASH ROUTER
    // ──────────────────────────────────────────────
    const routeTitles = {
        '#overview': 'Operations Overview',
        '#problems': 'Problem Studio & Curriculum',
        '#topics': 'Topics & Module Management',
        '#students': 'Student Account Directory',
        '#lab': 'Active Lab Command Center',
        '#export': 'Exports & Disaster Recovery',
        '#system': 'AI & System Configuration'
    };

    const routeViews = {
        '#overview': 'viewOverview',
        '#problems': 'viewProblems',
        '#topics': 'viewTopics',
        '#students': 'viewStudents',
        '#lab': 'viewLab',
        '#export': 'viewExport',
        '#system': 'viewSystem'
    };

    function handleRoute() {
        const hash = window.location.hash || '#overview';
        const targetViewId = routeViews[hash] || 'viewOverview';
        const targetTitle = routeTitles[hash] || 'Operations Overview';

        state.activeView = targetViewId;
        pageTitle.textContent = targetTitle;

        // Update nav active link
        navLinks.forEach(link => {
            if (link.getAttribute('href') === hash) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });

        // Switch visible view panel
        viewSections.forEach(sec => {
            if (sec.id === targetViewId) {
                sec.classList.add('active');
            } else {
                sec.classList.remove('active');
            }
        });

        // View-specific on-demand data load
        if (targetViewId === 'viewProblems') loadProblemsView();
        else if (targetViewId === 'viewTopics') loadTopicsView();
        else if (targetViewId === 'viewStudents') loadStudentsView();
        else if (targetViewId === 'viewExport') loadBackupsView();
        else if (targetViewId === 'viewSystem') loadRateLimitConfig();
    }

    window.addEventListener('hashchange', handleRoute);

    // ──────────────────────────────────────────────
    // PORTAL INITIALIZATION
    // ──────────────────────────────────────────────
    function initPortal() {
        handleRoute();
        fetchOverviewData();

        // 10-second background polling for real-time overview & lab
        if (state.refreshInterval) clearInterval(state.refreshInterval);
        state.refreshInterval = setInterval(() => {
            fetchOverviewData(true);
        }, 10000);

        setupEventListeners();
    }

    // ──────────────────────────────────────────────
    // VIEW 1: OVERVIEW & TELEMETRY
    // ──────────────────────────────────────────────
    async function fetchOverviewData(isBackground = false) {
        if (!state.secret) return;
        try {
            const res = await fetch('/api/admin/dashboard', {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                state.dashboardData = data;
                renderOverview(data);
                renderLiveLab(data.online_students || []);
                renderSystemQuotas(data.model_quotas || []);
            } else if (res.status === 401) {
                logoutBtn.click();
            }
        } catch (err) {
            if (!isBackground) console.error("Error fetching admin dashboard:", err);
        }
    }

    function renderOverview(data) {
        // Topbar Gemini Status
        const keyStatus = data.api_key_status || {};
        const topApiKeyDot = document.getElementById('topApiKeyDot');
        const topApiKeyText = document.getElementById('topApiKeyText');
        if (keyStatus.has_key) {
            topApiKeyDot.className = 'pulse-dot';
            topApiKeyText.textContent = `Gemini: Active (${keyStatus.masked_key})`;
        } else {
            topApiKeyDot.className = 'pulse-dot';
            topApiKeyDot.style.background = 'var(--admin-rose)';
            topApiKeyDot.style.boxShadow = 'none';
            topApiKeyText.textContent = 'Gemini: Not Configured';
        }

        // Platform metrics
        document.getElementById('valStudents').textContent = data.metrics.total_students || 0;
        const onlineCount = data.metrics.total_online || (data.online_students ? data.online_students.length : 0);
        document.getElementById('valOnline').textContent = onlineCount;
        document.getElementById('sidebarOnlineBadge').textContent = onlineCount;

        document.getElementById('valRuns').textContent = data.metrics.total_runs || 0;
        document.getElementById('valSubmissions').textContent = data.metrics.total_submissions || 0;
        document.getElementById('valSolved').textContent = data.metrics.total_solved || 0;

        let rate = 0;
        if (data.metrics.total_submissions > 0) {
            rate = Math.round((data.metrics.total_solved / data.metrics.total_submissions) * 100);
        }
        document.getElementById('valRate').textContent = rate + '%';

        // Server Hardware metrics
        const sys = data.system_metrics || {};
        document.getElementById('sysRpm').textContent = sys.requests_per_minute || 0;
        document.getElementById('sysCpu').textContent = (sys.cpu_percent || 0) + '%';
        document.getElementById('barCpu').style.width = (sys.cpu_percent || 0) + '%';
        if (sys.cpu_percent > 80) document.getElementById('barCpu').style.background = 'var(--admin-rose)';

        document.getElementById('sysMem').textContent = (sys.memory_percent || 0) + '%';
        document.getElementById('barMem').style.width = (sys.memory_percent || 0) + '%';
        if (sys.memory_percent > 85) document.getElementById('barMem').style.background = 'var(--admin-rose)';

        document.getElementById('sysDisk').textContent = (sys.disk_percent || 0) + '%';
        document.getElementById('barDisk').style.width = (sys.disk_percent || 0) + '%';

        // Toughest Problems
        const toughContainer = document.getElementById('toughestProblemsList');
        toughContainer.innerHTML = '';
        (data.toughest_problems || []).forEach(p => {
            const passRate = p.attempts > 0 ? Math.round((p.correct / p.attempts) * 100) : 0;
            const html = `
                <div style="margin-bottom: 0.85rem;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 0.25rem;">
                        <span style="font-weight: 600; color: #fff;">${escapeHtml(p.title)}</span>
                        <span style="color: var(--admin-text-muted);">${p.attempts} attempts (${passRate}% pass)</span>
                    </div>
                    <div class="bar-bg" style="height: 6px;">
                        <div class="bar-fill" style="width: ${passRate}%; background: ${passRate < 50 ? 'var(--admin-rose)' : 'var(--admin-amber)'};"></div>
                    </div>
                </div>
            `;
            toughContainer.insertAdjacentHTML('beforeend', html);
        });

        // Guidance Usage
        const guideContainer = document.getElementById('guidanceUsageList');
        guideContainer.innerHTML = '';
        const totalSessions = (data.guidance_usage || []).reduce((sum, g) => sum + g.c, 0);
        const levelNames = { 1: "Level 1 (Socratic Hints)", 2: "Level 2 (Logic Breakdown)", 3: "Level 3 (Targeted Syntax)" };

        (data.guidance_usage || []).forEach(g => {
            const pct = totalSessions > 0 ? Math.round((g.c / totalSessions) * 100) : 0;
            const name = levelNames[g.help_level] || `Level ${g.help_level}`;
            const html = `
                <div style="margin-bottom: 0.85rem;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 0.25rem;">
                        <span style="font-weight: 600; color: #fff;">${name}</span>
                        <span style="color: var(--admin-text-muted);">${pct}% (${g.c})</span>
                    </div>
                    <div class="bar-bg" style="height: 6px;">
                        <div class="bar-fill" style="width: ${pct}%; background: ${g.help_level === 3 ? 'var(--admin-rose)' : 'var(--admin-cyan)'};"></div>
                    </div>
                </div>
            `;
            guideContainer.insertAdjacentHTML('beforeend', html);
        });

        // Live Feed Ticker
        const liveFeedBody = document.getElementById('liveFeedBody');
        liveFeedBody.innerHTML = '';
        (data.recent_activity || []).forEach(a => {
            const time = formatLocalTime(a.created_at);
            const verdictBadge = a.is_correct
                ? `<span class="pill pill-solved">SOLVED</span>`
                : `<span class="pill pill-progress">ATTEMPT</span>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 600; color: #fff;">${escapeHtml(a.name)}</td>
                <td>${escapeHtml(a.title)}</td>
                <td>${verdictBadge}</td>
                <td><span class="pill">Level ${a.help_level || 1}</span></td>
                <td class="code-font" style="color: var(--admin-violet);">${escapeHtml(a.model_used || '-')}</td>
                <td style="color: var(--admin-text-muted); font-size: 0.8rem;">${time}</td>
            `;
            liveFeedBody.appendChild(tr);
        });
    }

    // ──────────────────────────────────────────────
    // VIEW 2: PROBLEM STUDIO CONTROLLER
    // ──────────────────────────────────────────────
    // VIEW 2: PROBLEM STUDIO CONTROLLER
    // ──────────────────────────────────────────────
    async function loadProblemsView() {
        const tbody = document.getElementById('problemsTableBody');
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-text-muted); padding: 2rem;">Loading problem studio catalog...</td></tr>`;

        try {
            const res = await fetch('/api/admin/problems', {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                state.problemsList = data.problems || [];
                populateTopicFilter(state.problemsList);
                renderProblemsTable();
            } else {
                tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-rose); padding: 2rem;">Failed to load problems (${res.status}).</td></tr>`;
            }
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-rose); padding: 2rem;">Error loading problems catalog.</td></tr>`;
        }
    }

    function populateTopicFilter(problems) {
        const select = document.getElementById('problemTopicFilter');
        const currentVal = select.value;
        const topics = [...new Set(problems.map(p => p.topic))].sort();

        select.innerHTML = `<option value="">All Topics</option>`;
        topics.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            if (t === currentVal) opt.selected = true;
            select.appendChild(opt);
        });
    }

    function renderProblemsTable() {
        const tbody = document.getElementById('problemsTableBody');
        const query = (document.getElementById('problemSearchInput').value || '').trim().toLowerCase();
        const selectedTopic = document.getElementById('problemTopicFilter').value;
        const selectedDiff = document.getElementById('problemDifficultyFilter').value;

        const filtered = (state.problemsList || []).filter(p => {
            const matchQuery = !query || p.title.toLowerCase().includes(query) || (p.topic && p.topic.toLowerCase().includes(query));
            const matchTopic = !selectedTopic || p.topic === selectedTopic;
            const matchDiff = !selectedDiff || p.difficulty.toLowerCase() === selectedDiff.toLowerCase();
            return matchQuery && matchTopic && matchDiff;
        });

        document.getElementById('problemCountBadge').textContent = `${filtered.length} Problems`;
        tbody.innerHTML = '';

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-text-muted); padding: 2rem;">No problems match current filters.</td></tr>`;
            return;
        }

        filtered.forEach(p => {
            const diffClass = `pill-${(p.difficulty || 'Easy').toLowerCase()}`;
            const hasDirective = p.teacher_instructions && p.teacher_instructions.trim().length > 0;
            const directiveBadge = hasDirective
                ? `<span class="pill pill-active" title="${escapeHtml(p.teacher_instructions)}">Directive Active</span>`
                : `<span style="color: var(--admin-text-faint); font-size: 0.8rem;">None</span>`;

            const statusBadge = p.is_active
                ? `<span class="pill pill-active">Active</span>`
                : `<span class="pill" style="background: rgba(244,63,94,0.15); color: var(--admin-rose); border: 1px solid rgba(244,63,94,0.3);">Inactive</span>`;

            const actionBtn = p.is_active
                ? `<button class="btn btn-danger btn-xs" onclick="window.deactivateProblem(${p.id})" style="margin-left: 4px;">Deactivate</button>`
                : `<button class="btn btn-success btn-xs" onclick="window.activateProblem(${p.id})" style="margin-left: 4px; background: rgba(16,185,129,0.2); color: var(--admin-emerald); border: 1px solid rgba(16,185,129,0.3);">Activate</button>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 700; color: var(--admin-text-muted);">${p.id}</td>
                <td style="font-weight: 600; color: #fff;">${escapeHtml(p.title)}</td>
                <td><span class="pill pill-inactive">${escapeHtml(p.topic)}</span></td>
                <td><span class="pill ${diffClass}">${escapeHtml(p.difficulty)}</span></td>
                <td>${directiveBadge}</td>
                <td>${statusBadge}</td>
                <td style="text-align: right; white-space: nowrap;">
                    <button class="btn btn-secondary btn-xs" onclick="window.editProblemInStudio(${p.id})">Edit</button>
                    ${actionBtn}
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    // Problem Drawer Tabs
    const drawerTabBtns = document.querySelectorAll('#problemDrawer .tab-btn');
    const drawerTabPanels = document.querySelectorAll('#problemDrawer .tab-content-panel');
    drawerTabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            drawerTabBtns.forEach(b => b.classList.remove('active'));
            drawerTabPanels.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(targetId).classList.add('active');
        });
    });

    document.getElementById('btnCreateProblem').addEventListener('click', () => {
        document.getElementById('editProblemId').value = '';
        document.getElementById('drawerProblemTitle').textContent = 'Create New Practice Problem';
        document.getElementById('studioTitle').value = '';
        document.getElementById('studioTopic').value = '';
        document.getElementById('studioDifficulty').value = 'Easy';
        document.getElementById('studioConcepts').value = '';
        document.getElementById('studioDescription').value = '';
        document.getElementById('studioStarterCode').value = '';
        document.getElementById('studioSampleInput').value = '';
        document.getElementById('studioSampleOutput').value = '';
        document.getElementById('studioRubric').value = '';
        document.getElementById('studioReferenceSolution').value = '';
        document.getElementById('studioTeacherInstructions').value = '';

        // Reset to first tab
        drawerTabBtns[0].click();
        problemDrawer.classList.remove('hidden');
    });

    window.editProblemInStudio = async function(problemId) {
        try {
            const res = await fetch(`/api/admin/problems/${problemId}/full`, {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                document.getElementById('editProblemId').value = data.id;
                document.getElementById('drawerProblemTitle').textContent = `Edit Problem #${data.id}: ${data.title}`;
                document.getElementById('studioTitle').value = data.title || '';
                document.getElementById('studioTopic').value = data.topic || '';
                document.getElementById('studioDifficulty').value = data.difficulty || 'Easy';
                document.getElementById('studioConcepts').value = (data.concepts || []).join(', ');
                document.getElementById('studioDescription').value = data.description || '';
                document.getElementById('studioStarterCode').value = data.starter_code || '';
                document.getElementById('studioSampleInput').value = data.sample_input || '';
                document.getElementById('studioSampleOutput').value = data.sample_output || '';
                document.getElementById('studioRubric').value = data.ai_rubric || '';
                document.getElementById('studioReferenceSolution').value = data.reference_solution || '';
                document.getElementById('studioTeacherInstructions').value = data.teacher_instructions || '';

                drawerTabBtns[0].click();
                problemDrawer.classList.remove('hidden');
            } else {
                showToast("Failed to load full problem details", "error");
            }
        } catch (err) {
            showToast("Network error loading problem", "error");
        }
    };

    document.getElementById('closeProblemDrawerBtn').addEventListener('click', () => {
        problemDrawer.classList.add('hidden');
    });
    document.getElementById('cancelDrawerBtn').addEventListener('click', () => {
        problemDrawer.classList.add('hidden');
    });

    document.getElementById('saveProblemBtn').addEventListener('click', async () => {
        const id = document.getElementById('editProblemId').value;
        const title = document.getElementById('studioTitle').value.trim();
        const topic = document.getElementById('studioTopic').value.trim();
        const difficulty = document.getElementById('studioDifficulty').value;
        const concepts = document.getElementById('studioConcepts').value.split(',').map(c => c.trim()).filter(Boolean);
        const description = document.getElementById('studioDescription').value.trim();
        const starter_code = document.getElementById('studioStarterCode').value;
        const sample_input = document.getElementById('studioSampleInput').value;
        const sample_output = document.getElementById('studioSampleOutput').value.trim();
        const ai_rubric = document.getElementById('studioRubric').value.trim();
        const reference_solution = document.getElementById('studioReferenceSolution').value.trim();
        const teacher_instructions = document.getElementById('studioTeacherInstructions').value.trim();

        if (!title || !topic || !description || !sample_output || !ai_rubric) {
            showToast("Please fill in all required problem fields", "error");
            return;
        }

        const payload = {
            title, topic, difficulty, concepts, description,
            starter_code, sample_input, sample_output, ai_rubric,
            reference_solution, teacher_instructions
        };

        try {
            const url = id ? `/api/admin/problems/${id}` : '/api/admin/problems';
            const method = id ? 'PUT' : 'POST';

            const res = await fetch(url, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-Admin-Secret': state.secret
                },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                showToast(id ? "Problem updated successfully!" : "New problem created!");
                problemDrawer.classList.add('hidden');
                loadProblemsView();
            } else {
                const err = await res.json();
                showToast(err.detail || "Error saving problem", "error");
            }
        } catch (err) {
            showToast("Network error saving problem", "error");
        }
    });

    window.deactivateProblem = async function(problemId) {
        if (!confirm(`Are you sure you want to deactivate problem #${problemId}?`)) return;

        try {
            const res = await fetch(`/api/admin/problems/${problemId}?hard=false`, {
                method: 'DELETE',
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                showToast(`Problem #${problemId} deactivated.`);
                loadProblemsView();
            } else {
                const err = await res.json();
                showToast(err.detail || "Error deactivating problem", "error");
            }
        } catch (err) {
            showToast("Network error deactivating problem", "error");
        }
    };

    window.activateProblem = async function(problemId) {
        try {
            const res = await fetch(`/api/admin/problems/${problemId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Admin-Secret': state.secret
                },
                body: JSON.stringify({ is_active: true })
            });
            if (res.ok) {
                showToast(`Problem #${problemId} restored to active status.`);
                loadProblemsView();
            } else {
                const err = await res.json();
                showToast(err.detail || "Error restoring problem", "error");
            }
        } catch (err) {
            showToast("Network error restoring problem", "error");
        }
    };

    // ──────────────────────────────────────────────
    // VIEW 3: TOPICS CONTROLLER
    // ──────────────────────────────────────────────
    async function loadTopicsView() {
        const tbody = document.getElementById('topicsTableBody');
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-text-muted); padding: 2rem;">Loading curriculum modules...</td></tr>`;

        try {
            const res = await fetch('/api/admin/topics', {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                state.topicsList = data.topics || [];
                renderTopicsTable();
            }
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-rose); padding: 2rem;">Error loading topics.</td></tr>`;
        }
    }

    function renderTopicsTable() {
        const tbody = document.getElementById('topicsTableBody');
        tbody.innerHTML = '';

        if (!state.topicsList || state.topicsList.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--admin-text-muted); padding: 2rem;">No curriculum topics defined.</td></tr>`;
            return;
        }

        state.topicsList.forEach(t => {
            const rate = t.total_sessions > 0 ? Math.round((t.solved_sessions / t.total_sessions) * 100) : 0;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 700; color: #fff;">${escapeHtml(t.topic_name)}</td>
                <td style="font-weight: 600;">${t.total_problems}</td>
                <td style="color: var(--admin-cyan); font-weight: 600;">${t.active_problems}</td>
                <td>${t.total_sessions}</td>
                <td style="color: var(--admin-emerald); font-weight: 700;">${t.solved_sessions}</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-size: 0.8rem; font-weight: 600; width: 35px;">${rate}%</span>
                        <div class="bar-bg" style="width: 80px; height: 5px;">
                            <div class="bar-fill" style="width: ${rate}%;"></div>
                        </div>
                    </div>
                </td>
                <td style="text-align: right;">
                    <button class="btn btn-secondary btn-xs" onclick="window.openRenameTopicModal('${escapeHtml(t.topic_name)}')">Rename</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    document.getElementById('btnAddTopicBtn').addEventListener('click', () => {
        document.getElementById('topicModalTitle').textContent = 'Add New Curriculum Topic';
        document.getElementById('topicModalMode').value = 'create';
        document.getElementById('topicModalNameInput').value = '';
        document.getElementById('topicModalDescInput').value = '';
        topicModal.classList.remove('hidden');
    });

    window.openRenameTopicModal = function(oldName) {
        document.getElementById('topicModalTitle').textContent = `Rename Topic: ${oldName}`;
        document.getElementById('topicModalMode').value = 'rename';
        document.getElementById('topicModalOldName').value = oldName;
        document.getElementById('topicModalNameInput').value = oldName;
        document.getElementById('topicModalDescInput').value = '';
        topicModal.classList.remove('hidden');
    };

    document.getElementById('closeTopicModalBtn').addEventListener('click', () => topicModal.classList.add('hidden'));
    document.getElementById('cancelTopicModalBtn').addEventListener('click', () => topicModal.classList.add('hidden'));

    document.getElementById('confirmTopicModalBtn').addEventListener('click', async () => {
        const mode = document.getElementById('topicModalMode').value;
        const name = document.getElementById('topicModalNameInput').value.trim();
        const description = document.getElementById('topicModalDescInput').value.trim();

        if (!name) {
            showToast("Please enter a topic name", "error");
            return;
        }

        try {
            if (mode === 'create') {
                const res = await fetch('/api/admin/topics', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                    body: JSON.stringify({ name, description })
                });
                if (res.ok) {
                    showToast("Topic created successfully!");
                    topicModal.classList.add('hidden');
                    loadTopicsView();
                } else {
                    const err = await res.json();
                    showToast(err.detail || "Error creating topic", "error");
                }
            } else {
                const oldName = document.getElementById('topicModalOldName').value;
                const res = await fetch(`/api/admin/topics/${encodeURIComponent(oldName)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                    body: JSON.stringify({ new_name: name, description })
                });
                if (res.ok) {
                    const data = await res.json();
                    showToast(`Topic renamed! Updated ${data.problems_updated} associated problem(s).`);
                    topicModal.classList.add('hidden');
                    loadTopicsView();
                } else {
                    const err = await res.json();
                    showToast(err.detail || "Error renaming topic", "error");
                }
            }
        } catch (err) {
            showToast("Network error updating topic", "error");
        }
    });

    // ──────────────────────────────────────────────
    // VIEW 4: STUDENT ACCOUNTS CONTROLLER
    // ──────────────────────────────────────────────
    async function loadStudentsView() {
        const tbody = document.getElementById('studentsTableBody');
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--admin-text-muted); padding: 2rem;">Loading student accounts roster...</td></tr>`;

        const query = state.studentsSearch ? `&search=${encodeURIComponent(state.studentsSearch)}` : '';
        const section = state.studentsSection ? `&section=${encodeURIComponent(state.studentsSection)}` : '';

        try {
            const res = await fetch(`/api/admin/students?page=${state.studentsPage}&page_size=25${section}${query}`, {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                state.studentsTotalPages = data.total_pages || 1;
                document.getElementById('studentCountBadge').textContent = `${data.total} Students`;
                document.getElementById('paginationInfo').textContent = `Showing page ${data.page} of ${data.total_pages}`;
                document.getElementById('prevPageBtn').disabled = data.page <= 1;
                document.getElementById('nextPageBtn').disabled = data.page >= data.total_pages;

                renderStudentsTable(data.students || []);
            }
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--admin-rose); padding: 2rem;">Error loading student roster.</td></tr>`;
        }
    }

    function renderStudentsTable(students) {
        const tbody = document.getElementById('studentsTableBody');
        tbody.innerHTML = '';

        if (!students || students.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--admin-text-muted); padding: 2rem;">No students found matching your criteria.</td></tr>`;
            return;
        }

        students.forEach(s => {
            const lastActive = s.last_active_at ? formatLocalDateTime(s.last_active_at) : 'Never';
            const statusBadge = s.is_active
                ? `<span class="pill pill-active">Active</span>`
                : `<span class="pill pill-inactive">Inactive</span>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="code-font" style="font-weight: 700; color: #fff;">${escapeHtml(s.roll_no)}</td>
                <td style="font-weight: 600;">${escapeHtml(s.name)}</td>
                <td><span class="pill" style="background: rgba(148, 163, 184, 0.15);">Sec ${escapeHtml(s.section)}</span></td>
                <td style="color: var(--admin-emerald); font-weight: 700;">${s.problems_solved || 0}</td>
                <td class="code-font" style="color: var(--admin-cyan);">${formatDuration(s.total_time_seconds || 0)}</td>
                <td>${statusBadge}</td>
                <td style="color: var(--admin-text-muted); font-size: 0.8rem;">${lastActive}</td>
                <td style="text-align: right; white-space: nowrap;">
                    <button class="btn btn-secondary btn-xs" onclick="window.inspectStudent(${s.id})">Telemetry</button>
                    <button class="btn btn-secondary btn-xs" onclick="window.openStudentRateLimitModal(${s.id}, '${escapeHtml(s.name)}', '${escapeHtml(s.roll_no)}')" style="margin-left: 4px;" title="Individual Guidance Rate Limits">Limits</button>
                    <button class="btn btn-secondary btn-xs" onclick="window.openResetPasswordModal(${s.id}, '${escapeHtml(s.name)}', '${escapeHtml(s.roll_no)}', '${escapeHtml(s.section)}')" style="margin-left: 4px;">Reset Pw</button>
                    <button class="btn btn-danger btn-xs" onclick="window.deleteStudent(${s.id}, '${escapeHtml(s.roll_no)}')" style="margin-left: 4px;">Deactivate</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    document.getElementById('prevPageBtn').addEventListener('click', () => {
        if (state.studentsPage > 1) {
            state.studentsPage--;
            loadStudentsView();
        }
    });

    document.getElementById('nextPageBtn').addEventListener('click', () => {
        if (state.studentsPage < state.studentsTotalPages) {
            state.studentsPage++;
            loadStudentsView();
        }
    });

    document.getElementById('studentSearchInput').addEventListener('input', (e) => {
        state.studentsSearch = e.target.value.trim();
        state.studentsPage = 1;
        loadStudentsView();
    });

    document.getElementById('studentSectionFilter').addEventListener('change', (e) => {
        state.studentsSection = e.target.value;
        state.studentsPage = 1;
        loadStudentsView();
    });

    // Student Single Password Reset Modal
    window.openResetPasswordModal = function(id, name, roll, section) {
        document.getElementById('resetPwStudentId').value = id;
        document.getElementById('resetPwStudentInfo').textContent = `Student: ${name} (Section ${section}, Roll No: ${roll})`;
        document.getElementById('resetPwInput').value = '123';
        document.getElementById('resetPwRequireChange').checked = true;
        resetPwModal.classList.remove('hidden');
    };

    document.getElementById('closeResetPwModalBtn').addEventListener('click', () => resetPwModal.classList.add('hidden'));
    document.getElementById('cancelResetPwBtn').addEventListener('click', () => resetPwModal.classList.add('hidden'));

    document.getElementById('confirmResetPwBtn').addEventListener('click', async () => {
        const id = document.getElementById('resetPwStudentId').value;
        const new_password = document.getElementById('resetPwInput').value.trim();
        const require_change = document.getElementById('resetPwRequireChange').checked;

        try {
            const res = await fetch(`/api/admin/students/${id}/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ new_password, require_change })
            });
            if (res.ok) {
                const data = await res.json();
                showToast(`Password for Roll ${data.roll_no} reset to '${new_password}'.`);
                resetPwModal.classList.add('hidden');
            } else {
                showToast("Failed to reset student password", "error");
            }
        } catch (err) {
            showToast("Network error resetting password", "error");
        }
    });

    // Bulk Section Reset Modal
    document.getElementById('btnBulkResetModal').addEventListener('click', () => {
        bulkResetModal.classList.remove('hidden');
    });
    document.getElementById('closeBulkResetModalBtn').addEventListener('click', () => bulkResetModal.classList.add('hidden'));
    document.getElementById('cancelBulkResetBtn').addEventListener('click', () => bulkResetModal.classList.add('hidden'));

    document.getElementById('confirmBulkResetBtn').addEventListener('click', async () => {
        const section = document.getElementById('bulkResetSectionSelect').value;
        const default_password = document.getElementById('bulkResetDefaultPwInput').value.trim();

        if (!confirm(`Confirm bulk password reset for ${section ? 'Section ' + section : 'ALL SECTIONS'}? This will invalidate all active sessions.`)) return;

        try {
            const res = await fetch('/api/admin/students/bulk-reset-passwords', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ section: section || null, default_password })
            });
            if (res.ok) {
                const data = await res.json();
                showToast(data.message || `Reset ${data.students_affected} student passwords!`);
                bulkResetModal.classList.add('hidden');
                loadStudentsView();
            } else {
                showToast("Bulk reset failed", "error");
            }
        } catch (err) {
            showToast("Network error performing bulk reset", "error");
        }
    });

    // Add Student Account Modal
    document.getElementById('btnAddStudentModal').addEventListener('click', () => {
        document.getElementById('newStudentName').value = '';
        document.getElementById('newStudentRoll').value = '';
        document.getElementById('newStudentSection').value = '';
        document.getElementById('newStudentPassword').value = '123';
        addStudentModal.classList.remove('hidden');
    });
    document.getElementById('closeAddStudentModalBtn').addEventListener('click', () => addStudentModal.classList.add('hidden'));
    document.getElementById('cancelAddStudentBtn').addEventListener('click', () => addStudentModal.classList.add('hidden'));

    document.getElementById('confirmAddStudentBtn').addEventListener('click', async () => {
        const name = document.getElementById('newStudentName').value.trim();
        const roll_no = document.getElementById('newStudentRoll').value.trim();
        const section = document.getElementById('newStudentSection').value.trim().toUpperCase();
        const password = document.getElementById('newStudentPassword').value.trim();

        if (!name || !roll_no || !section) {
            showToast("Please provide Student Name, Roll No, and Section", "error");
            return;
        }

        try {
            const res = await fetch('/api/admin/students', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ name, roll_no, section, password, needs_password_change: true })
            });
            if (res.ok) {
                showToast(`Student ${name} (${roll_no}) created successfully!`);
                addStudentModal.classList.add('hidden');
                loadStudentsView();
            } else {
                const err = await res.json();
                showToast(err.detail || "Error creating student", "error");
            }
        } catch (err) {
            showToast("Network error creating student", "error");
        }
    });

    window.deleteStudent = async function(id, roll) {
        if (!confirm(`Are you sure you want to deactivate student ${roll}?`)) return;

        try {
            const res = await fetch(`/api/admin/students/${id}?hard=false`, {
                method: 'DELETE',
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                showToast(`Student ${roll} deactivated.`);
                loadStudentsView();
            } else {
                showToast("Failed to deactivate student", "error");
            }
        } catch (err) {
            showToast("Network error deactivating student", "error");
        }
    };

    // ──────────────────────────────────────────────
    // VIEW 5: LIVE LAB COMMAND CENTER CONTROLLER
    // ──────────────────────────────────────────────
    function renderLiveLab(onlineList) {
        const tbody = document.getElementById('liveLabTableBody');
        const badge = document.getElementById('liveLabCountBadge');
        if (!tbody) return;

        badge.textContent = `${onlineList.length} Online Now`;
        tbody.innerHTML = '';

        if (!onlineList || onlineList.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--admin-text-muted); padding: 3rem;">No active student connections detected in the last 120 seconds.</td></tr>`;
            return;
        }

        onlineList.forEach(s => {
            const secAgo = s.seconds_ago !== undefined && s.seconds_ago !== null ? s.seconds_ago : 0;
            const seenText = secAgo <= 15 ? 'Active just now' : `${secAgo}s ago`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 700; color: #fff;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="pulse-dot"></span>
                        <span>${escapeHtml(s.student_name)}</span>
                    </div>
                </td>
                <td><span class="pill" style="background: rgba(148, 163, 184, 0.15);">Sec ${escapeHtml(s.section)}</span></td>
                <td class="code-font">${escapeHtml(s.roll_no)}</td>
                <td>
                    <span class="pill pill-active">${escapeHtml(s.problem_title)}</span>
                    <span style="color: var(--admin-text-faint); font-size: 0.78rem; margin-left: 4px;">(${escapeHtml(s.problem_topic)})</span>
                </td>
                <td class="code-font" style="color: var(--admin-cyan);">⏱ ${formatDuration(s.time_spent_seconds || 0)}</td>
                <td style="font-weight: 700; color: var(--admin-cyan);">${s.run_count || 0}</td>
                <td style="color: var(--admin-emerald); font-size: 0.8rem; font-weight: 600;">${seenText}</td>
                <td style="text-align: right; white-space: nowrap;">
                    <button class="btn btn-emerald btn-xs" onclick="window.overridePassSession(${s.session_id})" title="Manually mark problem as solved">Pass</button>
                    <button class="btn btn-danger btn-xs" onclick="window.resetProblemSession(${s.session_id})" style="margin-left: 4px;" title="Clear student draft to restart problem fresh">Reset</button>
                    <button class="btn btn-secondary btn-xs" onclick="window.inspectStudent(${s.student_id})" style="margin-left: 4px;">Inspect</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    window.overridePassSession = async function(sessionId) {
        if (!confirm("Manually override and mark this problem as SOLVED for the student?")) return;

        try {
            const res = await fetch(`/api/admin/sessions/${sessionId}/override-pass`, {
                method: 'POST',
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                showToast(data.message || "Problem manually marked as Solved!");
                fetchOverviewData();
            } else {
                showToast("Failed to override pass session", "error");
            }
        } catch (err) {
            showToast("Network error overriding pass", "error");
        }
    };

    window.resetProblemSession = async function(sessionId) {
        if (!confirm("Reset this session? This will clear the student's active draft and attempts counter.")) return;

        try {
            const res = await fetch(`/api/admin/sessions/${sessionId}/reset`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ clear_history: false })
            });
            if (res.ok) {
                showToast("Problem session reset successfully. Student can start fresh!");
                fetchOverviewData();
            } else {
                showToast("Failed to reset session", "error");
            }
        } catch (err) {
            showToast("Network error resetting session", "error");
        }
    };

    // ──────────────────────────────────────────────
    // VIEW 6: EXPORTS & BACKUPS CONTROLLER
    // ──────────────────────────────────────────────
    document.getElementById('btnDownloadGradesCsv').addEventListener('click', () => {
        const sec = document.getElementById('exportSectionSelect').value;
        const query = sec ? `?section=${encodeURIComponent(sec)}` : '';
        window.open(`/api/admin/export/grades.csv${query}`, '_blank');
    });

    document.getElementById('btnDownloadSubmissionsCsv').addEventListener('click', () => {
        window.open('/api/admin/export/submissions.csv', '_blank');
    });

    document.getElementById('btnDownloadDbBackup').addEventListener('click', () => {
        window.open('/api/admin/backup/download', '_blank');
    });

    async function loadBackupsView() {
        const statusEl = document.getElementById('githubBackupStatusText');
        statusEl.textContent = "Checking GitHub cloud backups...";

        try {
            const res = await fetch('/api/admin/backup/status', {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                if (data.github_configured) {
                    statusEl.innerHTML = `<span style="color: var(--admin-emerald); font-weight: 600;">✓ Cloud Active:</span> ${data.github_repo || 'Connected'} (${data.github_backups_count || 0} backups archived)`;
                } else {
                    statusEl.innerHTML = `<span style="color: var(--admin-amber); font-weight: 600;">⚠️ Local Mode:</span> Cloud credentials not set in .env. Daily backups saved locally in /backups folder.`;
                }
            }
        } catch (err) {
            statusEl.textContent = "Cannot reach backup service.";
        }
    }

    document.getElementById('btnTriggerCloudBackup').addEventListener('click', async () => {
        showToast("Triggering cloud snapshot...", "info");
        try {
            const res = await fetch('/api/admin/backup', {
                method: 'POST',
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                showToast(data.message || "Backup completed successfully!");
                loadBackupsView();
            } else {
                showToast("Backup failed. Check server logs.", "error");
            }
        } catch (err) {
            showToast("Network error triggering backup", "error");
        }
    });

    document.getElementById('btnRestoreFromCloud').addEventListener('click', async () => {
        if (!confirm("Pull latest database from GitHub? This will merge/sync latest student progress.")) return;
        try {
            const res = await fetch('/api/admin/backup/restore-github', {
                method: 'POST',
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                showToast("Database restored from cloud sync!");
                fetchOverviewData();
            } else {
                showToast("Restore failed", "error");
            }
        } catch (err) {
            showToast("Network error during restore", "error");
        }
    });

    // ──────────────────────────────────────────────
    // VIEW 7: AI & SYSTEM CONTROLLER
    // ──────────────────────────────────────────────
    function renderSystemQuotas(quotas) {
        const tbody = document.getElementById('systemQuotasBody');
        tbody.innerHTML = '';

        if (!quotas || quotas.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--admin-text-muted); padding: 1.5rem;">No multi-model quota telemetry available.</td></tr>`;
            return;
        }

        quotas.forEach(q => {
            const pct = q.day_limit > 0 ? Math.min(100, Math.round((q.day_used / q.day_limit) * 100)) : 0;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="code-font" style="font-weight: 700; color: #fff;">${escapeHtml(q.model)}</td>
                <td><span class="pill pill-active">${escapeHtml(q.tier)}</span></td>
                <td>
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 0.25rem;">
                        <span>${q.day_used} / ${q.day_limit} reqs</span>
                        <span style="color: var(--admin-text-muted);">${pct}%</span>
                    </div>
                    <div class="bar-bg" style="height: 5px;">
                        <div class="bar-fill" style="width: ${pct}%; background: ${pct > 85 ? 'var(--admin-rose)' : 'var(--admin-cyan)'};"></div>
                    </div>
                </td>
                <td class="code-font">${q.rpm_active} / ${q.rpm_limit}</td>
                <td><span class="pill pill-solved">${escapeHtml(q.status)}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    // Rate Limit Config Placeholder
    async function loadRateLimitConfig() {
        try {
            const res = await fetch('/api/admin/config/ratelimit', {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const cfg = await res.json();
                document.getElementById('toggleRateLimit').checked = Boolean(cfg.enabled);
                document.getElementById('inputCooldownSeconds').value = cfg.cooldown_seconds !== undefined ? cfg.cooldown_seconds : 0.0;
                document.getElementById('inputMaxGuidance').value = cfg.daily_guidance_limit !== undefined ? cfg.daily_guidance_limit : (cfg.max_guidance_per_problem || 50);
                const overridesBadge = document.getElementById('customOverridesCountBadge');
                if (overridesBadge) {
                    const count = cfg.custom_overrides_count || 0;
                    overridesBadge.textContent = `${count} Student Override${count === 1 ? '' : 's'}`;
                }
            }
        } catch (err) {
            console.warn("Could not load rate limit config:", err);
        }
    }

    document.getElementById('btnSaveRateLimit').addEventListener('click', async () => {
        const enabled = document.getElementById('toggleRateLimit').checked;
        const cooldown_seconds = parseFloat(document.getElementById('inputCooldownSeconds').value) || 0.0;
        const daily_guidance_limit = parseInt(document.getElementById('inputMaxGuidance').value, 10) || 0;

        try {
            const res = await fetch('/api/admin/config/ratelimit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ enabled, cooldown_seconds, daily_guidance_limit, max_guidance_per_problem: daily_guidance_limit })
            });
            if (res.ok) {
                showToast("Guidance rate limit preferences saved!");
            } else {
                showToast("Failed to save rate limit rules", "error");
            }
        } catch (err) {
            showToast("Network error saving rate limits", "error");
        }
    });


    // ──────────────────────────────────────────────
    // API KEY MODAL
    // ──────────────────────────────────────────────
    document.getElementById('quickKeyModalBtn').addEventListener('click', () => {
        document.getElementById('newApiKeyInput').value = '';
        apiKeyModal.classList.remove('hidden');
    });
    document.getElementById('topApiKeyPill').addEventListener('click', () => {
        document.getElementById('newApiKeyInput').value = '';
        apiKeyModal.classList.remove('hidden');
    });
    document.getElementById('closeApiKeyModalBtn').addEventListener('click', () => apiKeyModal.classList.add('hidden'));
    document.getElementById('cancelApiKeyBtn').addEventListener('click', () => apiKeyModal.classList.add('hidden'));

    document.getElementById('saveApiKeyBtn').addEventListener('click', async () => {
        const key = document.getElementById('newApiKeyInput').value.trim();
        if (!key) {
            showToast("Please enter an API key", "error");
            return;
        }

        try {
            const res = await fetch('/api/config/key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ api_key: key })
            });
            if (res.ok) {
                showToast("Gemini API key updated and verified!");
                apiKeyModal.classList.add('hidden');
                fetchOverviewData();
            } else {
                const err = await res.json();
                showToast(err.detail || "Invalid API key", "error");
            }
        } catch (err) {
            showToast("Network error saving key", "error");
        }
    });

    // ──────────────────────────────────────────────
    // STUDENT INDIVIDUAL RATE LIMIT MODAL
    // ──────────────────────────────────────────────
    const studentRateLimitModal = document.getElementById('studentRateLimitModal');

    window.openStudentRateLimitModal = async function(studentId, name, roll) {
        document.getElementById('studentRateLimitStudentId').value = studentId;
        document.getElementById('studentRateLimitModalTitle').textContent = `Guidance Limit: ${name}`;
        document.getElementById('studentRateLimitMeta').textContent = `Roll No: ${roll} | Student ID: ${studentId}`;

        try {
            const res = await fetch(`/api/admin/students/${studentId}/ratelimit`, {
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                const data = await res.json();
                const rl = data.rate_limit || {};
                document.getElementById('studentRateLimitUseCustom').checked = Boolean(rl.use_custom);
                document.getElementById('studentRateLimitCooldown').value = rl.cooldown_seconds !== undefined ? rl.cooldown_seconds : 0.0;
                document.getElementById('studentRateLimitMaxGuidance').value = rl.daily_guidance_limit !== undefined ? rl.daily_guidance_limit : (rl.max_guidance_per_problem || 50);
                document.getElementById('studentRateLimitIsExempt').checked = Boolean(rl.is_exempt);
                studentRateLimitModal.classList.remove('hidden');
            }
        } catch (err) {
            showToast("Error loading student rate limits", "error");
        }
    };

    document.getElementById('closeStudentRateLimitModalBtn').addEventListener('click', () => studentRateLimitModal.classList.add('hidden'));
    document.getElementById('cancelStudentRateLimitBtn').addEventListener('click', () => studentRateLimitModal.classList.add('hidden'));

    document.getElementById('saveStudentRateLimitBtn').addEventListener('click', async () => {
        const studentId = document.getElementById('studentRateLimitStudentId').value;
        const use_custom = document.getElementById('studentRateLimitUseCustom').checked;
        const cooldown_seconds = parseFloat(document.getElementById('studentRateLimitCooldown').value) || 0.0;
        const daily_guidance_limit = parseInt(document.getElementById('studentRateLimitMaxGuidance').value, 10) || 0;
        const is_exempt = document.getElementById('studentRateLimitIsExempt').checked;

        try {
            const res = await fetch(`/api/admin/students/${studentId}/ratelimit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': state.secret },
                body: JSON.stringify({ use_custom, cooldown_seconds, daily_guidance_limit, max_guidance_per_problem: daily_guidance_limit, is_exempt })
            });
            if (res.ok) {
                const data = await res.json();
                showToast(data.message || "Student rate limits updated!");
                studentRateLimitModal.classList.add('hidden');
                loadRateLimitConfig();
            } else {
                showToast("Failed to save student limits", "error");
            }
        } catch (err) {
            showToast("Network error saving student limits", "error");
        }
    });


    document.getElementById('revertStudentRateLimitBtn').addEventListener('click', async () => {
        const studentId = document.getElementById('studentRateLimitStudentId').value;
        try {
            const res = await fetch(`/api/admin/students/${studentId}/ratelimit`, {
                method: 'DELETE',
                headers: { 'X-Admin-Secret': state.secret }
            });
            if (res.ok) {
                showToast("Student reverted to global rate limit policy.");
                studentRateLimitModal.classList.add('hidden');
                loadRateLimitConfig();
            }
        } catch (err) {
            showToast("Network error reverting limits", "error");
        }
    });

    // ──────────────────────────────────────────────
    // EVENT LISTENERS & MODAL CLOSE
    // ──────────────────────────────────────────────
    function setupEventListeners() {
        document.getElementById('modalCloseBtn').addEventListener('click', () => studentModal.classList.add('hidden'));

        // Problem Studio Filters
        const pSearch = document.getElementById('problemSearchInput');
        const pTopic = document.getElementById('problemTopicFilter');
        const pDiff = document.getElementById('problemDifficultyFilter');
        if (pSearch) pSearch.addEventListener('input', renderProblemsTable);
        if (pTopic) pTopic.addEventListener('change', renderProblemsTable);
        if (pDiff) pDiff.addEventListener('change', renderProblemsTable);

        // Click outside modal or drawer to close
        [studentModal, problemDrawer, resetPwModal, bulkResetModal, addStudentModal, topicModal, apiKeyModal, studentRateLimitModal].forEach(m => {
            if (m) {
                m.addEventListener('click', (e) => {
                    if (e.target === m) m.classList.add('hidden');
                });
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                [studentModal, problemDrawer, resetPwModal, bulkResetModal, addStudentModal, topicModal, apiKeyModal, studentRateLimitModal].forEach(m => {
                    if (m) m.classList.add('hidden');
                });
            }
        });
    }

    // Check existing secret on load
    if (state.secret) {
        verifyAndInitialize(state.secret);
    }
});
