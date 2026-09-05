/**
 * Shared Student Authentication helper module for PyMentor frontend.
 */

const STORAGE_KEY = 'pymentor_student';

export function getCurrentStudent() {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
        const student = JSON.parse(raw);
        if (student && student.token) {
            return student;
        }
        clearAuth();
        return null;
    } catch (e) {
        clearAuth();
        return null;
    }
}

export function saveCurrentStudent(studentData) {
    if (!studentData) {
        clearAuth();
        return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(studentData));
}

export function clearAuth() {
    localStorage.removeItem(STORAGE_KEY);
}

export function requireAuth(redirectTo = '/login') {
    const student = getCurrentStudent();
    if (!student) {
        const currentPath = window.location.pathname + window.location.search;
        window.location.href = `${redirectTo}?next=${encodeURIComponent(currentPath)}`;
        return null;
    }
    return student;
}
