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

let mountPlugins = [];
let currentMountPlugin = null;
let currentMountId = null;
let mediaPaths = {};

function normalizeMountPlugins(rawPlugins) {
    if (!Array.isArray(rawPlugins)) {
        return [];
    }

    return rawPlugins
        .filter((plugin) => plugin && typeof plugin === 'object')
        .map((plugin) => ({
            ...plugin,
            id: typeof plugin.id === 'string' ? plugin.id.trim() : '',
            category: typeof plugin.category === 'string' ? plugin.category : '',
        }))
        .filter((plugin) => plugin.id && plugin.category === 'mount' && plugin.enabled);
}

async function loadPage() {
    await Promise.all([
        loadMediaPaths(),
        loadMountPlugins()
    ]);
}

// ========== Media Paths ==========
async function loadMediaPaths() {
    try {
        const response = await requestApiResponse('/api/disks/media-paths');
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || `Failed to load media paths (${response.status})`);
        }
        mediaPaths = data.paths || {};

        document.getElementById('path-downloads').value = mediaPaths.downloads || '';
        document.getElementById('path-storage').value = mediaPaths.storage || '';
        document.getElementById('path-backup').value = mediaPaths.backup || '';
        document.getElementById('path-config').value = mediaPaths.config || '';
    } catch (error) {
        console.error('Failed to load media paths:', error);
    }
}

