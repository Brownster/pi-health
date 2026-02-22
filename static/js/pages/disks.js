import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearElement, createEmptyState, createErrorState, createLoadingState } from '/js/lib/states.js';
import { requestApiResponse } from '/js/lib/http.js';
import { escapeHtml, encodeDataAttr, formatBytes } from '/js/lib/format.js';
import { showNotification } from '/js/lib/notify.js';
import { setNodeContent } from '/js/lib/dom.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

let diskInventory = [];
let currentMount = {};
let smartData = [];
let currentSmartDevice = null;

function parseDataBool(value, defaultValue = false) {
    if (value === undefined || value === null || value === '') {
        return defaultValue;
    }
    return value === 'true';
}

function renderHelperUnavailable() {
    const helperStatus = document.getElementById('helper-status');
    if (!helperStatus) {
        return;
    }

    helperStatus.className = 'mb-6 p-4 rounded-lg border bg-yellow-900/30 border-yellow-700';
    helperStatus.innerHTML = `
        <div class="flex items-center">
            <svg class="w-5 h-5 mr-2 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
            </svg>
            <div>
                <p class="font-medium text-yellow-300">Helper Service Not Running</p>
                <p class="text-sm text-yellow-200/70">Disk management requires the pihealth-helper service. Start it with: <code class="bg-gray-800 px-1 rounded">sudo systemctl start pihealth-helper</code></p>
            </div>
        </div>
    `;
    helperStatus.classList.remove('hidden');

    setNodeContent('disk-list', createEmptyState({
        title: 'Helper service required for disk information',
        containerClass: 'text-center py-10',
        titleClass: 'text-gray-500',
    }));
}

function hideHelperStatus() {
    const helperStatus = document.getElementById('helper-status');
    if (helperStatus) {
        helperStatus.classList.add('hidden');
    }
}

async function loadDisks() {
    setNodeContent('disk-list', createLoadingState({
        message: 'Loading...',
        containerClass: 'text-center py-10',
        messageClass: 'text-gray-400',
    }));

    try {
        const response = await requestApiResponse('/api/disks');
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data?.error || `Failed to load disks (${response.status})`);
        }

        if (!data.helper_available) {
            renderHelperUnavailable();
            return;
        }

        hideHelperStatus();
        diskInventory = data.disks || [];

        if (!diskInventory.length) {
            setNodeContent('disk-list', createEmptyState({
                title: 'No storage devices found',
                containerClass: 'text-center py-10',
                titleClass: 'text-gray-400',
            }));
            return;
        }

        renderDisks();
        await loadSuggestions();
    } catch (error) {
        setNodeContent('disk-list', createErrorState({
            title: `Error loading disks: ${error.message}`,
            containerClass: 'text-center py-10',
            titleClass: 'text-red-400',
        }));
    }
}

function renderDisks() {
    const diskList = document.getElementById('disk-list');
    if (!diskList) {
        return;
    }

    const html = diskInventory.map((disk) => {
        const hasPartitions = Array.isArray(disk.partitions) && disk.partitions.length > 0;
        const displayItems = hasPartitions ? disk.partitions : [disk];

        return `
            <div class="disk-card bg-gray-800 rounded-lg border border-purple-900/40 overflow-hidden">
                <div class="p-4 bg-gray-800/50 border-b border-gray-700">
                    <div class="flex flex-col gap-2 sm:flex-row sm:justify-between sm:items-start">
                        <div class="min-w-0">
                            <h4 class="font-semibold text-lg break-all">${escapeHtml(disk.path)}</h4>
                            <p class="text-sm text-gray-400 break-words">${escapeHtml(disk.model || 'Unknown device')} ${disk.serial ? `(${escapeHtml(disk.serial)})` : ''}</p>
                        </div>
                        <div class="text-left sm:text-right shrink-0">
                            <span class="text-lg font-medium">${escapeHtml(disk.size)}</span>
                            <p class="text-xs text-gray-500">${escapeHtml(disk.transport || 'unknown')} ${disk.hotplug ? '(removable)' : ''}</p>
                        </div>
                    </div>
                </div>
                <div class="divide-y divide-gray-700">
                    ${displayItems.map((part) => renderPartition(part)).join('')}
                </div>
            </div>
        `;
    }).join('');

    diskList.innerHTML = html;
    bindDiskActions(diskList);
}

