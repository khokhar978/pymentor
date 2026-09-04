/**
 * Python Practice — Practice Page (app.js)
 * Features:
 * - Monaco Editor with auto-save to localStorage and server database
 * - Real-time Pyodide execution in background Web Worker
 * - Interactive inline CMD/terminal input: real <input> element right in the output stream
 * - AI Mentor Guidance (Get Guidance button) synced with actual terminal session output
 */

const state = {
    student:          null,
    problemId:        null,
    problem:          null,
    sessionId:        null,
    helpLevel:        1,
    attemptsCount:    0,
    isRunning:        false,
    isGuidanceLoading: false,
    lastOutput:       null,
    editor:           null
};

const el = {
    // Header
    studentBadge:        document.getElementById('studentBadge'),
    studentNameDisplay:  document.getElementById('studentNameDisplay'),
    studentSecDisplay:   document.getElementById('studentSecDisplay'),
    switchStudentBtn:    document.getElementById('switchStudentBtn'),
    headerProblemTitle:  document.getElementById('headerProblemTitle'),

    // Problem panel
    difficultyBadge:     document.getElementById('difficultyBadge'),
    topicBadge:          document.getElementById('topicBadge'),
    problemTitle:        document.getElementById('problemTitle'),
    problemDescription:  document.getElementById('problemDescription'),
    sampleInputText:     document.getElementById('sampleInputText'),
    sampleOutputText:    document.getElementById('sampleOutputText'),
    conceptsList:        document.getElementById('conceptsList'),
    copyInputBtn:        document.getElementById('copyInputBtn'),
    attemptCounter:      document.getElementById('attemptCounter'),
    timeCounter:         document.getElementById('timeCounter'),

    // Toolbar
    levelSelect:         document.getElementById('levelSelect'),
    runBtn:              document.getElementById('runBtn'),
    runText:             document.getElementById('runText'),
    runSpinner:          document.getElementById('runSpinner'),
    guidanceBtn:         document.getElementById('guidanceBtn'),
    guidanceText:        document.getElementById('guidanceText'),
    guidanceSpinner:     document.getElementById('guidanceSpinner'),
    attemptBadge:        document.getElementById('attemptBadge'),

    // Panels
    outputBody:          document.getElementById('outputBody'),
    outputStatus:        document.getElementById('outputStatus'),
    guidanceBody:        document.getElementById('guidanceBody'),
    guidanceStatus:      document.getElementById('guidanceStatus'),


};

// ──────────────────────────────────────────────
// PYODIDE WORKER & TERMINAL STATE
// ──────────────────────────────────────────────
let pyodideWorker = null;
let controlBuffer = null;
let dataBuffer = null;
let controlArray = null;
let dataArray = null;
let isPyodideReady = false;
let activeInputEl = null;
let pendingRunCode = null;
const textEncoder = new TextEncoder();

// ──────────────────────────────────────────────
// INIT
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    initMonaco();
    setupListeners();
    loadStudentIdentity();
    initPyodideWorker();
    initHeartbeat();

    const params = new URLSearchParams(window.location.search);
    const pid = params.get('problem');
    if (pid) {
        state.problemId = parseInt(pid, 10);
        await loadProblem(state.problemId);
    } else {
        el.headerProblemTitle.textContent = 'No problem selected';
        el.problemTitle.textContent = 'No problem selected';
        el.problemDescription.textContent = 'Please go back to the Problems page and select a problem.';
    }
});

