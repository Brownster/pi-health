import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { requestApiJson } from '/js/lib/http.js';
import { formatBytes as formatBaseBytes } from '/js/lib/format.js';
import { showNotification as showBaseNotification } from '/js/lib/notify.js';

window.logout = logoutToLogin;

function showNotification(message, type = 'info') {
    showBaseNotification(message, type, {
        baseClass: 'bg-opacity-90 p-3 mb-2 rounded shadow-lg transform transition-all duration-500 opacity-0 text-white',
    });
}

function formatDateTime(date) {
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
}

function formatBytes(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value < 0) return '—';
    return formatBaseBytes(value, 1);
}

function getStatColorClass(percent) {
    if (!Number.isFinite(percent)) return 'text-gray-500';
    if (percent < 50) return 'text-green-400';
    if (percent < 80) return 'text-yellow-400';
    return 'text-red-400';
}

function loadingSpinner() {
    return '<div class="loading-spinner"></div>';
}

function normalizePercent(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
}

function formatCpuCell(cpuPercent, loading = false) {
    if (loading) return loadingSpinner();
    const pct = normalizePercent(cpuPercent);
    if (pct === null) return '<span class="text-gray-500">—</span>';

    const colorClass = getStatColorClass(pct);
    const barColor = pct < 50 ? 'bg-green-500' : pct < 80 ? 'bg-yellow-500' : 'bg-red-500';
    return `
        <span class="${colorClass} text-sm">${pct.toFixed(1)}%</span>
        <div class="w-full bg-gray-700 rounded-full h-1.5 mt-1">
            <div class="${barColor} h-1.5 rounded-full" style="width: ${Math.min(pct, 100)}%"></div>
        </div>
    `;
}

function formatMemoryCell(memPercent, memUsed, memLimit, loading = false) {
    if (loading) return loadingSpinner();
    const pct = normalizePercent(memPercent);
    if (pct === null) return '<span class="text-gray-500">—</span>';

    const colorClass = getStatColorClass(pct);
    const barColor = pct < 50 ? 'bg-green-500' : pct < 80 ? 'bg-yellow-500' : 'bg-red-500';
    return `
        <span class="${colorClass} text-sm">${pct.toFixed(1)}%</span>
        <div class="text-xs text-gray-400">${formatBytes(memUsed)} / ${formatBytes(memLimit)}</div>
        <div class="w-full bg-gray-700 rounded-full h-1.5 mt-1">
            <div class="${barColor} h-1.5 rounded-full" style="width: ${Math.min(pct, 100)}%"></div>
        </div>
    `;
}

let currentFilter = 'all';
let containerList = [];
let initialLoadComplete = false;
let previousNetworkStats = {};
let lastFetchTime = null;
let statsLoading = false;

function getContainerListEl() {
    return document.getElementById('container-list');
}

function findContainerRow(containerId) {
    const list = getContainerListEl();
    if (!list) return null;
    const id = String(containerId);
    return Array.from(list.querySelectorAll('tr[data-container-id]')).find((row) => row.dataset.containerId === id) || null;
}

function getContainerNameById(id) {
    const containerId = String(id);
    const cached = containerList.find((item) => String(item.id) === containerId);
    if (cached) return cached.name || containerId;

    const row = findContainerRow(containerId);
    return row ? (row.dataset.containerName || containerId) : containerId;
}

function getWebUIPort(container) {
    if (!container.ports || container.ports.length === 0) return null;

    const tcpPorts = container.ports.filter((port) => port.protocol !== 'udp');
    const hostTcp = tcpPorts.find((port) => port.host_port);
    const anyHost = container.ports.find((port) => port.host_port);
    const tcpContainer = tcpPorts.find((port) => port.container_port);
    const fallback = container.ports.find((port) => port.container_port);

    const candidate = hostTcp?.host_port || anyHost?.host_port || tcpContainer?.container_port || fallback?.container_port;
    const port = Number(candidate);
    if (!Number.isInteger(port) || port <= 0 || port > 65535) return null;
    return port;
}

