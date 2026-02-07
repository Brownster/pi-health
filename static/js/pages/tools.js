import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { requestApiResponse } from '/js/lib/http.js';
import { showNotification } from '/js/lib/notify.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

function statusPill(status) {
    if (status === 'active') return 'status-healthy';
    if (status === 'inactive') return 'status-degraded';
    return 'status-unconfigured';
}

async function loadCopyParty() {
    try {
        const res = await requestApiResponse('/api/tools/copyparty/status');
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || 'Failed to load');
        }

        const sharePath = document.getElementById('copyparty-share-path');
        const portInput = document.getElementById('copyparty-port');
        const extraArgs = document.getElementById('copyparty-extra-args');
        const serviceStatus = document.getElementById('copyparty-service-status');
        const installedStatus = document.getElementById('copyparty-installed');
        const statusPillEl = document.getElementById('copyparty-status-pill');
        const link = document.getElementById('copyparty-link');

        if (sharePath) sharePath.value = data.config?.share_path || '/srv/copyparty';
        if (portInput) portInput.value = data.config?.port || 3923;
        if (extraArgs) extraArgs.value = data.config?.extra_args || '';

        if (serviceStatus) serviceStatus.textContent = data.service_status || 'unknown';
        if (installedStatus) installedStatus.textContent = data.installed ? 'Yes' : 'No';

        if (statusPillEl) {
            statusPillEl.className = `status-pill ${statusPill(data.service_status)}`;
            statusPillEl.textContent = data.service_status || 'unknown';
        }

        if (link) {
            link.href = data.url || '#';
            link.classList.toggle('opacity-50', !data.installed);
            link.classList.toggle('pointer-events-none', !data.installed);
        }
    } catch (error) {
        showNotification(`CopyParty error: ${error.message}`, 'error');
    }
}

async function installCopyParty() {
    try {
        const res = await requestApiResponse('/api/tools/copyparty/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || 'Install failed');
        }

        showNotification('CopyParty installed', 'success');
        await loadCopyParty();
    } catch (error) {
        showNotification(`Install failed: ${error.message}`, 'error');
    }
}

async function saveCopyPartyConfig() {
    const payload = {
        share_path: document.getElementById('copyparty-share-path')?.value.trim() || '',
        port: parseInt(document.getElementById('copyparty-port')?.value || '', 10),
        extra_args: document.getElementById('copyparty-extra-args')?.value.trim() || '',
    };

    try {
        const res = await requestApiResponse('/api/tools/copyparty/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || 'Save failed');
        }

        showNotification('CopyParty configuration saved', 'success');
        await loadCopyParty();
    } catch (error) {
        showNotification(`Save failed: ${error.message}`, 'error');
    }
}

(async function initToolsPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    document.getElementById('copyparty-install-btn')?.addEventListener('click', installCopyParty);
    document.getElementById('copyparty-save-config')?.addEventListener('click', saveCopyPartyConfig);
    await loadCopyParty();
})();