function renderPartition(part) {
    const mounted = !!part.mounted;
    const statusClass = mounted ? 'mounted' : 'unmounted';
    const statusText = mounted ? 'Mounted' : 'Not Mounted';

    let usageBar = '';
    if (part.usage) {
        const percent = parseInt(part.usage.percent, 10) || 0;
        const colorClass = percent > 90 ? 'bg-red-500' : percent > 70 ? 'bg-yellow-500' : 'bg-green-500';
        usageBar = `
            <div class="mt-2">
                <div class="flex justify-between text-xs text-gray-400 mb-1">
                    <span>${formatBytes(part.usage.used)} used</span>
                    <span>${formatBytes(part.usage.available)} free</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill ${colorClass}" style="width: ${percent}%"></div>
                </div>
            </div>
        `;
    }

    let actions = '<span class="text-xs text-gray-500">No filesystem</span>';
    if (mounted) {
        actions = `
            <button type="button"
                    class="disk-action-btn px-3 py-2 text-sm rounded bg-red-700 hover:bg-red-600 text-white js-unmount"
                    data-mountpoint="${encodeDataAttr(part.mountpoint || '')}">
                Unmount
            </button>
        `;
    } else if (part.uuid) {
        actions = `
            <button type="button"
                    class="coraline-button disk-action-btn px-3 py-2 text-sm rounded text-white js-open-mount"
                    data-device="${encodeDataAttr(part.path || '')}"
                    data-uuid="${encodeDataAttr(part.uuid || '')}"
                    data-fstype="${encodeDataAttr(part.fstype || 'ext4')}">
                Mount
            </button>
        `;
    }

    return `
        <div class="p-4">
            <div class="flex flex-col gap-3 sm:flex-row sm:justify-between sm:items-start">
                <div class="flex-1 min-w-0">
                    <div class="flex flex-wrap items-center gap-2">
                        <span class="font-medium break-all">${escapeHtml(part.path || part.name)}</span>
                        <span class="text-xs px-2 py-0.5 rounded ${part.fstype ? 'bg-blue-900 text-blue-300' : 'bg-gray-700 text-gray-400'}">${escapeHtml(part.fstype || 'unknown')}</span>
                        <span class="text-xs ${statusClass}">${statusText}</span>
                    </div>
                    ${part.mountpoint ? `<p class="text-sm text-gray-400 mt-1 break-all">Mounted at: ${escapeHtml(part.mountpoint)}</p>` : ''}
                    ${part.uuid ? `<p class="text-xs text-gray-500 mt-1 break-all">UUID: ${escapeHtml(part.uuid)}</p>` : ''}
                    ${usageBar}
                </div>
                <div class="flex w-full sm:w-auto flex-wrap items-center gap-2 sm:justify-end">
                    <span class="text-sm text-gray-400">${escapeHtml(part.size)}</span>
                    ${actions}
                </div>
            </div>
        </div>
    `;
}

function bindDiskActions(diskList) {
    diskList.querySelectorAll('.js-unmount').forEach((button) => {
        button.addEventListener('click', async () => {
            const mountpoint = button.dataset.mountpoint || '';
            if (mountpoint) {
                await unmountDisk(mountpoint);
            }
        });
    });

    diskList.querySelectorAll('.js-open-mount').forEach((button) => {
        button.addEventListener('click', () => {
            openMountModal(
                button.dataset.device || '',
                button.dataset.uuid || '',
                button.dataset.fstype || 'ext4'
            );
        });
    });
}

