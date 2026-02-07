import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearElement, createEmptyState, createErrorState, createLoadingState } from '/js/lib/states.js';
import { requestApiJson, requestApiResponse } from '/js/lib/http.js';
import { showNotification } from '/js/lib/notify.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-72 flex flex-col items-end',
    includeFooter: true,
});

let catalogItems = [];
let installedServices = [];
let serviceStacks = {};
let availableStacks = [];
let activeInstall = null;
let activeRemove = null;

async function requestApi(url, options = {}) {
    const response = await requestApiResponse(url, options);
    let payload = {};

    try {
        payload = await response.json();
    } catch (_err) {
        payload = {};
    }

    return { response, payload };
}

function showLoadingState(message = 'Loading catalog...') {
    const grid = document.getElementById('catalog-grid');
    clearElement(grid);
    grid.appendChild(createLoadingState({ message }));
}

function getItemStacks(itemId) {
    return serviceStacks[itemId] || [];
}

async function loadCatalog() {
    showLoadingState();

    try {
        const [catalogData, statusData, stacksData] = await Promise.all([
            requestApiJson('/api/catalog'),
            requestApiJson('/api/catalog/status'),
            requestApiJson('/api/stacks'),
        ]);

        catalogItems = catalogData.items || [];
        installedServices = statusData.services || [];
        serviceStacks = statusData.service_stacks || {};
        availableStacks = (stacksData.stacks || []).map((stack) => stack.name);

        renderCatalog();
    } catch (_error) {
        const grid = document.getElementById('catalog-grid');
        clearElement(grid);
        grid.appendChild(createErrorState({
            title: 'Failed to load catalog.',
            subtitle: 'Refresh the page and try again.',
        }));
    }
}

function buildCatalogCard(item) {
    const installed = installedServices.includes(item.id);
    const stacks = getItemStacks(item.id);

    const card = document.createElement('div');
    card.className = 'bg-gray-800 rounded-lg shadow-lg p-4 border border-purple-900/40';

    const header = document.createElement('div');
    header.className = 'flex justify-between items-start';

    const title = document.createElement('h3');
    title.className = 'text-lg font-semibold';
    title.textContent = item.name || item.id;

    header.appendChild(title);

    if (installed) {
        const badge = document.createElement('span');
        badge.className = 'text-green-400 text-xs';
        badge.textContent = 'Installed';
        header.appendChild(badge);
    }

    card.appendChild(header);

    const description = document.createElement('p');
    description.className = 'text-sm text-gray-400 mt-2';
    description.textContent = item.description || 'No description';
    card.appendChild(description);

    if (item.requires && item.requires.length) {
        const req = document.createElement('p');
        req.className = 'text-xs text-yellow-300 mt-2';
        req.textContent = `Requires: ${item.requires.join(', ')}`;
        card.appendChild(req);
    }

    if (stacks.length) {
        const stackInfo = document.createElement('p');
        stackInfo.className = 'text-xs text-green-300 mt-1';
        stackInfo.textContent = `Stack: ${stacks.join(', ')}`;
        card.appendChild(stackInfo);
    }

    const actions = document.createElement('div');
    actions.className = 'mt-4 flex space-x-2';

    if (installed) {
        const removeBtn = document.createElement('button');
        removeBtn.className = 'px-3 py-1 text-sm rounded bg-red-700 hover:bg-red-600 text-white';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', () => openRemoveModal(item.id));
        actions.appendChild(removeBtn);
    } else {
        const installBtn = document.createElement('button');
        installBtn.className = 'coraline-button px-3 py-1 text-sm rounded text-white';
        installBtn.textContent = 'Install';
        installBtn.addEventListener('click', () => openInstallModal(item.id));
        actions.appendChild(installBtn);
    }

    if (item.id === 'vpn') {
        const configureBtn = document.createElement('button');
        configureBtn.className = 'px-3 py-1 text-sm rounded bg-purple-700 hover:bg-purple-600 text-white';
        configureBtn.textContent = 'Configure';
        configureBtn.addEventListener('click', () => openVpnModal());
        actions.appendChild(configureBtn);
    }

    card.appendChild(actions);

    return card;
}

function renderCatalog() {
    const grid = document.getElementById('catalog-grid');
    clearElement(grid);

    if (!catalogItems.length) {
        grid.appendChild(createEmptyState({
            title: 'No catalog items found.',
            subtitle: 'Add templates under catalog/.',
            titleClass: 'text-gray-300 text-lg',
        }));
        return;
    }

    catalogItems.forEach((item) => {
        grid.appendChild(buildCatalogCard(item));
    });
}