function calculateNetworkRate(containerId, currentRx, currentTx) {
    const rx = Number(currentRx);
    const tx = Number(currentTx);
    if (!Number.isFinite(rx) || !Number.isFinite(tx)) {
        return null;
    }

    const now = Date.now();
    const key = String(containerId);
    const prev = previousNetworkStats[key];

    if (!prev || !lastFetchTime) {
        previousNetworkStats[key] = { rx, tx };
        return null;
    }

    const timeDelta = (now - lastFetchTime) / 1000;
    if (timeDelta <= 0) return null;

    const rxRate = Math.max(0, (rx - prev.rx) / timeDelta);
    const txRate = Math.max(0, (tx - prev.tx) / timeDelta);

    previousNetworkStats[key] = { rx, tx };
    return { rxRate, txRate };
}

function formatNetworkCell(rx, tx, containerId, loading = false) {
    if (loading) return loadingSpinner();

    const rxValue = Number(rx);
    const txValue = Number(tx);
    if (!Number.isFinite(rxValue) || !Number.isFinite(txValue)) {
        return '<span class="text-gray-500">—</span>';
    }

    const rates = containerId ? calculateNetworkRate(containerId, rxValue, txValue) : null;
    if (rates) {
        return `<span class="text-blue-300">↓${formatBytes(rates.rxRate)}/s</span><br><span class="text-green-300">↑${formatBytes(rates.txRate)}/s</span>`;
    }

    return `<span class="text-blue-300">↓${formatBytes(rxValue)}</span><br><span class="text-green-300">↑${formatBytes(txValue)}</span>`;
}

function clearContainerList() {
    const list = getContainerListEl();
    if (!list) return;
    list.textContent = '';
}

function appendTableMessage(message, className = '') {
    const list = getContainerListEl();
    if (!list) return;

    clearContainerList();

    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 8;
    cell.className = `text-center py-4 ${className}`.trim();
    cell.textContent = message;
    row.appendChild(cell);
    list.appendChild(row);
}

function renderContainerNameCell(cell, container) {
    cell.textContent = '';
    cell.appendChild(document.createTextNode(container.name || 'Unnamed'));

    if (container.update_available) {
        const indicator = document.createElement('span');
        indicator.className = 'ml-1 text-yellow-400';
        indicator.title = 'Update available';
        indicator.textContent = '↻';
        cell.appendChild(indicator);
    }
}

function createStatusBadge(status) {
    const normalized = status || 'unknown';
    const statusClass = normalized === 'running' ? 'status-running' : normalized === 'stopped' ? 'status-stopped' : 'status-other';

    const badge = document.createElement('span');
    badge.className = `px-2 py-1 text-white rounded ${statusClass}`;
    badge.textContent = normalized;
    return badge;
}

function buildActionButton({ label, action, containerId, disabled = false, className }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.action = action;
    button.dataset.containerId = String(containerId);
    button.className = className;
    button.textContent = label;
    button.disabled = disabled;

    if (disabled) {
        button.classList.add('opacity-50', 'cursor-not-allowed');
    }

    return button;
}

function buildMenuButton({ label, action, containerId, roundedClass }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.menuAction = action;
    button.dataset.containerId = String(containerId);
    button.className = `w-full text-left px-3 py-2 text-xs hover:bg-gray-600 text-white ${roundedClass}`.trim();
    button.textContent = label;
    return button;
}

function buildUnavailableRow(container) {
    const row = document.createElement('tr');
    row.dataset.containerId = String(container.id || 'unavailable');
    row.dataset.containerName = container.name || 'Docker';

    const nameCell = document.createElement('td');
    nameCell.className = 'px-6 py-4 whitespace-nowrap text-sm font-medium';
    nameCell.textContent = container.name || 'Docker unavailable';
    row.appendChild(nameCell);

    const imageCell = document.createElement('td');
    imageCell.className = 'px-6 py-4 whitespace-nowrap text-sm';
    imageCell.textContent = container.image || 'N/A';
    row.appendChild(imageCell);

    const statusCell = document.createElement('td');
    statusCell.className = 'px-6 py-4 whitespace-nowrap';
    statusCell.appendChild(createStatusBadge(container.status || 'unavailable'));
    row.appendChild(statusCell);

    for (let i = 0; i < 3; i += 1) {
        const cell = document.createElement('td');
        cell.className = 'px-4 py-4 whitespace-nowrap text-sm text-gray-500';
        cell.textContent = '—';
        row.appendChild(cell);
    }

    const webCell = document.createElement('td');
    webCell.className = 'px-6 py-4 whitespace-nowrap text-sm';
    webCell.textContent = 'N/A';
    row.appendChild(webCell);

    const actionsCell = document.createElement('td');
    actionsCell.className = 'px-4 py-4 whitespace-nowrap text-sm text-gray-500';
    actionsCell.textContent = '—';
    row.appendChild(actionsCell);

    return row;
}