async function loadSuggestions() {
    try {
        const response = await requestApiResponse('/api/disks/suggested-mounts');
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.error || `Failed to load suggestions (${response.status})`);
        }

        const suggestions = data.suggestions || [];
        const section = document.getElementById('suggestions-section');
        const list = document.getElementById('suggestions-list');

        if (!section || !list) {
            return;
        }

        if (!suggestions.length) {
            section.classList.add('hidden');
            list.innerHTML = '';
            return;
        }

        section.classList.remove('hidden');
        list.innerHTML = suggestions.map((s) => `
            <div class="bg-gray-800 rounded-lg p-4 border border-purple-900/40 flex flex-col gap-3 sm:flex-row sm:justify-between sm:items-center">
                <div class="min-w-0">
                    <p class="font-medium break-all">${escapeHtml(s.device)} <span class="text-gray-400">(${escapeHtml(s.size)})</span></p>
                    <p class="text-sm text-gray-400 break-words">${escapeHtml(s.reason)}</p>
                </div>
                <button type="button"
                        class="coraline-button disk-action-btn px-3 py-2 text-sm rounded text-white js-open-suggested-mount self-start sm:self-auto"
                        data-device="${encodeDataAttr(s.device)}"
                        data-uuid="${encodeDataAttr(s.uuid)}"
                        data-fstype="${encodeDataAttr(s.fstype)}"
                        data-suggested-mount="${encodeDataAttr(s.suggested_mount)}">
                    Mount as ${escapeHtml(s.suggested_mount)}
                </button>
            </div>
        `).join('');

        list.querySelectorAll('.js-open-suggested-mount').forEach((button) => {
            button.addEventListener('click', () => {
                openMountModal(
                    button.dataset.device || '',
                    button.dataset.uuid || '',
                    button.dataset.fstype || 'ext4',
                    button.dataset.suggestedMount || ''
                );
            });
        });
    } catch (error) {
        console.error('Failed to load suggestions:', error);
    }
}

function openMountModal(device, uuid, fstype, suggestedMount = '') {
    currentMount = { device, uuid, fstype };
    const modal = document.getElementById('mount-modal');
    const mountDevice = document.getElementById('mount-device');
    const mountUuid = document.getElementById('mount-uuid');
    const mountFstype = document.getElementById('mount-fstype');
    const mountPoint = document.getElementById('mount-point');

    if (mountDevice) mountDevice.value = device;
    if (mountUuid) mountUuid.value = uuid;
    if (mountFstype) mountFstype.value = fstype;
    if (mountPoint) mountPoint.value = suggestedMount || '/mnt/';

    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function closeMountModal() {
    const modal = document.getElementById('mount-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    currentMount = {};
}

async function submitMount() {
    const mountpoint = document.getElementById('mount-point')?.value || '';
    const addToFstab = document.getElementById('mount-fstab')?.checked || false;

    if (!mountpoint || !mountpoint.startsWith('/mnt/')) {
        showNotification('Mountpoint must start with /mnt/', 'error');
        return;
    }

    try {
        const response = await requestApiResponse('/api/disks/mount', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                uuid: currentMount.uuid,
                mountpoint,
                fstype: currentMount.fstype,
                add_to_fstab: addToFstab,
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.error || 'Mount failed');
        }

        showNotification(`Mounted at ${mountpoint}`, 'success');
        closeMountModal();
        await loadDisks();
    } catch (error) {
        showNotification(`Mount failed: ${error.message}`, 'error');
    }
}

async function unmountDisk(mountpoint) {
    if (!window.confirm(`Unmount ${mountpoint}? Make sure no applications are using this storage.`)) {
        return;
    }

    try {
        const response = await requestApiResponse('/api/disks/unmount', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mountpoint,
                remove_from_fstab: false,
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.error || 'Unmount failed');
        }

        showNotification(`Unmounted ${mountpoint}`, 'success');
        await loadDisks();
    } catch (error) {
        showNotification(`Unmount failed: ${error.message}`, 'error');
    }
}

async function loadSmartData() {
    const smartList = document.getElementById('smart-list');
    if (!smartList) {
        return;
    }

    smartList.innerHTML = '<div class="text-gray-400 text-sm">Loading SMART data...</div>';

    try {
        const response = await requestApiResponse('/api/disks/smart');
        const data = await response.json().catch(() => ({}));

        if (data.error) {
            smartList.innerHTML = `<div class="text-red-400 text-sm">${escapeHtml(data.error)}</div>`;
            return;
        }

        if (!response.ok) {
            throw new Error(data?.error || `Failed to load SMART data (${response.status})`);
        }

        smartData = data.disks || [];

        if (!smartData.length) {
            smartList.innerHTML = '<div class="text-gray-400 text-sm">No SMART-capable devices found</div>';
            return;
        }

        renderSmartCards();
    } catch (error) {
        smartList.innerHTML = `<div class="text-red-400 text-sm">Error: ${escapeHtml(error.message)}</div>`;
    }
}

