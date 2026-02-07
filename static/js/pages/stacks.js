import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearElement, createEmptyState, createErrorState } from '/js/lib/states.js';
import { requestApiJson } from '/js/lib/http.js';
import { showNotification } from '/js/lib/notify.js';

ensureDashboardShell({
    notificationClass: 'fixed top-4 right-4 z-50 w-80 flex flex-col items-end',
    includeFooter: true,
});

let stacks = [];
let currentStack = null;
let eventSource = null;
let editComposeEditor = null;
let newComposeEditor = null;

function statusClass(status) {
    const value = status || 'unknown';
    return `status-${value}`;
}

function formatNowTime() {
    return new Date().toLocaleTimeString();
}

async function loadStacks() {
    const grid = document.getElementById('stacks-grid');
    const refreshBtn = document.getElementById('refresh-btn');

    refreshBtn.classList.add('animate-pulse');

    try {
        const data = await requestApiJson('/api/stacks?status=true');

        if (data.error) {
            throw new Error(data.error);
        }

        stacks = data.stacks || [];
        renderStacks();

        document.getElementById('last-updated').textContent = `Last updated: ${formatNowTime()}`;
    } catch (error) {
        console.error('Error loading stacks:', error);
        clearElement(grid);
        grid.appendChild(createErrorState({
            title: `Error loading stacks: ${error.message}`,
            subtitle: 'Make sure STACKS_PATH is configured and accessible.',
        }));
    } finally {
        refreshBtn.classList.remove('animate-pulse');
    }
}

function renderStacks() {
    const grid = document.getElementById('stacks-grid');
    clearElement(grid);

    if (!stacks.length) {
        grid.appendChild(createEmptyState({
            title: 'No stacks found',
            subtitle: 'Create a new stack or check your STACKS_PATH configuration.',
            titleClass: 'mt-4 text-xl',
        }));
        return;
    }

    stacks.forEach((stack) => {
        const card = document.createElement('div');
        card.className = 'stack-card bg-gray-800 rounded-lg p-4 cursor-pointer';
        card.addEventListener('click', () => {
            openStack(stack.name);
        });

        const header = document.createElement('div');
        header.className = 'flex justify-between items-start mb-3';

        const title = document.createElement('h3');
        title.className = 'text-lg font-semibold';
        title.textContent = stack.name;

        const status = document.createElement('span');
        status.className = `px-2 py-1 text-xs rounded text-white ${statusClass(stack.status)}`;
        status.textContent = stack.status || 'unknown';

        header.appendChild(title);
        header.appendChild(status);
        card.appendChild(header);

        const details = document.createElement('div');
        details.className = 'text-sm text-gray-400 mb-3';

        const composeFile = document.createElement('div');
        composeFile.textContent = stack.compose_file || 'compose.yaml';
        details.appendChild(composeFile);

        if (stack.container_count) {
            const containerInfo = document.createElement('div');
            containerInfo.className = 'mt-1';
            containerInfo.textContent = `${stack.running_count}/${stack.container_count} running`;
            details.appendChild(containerInfo);
        }

        card.appendChild(details);

        const actions = document.createElement('div');
        actions.className = 'flex space-x-2';

        const startBtn = document.createElement('button');
        startBtn.className = 'flex-1 py-1 px-2 bg-green-700 hover:bg-green-600 rounded text-sm text-center';
        startBtn.textContent = 'Start';
        startBtn.disabled = stack.status === 'running';
        if (startBtn.disabled) startBtn.style.opacity = '0.5';
        startBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            quickAction(stack.name, 'up');
        });

        const stopBtn = document.createElement('button');
        stopBtn.className = 'flex-1 py-1 px-2 bg-red-700 hover:bg-red-600 rounded text-sm text-center';
        stopBtn.textContent = 'Stop';
        stopBtn.disabled = stack.status === 'stopped';
        if (stopBtn.disabled) stopBtn.style.opacity = '0.5';
        stopBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            quickAction(stack.name, 'down');
        });

        const restartBtn = document.createElement('button');
        restartBtn.className = 'flex-1 py-1 px-2 bg-yellow-700 hover:bg-yellow-600 rounded text-sm text-center';
        restartBtn.textContent = 'Restart';
        restartBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            quickAction(stack.name, 'restart');
        });

        actions.appendChild(startBtn);
        actions.appendChild(stopBtn);
        actions.appendChild(restartBtn);
        card.appendChild(actions);

        grid.appendChild(card);
    });
}