async function saveMediaPaths() {
    const paths = {
        downloads: document.getElementById('path-downloads').value,
        storage: document.getElementById('path-storage').value,
        backup: document.getElementById('path-backup').value,
        config: document.getElementById('path-config').value
    };

    try {
        const response = await requestApiResponse('/api/disks/media-paths', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(paths)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        showNotification('Media paths saved', 'success');
        mediaPaths = data.paths;
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// ========== Startup Service Diff ==========
async function previewStartupService() {
    try {
        const res = await requestApiResponse('/api/disks/startup-service/preview');
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.error || `Preview failed (${res.status})`;
            showNotification(errMsg, 'error');
            // Fallback to simple apply
            if (confirm('Preview unavailable. Apply startup service changes anyway?')) {
                applyStartupService();
            }
            return;
        }
        const data = await res.json();

        if (!data.script?.changed && !data.service?.changed) {
            showNotification('No changes needed', 'info');
            return;
        }

        renderDiff(data);
        document.getElementById('diff-modal').classList.remove('hidden');
    } catch (e) {
        console.error('Preview error:', e);
        showNotification('Preview failed: ' + e.message, 'error');
        // Fallback: just apply
        if (confirm('Preview unavailable. Apply startup service changes anyway?')) {
            applyStartupService();
        }
    }
}

function renderDiff(data) {
    const content = document.getElementById('diff-content');
    let html = '';

    if (data.script?.changed) {
        html += `
            <div>
                <h4 class="font-semibold mb-2">${escapeHtml(data.script.path)}</h4>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <p class="text-sm text-gray-400 mb-1">Current</p>
                        <pre class="bg-gray-900 p-3 rounded text-xs overflow-auto max-h-64 text-red-300">${escapeHtml(data.script.current || '(file does not exist)')}</pre>
                    </div>
                    <div>
                        <p class="text-sm text-gray-400 mb-1">Proposed</p>
                        <pre class="bg-gray-900 p-3 rounded text-xs overflow-auto max-h-64 text-green-300">${escapeHtml(data.script.proposed)}</pre>
                    </div>
                </div>
            </div>
        `;
    }

    if (data.service?.changed) {
        html += `
            <div>
                <h4 class="font-semibold mb-2">${escapeHtml(data.service.path)}</h4>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <p class="text-sm text-gray-400 mb-1">Current</p>
                        <pre class="bg-gray-900 p-3 rounded text-xs overflow-auto max-h-64 text-red-300">${escapeHtml(data.service.current || '(file does not exist)')}</pre>
                    </div>
                    <div>
                        <p class="text-sm text-gray-400 mb-1">Proposed</p>
                        <pre class="bg-gray-900 p-3 rounded text-xs overflow-auto max-h-64 text-green-300">${escapeHtml(data.service.proposed)}</pre>
                    </div>
                </div>
            </div>
        `;
    }

    content.innerHTML = html || '<p class="text-gray-400">No changes to preview</p>';
}

function closeDiffModal() {
    document.getElementById('diff-modal').classList.add('hidden');
}

async function applyStartupService() {
    try {
        const res = await requestApiResponse('/api/disks/startup-service', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to update service');
        showNotification('Startup service updated', 'success');
        closeDiffModal();
    } catch (e) {
        showNotification('Failed: ' + e.message, 'error');
    }
}

// ========== Mount Plugins ==========
async function loadMountPlugins() {
    setNodeContent('mount-plugins', createLoadingState({
        message: 'Loading mount plugins...',
        containerClass: 'text-center py-10',
        messageClass: 'text-gray-400',
    }));

    try {
        const res = await requestApiResponse('/api/storage/plugins');
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || `Failed to load plugins (${res.status})`);
        }

        mountPlugins = normalizeMountPlugins(data.plugins);

        await renderMountPluginSections();
    } catch (e) {
        setNodeContent('mount-plugins', createErrorState({
            title: `Failed to load plugins: ${e.message}`,
            containerClass: 'text-center py-10',
            titleClass: 'text-red-400',
        }));
    }
}

async function renderMountPluginSections() {
    const container = document.getElementById('mount-plugins');

    if (!mountPlugins.length) {
        setNodeContent('mount-plugins', createEmptyState({
            title: 'No mount plugins enabled.',
            action: { href: '/plugins.html', label: 'Enable plugins →' },
            containerClass: 'text-center py-10',
            titleClass: 'text-gray-500 mb-2',
            actionClass: 'text-purple-400 hover:underline',
        }));
        return;
    }

    let html = '';
    for (const plugin of mountPlugins) {
        // Fetch mounts for this plugin
        let mounts = [];
        try {
            const res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(plugin.id)}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.error || `Failed to load mounts (${res.status})`);
            }
            mounts = data.mounts || [];
        } catch (e) {
            console.error(`Failed to load mounts for ${plugin.id}:`, e);
        }

        html += `
            <section class="bg-gray-800 border border-purple-900/40 rounded-lg p-5 mb-6">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h3 class="text-lg font-semibold">${escapeHtml(plugin.name)}</h3>
                        <p class="text-sm text-gray-400">${escapeHtml(plugin.description)}</p>
                    </div>
                    <div class="flex gap-2">
                        <button type="button"
                                class="js-detect-mounts py-2 px-4 rounded text-sm border border-purple-700 text-purple-300 hover:bg-purple-900"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                ${!plugin.installed ? 'disabled' : ''}
                                title="Detect existing mounts on this system">
                            Detect
                        </button>
                        <button type="button"
                                class="js-open-add-mount coraline-button py-2 px-4 rounded text-sm"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                ${!plugin.installed ? 'disabled title="Install dependencies first"' : ''}>
                            + Add Mount
                        </button>
                    </div>
                </div>

                ${!plugin.installed ? `
                    <div class="p-3 bg-yellow-900/20 border border-yellow-800 rounded mb-4">
                        <p class="text-sm text-yellow-300 mb-1">Install required packages:</p>
                        <code class="text-xs bg-gray-900 px-2 py-1 rounded">${escapeHtml(plugin.install_instructions)}</code>
                    </div>
                ` : ''}

                <div class="space-y-3" id="mounts-${encodeDataAttr(plugin.id)}">
                    ${mounts.length === 0 ?
                        '<p class="text-gray-500 text-sm">No mounts configured</p>' :
                        mounts.map(m => renderMountCard(plugin.id, m)).join('')
                    }
                </div>
            </section>
        `;
    }

    container.innerHTML = html;
    bindMountPluginActions(container);
}

function bindMountPluginActions(container) {
    if (!container) return;

    container.querySelectorAll('.js-detect-mounts').forEach((button) => {
        button.addEventListener('click', () => {
            detectMounts(button.dataset.pluginId || '');
        });
    });

    container.querySelectorAll('.js-open-add-mount').forEach((button) => {
        button.addEventListener('click', () => {
            openAddMountModal(button.dataset.pluginId || '');
        });
    });

    container.querySelectorAll('.js-mount-remote').forEach((button) => {
        button.addEventListener('click', () => {
            mountRemote(button.dataset.pluginId || '', button.dataset.mountId || '');
        });
    });

    container.querySelectorAll('.js-unmount-remote').forEach((button) => {
        button.addEventListener('click', () => {
            unmountRemote(button.dataset.pluginId || '', button.dataset.mountId || '');
        });
    });

    container.querySelectorAll('.js-edit-mount').forEach((button) => {
        button.addEventListener('click', () => {
            editMount(button.dataset.pluginId || '', button.dataset.mountId || '');
        });
    });

    container.querySelectorAll('.js-remove-mount').forEach((button) => {
        button.addEventListener('click', () => {
            removeMount(button.dataset.pluginId || '', button.dataset.mountId || '');
        });
    });
}