function renderSmartCards() {
    const smartList = document.getElementById('smart-list');
    if (!smartList) {
        return;
    }

    smartList.innerHTML = smartData.map((disk) => {
        const data = disk.data || {};
        const device = disk.device || 'unknown';
        const deviceName = device.replace('/dev/', '');
        const status = data.health_status || 'unknown';
        const statusClass = status === 'healthy'
            ? 'healthy'
            : status === 'warning'
                ? 'warning'
                : status === 'failing'
                    ? 'failing'
                    : 'unknown';

        let powerOnDisplay = 'Unknown';
        if (data.power_on_hours != null) {
            const hours = data.power_on_hours;
            const days = Math.floor(hours / 24);
            const years = Math.floor(days / 365);
            const remainingDays = days % 365;
            powerOnDisplay = years > 0 ? `${years}y ${remainingDays}d` : days > 0 ? `${days}d` : `${hours}h`;
        }

        const driveIcon = data.drive_type === 'nvme'
            ? '⚡'
            : data.drive_type === 'ssd'
                ? '💾'
                : data.drive_type === 'hdd'
                    ? '🗄️'
                    : '💿';

        return `
            <div class="bg-gray-900 rounded-lg p-4 border border-gray-700 hover:border-purple-600 cursor-pointer transition-colors js-smart-card"
                 data-device-name="${encodeDataAttr(deviceName)}">
                <div class="flex flex-col gap-2 sm:flex-row sm:justify-between sm:items-start mb-3">
                    <div class="flex items-start min-w-0">
                        <span class="text-2xl mr-2 shrink-0">${driveIcon}</span>
                        <div class="min-w-0">
                            <h4 class="font-semibold break-all">${escapeHtml(device)}</h4>
                            <p class="text-xs text-gray-400 break-words">${escapeHtml(data.model || 'Unknown')}</p>
                        </div>
                    </div>
                    <span class="smart-badge ${statusClass} self-start">${escapeHtml(status.toUpperCase())}</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                    <div>
                        <span class="text-gray-400">Temp:</span>
                        <span class="${data.temperature_c > 55 ? 'text-yellow-400' : 'text-gray-200'}">${data.temperature_c != null ? `${data.temperature_c}°C` : 'N/A'}</span>
                    </div>
                    <div>
                        <span class="text-gray-400">Power On:</span>
                        <span class="text-gray-200">${escapeHtml(powerOnDisplay)}</span>
                    </div>
                    ${data.drive_type === 'nvme' ? `
                    <div>
                        <span class="text-gray-400">Used:</span>
                        <span class="${data.percentage_used > 90 ? 'text-red-400' : 'text-gray-200'}">${data.percentage_used != null ? `${data.percentage_used}%` : 'N/A'}</span>
                    </div>
                    <div>
                        <span class="text-gray-400">Spare:</span>
                        <span class="${data.available_spare < 10 ? 'text-red-400' : 'text-gray-200'}">${data.available_spare != null ? `${data.available_spare}%` : 'N/A'}</span>
                    </div>
                    ` : `
                    <div>
                        <span class="text-gray-400">Realloc:</span>
                        <span class="${data.reallocated_sectors > 0 ? 'text-yellow-400' : 'text-gray-200'}">${data.reallocated_sectors != null ? data.reallocated_sectors : 'N/A'}</span>
                    </div>
                    <div>
                        <span class="text-gray-400">Pending:</span>
                        <span class="${data.pending_sectors > 0 ? 'text-yellow-400' : 'text-gray-200'}">${data.pending_sectors != null ? data.pending_sectors : 'N/A'}</span>
                    </div>
                    `}
                </div>
                ${data.error_message ? `<p class="mt-2 text-xs text-yellow-400">${escapeHtml(data.error_message)}</p>` : ''}
            </div>
        `;
    }).join('');

    smartList.querySelectorAll('.js-smart-card').forEach((card) => {
        card.addEventListener('click', async () => {
            const deviceName = card.dataset.deviceName || '';
            if (deviceName) {
                await openSmartModal(deviceName);
            }
        });
    });
}