async function quickAction(stackName, action) {
    showNotification(`Running ${action} on ${stackName}...`, 'info');

    try {
        const data = await requestApiJson(`/api/stacks/${stackName}/${action}`, {
            method: 'POST',
        });

        if (data.success) {
            showNotification(`${action} completed on ${stackName}`, 'success');
        } else {
            showNotification(`${action} failed: ${data.stderr || data.error || 'Unknown error'}`, 'error');
        }

        window.setTimeout(loadStacks, 1000);
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

async function openStack(stackName) {
    currentStack = stackName;

    try {
        const data = await requestApiJson(`/api/stacks/${stackName}`);

        document.getElementById('modal-stack-name').textContent = stackName;

        const statusEl = document.getElementById('modal-stack-status');
        const status = data.status?.status || 'unknown';
        statusEl.textContent = status;
        statusEl.className = `ml-2 px-2 py-1 text-xs rounded text-white ${statusClass(status)}`;

        setComposeValue(editComposeEditor, 'edit-compose', data.compose_content || '');
        validateComposeEditor(editComposeEditor, 'edit-compose', 'compose-error-banner', 'compose-error-text', true);
        document.getElementById('edit-env').value = data.env_content || '';

        const serviceSelect = document.getElementById('log-service');
        clearElement(serviceSelect);

        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'All Services';
        serviceSelect.appendChild(defaultOption);

        if (data.status?.containers) {
            data.status.containers.forEach((container) => {
                const option = document.createElement('option');
                option.value = container.service;
                option.textContent = container.service;
                serviceSelect.appendChild(option);
            });
        }

        showTab('compose');
        refreshBackups();
        document.getElementById('stack-modal').classList.remove('hidden');

        if (editComposeEditor) {
            window.setTimeout(() => editComposeEditor.refresh(), 10);
        }
    } catch (error) {
        showNotification(`Error loading stack: ${error.message}`, 'error');
    }
}

function hideStackModal() {
    document.getElementById('stack-modal').classList.add('hidden');
    currentStack = null;

    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

function showTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach((button) => {
        if (button.dataset.tab === tabName) {
            button.classList.add('border-purple-500', 'text-purple-400');
            button.classList.remove('border-transparent', 'text-gray-400');
        } else {
            button.classList.remove('border-purple-500', 'text-purple-400');
            button.classList.add('border-transparent', 'text-gray-400');
        }
    });

    document.querySelectorAll('.tab-content').forEach((content) => {
        content.classList.add('hidden');
    });

    document.getElementById(`tab-${tabName}`).classList.remove('hidden');
}

async function stackAction(action) {
    if (!currentStack) return;

    const terminal = document.getElementById('terminal-output');
    terminal.textContent = `Running ${action}...\n`;
    showTab('terminal');

    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`/api/stacks/${currentStack}/${action}/stream`);

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.line) {
                terminal.textContent += `${data.line}\n`;
                terminal.scrollTop = terminal.scrollHeight;
            }
            if (data.done) {
                terminal.textContent += `\n--- Command completed (exit code: ${data.returncode}) ---\n`;
                eventSource.close();
                eventSource = null;

                if (data.returncode === 0) {
                    showNotification(`${action} completed successfully`, 'success');
                } else {
                    showNotification(`${action} completed with errors`, 'warning');
                }

                window.setTimeout(() => {
                    loadStacks();
                    if (currentStack) {
                        openStack(currentStack);
                    }
                }, 1000);
            }
            if (data.error) {
                terminal.textContent += `Error: ${data.error}\n`;
                eventSource.close();
                eventSource = null;
            }
        } catch (_error) {
            terminal.textContent += `${event.data}\n`;
        }
    };

    eventSource.onerror = () => {
        terminal.textContent += '\n--- Connection closed ---\n';
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    };
}