function buildContainerRow(container, showStatsLoading = false) {
    const row = document.createElement('tr');
    row.dataset.containerId = String(container.id);
    row.dataset.containerName = container.name || String(container.id);

    const isRunning = container.status === 'running';
    const hasStats = container.cpu_percent !== null && container.cpu_percent !== undefined;
    const loading = showStatsLoading && isRunning && !hasStats;

    const nameCell = document.createElement('td');
    nameCell.className = 'px-6 py-4 whitespace-nowrap text-sm font-medium';
    nameCell.dataset.cell = 'name';
    renderContainerNameCell(nameCell, container);
    row.appendChild(nameCell);

    const imageCell = document.createElement('td');
    imageCell.className = 'px-6 py-4 whitespace-nowrap text-sm text-gray-400 max-w-xs truncate';
    imageCell.title = container.image || '';
    imageCell.textContent = container.image || '—';
    row.appendChild(imageCell);

    const statusCell = document.createElement('td');
    statusCell.className = 'px-6 py-4 whitespace-nowrap';
    statusCell.dataset.cell = 'status';
    statusCell.appendChild(createStatusBadge(container.status));
    row.appendChild(statusCell);

    const cpuCell = document.createElement('td');
    cpuCell.className = 'px-4 py-4 whitespace-nowrap text-sm';
    cpuCell.dataset.stat = 'cpu';
    cpuCell.innerHTML = formatCpuCell(container.cpu_percent, loading);
    row.appendChild(cpuCell);

    const memoryCell = document.createElement('td');
    memoryCell.className = 'px-4 py-4 whitespace-nowrap text-sm';
    memoryCell.dataset.stat = 'memory';
    memoryCell.innerHTML = formatMemoryCell(container.memory_percent, container.memory_used, container.memory_limit, loading);
    row.appendChild(memoryCell);

    const networkCell = document.createElement('td');
    networkCell.className = 'px-4 py-4 whitespace-nowrap text-sm';
    networkCell.dataset.stat = 'network';
    networkCell.innerHTML = formatNetworkCell(container.net_rx, container.net_tx, container.id, loading);
    row.appendChild(networkCell);

    const webCell = document.createElement('td');
    webCell.className = 'px-4 py-4 whitespace-nowrap text-sm';
    const webPort = getWebUIPort(container);
    if (webPort) {
        const link = document.createElement('a');
        link.href = `http://${window.location.hostname}:${webPort}`;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'text-blue-500 hover:text-blue-400 underline';
        link.textContent = 'Open';
        webCell.appendChild(link);
    } else {
        webCell.textContent = 'N/A';
    }
    row.appendChild(webCell);

    const actionsCell = document.createElement('td');
    actionsCell.className = 'px-4 py-4 whitespace-nowrap text-sm';

    const actionWrap = document.createElement('div');
    actionWrap.className = 'flex items-center gap-1';

    actionWrap.appendChild(buildActionButton({
        label: 'Start',
        action: 'start',
        containerId: container.id,
        disabled: container.status === 'running',
        className: 'action-btn bg-green-700 hover:bg-green-600 text-white py-1 px-2 rounded text-xs',
    }));

    actionWrap.appendChild(buildActionButton({
        label: 'Stop',
        action: 'stop',
        containerId: container.id,
        disabled: ['stopped', 'exited'].includes(container.status),
        className: 'action-btn bg-yellow-700 hover:bg-yellow-600 text-white py-1 px-2 rounded text-xs',
    }));

    actionWrap.appendChild(buildActionButton({
        label: 'Restart',
        action: 'restart',
        containerId: container.id,
        className: 'action-btn bg-blue-700 hover:bg-blue-600 text-white py-1 px-2 rounded text-xs',
    }));

    const dropdownWrap = document.createElement('div');
    dropdownWrap.className = 'relative';
    dropdownWrap.dataset.dropdownContainer = String(container.id);

    const dropdownToggle = document.createElement('button');
    dropdownToggle.type = 'button';
    dropdownToggle.className = 'bg-gray-600 hover:bg-gray-500 text-white py-1 px-2 rounded text-xs';
    dropdownToggle.dataset.dropdownToggle = String(container.id);
    dropdownToggle.dataset.containerId = String(container.id);
    dropdownToggle.textContent = '⋮';
    dropdownWrap.appendChild(dropdownToggle);

    const dropdownMenu = document.createElement('div');
    dropdownMenu.className = 'dropdown-menu hidden absolute mt-1 w-36 bg-gray-700 rounded shadow-lg z-50 border border-gray-600';
    dropdownMenu.dataset.dropdownMenu = String(container.id);
    dropdownMenu.dataset.dropdownMenuFor = String(container.id);
    dropdownMenu.appendChild(buildMenuButton({ label: 'Check Update', action: 'check_update', containerId: container.id, roundedClass: 'rounded-t' }));
    dropdownMenu.appendChild(buildMenuButton({ label: 'Update', action: 'update', containerId: container.id, roundedClass: '' }));
    dropdownMenu.appendChild(buildMenuButton({ label: 'Logs', action: 'logs', containerId: container.id, roundedClass: '' }));
    dropdownMenu.appendChild(buildMenuButton({ label: 'Network Test', action: 'network-test', containerId: container.id, roundedClass: 'rounded-b' }));
    dropdownWrap.appendChild(dropdownMenu);

    actionWrap.appendChild(dropdownWrap);
    actionsCell.appendChild(actionWrap);
    row.appendChild(actionsCell);

    return row;
}

