import { getCurrentStudent, requireAuth } from './shared/auth.js';
import { apiFetch } from './shared/api.js';

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
    editor:           null,
    pendingCode:      null
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
let suggestionsEnabled = localStorage.getItem('pymentor_suggestions_enabled') !== 'false';

// ──────────────────────────────────────────────
// INIT
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    restorePanelDimensions();
    initResizablePanels();
    initMonaco();
    setupListeners();
    loadStudentIdentity();
    await loadDefaultHelpLevel();
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
        pyodideWorker = new Worker('/js/pyodide-worker.js?v=3.1');
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
    inputEl.placeholder = 'Type here & press Enter ↵';
    inputEl.autocomplete = 'off';
    inputEl.spellcheck = false;

    el.outputBody.appendChild(inputEl);
    activeInputEl = inputEl;

    // Auto-adjust width as user types
    function adjustWidth() {
        const textLen = Math.max((inputEl.value || '').length + 1, (inputEl.placeholder || '').length);
        inputEl.style.width = Math.max(170, textLen * 8.5) + 'px';
    }
    adjustWidth();
    inputEl.addEventListener('input', () => {
        adjustWidth();
        startTimerOnActivity();
    });

    // Handle Enter to submit input
    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            submitTerminalInput(inputEl);
        }
    });

    // Multi-tier focus to maximize compatibility across Safari, Chrome, and Firefox
    inputEl.focus();
    requestAnimationFrame(() => {
        inputEl.focus();
        el.outputBody.scrollTop = el.outputBody.scrollHeight;
    });
    setTimeout(() => {
        inputEl.focus();
        el.outputBody.scrollTop = el.outputBody.scrollHeight;
    }, 20);
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
    startTimerOnActivity();
    if (state.isRunning) return;
    if (!state.student) { requireAuth(); return; }
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

    // Auto-save to server database in background and register run click
    if (state.sessionId) {
        apiFetch('/api/session/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: state.sessionId, code, is_run: true })
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
let monacoReadyResolve = null;
const monacoReadyPromise = new Promise((resolve) => {
    monacoReadyResolve = resolve;
});

let isProgrammaticEdit = false;

async function setEditorCode(code) {
    if (typeof code !== 'string') return;
    state.pendingCode = code;
    isProgrammaticEdit = true;
    try {
        if (state.editor) {
            state.editor.setValue(code);
        } else {
            await monacoReadyPromise;
            if (state.editor) {
                state.editor.setValue(code);
            }
        }
    } finally {
        setTimeout(() => { isProgrammaticEdit = false; }, 100);
    }
}

function initMonaco() {
    require.config({
        paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }
    });
    require(['vs/editor/editor.main'], function () {
        const initialValue = state.pendingCode || '# Write your Python code here\n\n';
        state.editor = monaco.editor.create(document.getElementById('monacoEditor'), {
            value: initialValue,
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
            quickSuggestions: suggestionsEnabled,
            suggestOnTriggerCharacters: suggestionsEnabled,
            parameterHints: { enabled: suggestionsEnabled },
        });

        monacoReadyResolve(state.editor);

        // Auto-save code edits to localStorage on every change
        state.editor.onDidChangeModelContent(() => {
            if (!isProgrammaticEdit) {
                startTimerOnActivity();
            }
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
    if (el.levelSelect) el.levelSelect.addEventListener('change', () => {
        state.helpLevel = parseInt(el.levelSelect.value, 10);
    });

    // Auto-suggestion toggle (💡)
    const suggestToggleBtn = document.getElementById('suggestToggleBtn');
    function updateSuggestBtnLabel() {
        if (!suggestToggleBtn) return;
        suggestToggleBtn.textContent = '💡';
        if (suggestionsEnabled) {
            suggestToggleBtn.classList.add('active');
            suggestToggleBtn.classList.remove('inactive');
            suggestToggleBtn.title = 'Code auto-suggestions: ON (Click to disable)';
            suggestToggleBtn.setAttribute('aria-label', 'Code auto-suggestions: ON');
        } else {
            suggestToggleBtn.classList.remove('active');
            suggestToggleBtn.classList.add('inactive');
            suggestToggleBtn.title = 'Code auto-suggestions: OFF (Click to enable)';
            suggestToggleBtn.setAttribute('aria-label', 'Code auto-suggestions: OFF');
        }
    }
    if (suggestToggleBtn) {
        updateSuggestBtnLabel();
        suggestToggleBtn.addEventListener('click', () => {
            suggestionsEnabled = !suggestionsEnabled;
            localStorage.setItem('pymentor_suggestions_enabled', String(suggestionsEnabled));
            if (state.editor) {
                state.editor.updateOptions({
                    quickSuggestions: suggestionsEnabled,
                    suggestOnTriggerCharacters: suggestionsEnabled,
                    parameterHints: { enabled: suggestionsEnabled },
                });
            }
            updateSuggestBtnLabel();
        });
    }
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
    el.outputBody.addEventListener('click', (e) => {
        if (activeInputEl && e.target !== activeInputEl) {
            const sel = window.getSelection();
            if (!sel || sel.isCollapsed || sel.toString().length === 0) {
                activeInputEl.focus();
            }
        }
    });

    // Prevent accidental text drag-selection from stealing input focus
    el.outputBody.addEventListener('mousedown', (e) => {
        if (activeInputEl && e.target !== activeInputEl) {
            setTimeout(() => {
                if (activeInputEl) activeInputEl.focus();
            }, 0);
        }
    });

    // Keystroke forwarding: typing while terminal awaits input automatically routes to input box
    document.addEventListener('keydown', (e) => {
        if (!activeInputEl || document.activeElement === activeInputEl) return;
        const tag = (document.activeElement && document.activeElement.tagName) || '';
        if (tag === 'TEXTAREA' || (tag === 'INPUT' && document.activeElement !== activeInputEl)) {
            return; // Don't interrupt editor or dialog inputs
        }
        if (e.key.length === 1 || e.key === 'Backspace' || e.key === 'Enter') {
            activeInputEl.focus();
        }
    });

    window.addEventListener('resize', () => {
        if (state.editor) state.editor.layout();
    }, { passive: true });
}

// ──────────────────────────────────────────────
// RESIZABLE SPLIT PANELS
// ──────────────────────────────────────────────
function restorePanelDimensions() {
    try {
        const savedWidth = parseInt(localStorage.getItem('pymentor_problem_panel_width'), 10);
        if (savedWidth && savedWidth >= 200 && savedWidth <= window.innerWidth - 300) {
            document.documentElement.style.setProperty('--problem-panel-width', `${savedWidth}px`);
        }
        const savedHeight = parseInt(localStorage.getItem('pymentor_panels_height'), 10);
        if (savedHeight && savedHeight >= 100 && savedHeight <= window.innerHeight - 150) {
            document.documentElement.style.setProperty('--panels-height', `${savedHeight}px`);
        }
    } catch (e) {}
}

function initResizablePanels() {
    const gutterProblem = document.getElementById('gutterProblem');
    const gutterOutput = document.getElementById('gutterOutput');

    // 1. Column Gutter (Problem panel width)
    if (gutterProblem) {
        gutterProblem.addEventListener('mousedown', (e) => {
            e.preventDefault();
            document.body.classList.add('is-resizing', 'is-resizing-col');
            gutterProblem.classList.add('active');

            let lastWidth = null;

            const onMouseMove = (moveEvent) => {
                const layout = document.querySelector('.practice-layout');
                const layoutLeft = layout ? layout.getBoundingClientRect().left : 0;
                const newWidth = moveEvent.clientX - layoutLeft;
                const minWidth = 220;
                const maxWidth = Math.max(minWidth, window.innerWidth - 420);
                const clampedWidth = Math.min(Math.max(newWidth, minWidth), maxWidth);

                lastWidth = clampedWidth;
                document.documentElement.style.setProperty('--problem-panel-width', `${clampedWidth}px`);
                if (state.editor) {
                    state.editor.layout();
                }
            };

            const onMouseUp = () => {
                document.body.classList.remove('is-resizing', 'is-resizing-col');
                gutterProblem.classList.remove('active');
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);

                if (lastWidth) {
                    try {
                        localStorage.setItem('pymentor_problem_panel_width', String(lastWidth));
                    } catch (err) {}
                }
                if (state.editor) {
                    state.editor.layout();
                }
            };

            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        });

        // Double click to reset to default 390px
        gutterProblem.addEventListener('dblclick', () => {
            document.documentElement.style.setProperty('--problem-panel-width', '390px');
            try {
                localStorage.removeItem('pymentor_problem_panel_width');
            } catch (err) {}
            if (state.editor) {
                state.editor.layout();
            }
        });
    }

    // 2. Row Gutter (Terminal & Guidance panels height)
    if (gutterOutput) {
        gutterOutput.addEventListener('mousedown', (e) => {
            e.preventDefault();
            document.body.classList.add('is-resizing', 'is-resizing-row');
            gutterOutput.classList.add('active');

            let lastHeight = null;

            const onMouseMove = (moveEvent) => {
                const newHeight = window.innerHeight - moveEvent.clientY;
                const minHeight = 120;
                const maxHeight = Math.max(minHeight, window.innerHeight - 250);
                const clampedHeight = Math.min(Math.max(newHeight, minHeight), maxHeight);

                lastHeight = clampedHeight;
                document.documentElement.style.setProperty('--panels-height', `${clampedHeight}px`);
                if (state.editor) {
                    state.editor.layout();
                }
            };

            const onMouseUp = () => {
                document.body.classList.remove('is-resizing', 'is-resizing-row');
                gutterOutput.classList.remove('active');
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);

                if (lastHeight) {
                    try {
                        localStorage.setItem('pymentor_panels_height', String(lastHeight));
                    } catch (err) {}
                }
                if (state.editor) {
                    state.editor.layout();
                }
            };

            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        });

        // Double click to reset to default 260px
        gutterOutput.addEventListener('dblclick', () => {
            document.documentElement.style.setProperty('--panels-height', '260px');
            try {
                localStorage.removeItem('pymentor_panels_height');
            } catch (err) {}
            if (state.editor) {
                state.editor.layout();
            }
        });
    }
}

// ──────────────────────────────────────────────
// STUDENT IDENTITY
// ──────────────────────────────────────────────
function loadStudentIdentity() {
    state.student = requireAuth();
    if (!state.student) return;

    // Initialize default guidance level from student's saved preference
    const defaultLevel = parseInt(state.student.default_help_level, 10) || 1;
    state.helpLevel = defaultLevel;
    if (el.levelSelect) {
        el.levelSelect.value = String(defaultLevel);
    }

    updateStudentDisplay();
}

async function loadDefaultHelpLevel() {
    if (!state.student) return;
    try {
        const res = await apiFetch('/api/student/profile');
        if (res.ok) {
            const data = await res.json();
            const lvl = data.student?.default_help_level;
            if (lvl && lvl >= 1 && lvl <= 3) {
                const currentLocal = parseInt(state.student.default_help_level, 10) || 1;
                if (state.helpLevel === currentLocal) {
                    state.helpLevel = lvl;
                    if (el.levelSelect) el.levelSelect.value = String(lvl);
                }
                state.student.default_help_level = lvl;
                try {
                    const localStudent = JSON.parse(localStorage.getItem('pymentor_student') || '{}');
                    localStudent.default_help_level = lvl;
                    localStorage.setItem('pymentor_student', JSON.stringify(localStudent));
                } catch (e) {}
            }
        }
    } catch (e) {
        // Fall back gracefully
    }
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
    el.topicBadge.title       = p.topic || '';

    el.conceptsList.innerHTML = '';
    (p.concepts || []).forEach(c => {
        const tag = document.createElement('span');
        tag.className   = 'concept-tag';
        tag.textContent = c;
        el.conceptsList.appendChild(tag);
    });

    // Check if student has an unsaved local draft first, otherwise starter code
    const savedDraft = localStorage.getItem('pymentor_draft_' + p.id);
    if (savedDraft && savedDraft.trim()) {
        setEditorCode(savedDraft);
    } else if (p.starter_code && p.starter_code.trim()) {
        setEditorCode(p.starter_code);
    } else {
        setEditorCode('# Write your Python code here\n\n');
    }

    // Reset problem status indicators
    if (el.guidanceStatus) {
        el.guidanceStatus.className = 'status-pending';
        el.guidanceStatus.textContent = 'Pending';
    }

    document.title = p.title + ' | Python Practice';
}

// ──────────────────────────────────────────────
// SESSION
// ──────────────────────────────────────────────
async function startSession() {
    if (!state.student || !state.problemId) return;
    try {
        const res = await apiFetch('/api/session/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                problem_id:  state.problemId,
                help_level:  state.helpLevel
            })
        });
        if (res.status === 403) return;
        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || 'Session start failed');
        }
        const session = await res.json();
        state.sessionId     = session.session_id;
        state.attemptsCount = session.attempts_count || 0;
        updateAttemptDisplay();

        // Restore saved code: check local draft first, then server database last_code
        const savedDraft = localStorage.getItem('pymentor_draft_' + state.problemId);
        if (savedDraft && savedDraft.trim()) {
            await setEditorCode(savedDraft);
        } else if (session.last_code && session.last_code.trim()) {
            await setEditorCode(session.last_code);
            localStorage.setItem('pymentor_draft_' + state.problemId, session.last_code);
        }

        if (session.is_solved) {
            el.guidanceStatus.innerHTML = '<span class="status-solved">Solved &#10003;</span>';
        } else {
            el.guidanceStatus.className = 'status-pending';
            el.guidanceStatus.textContent = 'Pending';
        }

        // Initialize practice timer (ticks once student interacts)
        startActiveTimer(session.time_spent_seconds || 0, session.is_solved);
    } catch (err) { console.error('Session error:', err); }
}

