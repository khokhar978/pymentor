/**
 * Shared Notification and Announcement Client for PyMentor.
 * Features:
 * - 30s background HTTP polling for student-targeted notifications
 * - Full-width top alert banners (e.g. maintenance, system notices)
 * - Interactive slide-in toasts (e.g. announcements, personal mentor feedback)
 * - Notification bell with unread badge and dropdown drawer
 * - Persistent read/dismiss synchronization with the server
 */

import { getCurrentStudent } from './auth.js';
import { apiFetch } from './api.js';

let notificationsState = {
    items: [],
    unreadCount: 0,
    isOpen: false,
    pollInterval: null
};

// Session storage key for toasts already shown in current tab session
const SHOWN_TOASTS_KEY = 'pymentor_shown_toasts';

function getShownToastIds() {
    try {
        return JSON.parse(sessionStorage.getItem(SHOWN_TOASTS_KEY) || '[]');
    } catch (_) {
        return [];
    }
}

function markToastAsShown(id) {
    try {
        const ids = getShownToastIds();
        if (!ids.includes(id)) {
            ids.push(id);
            sessionStorage.setItem(SHOWN_TOASTS_KEY, JSON.stringify(ids.slice(-50)));
        }
    } catch (_) {}
}

/**
 * Format relative or localized timestamp
 */
function formatTime(isoStr) {
    if (!isoStr) return '';
    try {
        const date = new Date(isoStr.replace(' ', 'T'));
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        const diffDays = Math.floor(diffHours / 24);
        if (diffDays < 7) return `${diffDays}d ago`;
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (_) {
        return isoStr;
    }
}

/**
 * Basic safe text formatter with linebreaks and autolink
 */
function formatMessage(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    let safe = div.innerHTML;

    // Convert URLs to clickable links
    const urlPattern = /(\b(https?:\/\/)[-A-Z0-9+&@#\/%?=~_|!:,.;]*[-A-Z0-9+&@#\/%=~_|])/ig;
    safe = safe.replace(urlPattern, '<a href="$1" target="_blank" rel="noopener noreferrer" style="color:var(--brand);text-decoration:underline;">$1</a>');

    // Convert newlines to breaks
    return safe.replace(/\n/g, '<br>');
}

/**
 * Injects required DOM containers if not present
 */
function ensureDomElements() {
    // 1. Top banner container
    let bannerContainer = document.getElementById('pymentorBannerContainer');
    if (!bannerContainer) {
        bannerContainer = document.createElement('div');
        bannerContainer.id = 'pymentorBannerContainer';
        bannerContainer.className = 'pymentor-banner-container';
        document.body.insertBefore(bannerContainer, document.body.firstChild);
    }

    // 2. Toast container
    let toastContainer = document.getElementById('pymentorToastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'pymentorToastContainer';
        toastContainer.className = 'pymentor-toast-container';
        document.body.appendChild(toastContainer);
    }

    // 3. Dropdown drawer & backdrop
    let drawer = document.getElementById('pymentorNotificationDrawer');
    if (!drawer) {
        drawer = document.createElement('div');
        drawer.id = 'pymentorNotificationDrawer';
        drawer.className = 'pymentor-notification-drawer';
        drawer.innerHTML = `
            <div class="pnd-header">
                <div class="pnd-title-group">
                    <span class="pnd-title">Notifications</span>
                    <span id="pndUnreadPill" class="pnd-unread-pill" style="display:none;">0 new</span>
                </div>
                <button id="pndMarkAllBtn" class="pnd-btn-text" title="Mark all as read">Mark all as read</button>
            </div>
            <div id="pndList" class="pnd-list">
                <div class="pnd-loading">Loading notifications...</div>
            </div>
        `;
        document.body.appendChild(drawer);

        // Backdrop
        const backdrop = document.createElement('div');
        backdrop.id = 'pymentorNotificationBackdrop';
        backdrop.className = 'pymentor-notification-backdrop';
        backdrop.addEventListener('click', closeNotificationDrawer);
        document.body.appendChild(backdrop);

        // Mark all as read button
        document.getElementById('pndMarkAllBtn')?.addEventListener('click', async () => {
            await markAllNotificationsRead();
        });
    }

    // Wire up bell button if it exists in DOM
    const bellBtn = document.getElementById('notificationBellBtn');
    if (bellBtn && !bellBtn.dataset.wired) {
        bellBtn.dataset.wired = 'true';
        bellBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleNotificationDrawer();
        });
    }
}

/**
 * Fetches notifications from server
 */
export async function fetchNotifications() {
    const student = getCurrentStudent();
    if (!student || !student.token) {
        updateBellBadge(0);
        return;
    }

    try {
        const res = await apiFetch('/api/notifications');
        if (!res.ok) return;

        const data = await res.json();
        notificationsState.items = data.notifications || [];
        notificationsState.unreadCount = data.unread_count || 0;

        updateBellBadge(notificationsState.unreadCount);
        renderBanners();
        checkAndShowToasts();
        if (notificationsState.isOpen) {
            renderDrawerList();
        }
    } catch (err) {
        // Silently fail network error during polling
    }
}

/**
 * Updates the bell button badge
 */
function updateBellBadge(count) {
    const badge = document.getElementById('notificationBadge');
    const bellBtn = document.getElementById('notificationBellBtn');
    if (!badge) return;

    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.style.display = 'inline-flex';
        bellBtn?.classList.add('has-unread');
    } else {
        badge.style.display = 'none';
        bellBtn?.classList.remove('has-unread');
    }

    const pill = document.getElementById('pndUnreadPill');
    if (pill) {
        if (count > 0) {
            pill.textContent = `${count} new`;
            pill.style.display = 'inline-block';
        } else {
            pill.style.display = 'none';
        }
    }
}