function hasContainerListChanged(oldList, newList) {
    if (oldList.length !== newList.length) return true;
    const oldIds = new Set(oldList.map((container) => String(container.id)));
    const newIds = new Set(newList.map((container) => String(container.id)));
    for (const id of newIds) {
        if (!oldIds.has(id)) return true;
    }
    return false;
}

function closeAllDropdowns(exceptId = null) {
    document.querySelectorAll('[data-dropdown-menu-for]').forEach((menu) => {
        if (exceptId !== null && menu.dataset.dropdownMenuFor === String(exceptId)) {
            return;
        }
        menu.classList.add('hidden');
    });
}

function toggleDropdown(containerId) {
    const row = findContainerRow(containerId);
    if (!row) return;

    const menu = row.querySelector('[data-dropdown-menu-for]');
    if (!menu) return;

    const willOpen = menu.classList.contains('hidden');
    closeAllDropdowns();
    if (willOpen) {
        menu.classList.remove('hidden');
    }
}

function closeDropdown(containerId) {
    const row = findContainerRow(containerId);
    if (!row) return;

    const menu = row.querySelector('[data-dropdown-menu-for]');
    if (menu) {
        menu.classList.add('hidden');
    }
}

function updateActionButtons(row, container) {
    const startBtn = row.querySelector('button[data-action="start"]');
    const stopBtn = row.querySelector('button[data-action="stop"]');

    if (startBtn) {
        const disabled = container.status === 'running';
        startBtn.disabled = disabled;
        startBtn.classList.toggle('opacity-50', disabled);
        startBtn.classList.toggle('cursor-not-allowed', disabled);
    }

    if (stopBtn) {
        const disabled = ['stopped', 'exited'].includes(container.status);
        stopBtn.disabled = disabled;
        stopBtn.classList.toggle('opacity-50', disabled);
        stopBtn.classList.toggle('cursor-not-allowed', disabled);
    }
}