// ──────────────────────────────────────────────
// PYODIDE WORKER INITIALIZATION
// ──────────────────────────────────────────────
function initPyodideWorker() {
    el.outputStatus.textContent = 'Loading Python...';
    el.outputStatus.className = 'status-pending';

    if (typeof SharedArrayBuffer !== 'undefined') {
        controlBuffer = new SharedArrayBuffer(32); // 8 x 4 bytes
        dataBuffer = new SharedArrayBuffer(65536);  // 64 KB input buffer
        controlArray = new Int32Array(controlBuffer);
        dataArray = new Uint8Array(dataBuffer);
    } else {
        console.warn('SharedArrayBuffer not available. Native window.crossOriginIsolated is:', window.crossOriginIsolated);
    }

    try {
        pyodideWorker = new Worker('/js/pyodide-worker.js');
        pyodideWorker.postMessage({
            type: 'init',
            controlBuffer,
            dataBuffer
        });

        pyodideWorker.onmessage = handleWorkerMessage;
        pyodideWorker.onerror = (err) => {
            console.error('Worker error:', err);
            el.outputStatus.textContent = 'Runtime Error';
            el.outputStatus.className = 'status-progress';
        };
    } catch (e) {
        console.error('Failed to start worker:', e);
        el.outputStatus.textContent = 'Engine Offline';
    }
}

function handleWorkerMessage(e) {
    const msg = e.data;
    if (msg.type === 'ready') {
        isPyodideReady = true;
        el.outputStatus.innerHTML = '<span class="status-solved">Ready</span>';

        // If user clicked Run while Python was downloading, execute now
        if (pendingRunCode) {
            const codeToRun = pendingRunCode;
            pendingRunCode = null;
            executePyodide(codeToRun);
        }
    } else if (msg.type === 'status') {
        el.outputStatus.textContent = msg.message;
        el.outputStatus.className = 'status-pending';
    } else if (msg.type === 'stdout') {
        appendTerminalText(msg.text, false);
    } else if (msg.type === 'stderr') {
        appendTerminalText(msg.text, true);
    } else if (msg.type === 'await_input') {
        promptForTerminalInput(msg.prompt);
    } else if (msg.type === 'finished') {
        finishExecution(msg.has_error);
    } else if (msg.type === 'init_error') {
        el.outputStatus.textContent = 'Load Failed';
        el.outputStatus.className = 'status-progress';
        el.outputBody.innerHTML = '<span style="color:var(--text-terminal-error)">Error loading Python runtime: ' + (msg.error || 'Unknown error') + '</span>';
        console.error('Pyodide init error:', msg.error);
    }
}

// ──────────────────────────────────────────────
// INTERACTIVE TERMINAL OUTPUT & INPUT
// ──────────────────────────────────────────────
function appendTerminalText(text, isError = false) {
    // Clear placeholder if present
    const placeholder = el.outputBody.querySelector('.output-placeholder');
    if (placeholder) {
        el.outputBody.innerHTML = '';
    }

    if (isError) {
        const span = document.createElement('span');
        span.style.color = 'var(--text-terminal-error)';
        span.textContent = text;
        el.outputBody.appendChild(span);
    } else {
        const textNode = document.createTextNode(text);
        el.outputBody.appendChild(textNode);
    }

    el.outputBody.scrollTop = el.outputBody.scrollHeight;
}

function promptForTerminalInput(promptText) {
    // Fallback if SharedArrayBuffer is unavailable in browser
    if (!controlArray || !dataArray) {
        const val = window.prompt(promptText || 'Enter input:') || '';
        appendTerminalText(val + '\n', false);
        return;
    }

    // Create a real <input> element directly inside the terminal output line
    const inputEl = document.createElement('input');
    inputEl.type = 'text';
    inputEl.className = 'terminal-inline-input';
    inputEl.autocomplete = 'off';
    inputEl.spellcheck = false;

    el.outputBody.appendChild(inputEl);
    activeInputEl = inputEl;

    // Auto-adjust width as user types
    inputEl.addEventListener('input', () => {
        inputEl.style.width = Math.max(80, (inputEl.value.length + 1) * 8.5) + 'px';
    });

    // Handle Enter to submit input
    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            submitTerminalInput(inputEl);
        }
    });

    // Immediate focus with slight delay to ensure DOM attachment
    setTimeout(() => {
        inputEl.focus();
        el.outputBody.scrollTop = el.outputBody.scrollHeight;
    }, 10);
}

