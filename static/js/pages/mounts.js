import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearClientSession } from '/js/lib/session.js';
import { clearElement, createEmptyState, createErrorState, createLoadingState } from '/js/lib/states.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (response.status === 401) {
        clearClientSession();
        window.location.href = '/login.html';
        throw new Error('Authentication required');
    }
    return response;
}

let mountPlugins = [];
let currentMountPlugin = null;
let currentMountId = null;
let mediaPaths = {};

function setNodeContent(containerId, node) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }
    clearElement(container);
    container.appendChild(node);
}

function showNotification(message, type = 'info') {
    const area = document.getElementById('notification-area');
    const notification = document.createElement('div');
    notification.className = 'p-3 mb-2 rounded shadow-lg transform transition-all duration-300 opacity-0';
    if (type === 'success') notification.classList.add('bg-green-600');
    else if (type === 'error') notification.classList.add('bg-red-600');
    else notification.classList.add('bg-blue-600');
    notification.textContent = message;
    area.appendChild(notification);
    setTimeout(() => notification.classList.replace('opacity-0', 'opacity-100'), 10);
    setTimeout(() => {
        notification.classList.replace('opacity-100', 'opacity-0');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function encodeDataAttr(value) {
    return escapeHtml(String(value ?? ''));
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
        const response = await apiFetch('/api/disks/media-paths');
        const data = await response.json();
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
        const response = await apiFetch('/api/disks/media-paths', {
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
        const res = await apiFetch('/api/disks/startup-service/preview');
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
        const res = await apiFetch('/api/disks/startup-service', { method: 'POST' });
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
        const res = await apiFetch('/api/storage/plugins');
        const data = await res.json();

        // Filter to only mount-category plugins that are enabled
        mountPlugins = (data.plugins || []).filter(p =>
            p.category === 'mount' && p.enabled
        );

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
            const res = await apiFetch(`/api/storage/mounts/${plugin.id}`);
            const data = await res.json();
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
                        <button onclick="detectMounts(this.dataset.pluginId)"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                class="py-2 px-4 rounded text-sm border border-purple-700 text-purple-300 hover:bg-purple-900"
                                ${!plugin.installed ? 'disabled' : ''}
                                title="Detect existing mounts on this system">
                            Detect
                        </button>
                        <button onclick="openAddMountModal(this.dataset.pluginId)"
                                data-plugin-id="${encodeDataAttr(plugin.id)}"
                                class="coraline-button py-2 px-4 rounded text-sm"
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
                    `<button onclick="unmountRemote(this.dataset.pluginId, this.dataset.mountId)" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}" class="text-sm text-red-400 hover:text-red-300">Unmount</button>` :
                    `<button onclick="mountRemote(this.dataset.pluginId, this.dataset.mountId)" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}" class="text-sm text-green-400 hover:text-green-300">Mount</button>`
                }
                <button onclick="editMount(this.dataset.pluginId, this.dataset.mountId)" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}" class="text-sm text-gray-400 hover:text-white">Edit</button>
                <button onclick="removeMount(this.dataset.pluginId, this.dataset.mountId)" data-plugin-id="${encodeDataAttr(pluginId)}" data-mount-id="${encodeDataAttr(mount.id)}" class="text-sm text-gray-400 hover:text-red-400">Remove</button>
            </div>
        </div>
    `;
}

// ========== Mount Operations ==========
async function mountRemote(pluginId, mountId) {
    try {
        const res = await apiFetch(`/api/storage/mounts/${pluginId}/${mountId}/mount`, { method: 'POST' });
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
        const res = await apiFetch(`/api/storage/mounts/${pluginId}/${mountId}/unmount`, { method: 'POST' });
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
        const res = await apiFetch(`/api/storage/mounts/${pluginId}/${mountId}`, { method: 'DELETE' });
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
        const res = await apiFetch(`/api/storage/mounts/${pluginId}/detect`, { method: 'POST' });
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
        const res = await apiFetch(`/api/storage/plugins/${pluginId}`);
        const data = await res.json();
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
            apiFetch(`/api/storage/plugins/${pluginId}`),
            apiFetch(`/api/storage/mounts/${pluginId}`)
        ]);
        const schemaData = await schemaRes.json();
        const mountsData = await mountsRes.json();
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
    const properties = schema.properties || {};
    const required = schema.required || [];

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
            res = await apiFetch(`/api/storage/mounts/${currentMountPlugin}/${currentMountId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
        } else {
            res = await apiFetch(`/api/storage/mounts/${currentMountPlugin}`, {
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

Object.assign(window, {
    saveMediaPaths,
    previewStartupService,
    closeDiffModal,
    applyStartupService,
    detectMounts,
    openAddMountModal,
    closeMountModal,
    submitMountForm,
    mountRemote,
    unmountRemote,
    editMount,
    removeMount,
});

(async function initMountsPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    await loadPage();
})();
