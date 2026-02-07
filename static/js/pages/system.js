import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { requestJson } from '/js/lib/http.js';
import { formatBytes } from '/js/lib/format.js';
import { showNotification } from '/js/lib/notify.js';

const els = {
    cpuUsage: document.getElementById('cpu-usage'),
    cpuBar: document.getElementById('cpu-bar'),
    cpuCores: document.getElementById('cpu-cores'),
    memoryUsage: document.getElementById('memory-usage'),
    memoryBar: document.getElementById('memory-bar'),
    temperature: document.getElementById('temperature'),
    tempBar: document.getElementById('temp-bar'),
    diskUsage: document.getElementById('disk-usage'),
    diskBar1: document.getElementById('disk1-bar'),
    diskUsage2: document.getElementById('disk-usage-2'),
    diskBar2: document.getElementById('disk2-bar'),
    networkRecv: document.getElementById('network-recv'),
    networkSent: document.getElementById('network-sent'),
    networkRecvRate: document.getElementById('network-recv-rate'),
    networkSentRate: document.getElementById('network-sent-rate'),
    lastUpdated: document.getElementById('last-updated'),
    piSection: document.getElementById('pi-metrics-section'),
    throttleStatus: document.getElementById('throttle-status'),
    cpuFreq: document.getElementById('cpu-freq'),
    cpuVoltage: document.getElementById('cpu-voltage'),
    wifiCard: document.getElementById('wifi-card'),
    wifiInterface: document.getElementById('wifi-interface'),
    wifiSignal: document.getElementById('wifi-signal'),
    wifiBar: document.getElementById('wifi-bar'),
};

let networkSnapshot = { recv: null, sent: null, time: null };

function nowTime() {
    const date = new Date();
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
}

function colorClass(percent) {
    if (percent < 70) return 'ph-positive';
    if (percent < 85) return 'ph-warn';
    return 'ph-danger';
}

function renderCoreBreakdown(cores = []) {
    if (!cores.length) {
        els.cpuCores.textContent = '';
        const empty = document.createElement('div');
        empty.className = 'ph-muted';
        empty.textContent = 'Per-core stats unavailable';
        els.cpuCores.appendChild(empty);
        return;
    }

    els.cpuCores.textContent = '';

    cores.forEach((core) => {
        const usage = Number(core?.usage_percent);
        const pct = Number.isFinite(usage) ? usage : 0;
        const pctText = pct.toFixed(1);

        const row = document.createElement('div');
        row.className = 'flex items-center justify-between gap-3 ph-metric-row';

        const label = document.createElement('span');
        label.className = 'w-16';
        label.textContent = core?.core || 'Core';

        const progress = document.createElement('div');
        progress.className = 'flex-1 ph-progress';
        const progressFill = document.createElement('div');
        progressFill.style.width = `${Math.max(0, Math.min(pct, 100))}%`;
        progressFill.style.background = '#0ea5e9';
        progress.appendChild(progressFill);

        const value = document.createElement('span');
        value.className = 'w-12 text-right';
        value.textContent = `${pctText}%`;

        row.appendChild(label);
        row.appendChild(progress);
        row.appendChild(value);
        els.cpuCores.appendChild(row);
    });
}

function applyValue(el, value, percent) {
    el.textContent = value;
    el.classList.remove('ph-positive', 'ph-warn', 'ph-danger', 'fade-in');
    el.classList.add(colorClass(percent), 'fade-in');
}

function updatePiMetrics(data) {
    if (data.is_raspberry_pi) {
        els.piSection.classList.remove('hidden');
    } else {
        els.piSection.classList.add('hidden');
        return;
    }

    const t = data.throttling;
    els.throttleStatus.textContent = '';

    if (!t) {
        const item = document.createElement('p');
        item.className = 'ph-muted';
        item.textContent = 'N/A';
        els.throttleStatus.appendChild(item);
    } else if (t.has_issues) {
        const issues = [];
        if (t.under_voltage_now) issues.push({ className: 'ph-danger', text: 'Under-voltage detected' });
        if (t.throttled_now) issues.push({ className: 'ph-danger', text: 'CPU throttled' });
        if (t.freq_capped_now) issues.push({ className: 'ph-warn', text: 'Frequency capped' });
        if (t.soft_temp_limit_now) issues.push({ className: 'ph-warn', text: 'Soft temp limit' });

        issues.forEach((issue) => {
            const item = document.createElement('p');
            item.className = issue.className;
            item.textContent = issue.text;
            els.throttleStatus.appendChild(item);
        });
    } else {
        const item = document.createElement('p');
        item.className = 'ph-positive';
        item.textContent = 'All OK';
        els.throttleStatus.appendChild(item);
    }

    if (t?.has_historical_issues && !t.has_issues) {
        const historical = document.createElement('p');
        historical.className = 'ph-muted';
        historical.textContent = 'Historical issues detected since boot';
        els.throttleStatus.appendChild(historical);
    }

    const cpuFreq = Number(data.cpu_freq_mhz);
    const cpuVoltage = Number(data.cpu_voltage);

    els.cpuFreq.textContent = 'Frequency: ';
    const freqValue = document.createElement('span');
    freqValue.className = 'ph-muted';
    freqValue.textContent = Number.isFinite(cpuFreq) ? `${cpuFreq} MHz` : '—';
    els.cpuFreq.appendChild(freqValue);

    els.cpuVoltage.textContent = 'Voltage: ';
    const voltageValue = document.createElement('span');
    voltageValue.className = 'ph-muted';
    voltageValue.textContent = Number.isFinite(cpuVoltage) ? `${cpuVoltage.toFixed(4)} V` : '—';
    els.cpuVoltage.appendChild(voltageValue);

    if (!data.wifi_signal) {
        els.wifiCard.classList.add('hidden');
        return;
    }

    const wifi = data.wifi_signal;
    els.wifiCard.classList.remove('hidden');
    els.wifiInterface.textContent = `Interface: ${wifi.interface}`;
    els.wifiSignal.textContent = `${wifi.signal_level} dBm (${wifi.signal_percent}%)`;
    els.wifiSignal.className = colorClass(100 - wifi.signal_percent);
    els.wifiBar.style.width = `${wifi.signal_percent}%`;
}