function submitTerminalInput(inputEl) {
    const rawVal = (inputEl.value || '').replace(/[\r\n]/g, '');

    // Replace the input box with a static terminal text node + newline
    const enteredSpan = document.createElement('span');
    enteredSpan.className = 'terminal-entered';
    enteredSpan.textContent = rawVal;

    const newline = document.createTextNode('\n');

    if (inputEl.parentNode) {
        inputEl.parentNode.insertBefore(enteredSpan, inputEl);
        inputEl.parentNode.insertBefore(newline, inputEl);
        inputEl.parentNode.removeChild(inputEl);
    }
    activeInputEl = null;

    // Write bytes into SharedArrayBuffer and notify worker thread to resume
    const encoded = textEncoder.encode(rawVal);
    dataArray.set(encoded);
    Atomics.store(controlArray, 1, encoded.length);
    Atomics.store(controlArray, 0, 2); // state: INPUT_READY
    Atomics.notify(controlArray, 0, 1); // wake up worker!

    el.outputBody.scrollTop = el.outputBody.scrollHeight;
}

// ──────────────────────────────────────────────
// RUN CODE (EXECUTION & AUTO-SAVING)
// ──────────────────────────────────────────────
async function runCode() {
    if (state.isRunning) return;
    if (!state.student) { openModal(true); return; }
    if (!state.sessionId) { await startSession(); }

    const code = state.editor ? state.editor.getValue() : '';
    if (!code.trim()) {
        el.outputBody.innerHTML = '<span style="color:var(--text-terminal-error)">[Please write some Python code first.]</span>';
        return;
    }

    // Save to localStorage immediately
    if (state.problemId) {
        localStorage.setItem('pymentor_draft_' + state.problemId, code);
    }

    // Auto-save to server database in background
    if (state.sessionId) {
        fetch('/api/session/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.student.token },
            body: JSON.stringify({ session_id: state.sessionId, code })
        }).catch(err => console.warn('Background auto-save error:', err));
    }

    // If Pyodide is still downloading, queue execution and notify user
    if (!isPyodideReady) {
        pendingRunCode = code;
        state.isRunning = true;
        el.runBtn.disabled = true;
        el.runText.textContent = 'Loading...';
        el.runSpinner.classList.remove('hidden');
        el.outputBody.innerHTML = '<span style="color:var(--text-faint)">Python runtime is initializing (first load takes a few seconds)... code will run automatically when ready.</span>';
        return;
    }

    executePyodide(code);
}

function executePyodide(code) {
    state.isRunning = true;
    el.runBtn.disabled = true;
    el.runText.textContent = 'Running...';
    el.runSpinner.classList.remove('hidden');

    // Clear output terminal
    el.outputBody.innerHTML = '';
    el.outputStatus.className = 'status-pending';
    el.outputStatus.textContent = 'Running...';

    // Dispatch code execution to Web Worker
    pyodideWorker.postMessage({ type: 'run', code });
}

function finishExecution(hasError) {
    state.isRunning = false;
    el.runBtn.disabled = false;
    el.runText.textContent = 'Run';
    el.runSpinner.classList.add('hidden');

    el.outputStatus.className = hasError ? 'status-progress' : 'status-solved';
    el.outputStatus.textContent = hasError ? 'Error' : 'OK';

    // Capture complete terminal content for AI Mentor context
    state.lastOutput = el.outputBody.innerText.trim();
}

// ──────────────────────────────────────────────
// MONACO EDITOR
// ──────────────────────────────────────────────
function initMonaco() {
    require.config({
        paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }
    });
    require(['vs/editor/editor.main'], function () {
        state.editor = monaco.editor.create(document.getElementById('monacoEditor'), {
            value: '# Write your Python code here\n\n',
            language: 'python',
            theme: 'vs-dark',
            fontSize: 13.5,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            tabSize: 4,
            insertSpaces: true,
            automaticLayout: true,
            minimap: { enabled: false },
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            cursorBlinking: 'smooth',
            padding: { top: 12, bottom: 12 },
            wordWrap: 'off',
        });

        // Auto-save code edits to localStorage on every change
        state.editor.onDidChangeModelContent(() => {
            if (state.problemId) {
                const currentCode = state.editor.getValue();
                localStorage.setItem('pymentor_draft_' + state.problemId, currentCode);
            }
        });

        // Ctrl+Enter = Run
        state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
            if (!state.isRunning) runCode();
        });
    });
}

