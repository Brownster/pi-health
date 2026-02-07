import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearElement, createEmptyState, createErrorState, createLoadingState } from '/js/lib/states.js';
import { requestApiResponse } from '/js/lib/http.js';
import { escapeHtml, encodeDataAttr } from '/js/lib/format.js';
import { showNotification } from '/js/lib/notify.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

const CATEGORY_LINKS = {
    storage: '/pools.html',
    mount: '/mounts.html',
    share: '/shares.html',
};

const CATEGORY_SECTIONS = [
    {
        key: 'storage',
        title: 'Storage Pools',
        description: 'Configure these plugins on the <a href="/pools.html" class="text-purple-400 hover:underline">Pools</a> page.',
        iconPath: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4',
    },
    {
        key: 'mount',
        title: 'Remote Mounts',
        description: 'Configure these plugins on the <a href="/mounts.html" class="text-purple-400 hover:underline">Mounts</a> page.',
        iconPath: 'M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2',
    },
    {
        key: 'share',
        title: 'Network Shares',
        description: 'Configure these plugins on the <a href="/shares.html" class="text-purple-400 hover:underline">Shares</a> page.',
        iconPath: 'M3 7h8m-8 5h18m-10 5h10',
    },
];

function statusClass(status) {
    if (status === 'healthy') return 'status-healthy';
    if (status === 'error') return 'status-error';
    return 'status-unconfigured';
}

function setContainerNode(node) {
    const container = document.getElementById('plugins-list');
    if (!container) {
        return;
    }
    clearElement(container);
    container.appendChild(node);
}

async function loadPlugins() {
    setContainerNode(createLoadingState({
        message: 'Loading plugins...',
        containerClass: 'text-center py-10',
        messageClass: 'text-gray-400',
    }));

    try {
        const response = await requestApiResponse('/api/storage/plugins');
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload?.error || `Failed to load plugins (${response.status})`);
        }
        renderPlugins(payload.plugins || []);
    } catch (error) {
        setContainerNode(createErrorState({
            title: `Failed to load plugins: ${error.message}`,
            containerClass: 'text-center py-10',
            titleClass: 'text-red-400',
        }));
    }
}

function renderPlugins(plugins) {
    const container = document.getElementById('plugins-list');
    if (!container) {
        return;
    }

    if (!plugins.length) {
        setContainerNode(createEmptyState({
            title: 'No plugins available',
            containerClass: 'text-center py-10',
            titleClass: 'text-gray-500',
        }));
        return;
    }

    let html = '';
    for (const section of CATEGORY_SECTIONS) {
        const sectionPlugins = plugins.filter((plugin) => plugin.category === section.key);
        if (!sectionPlugins.length) {
            continue;
        }

        html += `
            <div class="mb-6">
                <h3 class="text-lg font-semibold mb-3 flex items-center">
                    <svg class="w-5 h-5 mr-2 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${section.iconPath}"></path>
                    </svg>
                    ${section.title}
                </h3>
                <p class="text-sm text-gray-400 mb-3">${section.description}</p>
                ${sectionPlugins.map((plugin) => renderPluginCard(plugin)).join('')}
            </div>
        `;
    }

    container.innerHTML = html;
    bindPluginActions(container);
}

function renderPluginCard(plugin) {
    const statusValue = String(plugin.status || 'unconfigured');
    const statusCss = statusClass(statusValue);
    const pluginId = String(plugin.id || '');
    const categoryLink = CATEGORY_LINKS[plugin.category] || '';

    return `
        <div class="bg-gray-800 border border-purple-900/40 rounded-lg p-5 mb-3">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-lg font-semibold">${escapeHtml(plugin.name || pluginId || 'Unknown Plugin')}</h4>
                        <span class="status-pill ${statusCss}">${escapeHtml(statusValue)}</span>
                    </div>
                    <p class="text-sm text-gray-400 mb-2">${escapeHtml(plugin.description || '')}</p>
                    <p class="text-xs text-gray-500">Version ${escapeHtml(plugin.version || 'unknown')}</p>
                    ${plugin.source ? `<p class="text-xs text-gray-500 mt-1">Source: ${escapeHtml(plugin.source)}</p>` : ''}

                    ${!plugin.installed ? `
                        <div class="mt-3 p-3 bg-yellow-900/20 border border-yellow-800 rounded">
                            <p class="text-sm text-yellow-300 mb-2">Missing dependencies</p>
                            <code class="text-xs bg-gray-900 px-2 py-1 rounded">${escapeHtml(plugin.install_instructions || '')}</code>
                        </div>
                    ` : ''}

                    ${plugin.enabled && plugin.configured && categoryLink ? `
                        <a href="${categoryLink}" class="inline-block mt-3 text-sm text-purple-400 hover:text-purple-300">
                            Configure &rarr;
                        </a>
                    ` : ''}
                </div>

                <div class="flex items-center gap-4 ml-4">
                    ${plugin.type && plugin.type !== 'builtin' ? `
                        <button type="button"
                                class="text-xs text-red-300 hover:text-red-200 js-remove-plugin"
                                data-plugin-id="${encodeDataAttr(pluginId)}">
                            Remove
                        </button>
                    ` : ''}
                    <label class="toggle-switch">
                        <input type="checkbox"
                               class="js-plugin-toggle"
                               data-plugin-id="${encodeDataAttr(pluginId)}"
                               ${plugin.enabled ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
        </div>
    `;
}