function updateContainerRows() {
    containerList.forEach((container) => {
        const row = findContainerRow(container.id);
        if (!row) return;

        row.dataset.containerName = container.name || String(container.id);

        const statusCell = row.querySelector('[data-cell="status"]');
        if (statusCell) {
            statusCell.textContent = '';
            statusCell.appendChild(createStatusBadge(container.status));
        }

        const nameCell = row.querySelector('[data-cell="name"]');
        if (nameCell) {
            renderContainerNameCell(nameCell, container);
        }

        const cpuCell = row.querySelector('td[data-stat="cpu"]');
        if (cpuCell) {
            cpuCell.innerHTML = formatCpuCell(container.cpu_percent);
        }

        const memoryCell = row.querySelector('td[data-stat="memory"]');
        if (memoryCell) {
            memoryCell.innerHTML = formatMemoryCell(container.memory_percent, container.memory_used, container.memory_limit);
        }

        const networkCell = row.querySelector('td[data-stat="network"]');
        if (networkCell) {
            networkCell.innerHTML = formatNetworkCell(container.net_rx, container.net_tx, container.id);
        }

        updateActionButtons(row, container);
    });
}

function renderContainers(showStatsLoading = false) {
    const list = getContainerListEl();
    if (!list) return;

    clearContainerList();

    const filteredContainers = containerList.filter((container) => {
        if (currentFilter === 'all') return true;
        return container.status === currentFilter;
    });

    if (filteredContainers.length === 0) {
        appendTableMessage(`No ${currentFilter} containers found`);
        return;
    }

    if (
        filteredContainers.length === 1 &&
        (filteredContainers[0].status === 'unavailable' || filteredContainers[0].status === 'error')
    ) {
        list.appendChild(buildUnavailableRow(filteredContainers[0]));
        return;
    }

    filteredContainers.forEach((container) => {
        list.appendChild(buildContainerRow(container, showStatsLoading));
    });
}

async function fetchDockerContainers(forceFullRender = false, includeStats = false) {
    const lastUpdatedEl = document.getElementById('last-updated');

    if (!initialLoadComplete) {
        appendTableMessage('Loading...');
    }

    try {
        const statsParam = includeStats ? 'true' : 'false';
        const newContainerList = await requestApiJson(`/api/containers?stats=${statsParam}`);
        if (lastUpdatedEl) {
            lastUpdatedEl.textContent = `Last updated: ${formatDateTime(new Date())}`;
        }

        const needsFullRender =
            forceFullRender ||
            !initialLoadComplete ||
            hasContainerListChanged(containerList, newContainerList);

        containerList = newContainerList;

        if (needsFullRender) {
            renderContainers(!includeStats);
        } else {
            updateContainerRows();
        }

        lastFetchTime = Date.now();

        initialLoadComplete = true;

        if (!includeStats) {
            fetchContainerStats();
        }
    } catch (error) {
        console.error('Error fetching Docker containers:', error);
        if (!initialLoadComplete) {
            appendTableMessage('Error loading containers', 'text-red-500');
        }
        showNotification('Error fetching containers', 'error');
    }
}

async function fetchContainerStats() {
    const runningContainers = containerList.filter((container) => container.status === 'running');
    if (runningContainers.length === 0) return;

    statsLoading = true;
    const ids = runningContainers.map((container) => container.id).join(',');

    try {
        const stats = await requestApiJson(`/api/containers/stats?ids=${encodeURIComponent(ids)}`);

        containerList.forEach((container) => {
            const containerStats = stats[container.id];
            if (!containerStats) return;
            container.cpu_percent = containerStats.cpu_percent;
            container.memory_percent = containerStats.memory_percent;
            container.memory_used = containerStats.memory_used;
            container.memory_limit = containerStats.memory_limit;
            container.net_rx = containerStats.net_rx;
            container.net_tx = containerStats.net_tx;
        });

        updateContainerRows();
        lastFetchTime = Date.now();
    } catch (error) {
        console.error('Error fetching container stats:', error);
    } finally {
        statsLoading = false;
    }
}