// ──────────────────────────────────────────────
// LISTENERS
// ──────────────────────────────────────────────
function setupListeners() {
    const handleProfileClick = () => {
        if (state.student) {
            window.location.href = '/profile';
        } else {
            const next = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.href = '/login?next=' + next;
        }
    };
    if (el.switchStudentBtn) el.switchStudentBtn.addEventListener('click', handleProfileClick);
    if (el.studentBadge) el.studentBadge.addEventListener('click', handleProfileClick);
    el.levelSelect.addEventListener('change', () => {
        state.helpLevel = parseInt(el.levelSelect.value, 10);
    });
    el.runBtn.addEventListener('click', runCode);
    el.guidanceBtn.addEventListener('click', getGuidance);
    el.copyInputBtn.addEventListener('click', () => {
        if (!state.problem) return;
        navigator.clipboard.writeText(state.problem.sample_input || '').then(() => {
            el.copyInputBtn.textContent = 'Copied!';
            setTimeout(() => { el.copyInputBtn.textContent = 'Copy'; }, 1500);
        });
    });

    // Clicking anywhere in the terminal re-focuses active inline input
    el.outputBody.addEventListener('click', () => {
        if (activeInputEl) {
            activeInputEl.focus();
        }
    });
}

// ──────────────────────────────────────────────
// STUDENT IDENTITY
// ──────────────────────────────────────────────
function loadStudentIdentity() {
    const saved = localStorage.getItem('pymentor_student');
    if (saved) {
        try { 
            state.student = JSON.parse(saved); 
            updateStudentDisplay(); 
            return; 
        }
        catch (e) {
            localStorage.removeItem('pymentor_student');
        }
    }
    updateStudentDisplay();
    // Redirect to login page preserving destination
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = '/login?next=' + next;
}

function updateStudentDisplay() {
    if (!state.student) {
        if (el.studentNameDisplay) el.studentNameDisplay.textContent = 'Not Logged In';
        if (el.studentSecDisplay) el.studentSecDisplay.textContent = 'Click to Log In';
        if (el.switchStudentBtn) el.switchStudentBtn.textContent = 'Log In';
        return;
    }
    if (el.studentNameDisplay) el.studentNameDisplay.textContent = state.student.name + ` (Roll ${state.student.roll_no})`;
    if (el.studentSecDisplay) el.studentSecDisplay.textContent = 'Sec ' + state.student.section;
    if (el.switchStudentBtn) el.switchStudentBtn.textContent = 'Profile';
}

// ──────────────────────────────────────────────
// PROBLEM LOADING
// ──────────────────────────────────────────────
async function loadProblem(problemId) {
    try {
        const res = await fetch('/api/problems/' + problemId);
        if (!res.ok) throw new Error('Problem not found');
        state.problem = await res.json();
        renderProblem(state.problem);
        if (state.student) await startSession();
    } catch (err) {
        el.problemTitle.textContent       = 'Error loading problem';
        el.problemDescription.textContent = err.message;
    }
}

function renderProblem(p) {
    el.headerProblemTitle.textContent  = p.title;
    el.problemTitle.textContent        = p.title;
    el.problemDescription.textContent  = p.description;
    el.sampleInputText.textContent     = p.sample_input  || '(none)';
    el.sampleOutputText.textContent    = p.sample_output || '(none)';

    const diff = (p.difficulty || 'easy').toLowerCase();
    el.difficultyBadge.textContent = p.difficulty;
    el.difficultyBadge.className   = 'difficulty-badge ' + diff;

    el.topicBadge.textContent = p.topic;

    el.conceptsList.innerHTML = '';
    (p.concepts || []).forEach(c => {
        const tag = document.createElement('span');
        tag.className   = 'concept-tag';
        tag.textContent = c;
        el.conceptsList.appendChild(tag);
    });

    // Check if student has an unsaved local draft first
    const savedDraft = localStorage.getItem('pymentor_draft_' + p.id);
    if (savedDraft && savedDraft.trim() && state.editor) {
        state.editor.setValue(savedDraft);
    } else if (state.editor) {
        state.editor.setValue(p.starter_code || '# Write your Python code here\n\n');
    }

    document.title = p.title + ' | Python Practice';
}