async function openSmartModal(deviceName) {
    currentSmartDevice = deviceName;
    const modal = document.getElementById('smart-modal');
    const title = document.getElementById('smart-modal-title');
    const content = document.getElementById('smart-modal-content');

    if (title) {
        title.textContent = `SMART Details - /dev/${deviceName}`;
    }
    if (content) {
        content.innerHTML = '<div class="text-gray-400">Loading detailed SMART data...</div>';
    }

    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    try {
        const response = await requestApiResponse(`/api/disks/${encodeURIComponent(deviceName)}/smart`);
        const data = await response.json().catch(() => ({}));

        if (data.error) {
            if (content) {
                content.innerHTML = `<div class="text-red-400">${escapeHtml(data.error)}</div>`;
            }
            return;
        }

        if (!response.ok) {
            throw new Error(data?.error || `Failed to load SMART details (${response.status})`);
        }

        renderSmartDetails(data);
    } catch (error) {
        if (content) {
            content.innerHTML = `<div class="text-red-400">Error: ${escapeHtml(error.message)}</div>`;
        }
    }
}

function renderSmartDetails(data) {
    const content = document.getElementById('smart-modal-content');
    if (!content) {
        return;
    }

    const status = data.health_status || 'unknown';
    const statusClass = status === 'healthy'
        ? 'healthy'
        : status === 'warning'
            ? 'warning'
            : status === 'failing'
                ? 'failing'
                : 'unknown';

    let html = `
        <div class="mb-6">
            <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mb-4">
                <div class="min-w-0">
                    <h4 class="font-semibold text-lg break-words">${escapeHtml(data.model || 'Unknown Model')}</h4>
                    <p class="text-sm text-gray-400 break-all">Serial: ${escapeHtml(data.serial || 'Unknown')}</p>
                </div>
                <span class="smart-badge ${statusClass} self-start">${escapeHtml(status.toUpperCase())}</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                <div class="bg-gray-800 p-3 rounded">
                    <span class="text-gray-400 block">Type</span>
                    <span class="font-medium">${escapeHtml((data.drive_type || 'unknown').toUpperCase())}</span>
                </div>
                <div class="bg-gray-800 p-3 rounded">
                    <span class="text-gray-400 block">Temperature</span>
                    <span class="font-medium ${data.temperature_c > 55 ? 'text-yellow-400' : ''}">${data.temperature_c != null ? `${data.temperature_c}°C` : 'N/A'}</span>
                </div>
                <div class="bg-gray-800 p-3 rounded">
                    <span class="text-gray-400 block">Power On Hours</span>
                    <span class="font-medium">${data.power_on_hours != null ? Number(data.power_on_hours).toLocaleString() : 'N/A'}</span>
                </div>
                <div class="bg-gray-800 p-3 rounded">
                    <span class="text-gray-400 block">SMART</span>
                    <span class="font-medium">${data.smart_enabled ? 'Enabled' : data.smart_available ? 'Available' : 'N/A'}</span>
                </div>
            </div>
        </div>
    `;

    if (data.error_message) {
        html += `
            <div class="mb-4 p-3 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-300 text-sm">
                <strong>Warning:</strong> ${escapeHtml(data.error_message)}
            </div>
        `;
    }

    if (Array.isArray(data.attributes) && data.attributes.length > 0) {
        html += `
            <div>
                <h5 class="font-semibold mb-2">SMART Attributes</h5>
                <div class="overflow-x-auto disk-smart-table-wrap">
                    <table class="w-full text-sm min-w-[34rem]">
                        <thead>
                            <tr class="text-gray-400 border-b border-gray-700">
                                ${data.drive_type === 'nvme' ? `
                                    <th class="text-left py-2 px-2">Attribute</th>
                                    <th class="text-right py-2 px-2">Value</th>
                                ` : `
                                    <th class="text-left py-2 px-1">ID</th>
                                    <th class="text-left py-2 px-2">Attribute</th>
                                    <th class="text-right py-2 px-2">Value</th>
                                    <th class="text-right py-2 px-2">Worst</th>
                                    <th class="text-right py-2 px-2">Thresh</th>
                                    <th class="text-right py-2 px-2">Raw</th>
                                `}
                            </tr>
                        </thead>
                        <tbody>
        `;

        for (const attr of data.attributes) {
            const critical = attr.critical ? 'smart-attr-critical' : '';
            if (data.drive_type === 'nvme') {
                html += `
                    <tr class="border-b border-gray-800 smart-attr-row ${critical}">
                        <td class="py-2 px-2 break-words">${escapeHtml(attr.name)}</td>
                        <td class="py-2 px-2 text-right font-mono">${attr.value != null ? Number(attr.value).toLocaleString() : 'N/A'}</td>
                    </tr>
                `;
            } else {
                html += `
                    <tr class="border-b border-gray-800 smart-attr-row ${critical}">
                        <td class="py-2 px-1 text-gray-500">${attr.id || ''}</td>
                        <td class="py-2 px-2 break-words">${escapeHtml(attr.name)}</td>
                        <td class="py-2 px-2 text-right font-mono">${attr.value != null ? attr.value : ''}</td>
                        <td class="py-2 px-2 text-right font-mono text-gray-500">${attr.worst != null ? attr.worst : ''}</td>
                        <td class="py-2 px-2 text-right font-mono text-gray-500">${attr.thresh != null ? attr.thresh : ''}</td>
                        <td class="py-2 px-2 text-right font-mono ${attr.critical && attr.raw > 0 ? 'text-yellow-400' : ''}">${attr.raw != null ? Number(attr.raw).toLocaleString() : ''}</td>
                    </tr>
                `;
            }
        }

        html += `
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    content.innerHTML = html;
}

function closeSmartModal() {
    const modal = document.getElementById('smart-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    currentSmartDevice = null;
}

async function runSmartTest(testType) {
    if (!currentSmartDevice) {
        return;
    }

    const confirmation = testType === 'long'
        ? `Run a ${testType} SMART self-test on /dev/${currentSmartDevice}? This may take several hours.`
        : `Run a ${testType} SMART self-test on /dev/${currentSmartDevice}? This typically takes 1-2 minutes.`;

    if (!window.confirm(confirmation)) {
        return;
    }

    try {
        const response = await requestApiResponse(`/api/disks/${encodeURIComponent(currentSmartDevice)}/smart-test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ test_type: testType }),
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data?.error || 'Failed to start test');
        }

        showNotification(`${testType.charAt(0).toUpperCase() + testType.slice(1)} SMART test started on /dev/${currentSmartDevice}`, 'success');
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