function toggleStackName() {
    const select = document.getElementById('install-stack-select');
    const nameField = document.getElementById('new-stack-name-field');

    if (!select || !nameField) {
        return;
    }

    nameField.style.display = select.value === 'new' ? 'block' : 'none';
}

function buildInstallField(field) {
    const wrapper = document.createElement('div');

    const label = document.createElement('label');
    label.className = 'block text-sm text-gray-300 mb-1';
    label.textContent = field.label || field.key;

    const input = document.createElement('input');
    input.className = 'w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white';
    input.value = field.default || '';
    input.dataset.fieldKey = field.key;

    wrapper.appendChild(label);
    wrapper.appendChild(input);
    return wrapper;
}

function buildStackSelector(item) {
    const wrapper = document.createElement('div');
    wrapper.className = 'mt-4 pt-4 border-t border-gray-700';

    const label = document.createElement('label');
    label.className = 'block text-sm text-gray-300 mb-1';
    label.textContent = 'Target stack';

    const select = document.createElement('select');
    select.id = 'install-stack-select';
    select.className = 'w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white';

    const newOption = document.createElement('option');
    newOption.value = 'new';
    newOption.textContent = 'Create new stack';
    select.appendChild(newOption);

    availableStacks.forEach((name) => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });

    const requires = item.requires || [];
    let defaultStack = 'new';
    if (requires.includes('vpn') && serviceStacks.vpn && serviceStacks.vpn.length) {
        defaultStack = serviceStacks.vpn[0];
    }
    item.defaultStack = defaultStack;

    select.value = defaultStack;
    select.addEventListener('change', toggleStackName);

    const newStackField = document.createElement('div');
    newStackField.id = 'new-stack-name-field';
    newStackField.className = 'mt-3';

    const nameLabel = document.createElement('label');
    nameLabel.className = 'block text-sm text-gray-300 mb-1';
    nameLabel.textContent = 'New stack name';

    const nameInput = document.createElement('input');
    nameInput.id = 'install-stack-name';
    nameInput.className = 'w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white';
    nameInput.value = item.id || '';

    newStackField.appendChild(nameLabel);
    newStackField.appendChild(nameInput);

    wrapper.appendChild(label);
    wrapper.appendChild(select);
    wrapper.appendChild(newStackField);

    return wrapper;
}

