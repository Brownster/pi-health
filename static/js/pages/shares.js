import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { createEmptyState, createErrorState, createLoadingState } from '/js/lib/states.js';
import { requestApiResponse } from '/js/lib/http.js';
import { escapeHtml, encodeDataAttr } from '/js/lib/format.js';
import { showNotification } from '/js/lib/notify.js';
import { setNodeContent } from '/js/lib/dom.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

let sharePlugins = [];

function showSharesLoading() {
    const loadingState = document.getElementById('loading-state');
    const sharesContent = document.getElementById('shares-content');

    if (loadingState) {
        loadingState.classList.remove('hidden');
    }
    if (sharesContent) {
        sharesContent.classList.add('hidden');
    }

    setNodeContent('loading-state', createLoadingState({
        message: 'Loading share plugins...',
        containerClass: 'text-center py-10',
        messageClass: 'text-gray-400',
    }));
}

function statusClass(status) {
    if (status === 'healthy') return 'status-healthy';
    if (status === 'degraded') return 'status-degraded';
    if (status === 'error') return 'status-error';
    return 'status-unconfigured';
}

async function loadSharePlugins() {
    showSharesLoading();

    try {
        const res = await requestApiResponse('/api/storage/plugins');
        const data = await res.json();
        sharePlugins = (data.plugins || []).filter(p => p.category === 'share' && p.enabled);

        document.getElementById('loading-state').classList.add('hidden');
        document.getElementById('shares-content').classList.remove('hidden');

        if (sharePlugins.length === 0) {
            setNodeContent('shares-content', createEmptyState({
                title: 'No share plugins enabled.',
                action: { href: '/plugins.html', label: 'Enable plugins on the Plugins page' },
                containerClass: 'bg-gray-800 border border-purple-900/40 rounded-lg p-6 text-center',
                titleClass: 'text-gray-400 mb-4',
                actionClass: 'text-purple-400 hover:underline',
            }));
            return;
        }

        await renderSharePlugins();
    } catch (e) {
        setNodeContent('loading-state', createErrorState({
            title: `Failed to load shares: ${e.message}`,
            containerClass: 'text-center py-10',
            titleClass: 'text-red-400',
        }));
    }
}

async function renderSharePlugins() {
    const container = document.getElementById('shares-content');
    let html = '';

    for (const plugin of sharePlugins) {
        // Fetch detailed share info
        let shareData = { shares: [], service_running: false, status: 'unknown' };
        try {
            const res = await requestApiResponse(`/api/storage/shares/${plugin.id}`);
            shareData = await res.json();
        } catch (e) {
            console.error(`Failed to load shares for ${plugin.id}:`, e);
        }

        const serviceStatus = shareData.service_running
            ? '<span class="status-pill status-healthy">Service Running</span>'
            : '<span class="status-pill status-error">Service Stopped</span>';

        html += `
            <section class="bg-gray-800 border border-purple-900/40 rounded-lg p-6">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <div class="flex items-center gap-3 mb-1">
                            <h3 class="text-lg font-semibold">${escapeHtml(plugin.name)}</h3>
                            ${serviceStatus}
                            <span class="status-pill ${statusClass(shareData.status)}">${escapeHtml(shareData.status || 'unknown')}</span>
                        </div>
                        <p class="text-sm text-gray-400">${escapeHtml(plugin.description)}</p>
                    </div>
                    <div class="flex gap-2">
                        <button type="button"
                                class="js-run-plugin-command px-3 py-1 text-sm border border-purple-700 text-purple-300 rounded hover:bg-purple-900"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                data-command-id="apply"
                                title="Generate configuration file">
                            Apply Config
                        </button>
                        <button type="button"
                                class="js-run-plugin-command px-3 py-1 text-sm border border-yellow-700 text-yellow-300 rounded hover:bg-yellow-900/30"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                data-command-id="restart"
                                title="Restart Samba service">
                            Restart Service
                        </button>
                        <button type="button"
                                class="js-open-add-share coraline-button px-4 py-1 rounded text-sm"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                ${!plugin.installed ? 'disabled title="Install Samba first"' : ''}>
                            + Add Share
                        </button>
                    </div>
                </div>

                ${!plugin.installed ? `
                    <div class="p-3 bg-yellow-900/20 border border-yellow-800 rounded mb-4">
                        <p class="text-sm text-yellow-300">Install required packages:</p>
                        <code class="text-xs">${escapeHtml(plugin.install_instructions)}</code>
                    </div>
                ` : ''}

                <div class="space-y-3" id="shares-${encodeDataAttr(plugin.id)}">
                    ${shareData.shares.length === 0
                        ? '<p class="text-gray-500 text-sm py-4">No shares configured. Click "Add Share" to create one.</p>'
                        : shareData.shares.map(share => renderShareCard(plugin.id, share)).join('')
                    }
                </div>
            </section>
        `;
    }

    container.innerHTML = html;
    bindSharePluginActions(container);
}