function updateAttemptDisplay() {
    const text = 'Attempt #' + (state.attemptsCount + 1);
    if (el.attemptCounter) el.attemptCounter.textContent = text;
    if (el.attemptBadge)   el.attemptBadge.textContent   = text;
}

// ──────────────────────────────────────────────
// GET GUIDANCE (calls /api/session/submit)
// ──────────────────────────────────────────────
async function getGuidance() {
    startTimerOnActivity();
    if (state.isGuidanceLoading) return;
    if (!state.student) { requireAuth(); return; }
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
        const res = await apiFetch('/api/session/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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

        const parsedMarkdown = marked.parse(result.feedback || '');
        if (typeof DOMPurify !== 'undefined') {
            el.guidanceBody.innerHTML = DOMPurify.sanitize(parsedMarkdown);
        } else {
            el.guidanceBody.textContent = result.feedback || '';
        }
        el.guidanceBody.scrollTop = 0;

        if (result.is_correct) {
            isProblemCurrentlySolved = true;
            isTimerStarted = false;
            if (activeTimerInterval) {
                clearInterval(activeTimerInterval);
                activeTimerInterval = null;
            }
            if (result.time_spent_seconds) {
                currentSessionSeconds = result.time_spent_seconds;
            }
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

    // Check & send heartbeat every 20 seconds
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(sendHeartbeat, 20000);

    // Re-anchor clock when returning to tab
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            markActive();
            if (isTimerStarted && !isProblemCurrentlySolved) {
                sendHeartbeat();
            }
        }
    });
}