async function controlContainer(id, action) {
    const containerId = String(id);
    const containerRow = findContainerRow(containerId);
    const containerName = containerRow ? (containerRow.dataset.containerName || containerId) : containerId;

    let actionBtn = null;
    let originalText = '';
    if (containerRow) {
        actionBtn = containerRow.querySelector(`button[data-action="${action}"]`);
        if (actionBtn) {
            originalText = actionBtn.textContent || '';
            actionBtn.disabled = true;
            actionBtn.classList.add('opacity-75');
            actionBtn.textContent = '...';
        }
    }

    const actionNames = {
        start: 'Starting',
        stop: 'Stopping',
        restart: 'Restarting',
        check_update: 'Checking',
        update: 'Updating',
    };
    showNotification(`${actionNames[action] || action} ${containerName}...`, 'info');

    try {
        const encodedId = encodeURIComponent(containerId);
        const result = await requestApiJson(`/api/containers/${encodedId}/${action}`, { method: 'POST' });

        if (result.error) {
            showNotification(`Error: ${result.error}`, 'error');
        } else {
            let message = `${containerName} ${action}ed successfully`;
            if (action === 'check_update') {
                message = result.update_available ? `${containerName}: Update available!` : `${containerName}: Up to date`;
            }
            if (action === 'update') {
                message = `${containerName} update triggered`;
            }
            showNotification(message, 'success');
        }

        if (containerRow) {
            await updateContainerStatus(containerId);
        } else {
            await fetchDockerContainers(true);
        }
    } catch (error) {
        console.error(`Error controlling container ${containerId}:`, error);
        showNotification(`Error ${action}ing container: ${error.message}`, 'error');
    } finally {
        if (actionBtn) {
            actionBtn.disabled = false;
            actionBtn.classList.remove('opacity-75');
            actionBtn.textContent = originalText;
        }
    }
}

async function updateContainerStatus(id) {
    const containerId = String(id);

    try {
        const containers = await requestApiJson('/api/containers');
        const container = containers.find((item) => String(item.id) === containerId);
        const row = findContainerRow(containerId);

        if (!container || !row) return;

        row.dataset.containerName = container.name || containerId;

        const nameCell = row.querySelector('[data-cell="name"]');
        const statusCell = row.querySelector('[data-cell="status"]');
        const cpuCell = row.querySelector('td[data-stat="cpu"]');
        const memoryCell = row.querySelector('td[data-stat="memory"]');
        const networkCell = row.querySelector('td[data-stat="network"]');

        if (nameCell) renderContainerNameCell(nameCell, container);
        if (statusCell) {
            statusCell.textContent = '';
            statusCell.appendChild(createStatusBadge(container.status));
        }
        if (cpuCell) cpuCell.innerHTML = formatCpuCell(container.cpu_percent);
        if (memoryCell) memoryCell.innerHTML = formatMemoryCell(container.memory_percent, container.memory_used, container.memory_limit);
        if (networkCell) networkCell.innerHTML = formatNetworkCell(container.net_rx, container.net_tx, container.id);

        for (let i = 0; i < containerList.length; i += 1) {
            if (String(containerList[i].id) === containerId) {
                containerList[i] = container;
                break;
            }
        }

        if (currentFilter !== 'all' && container.status !== currentFilter) {
            renderContainers();
        } else {
            updateActionButtons(row, container);

            const otherActions = ['restart', 'check_update', 'update'];
            otherActions.forEach((name) => {
                const button = row.querySelector(`button[data-action="${name}"], button[data-menu-action="${name}"]`);
                if (button) button.disabled = false;
            });
        }

        lastFetchTime = Date.now();
    } catch (error) {
        console.error('Error updating container status:', error);
        showNotification('Error updating container status', 'error');
    }
}

