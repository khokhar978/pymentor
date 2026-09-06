/**
 * PyMentor Theme Management (Light / Dark Mode)
 * - Persists theme preference in localStorage ('pymentor_theme')
 * - Falls back to OS system preference (prefers-color-scheme)
 * - Updates button icon (☀️ / 🌙)
 */

const STORAGE_KEY = 'pymentor_theme';

export function getPreferredTheme() {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === 'light' || saved === 'dark') return saved;
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch (e) {
        return 'light';
    }
}

export function applyTheme(theme) {
    const validTheme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', validTheme);
    try {
        localStorage.setItem(STORAGE_KEY, validTheme);
    } catch (e) {}

    // Update all theme toggle buttons on the page
    document.querySelectorAll('.btn-theme-toggle').forEach(btn => {
        if (btn.id === 'suggestToggleBtn' || btn.classList.contains('btn-suggest-toggle')) return;
        btn.textContent = validTheme === 'dark' ? '☀️' : '🌙';
        const label = validTheme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
        btn.setAttribute('aria-label', label);
        btn.setAttribute('title', label);
    });
}

export function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || getPreferredTheme();
    const nextTheme = current === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
}

// Expose on window for easy onclick attribute binding
if (typeof window !== 'undefined') {
    window.toggleTheme = toggleTheme;
    window.applyTheme = applyTheme;
    window.getPreferredTheme = getPreferredTheme;

    // Synchronize toggle button state on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            applyTheme(getPreferredTheme());
        });
    } else {
        applyTheme(getPreferredTheme());
    }
}