async function fetchSystemMetrics() {
    try {
        const { response, payload } = await requestJson('/api/stats');
        if (!response.ok) {
            throw new Error(payload?.error || `Request failed (${response.status})`);
        }
        const data = payload;

        const cpuPercent = data.cpu_usage_percent ? Number(data.cpu_usage_percent.toFixed(1)) : 0;
        applyValue(els.cpuUsage, `${cpuPercent}%`, cpuPercent);
        els.cpuBar.style.width = `${cpuPercent}%`;
        renderCoreBreakdown(data.cpu_usage_per_core || []);

        const memPercent = Number(data.memory_usage.percent.toFixed(1));
        applyValue(els.memoryUsage, `${memPercent}% (${formatBytes(data.memory_usage.used)} / ${formatBytes(data.memory_usage.total)})`, memPercent);
        els.memoryBar.style.width = `${memPercent}%`;

        if (data.temperature_celsius) {
            const temp = Number(data.temperature_celsius.toFixed(1));
            const tempPercent = Math.min((temp / 85) * 100, 100);
            applyValue(els.temperature, `${temp} °C`, tempPercent);
            els.tempBar.style.width = `${tempPercent}%`;
        } else {
            els.temperature.textContent = 'N/A';
            els.tempBar.style.width = '0%';
        }

        const disk1 = Number(data.disk_usage.percent.toFixed(1));
        applyValue(els.diskUsage, `${disk1}% (${formatBytes(data.disk_usage.used)} / ${formatBytes(data.disk_usage.total)})`, disk1);
        els.diskBar1.style.width = `${disk1}%`;

        const disk2 = Number(data.disk_usage_2.percent.toFixed(1));
        applyValue(els.diskUsage2, `${disk2}% (${formatBytes(data.disk_usage_2.used)} / ${formatBytes(data.disk_usage_2.total)})`, disk2);
        els.diskBar2.style.width = `${disk2}%`;

        els.networkRecv.textContent = `Received: ${formatBytes(data.network_usage.bytes_recv)}`;
        els.networkSent.textContent = `Sent: ${formatBytes(data.network_usage.bytes_sent)}`;

        const now = Date.now();
        if (networkSnapshot.recv !== null) {
            const deltaS = (now - networkSnapshot.time) / 1000;
            const recvRate = deltaS > 0 ? (data.network_usage.bytes_recv - networkSnapshot.recv) / deltaS : 0;
            const sentRate = deltaS > 0 ? (data.network_usage.bytes_sent - networkSnapshot.sent) / deltaS : 0;
            els.networkRecvRate.textContent = `Receive rate: ${formatBytes(Math.max(recvRate, 0))}/s`;
            els.networkSentRate.textContent = `Send rate: ${formatBytes(Math.max(sentRate, 0))}/s`;
        }

        networkSnapshot = {
            recv: data.network_usage.bytes_recv,
            sent: data.network_usage.bytes_sent,
            time: now,
        };

        updatePiMetrics(data);
        els.lastUpdated.textContent = `Last updated: ${nowTime()}`;
    } catch (error) {
        console.error('Error fetching system metrics:', error);
        [els.cpuUsage, els.memoryUsage, els.temperature, els.diskUsage, els.diskUsage2].forEach((el) => {
            el.textContent = 'Error';
            el.classList.remove('ph-positive', 'ph-warn');
            el.classList.add('ph-danger');
        });
        els.networkRecv.textContent = 'Received: Error';
        els.networkSent.textContent = 'Sent: Error';
        showNotification('Error fetching system metrics', 'error');
    }
}

async function sendSystemAction(action) {
    if (!window.confirm(`Are you sure you want to ${action} the system?`)) {
        return;
    }

    try {
        showNotification(`Sending ${action} command...`, 'info');
        const { response, payload } = await requestJson(`/api/${action}`, { method: 'POST' });
        const data = payload || {};

        if (!response.ok) {
            showNotification(`Error during ${action}: ${data.error || 'Unknown error'}`, 'error');
            return;
        }

        showNotification(`Successful ${action}: ${data.status}`, 'success');
    } catch (error) {
        console.error(`Error sending ${action} action:`, error);
        showNotification(`Error sending ${action} command: ${error.message}`, 'error');
    }
}

(async function initSystemPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) return;

    window.logout = logoutToLogin;

    document.querySelectorAll('[data-action]').forEach((button) => {
        button.addEventListener('click', () => sendSystemAction(button.dataset.action));
    });

    await fetchSystemMetrics();
    window.setInterval(fetchSystemMetrics, 5000);
})();