// ──────────────────────────────────────────────
// SESSION
// ──────────────────────────────────────────────
async function startSession() {
    if (!state.student || !state.problemId) return;
    try {
        const res = await fetch('/api/session/start', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.student.token },
            body: JSON.stringify({
                problem_id:  state.problemId,
                help_level:  state.helpLevel
            })
        });
        const session = await res.json();
        state.sessionId     = session.session_id;
        state.attemptsCount = session.attempts_count || 0;
        updateAttemptDisplay();

        // Restore saved code: check local draft first, then server database last_code
        const savedDraft = localStorage.getItem('pymentor_draft_' + state.problemId);
        if (savedDraft && savedDraft.trim() && state.editor) {
            state.editor.setValue(savedDraft);
        } else if (session.last_code && session.last_code.trim() && state.editor) {
            state.editor.setValue(session.last_code);
            localStorage.setItem('pymentor_draft_' + state.problemId, session.last_code);
        }

        if (session.is_solved) {
            el.guidanceStatus.innerHTML = '<span class="status-solved">Solved &#10003;</span>';
        }

        // Initialize practice timer
        startActiveTimer(session.time_spent_seconds || 0, session.is_solved);
    } catch (err) { console.error('Session error:', err); }
}

function updateAttemptDisplay() {
    const text = 'Attempt #' + (state.attemptsCount + 1);
    el.attemptCounter.textContent = text;
    el.attemptBadge.textContent   = text;
}

// ──────────────────────────────────────────────
// GET GUIDANCE (calls /api/session/submit)
// ──────────────────────────────────────────────
async function getGuidance() {
    if (state.isGuidanceLoading) return;
    if (!state.student) { openModal(true); return; }
    if (!state.sessionId) { await startSession(); }

    const code = state.editor ? state.editor.getValue() : '';
    if (!code.trim()) {
        el.guidanceBody.innerHTML = '<div class="placeholder-text">Write some code first before requesting guidance.</div>';
        return;
    }

    // Auto-save code
    if (state.problemId) {
        localStorage.setItem('pymentor_draft_' + state.problemId, code);
    }

    state.isGuidanceLoading = true;
    el.guidanceBtn.disabled      = true;
    el.guidanceText.textContent  = 'Loading...';
    el.guidanceSpinner.classList.remove('hidden');

    el.guidanceBody.innerHTML   = '<div class="loading-guidance"><div class="spinner-dark"></div>&nbsp;Analyzing your code...</div>';
    el.guidanceStatus.className   = 'status-pending';
    el.guidanceStatus.textContent = '...';

    try {
        const res = await fetch('/api/session/submit', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.student.token },
            body: JSON.stringify({
                session_id:       state.sessionId,
                code,
                help_level:       state.helpLevel,
                simulated_output: state.lastOutput || null
            })
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Request failed'); }
        const result = await res.json();

        state.attemptsCount = result.attempt_number || (state.attemptsCount + 1);
        updateAttemptDisplay();

        el.guidanceBody.innerHTML = marked.parse(result.feedback || '');
        el.guidanceBody.scrollTop = 0;

        if (result.is_correct) {
            isProblemCurrentlySolved = true;
            if (result.time_spent_seconds) {
                currentSessionSeconds = result.time_spent_seconds;
            }
            if (activeTimerInterval) clearInterval(activeTimerInterval);
            updateTimerDisplay();
            el.guidanceStatus.innerHTML = '<span class="status-solved">Solved &#10003;</span>';
            triggerConfetti();
        } else {
            el.guidanceStatus.innerHTML = '<span class="status-progress">In Progress</span>';
        }
    } catch (err) {
        el.guidanceBody.innerHTML   = '<div style="color:var(--error);font-size:13px;padding:4px;">' + err.message + '</div>';
        el.guidanceStatus.className   = 'status-pending';
        el.guidanceStatus.textContent = 'Error';
    } finally {
        state.isGuidanceLoading = false;
        el.guidanceBtn.disabled      = false;
        el.guidanceText.textContent  = 'Get Guidance';
        el.guidanceSpinner.classList.add('hidden');
    }
}

