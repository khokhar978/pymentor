/**
 * Shared utility functions: formatting, HTML sanitization, and local date helpers.
 */

export function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

export function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '0s';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
        return m > 0 ? `${h}h ${m}m` : `${h}h`;
    }
    if (m > 0) {
        return s > 0 ? `${m}m ${s < 10 ? '0' : ''}${s}s` : `${m}m`;
    }
    return `${s}s`;
}

export function parseLocalDate(str) {
    if (!str) return null;
    const s = String(str).replace('T', ' ').split('.')[0];
    const parts = s.split(' ');
    if (parts.length < 2) return new Date(s);
    const [y, m, d] = parts[0].split('-').map(Number);
    const [h, min, sec] = parts[1].split(':').map(Number);
    return new Date(y, m - 1, d, h || 0, min || 0, sec || 0);
}

export function formatLocalTime(str) {
    const d = parseLocalDate(str);
    if (!d || isNaN(d.getTime())) return str || '—';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatLocalDateTime(str) {
    const d = parseLocalDate(str);
    if (!d || isNaN(d.getTime())) return str || '—';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function formatLocalDateOnly(str) {
    const d = parseLocalDate(str);
    if (!d || isNaN(d.getTime())) return str || '—';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}
