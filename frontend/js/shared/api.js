/**
 * Shared API fetch wrapper with Bearer token authentication and uniform error interception.
 */

import { getCurrentStudent } from './auth.js';

export async function apiFetch(path, options = {}) {
    const student = getCurrentStudent();
    const headers = { ...options.headers };

    // Default to application/json if sending a string body and Content-Type is not specified
    if (options.body && typeof options.body === 'string' && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    if (student && student.token && !headers['Authorization']) {
        headers['Authorization'] = 'Bearer ' + student.token;
    }

    const res = await fetch(path, { ...options, headers });

    // Handle 403 forced password change redirect
    if (res.status === 403) {
        try {
            const clone = res.clone();
            const body = await clone.json();
            if (body.detail && body.detail.includes('change your default password')) {
                window.location.href = '/profile?force_change=1';
            }
        } catch (_) {}
    }

    return res;
}