async function saveCompose() {
    if (!currentStack) return false;

    const content = getComposeValue(editComposeEditor, 'edit-compose');
    if (!validateComposeEditor(editComposeEditor, 'edit-compose', 'compose-error-banner', 'compose-error-text')) {
        showNotification('Fix compose validation errors before saving', 'error');
        return false;
    }

    try {
        const data = await requestApiJson(`/api/stacks/${currentStack}/compose`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });

        if (data.status === 'saved') {
            showNotification('Compose file saved', 'success');
            return true;
        }

        throw new Error(data.error || 'Unable to save compose file');
    } catch (error) {
        showNotification(`Error saving: ${error.message}`, 'error');
        return false;
    }
}

async function saveEnv() {
    if (!currentStack) return;

    const content = document.getElementById('edit-env').value;

    try {
        const data = await requestApiJson(`/api/stacks/${currentStack}/env`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });

        if (data.status === 'saved') {
            showNotification('.env file saved', 'success');
            return;
        }

        throw new Error(data.error || 'Unable to save .env');
    } catch (error) {
        showNotification(`Error saving: ${error.message}`, 'error');
    }
}

async function deployStack() {
    if (!validateComposeEditor(editComposeEditor, 'edit-compose', 'compose-error-banner', 'compose-error-text')) {
        showNotification('Fix compose validation errors before deploying', 'error');
        return;
    }

    const saved = await saveCompose();
    if (!saved) {
        return;
    }

    await stackAction('up');
}

async function loadStackLogs() {
    if (!currentStack) return;

    const service = document.getElementById('log-service').value;
    const logsEl = document.getElementById('logs-output');
    logsEl.textContent = 'Loading logs...';

    try {
        const query = service ? `&service=${encodeURIComponent(service)}` : '';
        const data = await requestApiJson(`/api/stacks/${currentStack}/logs?tail=200${query}`);
        logsEl.textContent = data.logs || 'No logs available';
        logsEl.scrollTop = logsEl.scrollHeight;
    } catch (error) {
        logsEl.textContent = `Error loading logs: ${error.message}`;
    }
}

function showCreateStackModal() {
    document.getElementById('new-stack-name').value = '';
    setComposeValue(
        newComposeEditor,
        'new-stack-compose',
        `services:\n  app:\n    image: nginx:latest\n    ports:\n      - "8080:80"\n`
    );
    document.getElementById('new-stack-env').value = '';
    validateComposeEditor(newComposeEditor, 'new-stack-compose', 'new-compose-error-banner', 'new-compose-error-text', true);
    document.getElementById('create-modal').classList.remove('hidden');
}

function hideCreateStackModal() {
    document.getElementById('create-modal').classList.add('hidden');
}