async function viewLogs(id) {
    const containerId = String(id);
    const modal = document.getElementById('logs-modal');
    const content = document.getElementById('logs-content');
    const title = document.getElementById('logs-modal-title');
    const containerName = getContainerNameById(containerId);

    if (!modal || !content || !title) return;

    title.textContent = `Logs for ${containerName}`;
    content.textContent = 'Loading logs...';
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
        const result = await requestApiJson(`/api/containers/${encodeURIComponent(containerId)}/logs`);
        if (result.error) {
            content.textContent = `Error: ${result.error}`;
        } else {
            const nameFromServer = result.container || containerName;
            title.textContent = `Logs for ${nameFromServer}`;
            content.textContent = result.logs || 'No logs available.';
        }
    } catch (error) {
        console.error('Error fetching logs:', error);
        content.textContent = `Error loading logs: ${error.message}`;
    }
}

function closeLogsModal() {
    const modal = document.getElementById('logs-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

async function openContainerNetworkTest(id) {
    const containerId = String(id);
    const modal = document.getElementById('container-network-modal');
    const title = document.getElementById('container-network-title');
    const statusEl = document.getElementById('container-network-status');
    const localEl = document.getElementById('container-network-local');
    const publicEl = document.getElementById('container-network-public');
    const outputEl = document.getElementById('container-network-output');
    const methodEl = document.getElementById('container-network-method');
    const containerName = getContainerNameById(containerId);

    if (!modal || !title || !statusEl || !localEl || !publicEl || !outputEl || !methodEl) {
        return;
    }

    title.textContent = `Network Test: ${containerName}`;
    statusEl.textContent = 'Running test...';
    statusEl.classList.remove('text-green-400', 'text-red-400');
    localEl.textContent = '-';
    publicEl.textContent = '-';
    methodEl.textContent = '-';
    outputEl.textContent = 'Collecting diagnostics...';

    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
        const result = await requestApiJson(`/api/containers/${encodeURIComponent(containerId)}/network-test`, { method: 'POST' });
        if (result.error) {
            const message = result.error || 'Unable to run network test.';
            statusEl.textContent = 'Error';
            statusEl.classList.add('text-red-400');
            outputEl.textContent = message;
            showNotification(message, 'error');
            return;
        }

        statusEl.textContent = result.ping_success ? 'Success' : 'Failed';
        statusEl.classList.toggle('text-green-400', !!result.ping_success);
        statusEl.classList.toggle('text-red-400', !result.ping_success);
        localEl.textContent = result.local_ip || 'Unavailable';
        publicEl.textContent = result.public_ip || 'Unavailable';
        methodEl.textContent = result.probe_method || 'unknown';
        outputEl.textContent = result.ping_output || 'No output provided.';

        showNotification(`Network test ${result.ping_success ? 'passed' : 'completed'}`, result.ping_success ? 'success' : 'info');
    } catch (error) {
        console.error('Container network test failed:', error);
        statusEl.textContent = 'Error';
        statusEl.classList.add('text-red-400');
        outputEl.textContent = error.message;
        showNotification('Network test failed', 'error');
    }
}

async function runNetworkTest() {
    const card = document.getElementById('network-test-card');
    const statusEl = document.getElementById('network-test-status');
    const outputEl = document.getElementById('network-test-output');
    const localEl = document.getElementById('network-test-local');
    const publicEl = document.getElementById('network-test-public');

    if (!card || !statusEl || !outputEl || !localEl || !publicEl) return;

    card.classList.remove('hidden');
    statusEl.textContent = 'Running test...';
    statusEl.classList.remove('text-green-400', 'text-red-400');
    outputEl.textContent = 'Executing ping...';
    localEl.textContent = '-';
    publicEl.textContent = '-';

    try {
        const result = await requestApiJson('/api/network-test', { method: 'POST' });

        statusEl.textContent = result.ping_success ? 'Ping successful' : 'Ping failed';
        statusEl.classList.toggle('text-green-400', !!result.ping_success);
        statusEl.classList.toggle('text-red-400', !result.ping_success);
        outputEl.textContent = result.ping_output || 'No ping output returned.';
        localEl.textContent = result.local_ip || 'Unavailable';
        publicEl.textContent = result.public_ip || 'Unavailable';

        showNotification('Network test complete', result.ping_success ? 'success' : 'info');
    } catch (error) {
        console.error('Network test error:', error);
        statusEl.textContent = 'Network test failed';
        statusEl.classList.add('text-red-400');
        outputEl.textContent = error.message;
        showNotification('Network test failed', 'error');
    }
}

function setFilter(filter, button) {
    if (currentFilter === filter) return;

    currentFilter = filter;

    document.querySelectorAll('#filter-all, #filter-running, #filter-stopped').forEach((btn) => {
        btn.classList.remove('coraline-button');
        btn.classList.add('bg-gray-700', 'hover:bg-gray-600');
    });

    button.classList.remove('bg-gray-700', 'hover:bg-gray-600');
    button.classList.add('coraline-button');

    renderContainers();
}

function bindModalHandlers() {
    const logsClose = document.getElementById('logs-modal-close');
    const logsModal = document.getElementById('logs-modal');
    const containerNetworkClose = document.getElementById('container-network-close');
    const containerNetworkModal = document.getElementById('container-network-modal');

    logsClose?.addEventListener('click', closeLogsModal);
    logsModal?.addEventListener('click', (event) => {
        if (event.target === logsModal) {
            closeLogsModal();
        }
    });

    containerNetworkClose?.addEventListener('click', () => {
        if (!containerNetworkModal) return;
        containerNetworkModal.classList.add('hidden');
        containerNetworkModal.classList.remove('flex');
    });

    containerNetworkModal?.addEventListener('click', (event) => {
        if (event.target === containerNetworkModal) {
            containerNetworkModal.classList.add('hidden');
            containerNetworkModal.classList.remove('flex');
        }
    });
}

function bindStaticControls() {
    const networkTestButton = document.getElementById('network-test-button');
    const hideNetworkTestButton = document.getElementById('hide-network-test');
    const refreshButton = document.getElementById('refresh-button');
    const filterAll = document.getElementById('filter-all');
    const filterRunning = document.getElementById('filter-running');
    const filterStopped = document.getElementById('filter-stopped');

    networkTestButton?.addEventListener('click', function onNetworkTestClick() {
        this.classList.add('animate-pulse');
        runNetworkTest().finally(() => this.classList.remove('animate-pulse'));
    });

    hideNetworkTestButton?.addEventListener('click', () => {
        document.getElementById('network-test-card')?.classList.add('hidden');
    });

    filterAll?.addEventListener('click', function onFilterAll() {
        setFilter('all', this);
    });
    filterRunning?.addEventListener('click', function onFilterRunning() {
        setFilter('running', this);
    });
    filterStopped?.addEventListener('click', function onFilterStopped() {
        setFilter('stopped', this);
    });

    refreshButton?.addEventListener('click', function onRefreshClick() {
        this.classList.add('animate-pulse');
        fetchDockerContainers(true).finally(() => this.classList.remove('animate-pulse'));
    });
}

function bindContainerTableActions() {
    const list = getContainerListEl();
    if (!list) return;

    list.addEventListener('click', async (event) => {
        const toggleButton = event.target.closest('button[data-dropdown-toggle]');
        if (toggleButton) {
            event.preventDefault();
            const { containerId } = toggleButton.dataset;
            toggleDropdown(containerId);
            return;
        }

        const menuActionButton = event.target.closest('button[data-menu-action]');
        if (menuActionButton) {
            event.preventDefault();
            const { containerId, menuAction } = menuActionButton.dataset;

            if (menuAction === 'logs') {
                await viewLogs(containerId);
            } else if (menuAction === 'network-test') {
                await openContainerNetworkTest(containerId);
            } else if (menuAction) {
                await controlContainer(containerId, menuAction);
            }

            closeDropdown(containerId);
            return;
        }

        const actionButton = event.target.closest('button[data-action]');
        if (actionButton) {
            event.preventDefault();
            const { containerId, action } = actionButton.dataset;
            if (containerId && action) {
                await controlContainer(containerId, action);
            }
        }
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('[data-dropdown-container]')) {
            closeAllDropdowns();
        }
    });
}

async function initContainersPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) return;

    bindModalHandlers();
    bindStaticControls();
    bindContainerTableActions();

    await fetchDockerContainers();

    window.setInterval(() => fetchDockerContainers(false, true), 10000);
}

initContainersPage();
