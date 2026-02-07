import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { ensureDashboardShell } from '/js/lib/layout.js';
import { clearClientSession } from '/js/lib/session.js';

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

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showLoadError(message) {
    const loadingState = document.getElementById('loading-state');
    if (!loadingState) {
        return;
    }

    loadingState.innerHTML = `<p class="text-red-400">Failed to load network info: ${escapeHtml(message)}</p>`;
}

async function loadNetworkInfo() {
    try {
        const response = await apiFetch('/api/network/info');
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data?.error || `Request failed (${response.status})`);
        }

        const loadingState = document.getElementById('loading-state');
        const networkContent = document.getElementById('network-content');
        if (loadingState) {
            loadingState.classList.add('hidden');
        }
        if (networkContent) {
            networkContent.classList.remove('hidden');
        }

        renderNetworkInfo(data);
    } catch (error) {
        showLoadError(error.message || 'Unknown error');
    }
}

function renderNetworkInfo(data) {
    const hostname = document.getElementById('net-hostname');
    const fqdn = document.getElementById('net-fqdn');
    const publicIp = document.getElementById('net-public-ip');
    const gateway = document.getElementById('net-gateway');

    if (hostname) hostname.textContent = data.hostname || '-';
    if (fqdn) fqdn.textContent = data.fqdn || '-';
    if (publicIp) publicIp.textContent = data.public_ip || 'Not available';

    if (gateway) {
        if (data.default_gateway) {
            gateway.textContent = `${data.default_gateway.ip} (${data.default_gateway.interface})`;
        } else {
            gateway.textContent = '-';
        }
    }

    const dnsContainer = document.getElementById('dns-servers');
    const dnsServers = data.dns_servers || [];
    if (dnsContainer) {
        if (dnsServers.length > 0) {
            dnsContainer.innerHTML = dnsServers.map((dns) => `
                <div class="info-card">
                    <div class="info-value">${escapeHtml(dns)}</div>
                </div>
            `).join('');
        } else {
            dnsContainer.innerHTML = '<p class="text-gray-500">No DNS servers configured</p>';
        }
    }

    const interfacesContainer = document.getElementById('interfaces-list');
    const interfaces = data.interfaces || [];
    if (interfacesContainer) {
        if (interfaces.length > 0) {
            interfacesContainer.innerHTML = interfaces.map((iface) => renderInterface(iface)).join('');
        } else {
            interfacesContainer.innerHTML = '<p class="text-gray-500">No network interfaces found</p>';
        }
    }
}

function renderInterface(iface) {
    const state = String(iface.state || 'UNKNOWN');
    const stateClass = state === 'UP'
        ? 'status-up'
        : state === 'DOWN'
            ? 'status-down'
            : 'status-unknown';

    const ipv4Addrs = (iface.ipv4 || []).map((addr) => `
        <div class="flex items-center gap-2">
            <span class="text-green-400">${escapeHtml(addr.address)}/${escapeHtml(String(addr.prefix))}</span>
            ${addr.broadcast ? `<span class="text-gray-500 text-xs">(broadcast: ${escapeHtml(addr.broadcast)})</span>` : ''}
        </div>
    `).join('') || '<span class="text-gray-500">None</span>';

    const ipv6Addrs = (iface.ipv6 || [])
        .filter((addr) => addr.scope !== 'link')
        .map((addr) => `<div class="text-blue-400 text-sm">${escapeHtml(addr.address)}/${escapeHtml(String(addr.prefix))}</div>`)
        .join('') || '<span class="text-gray-500 text-sm">None (excluding link-local)</span>';

    return `
        <div class="interface-card p-4">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                    <span class="text-lg font-semibold font-mono">${escapeHtml(iface.name)}</span>
                    <span class="status-pill ${stateClass}">${escapeHtml(state)}</span>
                </div>
                <div class="text-sm text-gray-400">
                    MTU: ${escapeHtml(String(iface.mtu ?? '-'))}
                </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                    <div class="info-label mb-1">MAC Address</div>
                    <div class="font-mono text-gray-300">${escapeHtml(iface.mac) || '-'}</div>
                </div>
                <div>
                    <div class="info-label mb-1">IPv4 Addresses</div>
                    ${ipv4Addrs}
                </div>
                <div>
                    <div class="info-label mb-1">IPv6 Addresses</div>
                    ${ipv6Addrs}
                </div>
            </div>
        </div>
    `;
}

function refreshNetworkInfo() {
    const loadingState = document.getElementById('loading-state');
    const networkContent = document.getElementById('network-content');

    if (loadingState) {
        loadingState.classList.remove('hidden');
        loadingState.innerHTML = `
            <svg class="animate-spin h-8 w-8 mx-auto mb-4 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Loading network information...
        `;
    }

    if (networkContent) {
        networkContent.classList.add('hidden');
    }

    loadNetworkInfo();
}

Object.assign(window, {
    refreshNetworkInfo,
});

(async function initNetworkPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;
    await loadNetworkInfo();
})();