function renderMountCard(pluginId, mount) {
    const statusClass = mount.mounted ? 'status-connected' : 'status-disconnected';
    const statusText = mount.mounted ? 'Connected' : 'Disconnected';

    // Build source display based on plugin type
    let sourceDisplay = '';
    if (mount.host && mount.username) {
        // SSHFS
        sourceDisplay = `${mount.username}@${mount.host}:${mount.remote_path || '/'}`;
    } else if (mount.bucket) {
        // Rclone/S3
        sourceDisplay = `${mount.backend || 's3'}:${mount.bucket}`;
    } else {
        sourceDisplay = mount.remote_path || 'Unknown source';
    }

    return `
        <div class="bg-gray-900 rounded p-4 flex items-center justify-between">
            <div class="flex-1">
                <h4 class="font-medium">${escapeHtml(mount.name)}</h4>
                <p class="text-sm text-gray-400">${escapeHtml(sourceDisplay)}</p>
                <p class="text-xs text-gray-500">\u2192 ${escapeHtml(mount.mount_point)}</p>
            </div>
            <div class="flex items-center gap-3">
                <span class="status-pill ${statusClass}">${statusText}</span>
                ${mount.mounted ?
                    `<button type="button" class="js-unmount-remote text-sm text-red-400 hover:text-red-300" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}">Unmount</button>` :
                    `<button type="button" class="js-mount-remote text-sm text-green-400 hover:text-green-300" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}">Mount</button>`
                }
                <button type="button" class="js-edit-mount text-sm text-gray-400 hover:text-white" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}">Edit</button>
                <button type="button" class="js-remove-mount text-sm text-gray-400 hover:text-red-400" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}">Remove</button>
            </div>
        </div>
    `;
}

// ========== Mount Operations ==========
async function mountRemote(pluginId, mountId) {
    try {
        const res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(pluginId)}/${encodeURIComponent(mountId)}/mount`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        showNotification('Mounted successfully', 'success');
        loadMountPlugins();
    } catch (e) {
        showNotification('Mount failed: ' + e.message, 'error');
    }
}

async function unmountRemote(pluginId, mountId) {
    try {
        const res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(pluginId)}/${encodeURIComponent(mountId)}/unmount`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        showNotification('Unmounted successfully', 'success');
        loadMountPlugins();
    } catch (e) {
        showNotification('Unmount failed: ' + e.message, 'error');
    }
}

async function removeMount(pluginId, mountId) {
    if (!confirm('Remove this mount configuration?')) return;
    try {
        const res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(pluginId)}/${encodeURIComponent(mountId)}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        showNotification('Mount removed', 'success');
        loadMountPlugins();
    } catch (e) {
        showNotification('Remove failed: ' + e.message, 'error');
    }
}

async function detectMounts(pluginId) {
    try {
        showNotification('Detecting existing mounts...', 'info');
        const res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(pluginId)}/detect`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);

        if (data.imported > 0) {
            showNotification(`Imported ${data.imported} mount(s)`, 'success');
            loadMountPlugins();
        } else {
            showNotification(data.message || 'No new mounts found', 'info');
        }
    } catch (e) {
        showNotification('Detection failed: ' + e.message, 'error');
    }
}