function openInstallModalWithData(item) {
    const modal = document.getElementById('install-modal');
    const title = document.getElementById('install-title');
    const description = document.getElementById('install-description');
    const fieldsEl = document.getElementById('install-fields');

    activeInstall = item;

    title.textContent = `Install ${item.name || item.id}`;
    description.textContent = item.description || '';
    clearElement(fieldsEl);

    const fields = item.fields || [];
    if (!fields.length) {
        const empty = document.createElement('p');
        empty.className = 'text-sm text-gray-400';
        empty.textContent = 'No configuration fields for this app.';
        fieldsEl.appendChild(empty);
    } else {
        fields.forEach((field) => {
            fieldsEl.appendChild(buildInstallField(field));
        });
    }

    fieldsEl.appendChild(buildStackSelector(item));
    toggleStackName();

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

async function openInstallModal(id) {
    try {
        const data = await requestApiJson(`/api/catalog/${encodeURIComponent(id)}?apply_media_paths=true`);
        if (data.error || !data.item) {
            throw new Error(data.error || 'Failed to load app metadata');
        }

        openInstallModalWithData(data.item);
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

function closeInstallModal() {
    const modal = document.getElementById('install-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    activeInstall = null;
}

function openRemoveModal(id) {
    const modal = document.getElementById('remove-modal');
    const title = document.getElementById('remove-title');
    const stackSelect = document.getElementById('remove-stack-select');

    const stacks = getItemStacks(id);
    activeRemove = { id, stacks };

    title.textContent = `Remove ${id}`;
    clearElement(stackSelect);

    if (!stacks.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No stack found';
        stackSelect.appendChild(option);
        stackSelect.disabled = true;
    } else {
        stacks.forEach((name) => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            stackSelect.appendChild(option);
        });
        stackSelect.disabled = stacks.length <= 1;
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeRemoveModal() {
    const modal = document.getElementById('remove-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    activeRemove = null;
}

async function openVpnModal() {
    const modal = document.getElementById('vpn-modal');

    try {
        const { response, payload } = await requestApi('/api/setup/defaults');
        if (response.ok) {
            document.getElementById('vpn-config-dir').value = payload.config_dir || '/home/pi/docker';
            document.getElementById('vpn-network-name').value = payload.network_name || 'vpn_network';
        }
    } catch (_error) {
        // Ignore defaults fetch errors.
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeVpnModal() {
    const modal = document.getElementById('vpn-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

async function submitVpnConfig() {
    const payload = {
        config_dir: document.getElementById('vpn-config-dir').value.trim(),
        pia_username: document.getElementById('vpn-username').value.trim(),
        pia_password: document.getElementById('vpn-password').value.trim(),
        network_name: document.getElementById('vpn-network-name').value.trim() || 'vpn_network',
    };

    try {
        const { response, payload: data } = await requestApi('/api/setup/vpn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error(data.error || 'VPN setup failed');
        }

        showNotification('VPN setup complete', 'success');
        closeVpnModal();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

function getInstallValues() {
    const values = {};
    const fieldsContainer = document.getElementById('install-fields');
    fieldsContainer.querySelectorAll('input[data-field-key]').forEach((input) => {
        values[input.dataset.fieldKey] = input.value;
    });
    return values;
}

async function submitInstall() {
    if (!activeInstall) return;

    const values = getInstallValues();
    const stackSelect = document.getElementById('install-stack-select');
    const stackNameInput = document.getElementById('install-stack-name');
    const targetStack = stackSelect ? stackSelect.value : 'new';
    const stackName = stackNameInput ? stackNameInput.value.trim() : '';

    try {
        const { response, payload: data } = await requestApi('/api/catalog/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: activeInstall.id,
                values,
                start_service: true,
                target_stack: targetStack,
                stack_name: stackName,
            }),
        });

        if (!response.ok) {
            if (data.missing_dependencies && data.missing_dependencies.length > 0) {
                const deps = data.missing_dependencies.join(', ');
                if (window.confirm(`This app requires: ${deps}\n\nWould you like to install ${deps} first?`)) {
                    closeInstallModal();
                    openInstallModal(data.missing_dependencies[0]);
                    return;
                }
            }
            throw new Error(data.error || 'Install failed');
        }

        const msg = data.started ? `${data.name} installed and started` : `${data.name} installed`;
        showNotification(msg, 'success');
        closeInstallModal();
        loadCatalog();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function removeApp(id, targetStack) {
    if (!window.confirm(`Are you sure you want to remove ${id}? This will stop the container and remove it from the stack.`)) {
        return;
    }

    try {
        const { response, payload: data } = await requestApi('/api/catalog/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, stop_service: true, target_stack: targetStack }),
        });

        if (!response.ok) {
            if (data.dependents && data.dependents.length > 0) {
                const deps = data.dependents.join(', ');
                showNotification(`Cannot remove: ${deps} depend on this app. Remove them first.`, 'error');
                return;
            }
            throw new Error(data.error || 'Remove failed');
        }

        showNotification(`${id} removed successfully`, 'success');
        loadCatalog();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function submitRemove() {
    if (!activeRemove) return;

    const stackSelect = document.getElementById('remove-stack-select');
    const targetStack = stackSelect ? stackSelect.value : null;

    await removeApp(activeRemove.id, targetStack || null);
    closeRemoveModal();
}

function bindEvents() {
    document.getElementById('refresh-catalog-btn').addEventListener('click', loadCatalog);

    document.getElementById('install-close-btn').addEventListener('click', closeInstallModal);
    document.getElementById('install-cancel-btn').addEventListener('click', closeInstallModal);
    document.getElementById('install-submit-btn').addEventListener('click', submitInstall);

    document.getElementById('remove-close-btn').addEventListener('click', closeRemoveModal);
    document.getElementById('remove-cancel-btn').addEventListener('click', closeRemoveModal);
    document.getElementById('remove-submit-btn').addEventListener('click', submitRemove);

    document.getElementById('vpn-close-btn').addEventListener('click', closeVpnModal);
    document.getElementById('vpn-cancel-btn').addEventListener('click', closeVpnModal);
    document.getElementById('vpn-submit-btn').addEventListener('click', submitVpnConfig);

    document.getElementById('install-modal').addEventListener('click', (event) => {
        if (event.target.id === 'install-modal') {
            closeInstallModal();
        }
    });

    document.getElementById('remove-modal').addEventListener('click', (event) => {
        if (event.target.id === 'remove-modal') {
            closeRemoveModal();
        }
    });

    document.getElementById('vpn-modal').addEventListener('click', (event) => {
        if (event.target.id === 'vpn-modal') {
            closeVpnModal();
        }
    });
}

(async function initAppsPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;

    bindEvents();
    await loadCatalog();
})();