async function createStack() {
    const name = document.getElementById('new-stack-name').value.trim().toLowerCase();
    const compose = getComposeValue(newComposeEditor, 'new-stack-compose');
    const env = document.getElementById('new-stack-env').value;

    if (!name) {
        showNotification('Please enter a stack name', 'error');
        return;
    }

    if (!validateComposeEditor(newComposeEditor, 'new-stack-compose', 'new-compose-error-banner', 'new-compose-error-text')) {
        showNotification('Fix compose validation errors before creating', 'error');
        return;
    }

    try {
        const data = await requestApiJson(`/api/stacks/${name}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                compose_content: compose,
                env_content: env,
            }),
        });

        if (data.status === 'created') {
            showNotification(`Stack "${name}" created successfully`, 'success');
            hideCreateStackModal();
            loadStacks();
            return;
        }

        throw new Error(data.error || 'Unable to create stack');
    } catch (error) {
        showNotification(`Error creating stack: ${error.message}`, 'error');
    }
}

async function confirmDeleteStack() {
    if (!currentStack) return;

    if (!window.confirm(`Are you sure you want to delete "${currentStack}"?\n\nThis will stop all containers and remove the stack directory.`)) {
        return;
    }

    try {
        const data = await requestApiJson(`/api/stacks/${currentStack}`, { method: 'DELETE' });

        if (data.status === 'deleted') {
            showNotification(`Stack "${currentStack}" deleted`, 'success');
            hideStackModal();
            loadStacks();
            return;
        }

        throw new Error(data.error || 'Unable to delete stack');
    } catch (error) {
        showNotification(`Error deleting stack: ${error.message}`, 'error');
    }
}

function initEditors() {
    if (!window.CodeMirror) return;

    const editTextarea = document.getElementById('edit-compose');
    editComposeEditor = window.CodeMirror.fromTextArea(editTextarea, {
        mode: 'yaml',
        lineNumbers: true,
        lineWrapping: true,
        indentUnit: 2,
        tabSize: 2,
        theme: 'default',
    });
    editComposeEditor.on('change', () => {
        validateComposeEditor(editComposeEditor, 'edit-compose', 'compose-error-banner', 'compose-error-text', true);
    });

    const newTextarea = document.getElementById('new-stack-compose');
    newComposeEditor = window.CodeMirror.fromTextArea(newTextarea, {
        mode: 'yaml',
        lineNumbers: true,
        lineWrapping: true,
        indentUnit: 2,
        tabSize: 2,
        theme: 'default',
    });
    newComposeEditor.on('change', () => {
        validateComposeEditor(newComposeEditor, 'new-stack-compose', 'new-compose-error-banner', 'new-compose-error-text', true);
    });
}

function getComposeValue(editor, textareaId) {
    if (editor) {
        return editor.getValue();
    }
    return document.getElementById(textareaId).value;
}

function setComposeValue(editor, textareaId, value) {
    if (editor) {
        editor.setValue(value || '');
        return;
    }
    document.getElementById(textareaId).value = value || '';
}

function validateComposeEditor(editor, textareaId, bannerId, textId, soft = false) {
    const banner = document.getElementById(bannerId);
    const textEl = document.getElementById(textId);
    const content = getComposeValue(editor, textareaId);

    if (!window.jsyaml) {
        banner.classList.add('hidden');
        return true;
    }

    try {
        window.jsyaml.load(content || '');
        banner.classList.add('hidden');

        if (editor) {
            editor.getWrapperElement().classList.remove('editor-error');
        } else {
            document.getElementById(textareaId).classList.remove('editor-error');
        }

        return true;
    } catch (err) {
        textEl.textContent = err.message || String(err);
        banner.classList.remove('hidden');

        if (editor) {
            editor.getWrapperElement().classList.add('editor-error');
        } else {
            document.getElementById(textareaId).classList.add('editor-error');
        }

        return soft ? false : false;
    }
}

async function refreshBackups() {
    if (!currentStack) return;

    const select = document.getElementById('backup-select');
    clearElement(select);

    const loadingOption = document.createElement('option');
    loadingOption.value = '';
    loadingOption.textContent = 'Loading...';
    select.appendChild(loadingOption);

    try {
        const data = await requestApiJson(`/api/stacks/${currentStack}/backups`);
        const backups = data.backups || [];

        clearElement(select);

        if (!backups.length) {
            const noneOption = document.createElement('option');
            noneOption.value = '';
            noneOption.textContent = 'No backups available';
            select.appendChild(noneOption);
            return;
        }

        backups.forEach((name) => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            select.appendChild(option);
        });
    } catch (_error) {
        clearElement(select);
        const errorOption = document.createElement('option');
        errorOption.value = '';
        errorOption.textContent = 'Error loading backups';
        select.appendChild(errorOption);
    }
}

async function loadBackup() {
    if (!currentStack) return;

    const select = document.getElementById('backup-select');
    const backup = select.value;
    if (!backup) return;

    try {
        const data = await requestApiJson(`/api/stacks/${currentStack}/backups/${encodeURIComponent(backup)}`);
        setComposeValue(editComposeEditor, 'edit-compose', data.content || '');
        validateComposeEditor(editComposeEditor, 'edit-compose', 'compose-error-banner', 'compose-error-text', true);
        showNotification(`Loaded backup ${backup} into editor`, 'info');
    } catch (error) {
        showNotification(`Error loading backup: ${error.message}`, 'error');
    }
}

async function restoreBackup() {
    if (!currentStack) return;

    const select = document.getElementById('backup-select');
    const backup = select.value;
    if (!backup) return;

    if (!window.confirm(`Restore backup "${backup}"? This will overwrite the current compose file.`)) {
        return;
    }

    try {
        const data = await requestApiJson(`/api/stacks/${currentStack}/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backup }),
        });

        if (data.status === 'restored') {
            showNotification(`Restored backup ${backup}`, 'success');
            openStack(currentStack);
            return;
        }

        throw new Error(data.error || 'Unable to restore backup');
    } catch (error) {
        showNotification(`Error restoring backup: ${error.message}`, 'error');
    }
}

