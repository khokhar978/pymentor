document.addEventListener('DOMContentLoaded', () => {
    const loginOverlay = document.getElementById('adminLoginOverlay');
    const dashboardContent = document.getElementById('dashboardContent');
    const loginForm = document.getElementById('adminLoginForm');
    const secretInput = document.getElementById('adminSecretInput');
    const loginError = document.getElementById('loginError');
    const refreshBtn = document.getElementById('refreshBtn');
    const logoutBtn = document.getElementById('logoutBtn');

    // API Key Form elements
    const apiStatusDot = document.getElementById('apiStatusDot');
    const apiStatusTitle = document.getElementById('apiStatusTitle');
    const apiStatusSub = document.getElementById('apiStatusSub');
    const toggleKeyFormBtn = document.getElementById('toggleKeyFormBtn');
    const apiKeyFormPanel = document.getElementById('apiKeyFormPanel');
    const newApiKeyInput = document.getElementById('newApiKeyInput');
    const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
    const cancelKeyBtn = document.getElementById('cancelKeyBtn');
    const apiKeyFeedback = document.getElementById('apiKeyFeedback');

    // Roster elements
    const rosterTableBody = document.getElementById('rosterTableBody');
    const rosterCount = document.getElementById('rosterCount');
    const rosterSearch = document.getElementById('rosterSearch');
    const rosterSectionFilter = document.getElementById('rosterSectionFilter');

    // Student Modal elements
    const studentModal = document.getElementById('studentModal');
    const modalStudentName = document.getElementById('modalStudentName');
    const modalStudentMeta = document.getElementById('modalStudentMeta');
    const modalProblemsBody = document.getElementById('modalProblemsBody');
    const modalEventsBody = document.getElementById('modalEventsBody');
    const modalCloseBtn = document.getElementById('modalCloseBtn');

    let allStudents = [];
    let refreshInterval = null;

    // Check if we have a saved secret
    const savedSecret = localStorage.getItem('pymentor_admin_secret');
    if (savedSecret) {
        verifyAndLoad(savedSecret);
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const secret = secretInput.value.trim();
        verifyAndLoad(secret);
    });

    logoutBtn.addEventListener('click', () => {
        localStorage.removeItem('pymentor_admin_secret');
        dashboardContent.classList.add('hidden');
        loginOverlay.classList.remove('hidden');
        secretInput.value = '';
        if (refreshInterval) clearInterval(refreshInterval);
    });

    refreshBtn.addEventListener('click', () => {
        const secret = localStorage.getItem('pymentor_admin_secret');
        if (secret) fetchDashboardData(secret);
    });

    // API Key UI toggles
    toggleKeyFormBtn.addEventListener('click', () => {
        apiKeyFormPanel.classList.toggle('hidden');
        apiKeyFeedback.style.display = 'none';
        if (!apiKeyFormPanel.classList.contains('hidden')) {
            newApiKeyInput.focus();
        }
    });

    cancelKeyBtn.addEventListener('click', () => {
        apiKeyFormPanel.classList.add('hidden');
        newApiKeyInput.value = '';
        apiKeyFeedback.style.display = 'none';
    });

    saveApiKeyBtn.addEventListener('click', async () => {
        const secret = localStorage.getItem('pymentor_admin_secret');
        const key = newApiKeyInput.value.trim();
        if (!key) {
            apiKeyFeedback.textContent = "Please enter a valid API key.";
            apiKeyFeedback.style.color = "#ef4444";
            apiKeyFeedback.style.display = "block";
            return;
        }

        saveApiKeyBtn.disabled = true;
        saveApiKeyBtn.textContent = "Saving...";

        try {
            const res = await fetch('/api/config/key', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Admin-Secret': secret
                },
                body: JSON.stringify({ api_key: key })
            });

            const data = await res.json();
            if (res.ok) {
                apiKeyFeedback.textContent = "✓ " + (data.message || "API Key updated successfully!");
                apiKeyFeedback.style.color = "#10b981";
                apiKeyFeedback.style.display = "block";
                newApiKeyInput.value = '';
                setTimeout(() => {
                    apiKeyFormPanel.classList.add('hidden');
                    apiKeyFeedback.style.display = "none";
                    fetchDashboardData(secret);
                }, 1200);
            } else {
                apiKeyFeedback.textContent = data.detail || "Failed to update API key.";
                apiKeyFeedback.style.color = "#ef4444";
                apiKeyFeedback.style.display = "block";
            }
        } catch (err) {
            apiKeyFeedback.textContent = "Network error updating API key.";
            apiKeyFeedback.style.color = "#ef4444";
            apiKeyFeedback.style.display = "block";
        } finally {
            saveApiKeyBtn.disabled = false;
            saveApiKeyBtn.textContent = "Save & Verify Key";
        }
    });

    // Search & Filter in Roster
    rosterSearch.addEventListener('input', () => renderRosterTable());
    rosterSectionFilter.addEventListener('change', () => renderRosterTable());

    // Modal Close
    modalCloseBtn.addEventListener('click', () => {
        studentModal.classList.add('hidden');
    });

    studentModal.addEventListener('click', (e) => {
        if (e.target === studentModal) {
            studentModal.classList.add('hidden');
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !studentModal.classList.contains('hidden')) {
            studentModal.classList.add('hidden');
        }
    });

    async function verifyAndLoad(secret) {
        try {
            const res = await fetch('/api/status', {
                headers: { 'X-Admin-Secret': secret }
            });
            if (res.ok) {
                localStorage.setItem('pymentor_admin_secret', secret);
                loginOverlay.classList.add('hidden');
                dashboardContent.classList.remove('hidden');
                loginError.style.display = 'none';
                fetchDashboardData(secret);
                
                if (refreshInterval) clearInterval(refreshInterval);
                // Auto refresh every 10 seconds
                refreshInterval = setInterval(() => fetchDashboardData(secret), 10000);
            } else {
                localStorage.removeItem('pymentor_admin_secret');
                loginError.style.display = 'block';
                loginOverlay.classList.remove('hidden');
                dashboardContent.classList.add('hidden');
            }
        } catch (e) {
            loginError.textContent = "Cannot connect to server.";
            loginError.style.display = 'block';
        }
    }

    async function fetchDashboardData(secret) {
        try {
            const res = await fetch('/api/admin/dashboard', {
                headers: { 'X-Admin-Secret': secret }
            });
            if (res.ok) {
                const data = await res.json();
                renderDashboard(data);
                document.getElementById('lastUpdated').textContent = "Updated: " + new Date().toLocaleTimeString();
            } else if (res.status === 401) {
                logoutBtn.click(); // invalid secret
            }
        } catch (e) {
            console.error("Dashboard fetch error:", e);
        }
    }

    function renderDashboard(data) {
        // API Key Status Banner
        const keyStatus = data.api_key_status || {};
        if (keyStatus.has_key) {
            apiStatusDot.className = 'api-status-dot dot-green';
            apiStatusTitle.textContent = `Gemini API: Active (${keyStatus.masked_key})`;
            apiStatusSub.textContent = "AI Mentor & Code Simulator ready for student queries.";
        } else {
            apiStatusDot.className = 'api-status-dot dot-red';
            apiStatusTitle.textContent = "Gemini API: Not Configured";
            apiStatusSub.textContent = "Click 'Change API Key' to configure your key and enable AI evaluations.";
        }

        // Platform Metrics
        document.getElementById('valStudents').textContent = data.metrics.total_students || 0;
        const onlineCount = data.metrics.total_online || (data.online_students ? data.online_students.length : 0);
        const valOnlineEl = document.getElementById('valOnline');
        if (valOnlineEl) valOnlineEl.textContent = onlineCount;

        document.getElementById('valRuns').textContent = data.metrics.total_runs || 0;
        document.getElementById('valSubmissions').textContent = data.metrics.total_submissions || 0;
        document.getElementById('valSolved').textContent = data.metrics.total_solved || 0;
        
        let rate = 0;
        if (data.metrics.total_submissions > 0) {
            rate = Math.round((data.metrics.total_solved / data.metrics.total_submissions) * 100);
        }
        document.getElementById('valRate').textContent = rate + '%';

        // Real-Time Online Students Table
        renderOnlineStudents(data.online_students || []);

        // System Metrics
        const sys = data.system_metrics || {};
        document.getElementById('sysRpm').textContent = sys.requests_per_minute || 0;
        document.getElementById('sysCpu').textContent = (sys.cpu_percent || 0) + '%';
        document.getElementById('barCpu').style.width = (sys.cpu_percent || 0) + '%';
        if (sys.cpu_percent > 80) document.getElementById('barCpu').style.background = '#ef4444';
        
        document.getElementById('sysMem').textContent = (sys.memory_percent || 0) + '%';
        document.getElementById('barMem').style.width = (sys.memory_percent || 0) + '%';
        if (sys.memory_percent > 85) document.getElementById('barMem').style.background = '#ef4444';
        
        document.getElementById('sysDisk').textContent = (sys.disk_percent || 0) + '%';
        document.getElementById('barDisk').style.width = (sys.disk_percent || 0) + '%';

        // Model Quotas Table
        renderModelQuotas(data.model_quotas || []);

        // Student Roster
        allStudents = data.students_roster || [];
        renderRosterTable();

        // Toughest Problems
        const toughContainer = document.getElementById('toughestProblemsList');
        toughContainer.innerHTML = '';
        (data.toughest_problems || []).forEach(p => {
            let passRate = p.attempts > 0 ? Math.round((p.correct / p.attempts) * 100) : 0;
            const html = `
                <div class="bar-item">
                    <div class="bar-label">
                        <span>${escapeHtml(p.title)}</span>
                        <span>${p.attempts} attempts (${passRate}% pass)</span>
                    </div>
                    <div class="bar-bg">
                        <div class="bar-fill" style="width: ${passRate}%; background: ${passRate < 50 ? '#ef4444' : '#f59e0b'};"></div>
                    </div>
                </div>
            `;
            toughContainer.insertAdjacentHTML('beforeend', html);
        });

        // Guidance Usage
        const guideContainer = document.getElementById('guidanceUsageList');
        guideContainer.innerHTML = '';
        let totalSessions = (data.guidance_usage || []).reduce((sum, g) => sum + g.c, 0);
        const levelNames = {1: "Level 1 (Hints)", 2: "Level 2 (Logic)", 3: "Level 3 (Code)"};
        
        (data.guidance_usage || []).forEach(g => {
            let p = totalSessions > 0 ? Math.round((g.c / totalSessions) * 100) : 0;
            let name = levelNames[g.help_level] || `Level ${g.help_level}`;
            const html = `
                <div class="bar-item">
                    <div class="bar-label">
                        <span>${name}</span>
                        <span>${p}% (${g.c})</span>
                    </div>
                    <div class="bar-bg">
                        <div class="bar-fill" style="width: ${p}%; background: ${g.help_level === 3 ? '#ef4444' : '#3b82f6'};"></div>
                    </div>
                </div>
            `;
            guideContainer.insertAdjacentHTML('beforeend', html);
        });

        // Live Feed
        const feedContainer = document.getElementById('liveFeed');
        feedContainer.innerHTML = '';
        (data.recent_activity || []).forEach(a => {
            const time = formatLocalTime(a.created_at);
            const badgeClass = a.is_correct ? 'badge-success' : 'badge-fail';
            const badgeText = a.is_correct ? 'PASSED' : 'FAILED';
            const levelText = a.help_level > 1 ? ` (Help L${a.help_level})` : '';
            const modelText = a.model_used ? ` [${escapeHtml(a.model_used)}]` : '';
            
            const html = `
                <div class="feed-item">
                    <div class="feed-main">
                        <span class="feed-name">${escapeHtml(a.name)} <span style="color:#64748b; font-weight:normal;">submitted</span> ${escapeHtml(a.title)}</span>
                        <span class="feed-meta">${time}${levelText}${modelText}</span>
                    </div>
                    <span class="feed-badge ${badgeClass}">${badgeText}</span>
                </div>
            `;
            feedContainer.insertAdjacentHTML('beforeend', html);
        });
    }

    function renderModelQuotas(quotas) {
        const tbody = document.getElementById('quotasTableBody');
        tbody.innerHTML = '';

        if (!quotas || quotas.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #64748b;">No quota data available</td></tr>`;
            return;
        }

        quotas.forEach(q => {
            let pillClass = 'pill-ready';
            if (q.status.includes('Cooling')) pillClass = 'pill-cooling';
            else if (q.status.includes('Blocked') || q.status.includes('Exhausted')) pillClass = 'pill-blocked';

            const pct = q.day_limit > 0 ? Math.min(100, Math.round((q.day_used / q.day_limit) * 100)) : 0;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 600; font-family: 'Fira Code', monospace; color: #f1f5f9;">${escapeHtml(q.model)}</td>
                <td><span class="pill pill-tier">${escapeHtml(q.tier)}</span></td>
                <td>
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 0.3rem;">
                        <span>${q.day_used} / ${q.day_limit} reqs</span>
                        <span style="color: #94a3b8;">${pct}%</span>
                    </div>
                    <div class="bar-bg" style="height: 6px;">
                        <div class="bar-fill" style="width: ${pct}%; background: ${pct > 85 ? '#ef4444' : '#38bdf8'};"></div>
                    </div>
                </td>
                <td style="font-family: 'Fira Code', monospace;">${q.rpm_active} / ${q.rpm_limit}</td>
                <td><span class="pill ${pillClass}">${escapeHtml(q.status)}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    function renderOnlineStudents(list) {
        const tbody = document.getElementById('onlineStudentsBody');
        const badgeCount = document.getElementById('onlineBadgeCount');
        if (!tbody) return;

        if (badgeCount) {
            badgeCount.textContent = `${list.length} Online Now`;
            badgeCount.className = list.length > 0 ? 'pill pill-ready' : 'pill';
        }

        tbody.innerHTML = '';
        if (!list || list.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #64748b; padding: 2rem;">No students are currently in active practice sessions.</td></tr>`;
            return;
        }

        list.forEach(s => {
            const secAgo = s.seconds_ago !== undefined && s.seconds_ago !== null ? s.seconds_ago : 0;
            const seenText = secAgo <= 15 ? 'Active just now' : `${secAgo}s ago`;
            const duration = formatDuration(s.time_spent_seconds || 0);

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 600; color: #f1f5f9;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="pulse-dot"></span>
                        <span>${escapeHtml(s.student_name)}</span>
                    </div>
                </td>
                <td><span class="pill" style="background: rgba(148, 163, 184, 0.15); color: #cbd5e1;">Sec ${escapeHtml(s.section)}</span></td>
                <td style="font-family: 'Fira Code', monospace;">${escapeHtml(s.roll_no)}</td>
                <td>
                    <span class="pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 600;">
                        ${escapeHtml(s.problem_title)}
                    </span>
                    <span style="font-size: 0.78rem; color: #94a3b8; margin-left: 0.4rem;">(${escapeHtml(s.problem_topic)})</span>
                </td>
                <td style="color: #38bdf8; font-family: 'Fira Code', monospace; font-weight: 600;">⏱ ${duration}</td>
                <td style="color: #38bdf8; font-weight: 700;">${s.run_count || 0}</td>
                <td style="font-size: 0.8rem; color: #10b981; font-weight: 600;">${seenText}</td>
                <td>
                    <button class="btn-action btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.78rem;" onclick="window.inspectStudent(${s.student_id})">
                        Inspect
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    function formatDuration(sec) {
        if (!sec || sec <= 0) return '0s';
        if (sec < 60) return `${sec}s`;
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        if (m < 60) return `${m}m ${s > 0 ? s + 's' : ''}`.trim();
        const h = Math.floor(m / 60);
        const remM = m % 60;
        return `${h}h ${remM > 0 ? remM + 'm' : ''}`.trim();
    }

    function parseLocalDate(str) {
        if (!str) return null;
        const s = String(str).replace(' ', 'T');
        const d = new Date(s);
        return isNaN(d.getTime()) ? null : d;
    }

    function formatLocalTime(str) {
        const d = parseLocalDate(str);
        return d ? d.toLocaleTimeString() : '-';
    }

    function formatLocalDateTime(str) {
        const d = parseLocalDate(str);
        return d ? d.toLocaleString() : '-';
    }

    function formatLocalDateOnly(str) {
        const d = parseLocalDate(str);
        return d ? d.toLocaleDateString() : '-';
    }

    function renderRosterTable() {
        const query = rosterSearch.value.trim().toLowerCase();
        const section = rosterSectionFilter.value;

        const filtered = allStudents.filter(s => {
            const matchesQuery = !query || s.name.toLowerCase().includes(query) || s.roll_no.toLowerCase().includes(query);
            const matchesSection = !section || s.section === section;
            return matchesQuery && matchesSection;
        });

        rosterCount.textContent = `${filtered.length} of ${allStudents.length} Students`;
        rosterTableBody.innerHTML = '';

        if (filtered.length === 0) {
            rosterTableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: #64748b; padding: 2rem;">No students found matching your filters.</td></tr>`;
            return;
        }

        filtered.forEach(s => {
            const lastActiveTime = s.last_active ? formatLocalDateTime(s.last_active) : 'Never';
            const statusBadge = s.is_online
                ? `<span class="pill" style="background: rgba(16, 185, 129, 0.2); color: #10b981; font-size: 0.72rem; padding: 2px 7px; margin-left: 6px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;"><span class="pulse-dot" style="width:6px; height:6px;"></span>Online</span>`
                : `<span class="pill" style="background: rgba(148, 163, 184, 0.08); color: #64748b; font-size: 0.72rem; padding: 2px 7px; margin-left: 6px;">Offline</span>`;
            
            const currentProblemHtml = s.is_online && s.current_problem
                ? `<div style="font-size: 0.75rem; color: #38bdf8; margin-top: 3px; font-weight: 500;">Solving: ${escapeHtml(s.current_problem)}</div>`
                : '';

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 600; color: #f1f5f9;">
                    <div style="display: flex; align-items: center;">
                        <span>${escapeHtml(s.name)}</span>
                        ${statusBadge}
                    </div>
                    ${currentProblemHtml}
                </td>
                <td><span class="pill" style="background: rgba(148, 163, 184, 0.15); color: #cbd5e1;">Sec ${escapeHtml(s.section)}</span></td>
                <td style="font-family: 'Fira Code', monospace;">${escapeHtml(s.roll_no)}</td>
                <td style="font-weight: 600;">${s.problems_attempted}</td>
                <td style="color: #10b981; font-weight: 700;">${s.problems_solved}</td>
                <td style="color: #38bdf8; font-weight: 600;">${s.total_runs || 0}</td>
                <td style="color: #a78bfa; font-weight: 600;">${s.total_submissions || 0}</td>
                <td style="color: #38bdf8; font-family: 'Fira Code', monospace; font-size: 0.85rem; font-weight: 600;">${formatDuration(s.total_time_spent || 0)}</td>
                <td style="font-size: 0.8rem; color: #94a3b8;">${lastActiveTime}</td>
                <td>
                    <button class="btn-action btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.78rem;" onclick="window.inspectStudent(${s.id})">
                        Inspect Telemetry
                    </button>
                </td>
            `;
            rosterTableBody.appendChild(tr);
        });
    }

    // Expose student inspection globally for onclick
    window.inspectStudent = async function(studentId) {
        const secret = localStorage.getItem('pymentor_admin_secret');
        if (!secret) return;

        modalStudentName.textContent = "Loading student telemetry...";
        modalStudentMeta.textContent = "";
        modalProblemsBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #64748b; padding: 1.5rem;">Fetching telemetry data...</td></tr>`;
        modalEventsBody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: #64748b; padding: 1.5rem;">Fetching event stream...</td></tr>`;
        studentModal.classList.remove('hidden');

        try {
            const res = await fetch(`/api/admin/student/${studentId}`, {
                headers: { 'X-Admin-Secret': secret }
            });
            if (res.ok) {
                const data = await res.json();
                renderStudentModal(data);
            } else {
                modalStudentName.textContent = "Error loading student telemetry";
            }
        } catch (err) {
            console.error("Error inspecting student:", err);
            modalStudentName.textContent = "Network error loading student details";
        }
    };

    function renderStudentModal(data) {
        const st = data.student;
        modalStudentName.textContent = `${st.name}`;
        modalStudentMeta.textContent = `Section ${st.section} | Roll No: ${st.roll_no} | Registered: ${formatLocalDateOnly(st.created_at)}`;

        // Problems breakdown
        modalProblemsBody.innerHTML = '';
        if (!data.problems || data.problems.length === 0) {
            modalProblemsBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #64748b; padding: 1.5rem;">No problem attempts logged yet.</td></tr>`;
        } else {
            data.problems.forEach(p => {
                const isSolved = p.status === 'solved';
                const badge = isSolved 
                    ? `<span class="pill pill-ready">Solved</span>` 
                    : `<span class="pill pill-cooling">In Progress</span>`;
                const updated = p.updated_at ? formatLocalDateTime(p.updated_at) : '-';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="font-weight: 600; color: #f1f5f9;">${escapeHtml(p.title)}</td>
                    <td style="font-size: 0.85rem; color: #94a3b8;">${escapeHtml(p.topic)}</td>
                    <td>${badge}</td>
                    <td style="color: #38bdf8; font-weight: 700;">${p.run_count || 0}</td>
                    <td style="color: #a78bfa; font-weight: 700;">${p.guidance_count || 0}</td>
                    <td style="color: #38bdf8; font-family: 'Fira Code', monospace; font-size: 0.85rem; font-weight: 600;">${formatDuration(p.time_spent_seconds || 0)}</td>
                    <td style="font-family: 'Fira Code', monospace; font-size: 0.8rem; color: #cbd5e1;">${escapeHtml(p.last_model_used || 'None')}</td>
                    <td style="font-size: 0.8rem; color: #94a3b8;">${updated}</td>
                `;
                modalProblemsBody.appendChild(tr);
            });
        }

        // Events clickstream
        modalEventsBody.innerHTML = '';
        if (!data.events || data.events.length === 0) {
            modalEventsBody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: #64748b; padding: 1.5rem;">No recent clickstream events captured yet.</td></tr>`;
        } else {
            data.events.forEach(ev => {
                let metaText = '-';
                try {
                    const parsed = JSON.parse(ev.event_data || '{}');
                    metaText = JSON.stringify(parsed).replace(/[{}"]/g, ' ').trim();
                } catch(e) {
                    metaText = ev.event_data;
                }

                const evBadge = `<span class="pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-family: 'Fira Code', monospace;">${escapeHtml(ev.event_type)}</span>`;
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${evBadge}</td>
                    <td style="font-size: 0.85rem; font-family: 'Fira Code', monospace; color: #cbd5e1;">${escapeHtml(metaText)}</td>
                    <td style="font-size: 0.8rem; color: #94a3b8;">${formatLocalTime(ev.created_at)}</td>
                `;
                modalEventsBody.appendChild(tr);
            });
        }
    }

    function escapeHtml(unsafe) {
        if (!unsafe) return "";
        return unsafe
             .toString()
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }
});