/**
 * Renders unread banners at the top of the screen
 */
function renderBanners() {
    const container = document.getElementById('pymentorBannerContainer');
    if (!container) return;

    const unreadBanners = notificationsState.items.filter(n => n.type === 'banner' && !n.is_read);

    if (unreadBanners.length === 0) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';
    container.innerHTML = unreadBanners.map(banner => {
        const isCritical = banner.priority === 'critical' || banner.priority === 'high';
        const icon = isCritical ? '⚠️' : 'ℹ️';
        const priorityClass = isCritical ? 'banner-critical' : 'banner-normal';

        return `
            <div class="pymentor-banner ${priorityClass}" id="banner-${banner.id}">
                <div class="pb-content">
                    <span class="pb-icon">${icon}</span>
                    <div class="pb-text">
                        <strong class="pb-title">${escapeHtml(banner.title)}:</strong>
                        <span class="pb-message">${formatMessage(banner.message)}</span>
                    </div>
                </div>
                <button class="pb-dismiss" onclick="window.dismissPymentorNotification(${banner.id}, 'banner')" title="Dismiss notification">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    <span>Dismiss</span>
                </button>
            </div>
        `;
    }).join('');
}

/**
 * Checks for unread announcements/personal notes and pops up toasts
 */
function checkAndShowToasts() {
    const container = document.getElementById('pymentorToastContainer');
    if (!container) return;

    const shownIds = getShownToastIds();
    const candidates = notificationsState.items.filter(
        n => !n.is_read && n.type !== 'banner' && !shownIds.includes(n.id)
    );

    // Limit to showing at most 2 toasts at once to prevent spam
    const toShow = candidates.slice(0, 2);

    for (const item of toShow) {
        markToastAsShown(item.id);
        showToast(item);
    }
}

/**
 * Displays a single toast popup
 */
