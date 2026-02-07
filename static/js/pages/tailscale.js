import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearClientSession } from '/js/lib/session.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

let currentStatus = null;

async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (response.status === 401) {
        clearClientSession();
        window.location.href = '/login.html';
        throw new Error('Authentication required');
    }
    return response;
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function setLoadingState(isLoading, message = '') {
    const loadingState = document.getElementById('loading-state');
    if (!loadingState) {
        return;
    }

    if (isLoading) {
        loadingState.classList.remove('hidden');
        loadingState.innerHTML = `
            <svg class="animate-spin h-8 w-8 mx-auto mb-4 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            ${message || 'Loading Tailscale status...'}
        `;
    } else {
        loadingState.classList.add('hidden');
    }
}

function setLoadError(message) {
    const loadingState = document.getElementById('loading-state');
    if (!loadingState) {
        return;
    }
    loadingState.classList.remove('hidden');
    loadingState.innerHTML = `<p class="text-red-400">Failed to load Tailscale status: ${escapeHtml(message)}</p>`;
}

function showSetupSection(status) {
    const setupSection = document.getElementById('setup-section');
    const statusSection = document.getElementById('status-section');
    const setupStatus = document.getElementById('setup-status');

    if (setupSection) setupSection.classList.remove('hidden');
    if (statusSection) statusSection.classList.add('hidden');
    if (setupStatus) setupStatus.textContent = status;
}

function showStatusSection(data) {
    const setupSection = document.getElementById('setup-section');
    const statusSection = document.getElementById('status-section');
    if (setupSection) setupSection.classList.add('hidden');
    if (statusSection) statusSection.classList.remove('hidden');

    const statusEl = document.getElementById('connection-status');
    if (statusEl) {
        if (data.online) {
            statusEl.textContent = 'Online';
            statusEl.className = 'status-pill status-connected';
        } else {
            statusEl.textContent = 'Offline';
            statusEl.className = 'status-pill status-disconnected';
        }
    }

    const ips = data.tailscale_ips || [];
    const firstIp = ips[0] || '-';

    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    };

    setText('ts-ip', firstIp);
    setText('ts-hostname', data.hostname || '-');
    setText('ts-dns', data.dns_name || '-');
    setText('ts-tailnet', data.tailnet_name || '-');
    setText('ts-state', data.backend_state || '-');
    setText('ts-peers', data.peers !== undefined ? String(data.peers) : '-');
    setText('ts-relay', data.relay || 'Direct');

    const rx = formatBytes(data.rx_bytes || 0);
    const tx = formatBytes(data.tx_bytes || 0);
    setText('ts-traffic', `${rx} / ${tx}`);

    const accessUrl = data.dns_name ? String(data.dns_name).replace(/\.$/, '') : firstIp;
    setText('access-url', accessUrl);

    const health = data.health || [];
    const healthSection = document.getElementById('health-warnings');
    const healthList = document.getElementById('health-list');

    if (healthSection && healthList) {
        if (health.length > 0) {
            healthSection.classList.remove('hidden');
            healthList.innerHTML = health.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
        } else {
            healthSection.classList.add('hidden');
            healthList.innerHTML = '';
        }
    }
}

async function loadStatus() {
    try {
        const response = await apiFetch('/api/tailscale/status');
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data?.error || `Request failed (${response.status})`);
        }

        setLoadingState(false);
        currentStatus = data;

        if (!data.installed) {
            showSetupSection('Not Installed');
        } else if (!data.running) {
            showSetupSection('Not Running');
        } else {
            showStatusSection(data);
        }
    } catch (error) {
        setLoadError(error.message || 'Unknown error');
    }
}

function showNotification(message, type = 'info') {
    const area = document.getElementById('notification-area');
    if (!area) {
        return;
    }

    const colors = {
        success: 'bg-green-800 border-green-600',
        error: 'bg-red-800 border-red-600',
        info: 'bg-blue-800 border-blue-600',
    };

    const notification = document.createElement('div');
    notification.className = `${colors[type] || colors.info} border rounded-lg p-4 shadow-lg transition-opacity duration-500`;

    const messageEl = document.createElement('p');
    messageEl.className = 'text-white text-sm';
    messageEl.textContent = message;
    notification.appendChild(messageEl);

    area.appendChild(notification);
    setTimeout(() => {
        notification.classList.add('opacity-0');
        setTimeout(() => notification.remove(), 500);
    }, 5000);
}

async function setupTailscale() {
    const authKey = document.getElementById('tailscale-authkey')?.value.trim() || '';

    showNotification('Installing and configuring Tailscale...', 'info');

    try {
        const response = await apiFetch('/api/setup/tailscale', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auth_key: authKey }),
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.error || 'Setup failed');
        }

        showNotification('Tailscale setup complete!', 'success');
        setTimeout(() => loadStatus(), 2000);
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function reauthenticate() {
    if (!window.confirm('This will log out of Tailscale. You will need to re-authenticate. Continue?')) {
        return;
    }

    try {
        const response = await apiFetch('/api/tailscale/logout', { method: 'POST' });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data?.error || 'Logout failed');
        }

        showNotification('Logged out. Please set up Tailscale again.', 'info');
        await loadStatus();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

function refreshStatus() {
    setLoadingState(true, 'Loading Tailscale status...');
    const statusSection = document.getElementById('status-section');
    const setupSection = document.getElementById('setup-section');
    if (statusSection) statusSection.classList.add('hidden');
    if (setupSection) setupSection.classList.add('hidden');
    loadStatus();
}

Object.assign(window, {
    setupTailscale,
    reauthenticate,
    refreshStatus,
});

(async function initTailscalePage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    await loadStatus();
})();
