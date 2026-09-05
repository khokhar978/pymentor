/**
 * Python Practice — Login Page (login.js)
 * Dedicated authentication page handling student login and redirects.
 */

document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    const nextUrl = params.get('next');

    // If already logged in, redirect right away
    const existing = localStorage.getItem('pymentor_student');
    if (existing) {
        try {
            const student = JSON.parse(existing);
            if (student && student.token) {
                redirectAfterLogin(nextUrl);
                return;
            }
        } catch (e) {
            localStorage.removeItem('pymentor_student');
        }
    }

    const form = document.getElementById('loginForm');
    const rollInput = document.getElementById('rollInput');
    const secSelect = document.getElementById('sectionSelect');
    const pwdInput = document.getElementById('pwdInput');
    const submitBtn = document.getElementById('loginSubmitBtn');
    const btnText = document.getElementById('btnText');
    const btnSpinner = document.getElementById('btnSpinner');
    const alertEl = document.getElementById('loginAlert');
    const alertMsg = document.getElementById('alertMessage');

    const msg = params.get('msg');
    if (msg === 'password_updated') {
        showSuccess('Password updated successfully! Please log in with your new password.');
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const section = secSelect.value;
        const roll_no = rollInput.value.trim();
        const password = pwdInput.value.trim();

        if (!roll_no || !password) {
            showError('Please enter both your Roll Number and Password.');
            return;
        }

        hideError();
        submitBtn.disabled = true;
        btnText.textContent = 'Verifying...';
        btnSpinner.classList.remove('hidden');

        try {
            const res = await fetch('/api/student/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ section, roll_no, password })
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Login failed. Please check your section, roll number, and password.');
            }

            // Save authenticated student session
            localStorage.setItem('pymentor_student', JSON.stringify(data));

            // Redirect to target problem/practice or default problems list
            if (data.needs_password_change) {
                window.location.href = '/profile?force_change=1';
            } else {
                redirectAfterLogin(nextUrl);
            }

        } catch (err) {
            showError(err.message);
            submitBtn.disabled = false;
            btnText.textContent = 'Log In to Lab';
            btnSpinner.classList.add('hidden');
        }
    });

    function showError(msg) {
        alertEl.classList.remove('success');
        alertMsg.textContent = msg;
        alertEl.classList.remove('hidden');
    }

    function showSuccess(msg) {
        alertEl.classList.add('success');
        alertMsg.textContent = msg;
        alertEl.classList.remove('hidden');
    }

    function hideError() {
        alertEl.classList.add('hidden');
        alertEl.classList.remove('success');
        alertMsg.textContent = '';
    }

    function redirectAfterLogin(targetUrl) {
        if (targetUrl && targetUrl.startsWith('/')) {
            window.location.href = targetUrl;
        } else {
            window.location.href = '/problems';
        }
    }
});
