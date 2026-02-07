import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { createErrorState, createLoadingState } from '/js/lib/states.js';
import { requestApiResponse } from '/js/lib/http.js';
import { formatBytes } from '/js/lib/format.js';
import { showNotification as showBaseNotification } from '/js/lib/notify.js';
import { setNodeContent } from '/js/lib/dom.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

let currentStatus = null;

function setLoadingState(isLoading, message = '') {
    const loadingState = document.getElementById('loading-state');
    if (!loadingState) {
        return;
    }

    if (isLoading) {
        loadingState.classList.remove('hidden');
        setNodeContent('loading-state', createLoadingState({
            message: message || 'Loading Tailscale status...',
            containerClass: 'text-center py-10',
            messageClass: 'text-gray-400',
        }));
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
    setNodeContent('loading-state', createErrorState({
        title: `Failed to load Tailscale status: ${message}`,
        containerClass: 'text-center py-10',
        titleClass: 'text-red-400',
    }));
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
            healthList.textContent = '';
            health.forEach((item) => {
                const li = document.createElement('li');
                li.textContent = item;
                healthList.appendChild(li);
            });
        } else {
            healthSection.classList.add('hidden');
            healthList.textContent = '';
        }
    }
}

async function loadStatus() {
    try {
        const response = await requestApiResponse('/api/tailscale/status');
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
    showBaseNotification(message, type, {
        duration: 5000,
        baseClass: 'border rounded-lg p-4 shadow-lg transition-opacity duration-500 opacity-0 text-white',
        colorMap: {
            success: 'bg-green-800 border-green-600',
            error: 'bg-red-800 border-red-600',
            info: 'bg-blue-800 border-blue-600',
            warning: 'bg-yellow-800 border-yellow-600',
        },
    });
}

async function setupTailscale() {
    const authKey = document.getElementById('tailscale-authkey')?.value.trim() || '';

    showNotification('Installing and configuring Tailscale...', 'info');

    try {
        const response = await requestApiResponse('/api/setup/tailscale', {
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
        const response = await requestApiResponse('/api/tailscale/logout', { method: 'POST' });
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

function bindTailscaleActions() {
    const setupButton = document.getElementById('tailscale-setup-btn');
    if (setupButton) {
        setupButton.addEventListener('click', setupTailscale);
    }

    const refreshButton = document.getElementById('tailscale-refresh-btn');
    if (refreshButton) {
        refreshButton.addEventListener('click', refreshStatus);
    }

    const reauthButton = document.getElementById('tailscale-reauth-btn');
    if (reauthButton) {
        reauthButton.addEventListener('click', reauthenticate);
    }
}

(async function initTailscalePage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    bindTailscaleActions();
    await loadStatus();
})();