// ========== Mount Modal ==========
async function openAddMountModal(pluginId) {
    currentMountPlugin = pluginId;
    currentMountId = null;

    document.getElementById('mount-modal-title').textContent = 'Add Mount';

    // Load schema for this plugin
    try {
        const res = await requestApiResponse(`/api/storage/plugins/${encodeURIComponent(pluginId)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || `Failed to load plugin schema (${res.status})`);
        }
        renderMountForm(data.schema, {});
    } catch (e) {
        showNotification('Failed to load form: ' + e.message, 'error');
        return;
    }

    document.getElementById('mount-modal').classList.remove('hidden');
}

async function editMount(pluginId, mountId) {
    currentMountPlugin = pluginId;
    currentMountId = mountId;

    document.getElementById('mount-modal-title').textContent = 'Edit Mount';

    // Load plugin schema and mount data
    try {
        const [schemaRes, mountsRes] = await Promise.all([
            requestApiResponse(`/api/storage/plugins/${encodeURIComponent(pluginId)}`),
            requestApiResponse(`/api/storage/mounts/${encodeURIComponent(pluginId)}`)
        ]);
        const schemaData = await schemaRes.json().catch(() => ({}));
        const mountsData = await mountsRes.json().catch(() => ({}));
        if (!schemaRes.ok) {
            throw new Error(schemaData.error || `Failed to load plugin schema (${schemaRes.status})`);
        }
        if (!mountsRes.ok) {
            throw new Error(mountsData.error || `Failed to load mounts (${mountsRes.status})`);
        }
        const mount = (mountsData.mounts || []).find(m => m.id === mountId);
        renderMountForm(schemaData.schema, mount || {});
    } catch (e) {
        showNotification('Failed to load form: ' + e.message, 'error');
        return;
    }

    document.getElementById('mount-modal').classList.remove('hidden');
}

function renderMountForm(schema, values) {
    const form = document.getElementById('mount-modal-form');
    const schemaObj = schema && typeof schema === 'object' ? schema : {};
    const properties = schemaObj.properties && typeof schemaObj.properties === 'object' ? schemaObj.properties : {};
    const required = Array.isArray(schemaObj.required) ? schemaObj.required : [];

    let html = '';
    for (const [key, prop] of Object.entries(properties)) {
        if (key === 'id' && currentMountId) continue; // Don't show ID when editing

        const isRequired = required.includes(key);
        const value = values[key] ?? prop.default ?? '';
        const inputType = prop.type === 'integer' ? 'number'
            : key.includes('password') || key.includes('secret') ? 'password'
                : 'text';

        if (prop.enum) {
            const selectName = encodeDataAttr(key);
            html += `
                <div class="mb-4">
                    <label class="block text-sm text-gray-300 mb-1">${escapeHtml(prop.description || key)}${isRequired ? ' *' : ''}</label>
                    <select name="${selectName}" class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white text-sm">
                        ${prop.enum.map(opt => `<option value="${encodeDataAttr(opt)}" ${value === opt ? 'selected' : ''}>${escapeHtml(opt)}</option>`).join('')}
                    </select>
                </div>
            `;
        } else if (prop.type === 'boolean') {
            const inputName = encodeDataAttr(key);
            html += `
                <div class="mb-4 flex items-center gap-3">
                    <input type="checkbox" name="${inputName}" ${value ? 'checked' : ''} class="w-4 h-4 rounded">
                    <label class="text-sm text-gray-300">${escapeHtml(prop.description || key)}</label>
                </div>
            `;
        } else if (prop.type === 'object') {
            // Skip nested objects for simplicity
            continue;
        } else {
            const inputName = encodeDataAttr(key);
            html += `
                <div class="mb-4">
                    <label class="block text-sm text-gray-300 mb-1">${escapeHtml(prop.description || key)}${isRequired ? ' *' : ''}</label>
                    <input type="${inputType}" name="${inputName}" value="${escapeHtml(String(value))}"
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white text-sm"
                           ${isRequired ? 'required' : ''}>
                </div>
            `;
        }
    }

    form.innerHTML = html || '<p class="text-gray-400">No configuration options</p>';
}

function closeMountModal() {
    document.getElementById('mount-modal').classList.add('hidden');
    currentMountPlugin = null;
    currentMountId = null;
}

async function submitMountForm() {
    if (!currentMountPlugin) {
        showNotification('No mount plugin selected', 'error');
        return;
    }

    const form = document.getElementById('mount-modal-form');
    const formData = {};

    form.querySelectorAll('input, select').forEach(el => {
        if (el.type === 'checkbox') {
            formData[el.name] = el.checked;
        } else if (el.type === 'number') {
            formData[el.name] = parseInt(el.value, 10) || 0;
        } else {
            formData[el.name] = el.value;
        }
    });

    // Include original ID when editing
    if (currentMountId) {
        formData.id = currentMountId;
    }

    try {
        let res;
        if (currentMountId) {
            res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(currentMountPlugin)}/${encodeURIComponent(currentMountId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
        } else {
            res = await requestApiResponse(`/api/storage/mounts/${encodeURIComponent(currentMountPlugin)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.error);

        showNotification(currentMountId ? 'Mount updated' : 'Mount added', 'success');
        closeMountModal();
        loadMountPlugins();
    } catch (e) {
        showNotification('Failed: ' + e.message, 'error');
    }
}

function bindMountPageActions() {
    document.getElementById('save-media-paths')?.addEventListener('click', saveMediaPaths);
    document.getElementById('preview-startup-service')?.addEventListener('click', previewStartupService);

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('[data-action]');
        if (trigger) {
            const { action } = trigger.dataset;
            switch (action) {
            case 'close-mount-modal':
                closeMountModal();
                break;
            case 'submit-mount-form':
                submitMountForm();
                break;
            case 'close-diff-modal':
                closeDiffModal();
                break;
            case 'apply-startup-service':
                applyStartupService();
                break;
            default:
                break;
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

(async function initMountsPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    bindMountPageActions();
    await loadPage();
})();