function bindDiskPageActions() {
    const refreshButton = document.getElementById('disks-refresh-btn');
    if (refreshButton) {
        refreshButton.addEventListener('click', loadDisks);
    }

    const refreshSmartButton = document.getElementById('disks-smart-refresh-btn');
    if (refreshSmartButton) {
        refreshSmartButton.addEventListener('click', loadSmartData);
    }

    const closeMountTop = document.getElementById('disks-close-mount-top');
    if (closeMountTop) {
        closeMountTop.addEventListener('click', closeMountModal);
    }

    const closeMountBottom = document.getElementById('disks-close-mount-bottom');
    if (closeMountBottom) {
        closeMountBottom.addEventListener('click', closeMountModal);
    }

    const submitMountButton = document.getElementById('disks-submit-mount');
    if (submitMountButton) {
        submitMountButton.addEventListener('click', submitMount);
    }

    const smartModal = document.getElementById('smart-modal');
    if (smartModal) {
        smartModal.addEventListener('click', (event) => {
            if (event.target === smartModal) {
                closeSmartModal();
            }
        });
    }

    const smartModalPanel = document.querySelector('#smart-modal [data-modal-panel]');
    if (smartModalPanel) {
        smartModalPanel.addEventListener('click', (event) => {
            event.stopPropagation();
        });
    }

    const closeSmartTop = document.getElementById('disks-close-smart-top');
    if (closeSmartTop) {
        closeSmartTop.addEventListener('click', closeSmartModal);
    }

    const closeSmartBottom = document.getElementById('disks-close-smart-bottom');
    if (closeSmartBottom) {
        closeSmartBottom.addEventListener('click', closeSmartModal);
    }

    document.querySelectorAll('[data-smart-test]').forEach((button) => {
        button.addEventListener('click', () => {
            const testType = button.dataset.smartTest;
            if (testType) {
                runSmartTest(testType);
            }
        });
    });
}

(async function initDisksPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    bindDiskPageActions();
    await loadDisks();
})();
