import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { requestJson } from '/js/lib/http.js';
import { clearClientSession } from '/js/lib/session.js';

let currentConfig = {};
let backupConfig = {};
let logsVisible = false;
let pihealthUpdateConfig = {};

function showNotification(message, type = 'info') {
    const notificationArea = document.getElementById('notification-area');
    if (!notificationArea) {
        return;
    }

    const notification = document.createElement('div');
    notification.className = 'notification transform transition-all duration-500 opacity-0';

    if (type === 'success') {
        notification.classList.add('bg-green-600');
    } else if (type === 'error') {
        notification.classList.add('bg-red-600');
    } else {
        notification.classList.add('bg-blue-600');
    }

    notification.textContent = message;
    notificationArea.appendChild(notification);

    window.setTimeout(() => notification.classList.replace('opacity-0', 'opacity-100'), 10);
    window.setTimeout(() => {
        notification.classList.replace('opacity-100', 'opacity-0');
        window.setTimeout(() => notification.remove(), 500);
    }, 3000);
}

async function requestApi(url, options = {}) {
    const { response, payload } = await requestJson(url, options);

    if (response.status === 401) {
        clearClientSession();
        window.location.href = '/login.html';
        throw new Error('Authentication required');
    }

    return { response, payload: payload || {} };
}

async function requestApiJson(url, options = {}) {
    const { response, payload } = await requestApi(url, options);

    if (!response.ok) {
        const err = new Error(payload.error || payload.stderr || `Request failed (${response.status})`);
        err.status = response.status;
        err.data = payload;
        throw err;
    }

    return payload;
}

function clearElement(node) {
    while (node.firstChild) {
        node.removeChild(node.firstChild);
    }
}

function setButtonBusy(button, busy) {
    if (!button) {
        return;
    }
    button.disabled = busy;
    button.classList.toggle('animate-pulse', busy);
}

function setSettingsSection(section) {
    const sections = ['plugins', 'backups', 'updates'];
    sections.forEach((key) => {
        const block = document.getElementById(`settings-${key}`);
        if (block) {
            block.classList.toggle('hidden', key !== section);
        }
    });

    const updateBlock = document.getElementById('settings-pihealth-update');
    if (updateBlock) {
        updateBlock.classList.toggle('hidden', section !== 'updates');
    }

    const logsBlock = document.getElementById('settings-updates-logs');
    if (logsBlock) {
        logsBlock.classList.toggle('hidden', section !== 'updates' || !logsVisible);
    }
}

function highlightScheduleButtons(selector, selectedPreset) {
    document.querySelectorAll(selector).forEach((button) => {
        button.classList.toggle('selected', button.dataset.preset === selectedPreset);
    });
}

function setStatusBadge(element, enabled) {
    if (!element) {
        return;
    }

    if (enabled) {
        element.textContent = 'Enabled';
        element.className = 'px-3 py-1 rounded-full text-sm mr-4 bg-green-600';
        return;
    }

    element.textContent = 'Disabled';
    element.className = 'px-3 py-1 rounded-full text-sm mr-4 bg-gray-600';
}

function formatDateTime(value) {
    if (!value) {
        return '';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '';
    }

    return date.toLocaleString();
}

function parseUnixDateTime(seconds) {
    const numberValue = Number(seconds);
    if (!Number.isFinite(numberValue)) {
        return '';
    }
    return new Date(numberValue * 1000).toLocaleString();
}

async function loadPiHealthUpdateConfig() {
    try {
        const { response, payload } = await requestApi('/api/pihealth/update/config');
        if (!response.ok) {
            return;
        }

        pihealthUpdateConfig = payload;
        const repoPath = document.getElementById('pihealth-repo-path');
        const serviceName = document.getElementById('pihealth-service-name');

        if (repoPath) {
            repoPath.value = pihealthUpdateConfig.repo_path || '';
        }
        if (serviceName) {
            serviceName.value = pihealthUpdateConfig.service_name || '';
        }
    } catch (_error) {
        // Non-blocking section.
    }
}