// ──────────────────────────────────────────────
// CONFETTI
// ──────────────────────────────────────────────
function triggerConfetti() {
    if (typeof confetti !== 'undefined') {
        confetti({ particleCount: 100, spread: 70, origin: { y: 0.6 } });
    }
}

// ──────────────────────────────────────────────
// SERVER-AUTHORITATIVE HEARTBEAT (ACTIVE TIME TRACKING)
// ──────────────────────────────────────────────
let lastUserActivityTime = Date.now();
let heartbeatInterval = null;

function initHeartbeat() {
    const markActive = () => {
        lastUserActivityTime = Date.now();
    };

    ['keydown', 'mousedown', 'mousemove', 'scroll', 'touchstart'].forEach(evt => {
        window.addEventListener(evt, markActive, { passive: true });
    });

    if (state.editor) {
        state.editor.onDidChangeModelContent(markActive);
    }

    // Check & send heartbeat every 15 seconds
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(sendHeartbeat, 15000);

    // Re-anchor clock when returning to tab
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            markActive();
            sendHeartbeat();
        }
    });
}

async function sendHeartbeat() {
    // Only send heartbeat if:
    // 1. Student is logged in with active session
    // 2. Tab is currently visible/focused
    // 3. User interacted in the last 60 seconds (not idle/away)
    if (!state.student || !state.sessionId) return;
    if (document.hidden) return;
    if (Date.now() - lastUserActivityTime > 60000) return;

    try {
        const res = await fetch('/api/session/heartbeat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + state.student.token
            },
            body: JSON.stringify({ session_id: state.sessionId })
        });
        if (res.ok) {
            const data = await res.json();
            if (data.total_time_spent && !isProblemCurrentlySolved) {
                currentSessionSeconds = data.total_time_spent;
                updateTimerDisplay();
            }
        }
    } catch (err) {
        // Silently catch background heartbeat network hiccups
    }
}

// ──────────────────────────────────────────────
// ACTIVE TIMER DISPLAY
// ──────────────────────────────────────────────
let activeTimerInterval = null;
let currentSessionSeconds = 0;
let isProblemCurrentlySolved = false;

function startActiveTimer(initialSeconds, isSolved) {
    currentSessionSeconds = initialSeconds || 0;
    isProblemCurrentlySolved = Boolean(isSolved);
    updateTimerDisplay();

    if (activeTimerInterval) clearInterval(activeTimerInterval);

    // Only keep ticking if problem not yet solved
    if (!isProblemCurrentlySolved) {
        activeTimerInterval = setInterval(() => {
            // Tick when tab is active and user has interacted in last 60s
            if (!document.hidden && (Date.now() - lastUserActivityTime <= 60000)) {
                currentSessionSeconds++;
                updateTimerDisplay();
            }
        }, 1000);
    }
}

function updateTimerDisplay() {
    if (!el.timeCounter) return;
    const m = Math.floor(currentSessionSeconds / 60);
    const s = currentSessionSeconds % 60;
    const timeStr = m > 0 ? `${m}m ${s < 10 ? '0' : ''}${s}s` : `${s}s`;

    if (isProblemCurrentlySolved) {
        el.timeCounter.textContent = `✓ Solved in ${timeStr}`;
        el.timeCounter.className = 'time-pill solved';
        el.timeCounter.title = `Problem solved in ${timeStr}`;
    } else {
        el.timeCounter.textContent = `⏱ ${timeStr}`;
        el.timeCounter.className = 'time-pill';
        el.timeCounter.title = `Active practice time: ${timeStr}`;
    }
}