function bindStacksPageActions() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadStacks);
    }

    const newStackBtn = document.getElementById('new-stack-btn');
    if (newStackBtn) {
        newStackBtn.addEventListener('click', showCreateStackModal);
    }

    document.querySelectorAll('[data-action="hide-create-modal"]').forEach((button) => {
        button.addEventListener('click', hideCreateStackModal);
    });

    const createStackBtn = document.getElementById('create-stack-btn');
    if (createStackBtn) {
        createStackBtn.addEventListener('click', createStack);
    }

    document.querySelectorAll('[data-action="hide-stack-modal"]').forEach((button) => {
        button.addEventListener('click', hideStackModal);
    });

    document.querySelectorAll('.tab-btn').forEach((button) => {
        button.addEventListener('click', () => {
            const tab = button.dataset.tab;
            if (tab) {
                showTab(tab);
            }
        });
    });

    const saveComposeBtn = document.getElementById('stack-save-compose');
    if (saveComposeBtn) {
        saveComposeBtn.addEventListener('click', saveCompose);
    }

    const deployBtn = document.getElementById('stack-deploy');
    if (deployBtn) {
        deployBtn.addEventListener('click', deployStack);
    }

    const refreshBackupsBtn = document.getElementById('stack-refresh-backups');
    if (refreshBackupsBtn) {
        refreshBackupsBtn.addEventListener('click', refreshBackups);
    }

    const loadBackupBtn = document.getElementById('stack-load-backup');
    if (loadBackupBtn) {
        loadBackupBtn.addEventListener('click', loadBackup);
    }

    const restoreBackupBtn = document.getElementById('stack-restore-backup');
    if (restoreBackupBtn) {
        restoreBackupBtn.addEventListener('click', restoreBackup);
    }

    const saveEnvBtn = document.getElementById('stack-save-env');
    if (saveEnvBtn) {
        saveEnvBtn.addEventListener('click', saveEnv);
    }

    const refreshLogsBtn = document.getElementById('stack-refresh-logs');
    if (refreshLogsBtn) {
        refreshLogsBtn.addEventListener('click', loadStackLogs);
    }

    document.querySelectorAll('[data-stack-action]').forEach((button) => {
        button.addEventListener('click', () => {
            const action = button.dataset.stackAction;
            if (action) {
                stackAction(action);
            }
        });
    });

    const deleteBtn = document.getElementById('stack-delete');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', confirmDeleteStack);
    }
}

(async function initStacksPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;

    initEditors();
    bindStacksPageActions();
    await loadStacks();
    window.setInterval(loadStacks, 30000);
})();