function renderShareCard(pluginId, share) {
    const isEnabled = share.enabled !== false;
    const pathExists = share.path_exists !== false;
    const isActive = share.active;

    let statusBadge;
    if (!isEnabled) {
        statusBadge = '<span class="status-pill status-unconfigured">Disabled</span>';
    } else if (!pathExists) {
        statusBadge = '<span class="status-pill status-error">Path Missing</span>';
    } else if (isActive) {
        statusBadge = '<span class="status-pill status-healthy">Active</span>';
    } else {
        statusBadge = '<span class="status-pill status-degraded">Configured</span>';
    }

    return `
        <div class="bg-gray-900 rounded-lg p-4 ${!isEnabled ? 'opacity-60' : ''}">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-2">
                        <h4 class="font-semibold text-lg">${escapeHtml(share.name)}</h4>
                        ${statusBadge}
                        ${share.read_only ? '<span class="text-xs text-yellow-400">(Read Only)</span>' : ''}
                        ${share.guest_ok ? '<span class="text-xs text-blue-400">(Guest OK)</span>' : ''}
                    </div>
                    ${share.comment ? `<p class="text-sm text-gray-400 mb-1">${escapeHtml(share.comment)}</p>` : ''}
                    <p class="text-sm font-mono ${pathExists ? 'text-green-400' : 'text-red-400'}">
                        ${escapeHtml(share.path)}
                        ${!pathExists ? ' (not found)' : ''}
                    </p>
                    ${share.valid_users ? `<p class="text-xs text-gray-500 mt-1">Users: ${escapeHtml(share.valid_users)}</p>` : ''}
                </div>
                <div class="flex items-center gap-3 ml-4">
                    <label class="toggle-switch" title="${isEnabled ? 'Disable share' : 'Enable share'}">
                        <input type="checkbox" class="js-toggle-share" ${isEnabled ? 'checked' : ''}
                               data-plugin-id="${encodeDataAttr(pluginId)}"
                               data-share-name="${encodeDataAttr(share.name)}">
                        <span class="toggle-slider"></span>
                    </label>
                    <button data-plugin-id="${encodeDataAttr(pluginId)}"
                            type="button"
                            data-share="${encodeDataAttr(encodeURIComponent(JSON.stringify(share)))}"
                            class="js-open-edit-share text-sm text-gray-400 hover:text-white px-2 py-1">
                        Edit
                    </button>
                    <button type="button"
                            class="js-delete-share text-sm text-red-400 hover:text-red-300 px-2 py-1"
                            data-plugin-id="${encodeDataAttr(pluginId)}"
                            data-share-name="${encodeDataAttr(share.name)}">
                        Delete
                    </button>
                </div>
            </div>
        </div>
    `;
}

function bindSharePluginActions(container) {
    if (!container) return;

    container.querySelectorAll('.js-run-plugin-command').forEach((button) => {
        button.addEventListener('click', () => {
            runPluginCommand(button.dataset.pluginId || '', button.dataset.commandId || '');
        });
    });

    container.querySelectorAll('.js-open-add-share').forEach((button) => {
        button.addEventListener('click', () => {
            openAddShareModal(button.dataset.pluginId || '');
        });
    });

    container.querySelectorAll('.js-toggle-share').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
            toggleShare(checkbox.dataset.pluginId || '', checkbox.dataset.shareName || '', checkbox.checked);
        });
    });

    container.querySelectorAll('.js-open-edit-share').forEach((button) => {
        button.addEventListener('click', () => {
            openEditShareModalFromButton(button);
        });
    });

    container.querySelectorAll('.js-delete-share').forEach((button) => {
        button.addEventListener('click', () => {
            deleteShare(button.dataset.pluginId || '', button.dataset.shareName || '');
        });
    });
}

function openAddShareModal(pluginId) {
    document.getElementById('modal-title').textContent = 'Add Share';
    document.getElementById('share-plugin-id').value = pluginId;
    document.getElementById('share-edit-mode').value = 'false';
    document.getElementById('share-original-name').value = '';

    // Reset form
    document.getElementById('share-name').value = '';
    document.getElementById('share-name').disabled = false;
    document.getElementById('share-path').value = '';
    document.getElementById('share-comment').value = '';
    document.getElementById('share-readonly').checked = false;
    document.getElementById('share-guest').checked = false;
    document.getElementById('share-browseable').checked = true;
    document.getElementById('share-enabled').checked = true;
    document.getElementById('share-users').value = '';

    document.getElementById('share-modal').classList.remove('hidden');
}

function openEditShareModal(pluginId, share) {
    document.getElementById('modal-title').textContent = 'Edit Share';
    document.getElementById('share-plugin-id').value = pluginId;
    document.getElementById('share-edit-mode').value = 'true';
    document.getElementById('share-original-name').value = share.name;

    document.getElementById('share-name').value = share.name;
    document.getElementById('share-name').disabled = true; // Can't change name
    document.getElementById('share-path').value = share.path || '';
    document.getElementById('share-comment').value = share.comment || '';
    document.getElementById('share-readonly').checked = share.read_only || false;
    document.getElementById('share-guest').checked = share.guest_ok || false;
    document.getElementById('share-browseable').checked = share.browseable !== false;
    document.getElementById('share-enabled').checked = share.enabled !== false;
    document.getElementById('share-users').value = share.valid_users || '';

    document.getElementById('share-modal').classList.remove('hidden');
}