async function savePiHealthUpdateConfig() {
    const repoPath = document.getElementById('pihealth-repo-path');
    const serviceName = document.getElementById('pihealth-service-name');

    const payload = {
        repo_path: repoPath ? repoPath.value.trim() : '',
        service_name: serviceName ? serviceName.value.trim() : '',
    };

    try {
        const data = await requestApiJson('/api/pihealth/update/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        pihealthUpdateConfig = data.config || payload;
        showNotification('Update settings saved', 'success');
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function runPiHealthUpdate() {
    const runButton = document.getElementById('pihealth-run-btn');
    setButtonBusy(runButton, true);
    showNotification('Updating Pi-Health...', 'info');

    try {
        await requestApiJson('/api/pihealth/update', { method: 'POST' });
        showNotification('Update started. Reconnecting...', 'success');

        clearClientSession();
        window.setTimeout(() => {
            window.location.href = '/login.html';
        }, 3000);
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        setButtonBusy(runButton, false);
    }
}

async function loadBackupConfig() {
    try {
        backupConfig = await requestApiJson('/api/backups/config');
        renderBackupConfig();
    } catch (_error) {
        showNotification('Failed to load backup settings', 'error');
    }
}

function renderBackupConfig() {
    const backupEnabled = document.getElementById('backup-enabled');
    const backupDestDir = document.getElementById('backup-dest-dir');
    const backupConfigDir = document.getElementById('backup-config-dir');
    const backupStacksPath = document.getElementById('backup-stacks-path');
    const backupRetention = document.getElementById('backup-retention');
    const backupIncludeEnv = document.getElementById('backup-include-env');
    const backupPluginsEnabled = document.getElementById('backup-plugins-enabled');
    const backupPluginRetention = document.getElementById('backup-plugin-retention');

    if (backupEnabled) {
        backupEnabled.checked = Boolean(backupConfig.enabled);
    }
    if (backupDestDir) {
        backupDestDir.value = backupConfig.dest_dir || '/mnt/backup';
    }
    if (backupConfigDir) {
        backupConfigDir.value = backupConfig.config_dir || '/home/pi/docker';
    }
    if (backupStacksPath) {
        backupStacksPath.value = backupConfig.stacks_path || '/opt/stacks';
    }
    if (backupRetention) {
        backupRetention.value = backupConfig.retention_count || 7;
    }
    if (backupIncludeEnv) {
        backupIncludeEnv.checked = backupConfig.include_env !== false;
    }
    if (backupPluginsEnabled) {
        backupPluginsEnabled.checked = backupConfig.plugin_backup_enabled !== false;
    }
    if (backupPluginRetention) {
        backupPluginRetention.value = backupConfig.plugin_retention_count || 10;
    }

    setStatusBadge(document.getElementById('backup-status-badge'), Boolean(backupConfig.enabled));

    const schedulePreset = backupConfig.schedule_preset || 'daily_2am';
    backupConfig.schedule_preset = schedulePreset;
    highlightScheduleButtons('#settings-backups .schedule-btn', schedulePreset);

    loadBackupStatus();
    loadBackupList();
}

async function saveBackupConfig(overrides = null) {
    const backupEnabled = document.getElementById('backup-enabled');
    const backupDestDir = document.getElementById('backup-dest-dir');
    const backupConfigDir = document.getElementById('backup-config-dir');
    const backupStacksPath = document.getElementById('backup-stacks-path');
    const backupRetention = document.getElementById('backup-retention');
    const backupPluginsEnabled = document.getElementById('backup-plugins-enabled');
    const backupPluginRetention = document.getElementById('backup-plugin-retention');
    const backupIncludeEnv = document.getElementById('backup-include-env');

    const payload = {
        enabled: backupEnabled ? backupEnabled.checked : false,
        dest_dir: backupDestDir ? backupDestDir.value.trim() : '',
        config_dir: backupConfigDir ? backupConfigDir.value.trim() : '',
        stacks_path: backupStacksPath ? backupStacksPath.value.trim() : '',
        retention_count: parseInt(backupRetention ? backupRetention.value : '7', 10) || 7,
        plugin_backup_enabled: backupPluginsEnabled ? backupPluginsEnabled.checked : true,
        plugin_retention_count: parseInt(backupPluginRetention ? backupPluginRetention.value : '10', 10) || 10,
        include_env: backupIncludeEnv ? backupIncludeEnv.checked : true,
        schedule_preset: backupConfig.schedule_preset || 'daily_2am',
    };

    if (overrides) {
        Object.assign(payload, overrides);
    }

    try {
        const data = await requestApiJson('/api/backups/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        backupConfig = data.config || payload;
        renderBackupConfig();
        showNotification('Backup settings saved', 'success');
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function toggleBackup() {
    const backupEnabled = document.getElementById('backup-enabled');
    await saveBackupConfig({ enabled: backupEnabled ? backupEnabled.checked : false });
}

async function setBackupSchedule(preset) {
    backupConfig.schedule_preset = preset;
    await saveBackupConfig({ schedule_preset: preset });
}

function setNextRunText(element, text) {
    if (!element) {
        return;
    }
    element.textContent = text;
}

async function loadBackupStatus() {
    try {
        const { response, payload } = await requestApi('/api/backups/status');
        if (!response.ok) {
            return;
        }

        const nextRunEl = document.getElementById('backup-next-run');
        const nextRun = formatDateTime(payload.next_run);

        if (nextRun) {
            setNextRunText(nextRunEl, `Next scheduled run: ${nextRun}`);
        } else if (backupConfig.enabled) {
            setNextRunText(nextRunEl, 'Schedule will be set after saving');
        } else {
            setNextRunText(nextRunEl, '');
        }

        setButtonBusy(document.getElementById('backup-run-now'), Boolean(payload.backup_running));

        const lastRunEl = document.getElementById('backup-last-run');
        const lastRun = formatDateTime(payload.last_run);

        if (lastRun) {
            let message = `Last run: ${lastRun}`;
            const lastPluginRun = formatDateTime(payload.last_plugin_backup);
            if (lastPluginRun) {
                message += ` · plugins: ${lastPluginRun}`;
            }
            setNextRunText(lastRunEl, message);
        } else {
            setNextRunText(lastRunEl, 'No backups yet');
        }
    } catch (_error) {
        // Non-blocking section.
    }
}

function createBackupItem(item, { plugin = false } = {}) {
    const wrapper = document.createElement('div');
    wrapper.className = 'flex justify-between bg-gray-900/40 border border-gray-700 rounded px-3 py-2';

    const info = document.createElement('div');

    const title = document.createElement('div');
    title.className = 'text-blue-100';
    const archiveName = typeof item?.name === 'string' ? item.name : 'unknown';
    title.textContent = archiveName;

    const details = document.createElement('div');
    details.className = 'text-xs text-gray-500';

    const sizeBytes = Number(item?.size);
    const sizeMb = Number.isFinite(sizeBytes) ? (sizeBytes / (1024 * 1024)).toFixed(1) : '0.0';
    const date = parseUnixDateTime(item?.mtime) || 'Unknown time';
    details.textContent = `${sizeMb} MB · ${date}`;

    info.appendChild(title);
    info.appendChild(details);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'px-3 py-1 bg-red-700/70 hover:bg-red-700 text-white rounded text-xs';
    button.textContent = plugin ? 'Restore Plugins' : 'Restore';
    button.addEventListener('click', () => {
        if (plugin) {
            restorePluginBackup(archiveName);
        } else {
            restoreBackup(archiveName);
        }
    });

    wrapper.appendChild(info);
    wrapper.appendChild(button);

    return wrapper;
}

function renderBackupList(container, items, { emptyText, plugin = false }) {
    if (!container) {
        return;
    }

    clearElement(container);

    if (!items.length) {
        const empty = document.createElement('p');
        empty.textContent = emptyText;
        container.appendChild(empty);
        return;
    }

    items.forEach((item) => {
        container.appendChild(createBackupItem(item, { plugin }));
    });
}

async function loadBackupList() {
    try {
        const { response, payload } = await requestApi('/api/backups/list');
        if (!response.ok) {
            return;
        }

        const list = document.getElementById('backup-list');
        const pluginList = document.getElementById('backup-plugins-list');

        const backups = Array.isArray(payload.backups) ? payload.backups : [];
        const primary = backups.filter((item) => typeof item?.name === 'string' && item.name.startsWith('pi-health-backup-'));
        const plugins = backups.filter((item) => typeof item?.name === 'string' && item.name.startsWith('storage-plugins-'));

        renderBackupList(list, primary, { emptyText: 'No backups found' });
        renderBackupList(pluginList, plugins, { emptyText: 'No plugin backups found', plugin: true });
    } catch (_error) {
        // Non-blocking section.
    }
}

async function runBackupNow() {
    const runButton = document.getElementById('backup-run-now');
    setButtonBusy(runButton, true);

    try {
        await requestApiJson('/api/backups/run', { method: 'POST' });
        showNotification('Backup completed', 'success');
        loadBackupList();
        loadBackupStatus();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        setButtonBusy(runButton, false);
    }
}

async function restoreBackup(archiveName) {
    const confirmed = window.confirm(`Restore backup ${archiveName}? This will overwrite existing files in config and stacks.`);
    if (!confirmed) {
        return;
    }

    try {
        await requestApiJson('/api/backups/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ archive_name: archiveName, stop_stacks: true, start_stacks: true }),
        });
        showNotification('Restore completed', 'success');
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function restorePluginBackup(archiveName) {
    const confirmed = window.confirm(`Restore plugin backup ${archiveName}? This will overwrite storage plugin config files.`);
    if (!confirmed) {
        return;
    }

    try {
        await requestApiJson('/api/backups/restore-plugins', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ archive_name: archiveName }),
        });
        showNotification('Plugin restore completed', 'success');
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function loadConfig() {
    try {
        currentConfig = await requestApiJson('/api/auto-update/config');
        renderConfig();
    } catch (_error) {
        showNotification('Failed to load settings', 'error');
    }
}

function renderConfig() {
    const enabled = Boolean(currentConfig.enabled);

    const enabledCheckbox = document.getElementById('auto-update-enabled');
    if (enabledCheckbox) {
        enabledCheckbox.checked = enabled;
    }

    const scheduleSection = document.getElementById('schedule-section');
    const exclusionsSection = document.getElementById('exclusions-section');

    if (scheduleSection) {
        scheduleSection.classList.toggle('hidden', !enabled);
    }
    if (exclusionsSection) {
        exclusionsSection.classList.toggle('hidden', !enabled);
    }

    setStatusBadge(document.getElementById('status-badge'), enabled);

    highlightScheduleButtons('#settings-updates .updates-schedule-btn', currentConfig.schedule_preset);

    loadStatus();
    loadStacks();
}

async function toggleAutoUpdate() {
    const enabledInput = document.getElementById('auto-update-enabled');
    const enabled = enabledInput ? enabledInput.checked : false;

    const updates = { enabled };
    if (enabled && (!currentConfig.schedule_preset || currentConfig.schedule_preset === 'disabled')) {
        updates.schedule_preset = 'daily_4am';
    }

    await saveConfig(updates);
}

async function setSchedule(preset) {
    await saveConfig({ schedule_preset: preset });
}

async function saveConfig(updates) {
    try {
        const result = await requestApiJson('/api/auto-update/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });

        currentConfig = result.config || currentConfig;
        renderConfig();
        showNotification('Settings saved', 'success');
    } catch (_error) {
        showNotification('Failed to save settings', 'error');
        renderConfig();
    }
}

async function loadStatus() {
    try {
        const { response, payload } = await requestApi('/api/auto-update/status');
        if (!response.ok) {
            return;
        }

        const nextRunEl = document.getElementById('next-run');
        const nextRun = formatDateTime(payload.next_run);

        if (nextRun) {
            setNextRunText(nextRunEl, `Next scheduled run: ${nextRun}`);
        } else if (currentConfig.enabled) {
            setNextRunText(nextRunEl, 'Schedule will be set after saving');
        } else {
            setNextRunText(nextRunEl, '');
        }

        setButtonBusy(document.getElementById('run-now-btn'), Boolean(payload.update_running));

        if (payload.last_run_result) {
            currentConfig.last_run = payload.last_run;
            currentConfig.last_run_result = payload.last_run_result;
        }
    } catch (_error) {
        // Non-blocking section.
    }
}

function stackStatusClass(status) {
    if (status === 'running') {
        return 'bg-green-600';
    }
    if (status === 'stopped') {
        return 'bg-red-600';
    }
    return 'bg-gray-600';
}

function getStacksList(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }

    if (Array.isArray(payload?.stacks)) {
        return payload.stacks;
    }

    return [];
}

function renderStacksLoadError(container) {
    clearElement(container);
    const error = document.createElement('p');
    error.className = 'text-gray-500 text-sm';
    error.textContent = 'Failed to load stacks';
    container.appendChild(error);
}

async function loadStacks() {
    const container = document.getElementById('stacks-list');
    if (!container) {
        return;
    }

    try {
        const { response, payload } = await requestApi('/api/stacks');
        if (!response.ok) {
            renderStacksLoadError(container);
            return;
        }

        const stacks = getStacksList(payload);
        clearElement(container);

        if (!stacks.length) {
            const empty = document.createElement('p');
            empty.className = 'text-gray-500 text-sm';
            empty.textContent = 'No stacks found';
            container.appendChild(empty);
            return;
        }

        const excludedStacks = Array.isArray(currentConfig.excluded_stacks) ? currentConfig.excluded_stacks : [];

        stacks.forEach((stack) => {
            const name = stack?.name || 'unknown';
            const label = document.createElement('label');
            label.className = 'flex items-center space-x-3 p-3 bg-gray-700 rounded cursor-pointer hover:bg-gray-600 transition-colors';

            const input = document.createElement('input');
            input.type = 'checkbox';
            input.className = 'w-4 h-4 rounded border-gray-500 text-purple-600 focus:ring-purple-500';
            input.checked = excludedStacks.includes(name);
            input.addEventListener('change', () => {
                toggleExclusion(name, input.checked);
            });

            const nameSpan = document.createElement('span');
            nameSpan.className = 'flex-1';
            nameSpan.textContent = name;

            const statusSpan = document.createElement('span');
            statusSpan.className = `text-xs px-2 py-1 rounded ${stackStatusClass(stack?.status)}`;
            statusSpan.textContent = stack?.status || 'unknown';

            label.appendChild(input);
            label.appendChild(nameSpan);
            label.appendChild(statusSpan);
            container.appendChild(label);
        });
    } catch (_error) {
        renderStacksLoadError(container);
    }
}

async function toggleExclusion(stackName, excluded) {
    let excludedStacks = Array.isArray(currentConfig.excluded_stacks) ? [...currentConfig.excluded_stacks] : [];

    if (excluded && !excludedStacks.includes(stackName)) {
        excludedStacks.push(stackName);
    } else if (!excluded) {
        excludedStacks = excludedStacks.filter((item) => item !== stackName);
    }

    await saveConfig({ excluded_stacks: excludedStacks });
}

async function runNow() {
    const runBtn = document.getElementById('run-now-btn');
    setButtonBusy(runBtn, true);

    showNotification('Running update check...', 'info');

    try {
        const result = await requestApiJson('/api/auto-update/run-now', { method: 'POST' });
        const runResult = result.results || {};
        const updated = Array.isArray(runResult.updated) ? runResult.updated : [];
        const skipped = Array.isArray(runResult.skipped) ? runResult.skipped : [];
        const failed = Array.isArray(runResult.failed) ? runResult.failed : [];

        const message = `Updated: ${updated.length}, Skipped: ${skipped.length}, Failed: ${failed.length}`;
        showNotification(message, failed.length ? 'error' : 'success');

        currentConfig.last_run = runResult.timestamp || null;
        currentConfig.last_run_result = runResult;

        await showLogs();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        setButtonBusy(runBtn, false);
    }
}

async function toggleLogs() {
    const section = document.getElementById('settings-updates-logs');
    if (!section) {
        return;
    }

    logsVisible = !logsVisible;

    if (logsVisible) {
        section.classList.remove('hidden');
        await fetchAndRenderLogs();
    } else {
        section.classList.add('hidden');
    }
}

async function fetchAndRenderLogs() {
    try {
        const { response, payload } = await requestApi('/api/auto-update/logs');
        if (response.ok) {
            currentConfig.last_run = payload.last_run;
            currentConfig.last_run_result = payload.last_run_result;
        }
    } catch (_error) {
        // Non-blocking section.
    }

    renderLogs();
}

async function showLogs() {
    logsVisible = true;

    const logsSection = document.getElementById('settings-updates-logs');
    if (logsSection) {
        logsSection.classList.remove('hidden');
    }

    await fetchAndRenderLogs();
}

function appendChipList(parent, items, chipClass) {
    const list = document.createElement('div');
    list.className = 'mt-1 flex flex-wrap gap-2';

    items.forEach((item) => {
        const chip = document.createElement('span');
        chip.className = `px-2 py-1 rounded text-sm ${chipClass}`;
        chip.textContent = item;
        list.appendChild(chip);
    });

    parent.appendChild(list);
}

function appendGroup(container, titleText, titleClass, entries, chipClass) {
    const group = document.createElement('div');
    group.className = 'mb-3';

    const title = document.createElement('span');
    title.className = `${titleClass} font-medium`;
    title.textContent = `${titleText} (${entries.length}):`;

    group.appendChild(title);
    appendChipList(group, entries, chipClass);
    container.appendChild(group);
}

function appendFailedGroup(container, failedEntries) {
    const group = document.createElement('div');
    group.className = 'mb-3';

    const title = document.createElement('span');
    title.className = 'text-red-400 font-medium';
    title.textContent = `Failed (${failedEntries.length}):`;
    group.appendChild(title);

    const list = document.createElement('div');
    list.className = 'mt-1 space-y-1';

    failedEntries.forEach((entry) => {
        const row = document.createElement('div');
        row.className = 'px-2 py-1 bg-red-600/30 rounded text-sm';

        const name = document.createElement('span');
        name.className = 'font-medium';
        name.textContent = `${entry?.name || 'unknown'}: `;

        const error = document.createElement('span');
        error.className = 'text-red-300';
        error.textContent = entry?.error || 'Unknown error';

        row.appendChild(name);
        row.appendChild(error);
        list.appendChild(row);
    });

    group.appendChild(list);
    container.appendChild(group);
}

function renderLogs() {
    const content = document.getElementById('logs-content');
    if (!content) {
        return;
    }

    clearElement(content);

    const runResult = currentConfig.last_run_result;
    if (!runResult) {
        const empty = document.createElement('p');
        empty.className = 'text-gray-400';
        empty.textContent = 'No updates have run yet';
        content.appendChild(empty);
        return;
    }

    const timestamp = formatDateTime(runResult.timestamp) || 'Unknown';
    const lastRun = document.createElement('p');
    lastRun.className = 'text-sm text-gray-400 mb-4';
    lastRun.textContent = `Last run: ${timestamp}`;
    content.appendChild(lastRun);

    const updated = Array.isArray(runResult.updated) ? runResult.updated : [];
    const skipped = Array.isArray(runResult.skipped) ? runResult.skipped : [];
    const failed = Array.isArray(runResult.failed) ? runResult.failed : [];

    if (updated.length) {
        appendGroup(content, 'Updated', 'text-green-400', updated, 'bg-green-600/30');
    }

    if (skipped.length) {
        appendGroup(content, 'Skipped', 'text-gray-400', skipped, 'bg-gray-600/30');
    }

    if (failed.length) {
        appendFailedGroup(content, failed);
    }

    if (!updated.length && !skipped.length && !failed.length) {
        const empty = document.createElement('p');
        empty.className = 'text-gray-400';
        empty.textContent = 'No stacks processed';
        content.appendChild(empty);
    }
}

function bindEventListeners() {
    const sectionSelect = document.getElementById('settings-section');
    sectionSelect?.addEventListener('change', (event) => {
        setSettingsSection(event.target.value);
    });

    const backupEnabled = document.getElementById('backup-enabled');
    backupEnabled?.addEventListener('change', toggleBackup);

    const backupIncludeEnv = document.getElementById('backup-include-env');
    backupIncludeEnv?.addEventListener('change', () => {
        saveBackupConfig({ include_env: backupIncludeEnv.checked });
    });

    const backupPluginsEnabled = document.getElementById('backup-plugins-enabled');
    backupPluginsEnabled?.addEventListener('change', () => {
        saveBackupConfig({ plugin_backup_enabled: backupPluginsEnabled.checked });
    });

    const backupSaveBtn = document.getElementById('backup-save-btn');
    backupSaveBtn?.addEventListener('click', () => {
        saveBackupConfig();
    });

    const backupRunNowBtn = document.getElementById('backup-run-now');
    backupRunNowBtn?.addEventListener('click', runBackupNow);

    document.querySelectorAll('#settings-backups .schedule-btn').forEach((button) => {
        button.addEventListener('click', () => {
            const preset = button.dataset.preset;
            if (preset) {
                setBackupSchedule(preset);
            }
        });
    });

    const autoUpdateEnabled = document.getElementById('auto-update-enabled');
    autoUpdateEnabled?.addEventListener('change', toggleAutoUpdate);

    document.querySelectorAll('#settings-updates .updates-schedule-btn').forEach((button) => {
        button.addEventListener('click', () => {
            const preset = button.dataset.preset;
            if (preset) {
                setSchedule(preset);
            }
        });
    });

    const runNowBtn = document.getElementById('run-now-btn');
    runNowBtn?.addEventListener('click', runNow);

    const logsToggleBtn = document.getElementById('toggle-logs-btn');
    logsToggleBtn?.addEventListener('click', toggleLogs);

    const logsCloseBtn = document.getElementById('close-logs-btn');
    logsCloseBtn?.addEventListener('click', toggleLogs);

    const pihealthSaveBtn = document.getElementById('pihealth-save-btn');
    pihealthSaveBtn?.addEventListener('click', savePiHealthUpdateConfig);

    const pihealthRunBtn = document.getElementById('pihealth-run-btn');
    pihealthRunBtn?.addEventListener('click', runPiHealthUpdate);
}

(async function initSettingsPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;

    bindEventListeners();

    const sectionSelect = document.getElementById('settings-section');
    if (sectionSelect) {
        setSettingsSection(sectionSelect.value);
    }

    await Promise.allSettled([
        loadConfig(),
        loadBackupConfig(),
        loadPiHealthUpdateConfig(),
    ]);

    window.setInterval(loadStatus, 30000);
    window.setInterval(loadBackupStatus, 30000);
})();