function showToast(item) {
    const container = document.getElementById('pymentorToastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.id = `toast-${item.id}`;
    toast.className = `pymentor-toast toast-${item.type} priority-${item.priority}`;

    const icon = item.type === 'personal' ? '💬' : (item.priority === 'critical' ? '🚨' : '📢');
    const typeLabel = item.type === 'personal' ? 'Personal Review' : 'Announcement';

    toast.innerHTML = `
        <div class="pt-header">
            <span class="pt-badge"><span class="pt-icon">${icon}</span> ${typeLabel}</span>
            <span class="pt-time">${formatTime(item.created_at)}</span>
            <button class="pt-close" onclick="window.dismissPymentorNotification(${item.id}, 'toast')" title="Dismiss">&times;</button>
        </div>
        <div class="pt-title">${escapeHtml(item.title)}</div>
        <div class="pt-body">${formatMessage(item.message)}</div>
        <div class="pt-footer">
            <button class="pt-action-btn" onclick="window.dismissPymentorNotification(${item.id}, 'toast')">Got it</button>
        </div>
    `;

    container.appendChild(toast);

    // Trigger enter animation
    requestAnimationFrame(() => {
        toast.classList.add('visible');
    });

    // Auto dismiss announcements after 14 seconds (keep personal notes until clicked)
    if (item.type === 'announcement' && item.priority !== 'critical') {
        setTimeout(() => {
            if (document.body.contains(toast)) {
                dismissNotification(item.id, 'toast');
            }
        }, 14000);
    }
}

/**
 * Marks a notification as read and animates dismissal
 */
export async function dismissNotification(notificationId, source) {
    // Optimistically update local state
    const item = notificationsState.items.find(n => n.id === notificationId);
    if (item && !item.is_read) {
        item.is_read = true;
        notificationsState.unreadCount = Math.max(0, notificationsState.unreadCount - 1);
        updateBellBadge(notificationsState.unreadCount);
    }

    // Animate DOM element out
    if (source === 'banner') {
        const el = document.getElementById(`banner-${notificationId}`);
        if (el) {
            el.classList.add('slide-up');
            setTimeout(() => el.remove(), 300);
        }
    } else if (source === 'toast') {
        const el = document.getElementById(`toast-${notificationId}`);
        if (el) {
            el.classList.remove('visible');
            setTimeout(() => el.remove(), 300);
        }
    }

    // Server update
    try {
        await apiFetch(`/api/notifications/${notificationId}/read`, { method: 'POST' });
    } catch (_) {}

    // Refresh drawer list if open
    if (notificationsState.isOpen) {
        renderDrawerList();
    }
}

window.dismissPymentorNotification = dismissNotification;

/**
 * Marks all notifications as read
 */
export async function markAllNotificationsRead() {
    notificationsState.items.forEach(n => { n.is_read = true; });
    notificationsState.unreadCount = 0;
    updateBellBadge(0);

    // Clean up banners and toasts
    renderBanners();
    const toastContainer = document.getElementById('pymentorToastContainer');
    if (toastContainer) toastContainer.innerHTML = '';

    renderDrawerList();

    try {
        await apiFetch('/api/notifications/read-all', { method: 'POST' });
    } catch (_) {}
}

/**
 * Renders the contents of the dropdown drawer
 */
function renderDrawerList() {
    const list = document.getElementById('pndList');
    if (!list) return;

    if (notificationsState.items.length === 0) {
        list.innerHTML = `
            <div class="pnd-empty">
                <div class="pnd-empty-icon">🎉</div>
                <div class="pnd-empty-text">All caught up!</div>
                <div class="pnd-empty-sub">No announcements or updates at this time.</div>
            </div>
        `;
        return;
    }

    list.innerHTML = notificationsState.items.map(item => {
        const icon = item.type === 'banner' ? '⚠️' : (item.type === 'personal' ? '💬' : '📢');
        const typeLabel = item.type === 'banner' ? 'Banner Alert' : (item.type === 'personal' ? 'Personal Note' : 'Announcement');
        const unreadClass = item.is_read ? 'read' : 'unread';

        return `
            <div class="pnd-item ${unreadClass} type-${item.type}" id="drawer-item-${item.id}">
                <div class="pnd-item-top">
                    <div class="pnd-item-badge">
                        <span class="pnd-badge-icon">${icon}</span>
                        <span class="pnd-badge-label">${typeLabel}</span>
                    </div>
                    <span class="pnd-item-time">${formatTime(item.created_at)}</span>
                </div>
                <div class="pnd-item-title">${escapeHtml(item.title)}</div>
                <div class="pnd-item-body">${formatMessage(item.message)}</div>
                ${!item.is_read ? `
                    <div class="pnd-item-actions">
                        <button class="pnd-item-dismiss" onclick="window.dismissPymentorNotification(${item.id}, 'drawer')">
                            Mark as read
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

/**
 * Drawer Toggle Logic
 */
export function toggleNotificationDrawer() {
    if (notificationsState.isOpen) {
        closeNotificationDrawer();
    } else {
        openNotificationDrawer();
    }
}

export function openNotificationDrawer() {
    ensureDomElements();
    notificationsState.isOpen = true;

    const drawer = document.getElementById('pymentorNotificationDrawer');
    const backdrop = document.getElementById('pymentorNotificationBackdrop');
    if (drawer) drawer.classList.add('open');
    if (backdrop) backdrop.classList.add('visible');

    renderDrawerList();
}

export function closeNotificationDrawer() {
    notificationsState.isOpen = false;
    const drawer = document.getElementById('pymentorNotificationDrawer');
    const backdrop = document.getElementById('pymentorNotificationBackdrop');
    if (drawer) drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('visible');
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * Main initialization entrypoint.
 * Call this from problems.js, app.js, and profile.js.
 */
export function initNotifications() {
    ensureDomElements();

    // Initial fetch
    fetchNotifications();

    // Clear any previous polling interval
    if (notificationsState.pollInterval) {
        clearInterval(notificationsState.pollInterval);
    }

    // Poll every 30 seconds
    notificationsState.pollInterval = setInterval(fetchNotifications, 30000);
}