function openEditShareModalFromButton(button) {
    const pluginId = button.getAttribute('data-plugin-id');
    const shareData = button.getAttribute('data-share');
    if (!pluginId || !shareData) {
        showNotification('Missing share data', 'error');
        return;
    }
    try {
        const share = JSON.parse(decodeURIComponent(shareData));
        openEditShareModal(pluginId, share);
    } catch (e) {
        showNotification('Failed to load share data', 'error');
    }
}

function closeShareModal() {
    document.getElementById('share-modal').classList.add('hidden');
}

async function saveShare(event) {
    event.preventDefault();

    const pluginId = document.getElementById('share-plugin-id').value;
    const isEdit = document.getElementById('share-edit-mode').value === 'true';
    const originalName = document.getElementById('share-original-name').value;

    const share = {
        name: document.getElementById('share-name').value.trim(),
        path: document.getElementById('share-path').value.trim(),
        comment: document.getElementById('share-comment').value.trim(),
        read_only: document.getElementById('share-readonly').checked,
        guest_ok: document.getElementById('share-guest').checked,
        browseable: document.getElementById('share-browseable').checked,
        enabled: document.getElementById('share-enabled').checked,
        valid_users: document.getElementById('share-users').value.trim()
    };

    try {
        let res;
        if (isEdit) {
            res = await requestApiResponse(`/api/storage/shares/${pluginId}/${encodeURIComponent(originalName)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(share)
            });
        } else {
            res = await requestApiResponse(`/api/storage/shares/${pluginId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(share)
            });
        }

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || 'Failed to save share');
        }

        showNotification(isEdit ? 'Share updated' : 'Share created', 'success');
        closeShareModal();
        await renderSharePlugins();
    } catch (e) {
        showNotification(`Error: ${e.message}`, 'error');
    }
}

async function toggleShare(pluginId, shareName, enabled) {
    try {
        const res = await requestApiResponse(`/api/storage/shares/${pluginId}/${encodeURIComponent(shareName)}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || 'Failed to toggle share');
        }

        showNotification(`Share ${enabled ? 'enabled' : 'disabled'}`, 'success');
        await renderSharePlugins();
    } catch (e) {
        showNotification(`Error: ${e.message}`, 'error');
        await renderSharePlugins(); // Reset toggle state
    }
}

async function deleteShare(pluginId, shareName) {
    if (!confirm(`Delete share "${shareName}"? This cannot be undone.`)) {
        return;
    }

    try {
        const res = await requestApiResponse(`/api/storage/shares/${pluginId}/${encodeURIComponent(shareName)}`, {
            method: 'DELETE'
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || 'Failed to delete share');
        }

        showNotification('Share deleted', 'success');
        await renderSharePlugins();
    } catch (e) {
        showNotification(`Error: ${e.message}`, 'error');
    }
}

async function runPluginCommand(pluginId, commandId) {
    if (commandId === 'restart' && !confirm('Restart Samba service? This will briefly disconnect clients.')) {
        return;
    }

    document.getElementById('output-modal-title').textContent =
        commandId === 'restart' ? 'Restarting Service' : 'Applying Configuration';
    document.getElementById('output-content').textContent = '';
    document.getElementById('output-modal').classList.remove('hidden');

    try {
        const res = await requestApiResponse(`/api/storage/plugins/${pluginId}/commands/${commandId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'output') {
                            document.getElementById('output-content').textContent += data.line;
                        } else if (data.type === 'complete') {
                            if (data.success) {
                                showNotification(data.message || 'Command completed', 'success');
                            }
                        } else if (data.type === 'error') {
                            document.getElementById('output-content').textContent += `\nError: ${data.error}`;
                        }
                    } catch (e) {}
                }
            }
        }

        await renderSharePlugins();
    } catch (e) {
        document.getElementById('output-content').textContent += `\nError: ${e.message}`;
        showNotification(`Error: ${e.message}`, 'error');
    }
}

function closeOutputModal() {
    document.getElementById('output-modal').classList.add('hidden');
}

function bindSharePageActions() {
    document.getElementById('share-form')?.addEventListener('submit', saveShare);

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('[data-action]');
        if (trigger) {
            const { action } = trigger.dataset;
            if (action === 'close-share-modal') {
                closeShareModal();
            } else if (action === 'close-output-modal') {
                closeOutputModal();
            }
        }

        if (event.target instanceof HTMLElement && event.target.matches('[data-overlay-close]')) {
            const modalId = event.target.dataset.overlayClose;
            if (modalId) {
                document.getElementById(modalId)?.classList.add('hidden');
            }
        }
    });
}

(async function initSharesPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    bindSharePageActions();
    await loadSharePlugins();
})();