async function sendHeartbeat() {
    // Only send heartbeat if:
    // 1. Student is logged in with active session
    // 2. Tab is currently visible/focused
    // 3. Problem is not already solved
    // 4. Timer has started on user activity
    // 5. User interacted in the last 60 seconds (not idle/away)
    if (!state.student || !state.sessionId) return;
    if (document.hidden) return;
    if (isProblemCurrentlySolved || !isTimerStarted) return;
    if (Date.now() - lastUserActivityTime > 60000) return;

    try {
        const res = await apiFetch('/api/session/heartbeat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ session_id: state.sessionId })
        });
        if (res.ok) {
            const data = await res.json();
            if (data.status === 'completed') {
                isProblemCurrentlySolved = true;
                isTimerStarted = false;
                if (activeTimerInterval) {
                    clearInterval(activeTimerInterval);
                    activeTimerInterval = null;
                }
                updateTimerDisplay();
                if (el.solvedBadge) el.solvedBadge.classList.remove('hidden');
            } else if (data.total_time_spent && !isProblemCurrentlySolved) {
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
let isTimerStarted = false;

function startActiveTimer(initialSeconds, isSolved) {
    currentSessionSeconds = initialSeconds || 0;
    isProblemCurrentlySolved = Boolean(isSolved);
    isTimerStarted = false;

    if (activeTimerInterval) {
        clearInterval(activeTimerInterval);
        activeTimerInterval = null;
    }

    updateTimerDisplay();

    if (isProblemCurrentlySolved) {
        if (el.solvedBadge) el.solvedBadge.classList.remove('hidden');
    } else {
        if (el.solvedBadge) el.solvedBadge.classList.add('hidden');
    }
}

function startTimerOnActivity() {
    if (isProblemCurrentlySolved || isTimerStarted) return;
    isTimerStarted = true;
    lastUserActivityTime = Date.now();

    if (activeTimerInterval) clearInterval(activeTimerInterval);
    activeTimerInterval = setInterval(() => {
        if (isProblemCurrentlySolved) {
            clearInterval(activeTimerInterval);
            activeTimerInterval = null;
            return;
        }
        // Tick when tab is active and user has interacted in last 60s
        if (!document.hidden && (Date.now() - lastUserActivityTime <= 60000)) {
            currentSessionSeconds++;
            updateTimerDisplay();
        }
    }, 1000);
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
        el.timeCounter.title = isTimerStarted ? `Active practice time: ${timeStr}` : `Practice time (starts on activity): ${timeStr}`;
    }
}