function bindPluginActions(container) {
    container.querySelectorAll('.js-plugin-toggle').forEach((checkbox) => {
        checkbox.addEventListener('change', async () => {
            const pluginId = checkbox.dataset.pluginId || '';
            checkbox.disabled = true;
            await togglePlugin(pluginId, checkbox.checked);
            checkbox.disabled = false;
        });
    });

    container.querySelectorAll('.js-remove-plugin').forEach((button) => {
        button.addEventListener('click', async () => {
            const pluginId = button.dataset.pluginId || '';
            await removePlugin(pluginId);
        });
    });
}

async function togglePlugin(pluginId, enabled) {
    if (!pluginId) {
        showNotification('Plugin ID is missing', 'error');
        await loadPlugins();
        return;
    }

    try {
        const response = await requestApiResponse(`/api/storage/plugins/${encodeURIComponent(pluginId)}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload?.error || 'Failed to update plugin');
        }

        showNotification(`Plugin ${enabled ? 'enabled' : 'disabled'}`, 'success');
        await loadPlugins();
    } catch (error) {
        showNotification(`Failed: ${error.message}`, 'error');
        await loadPlugins();
    }
}

function openInstallModal() {
    const modal = document.getElementById('install-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

function closeInstallModal() {
    const modal = document.getElementById('install-modal');
    const form = document.getElementById('install-form');
    if (modal) {
        modal.classList.add('hidden');
    }
    if (form) {
        form.reset();
    }
    toggleInstallType('github');
}

function toggleInstallType(type) {
    const sourceInput = document.querySelector('#install-form input[name="source"]');
    const pipFields = document.getElementById('pip-fields');
    const entryInput = document.querySelector('#install-form input[name="entry"]');
    const classInput = document.querySelector('#install-form input[name="class_name"]');

    if (sourceInput) {
        sourceInput.placeholder = type === 'pip' ? 'pihealth-plugin-foo' : 'https://github.com/org/repo';
    }

    if (pipFields && entryInput && classInput) {
        if (type === 'pip') {
            pipFields.classList.remove('hidden');
            entryInput.required = true;
            classInput.required = true;
        } else {
            pipFields.classList.add('hidden');
            entryInput.required = false;
            classInput.required = false;
        }
    }
}

async function submitInstall() {
    const form = document.getElementById('install-form');
    if (!form) {
        showNotification('Install form not found', 'error');
        return;
    }

    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());

    try {
        const response = await requestApiResponse('/api/storage/plugins/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.error || 'Install failed');
        }

        showNotification('Plugin installed (restart to load)', 'success');
        closeInstallModal();
        await loadPlugins();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function removePlugin(pluginId) {
    if (!pluginId) {
        showNotification('Plugin ID is missing', 'error');
        return;
    }

    if (!window.confirm('Remove this plugin?')) {
        return;
    }

    try {
        const response = await requestApiResponse(`/api/storage/plugins/${encodeURIComponent(pluginId)}/remove`, {
            method: 'DELETE',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.error || 'Remove failed');
        }

        showNotification('Plugin removed (restart to unload)', 'success');
        await loadPlugins();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

function bindPluginPageActions() {
    const openButton = document.getElementById('plugin-open-install');
    if (openButton) {
        openButton.addEventListener('click', openInstallModal);
    }

    const closeTopButton = document.getElementById('plugin-close-install-top');
    if (closeTopButton) {
        closeTopButton.addEventListener('click', closeInstallModal);
    }

    const closeBottomButton = document.getElementById('plugin-close-install-bottom');
    if (closeBottomButton) {
        closeBottomButton.addEventListener('click', closeInstallModal);
    }

    const installTypeSelect = document.getElementById('plugin-install-type');
    if (installTypeSelect) {
        installTypeSelect.addEventListener('change', (event) => {
            toggleInstallType(event.target.value);
        });
    }

    const submitButton = document.getElementById('plugin-submit-install');
    if (submitButton) {
        submitButton.addEventListener('click', submitInstall);
    }
}

(async function initPluginsPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    bindPluginPageActions();
    await loadPlugins();
})();
