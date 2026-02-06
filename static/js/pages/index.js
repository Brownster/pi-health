import { ensureAuthenticated, logoutToLogin } from '/js/lib/auth.js';
import { requestJson } from '/js/lib/http.js';

const serviceGrid = document.getElementById('service-grid');
const serviceCount = document.getElementById('service-count');
const refreshTime = document.getElementById('refresh-time');

const serviceOverrides = {
    transmission: { icon: 'transfer', name: 'Transmission' },
    jackett: { icon: 'search', name: 'Jackett' },
    sonarr: { icon: 'tv', name: 'Sonarr' },
    radarr: { icon: 'film', name: 'Radarr' },
    nzbget: { icon: 'download', name: 'NZBGet' },
    jellyfin: { icon: 'collection', name: 'Jellyfin' },
    get_iplayer: { icon: 'play', name: 'Get iPlayer' },
    rtdclient: { icon: 'cloud-download', name: 'RTD Client' },
    'airsonic-advanced': { icon: 'music', name: 'Airsonic' },
    rdtclient: { icon: 'cloud-download', name: 'RDT Client' },
    lidarr: { icon: 'music', name: 'Lidarr' },
    audiobookshelf: { icon: 'book', name: 'Audiobookshelf' },
};

function formatRefreshTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function renderState(message, tone = 'info', action = null) {
    serviceGrid.textContent = '';
    const section = document.createElement('section');
    section.className = 'ph-state';
    section.dataset.tone = tone;

    const content = document.createElement('div');
    const messageEl = document.createElement('p');
    messageEl.textContent = message;
    content.appendChild(messageEl);

    if (action?.href && action?.label) {
        const link = document.createElement('a');
        link.className = 'ph-action-link';
        link.href = action.href;
        link.textContent = action.label;
        content.appendChild(link);
    }

    section.appendChild(content);
    serviceGrid.appendChild(section);
}

function getDefaultIcons() {
    return {
        transfer: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><path d="M8 15V9m0 0L5 12m3-3l3 3m5-3v6m0 0l3-3m-3 3l-3-3" stroke="#f8fafc" stroke-width="2" stroke-linecap="round"/></svg>',
        search: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><circle cx="10.5" cy="10.5" r="3" stroke="#f8fafc" stroke-width="2"/><path d="M12.5 12.5l4 4" stroke="#f8fafc" stroke-width="2" stroke-linecap="round"/></svg>',
        tv: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><rect x="7" y="8" width="10" height="6" rx="1" stroke="#f8fafc" stroke-width="1.5"/></svg>',
        film: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><rect x="7" y="7" width="10" height="10" rx="1" stroke="#f8fafc" stroke-width="1.5"/></svg>',
        download: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><path d="M12 7v8m0 0l-3-3m3 3l3-3" stroke="#f8fafc" stroke-width="2" stroke-linecap="round"/></svg>',
        collection: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><rect x="7" y="8" width="10" height="3" rx="0.5" stroke="#f8fafc" stroke-width="1.5"/><rect x="7" y="13" width="10" height="3" rx="0.5" stroke="#f8fafc" stroke-width="1.5"/></svg>',
        play: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><path d="M10 8l6 4-6 4V8z" fill="#f8fafc"/></svg>',
        'cloud-download': '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><path d="M8 11a3 3 0 016 0h2c1 0 2 1 2 2s-1 2-2 2H8c-1 0-2-1-2-2s1-2 2-2z" stroke="#f8fafc" stroke-width="1.5"/></svg>',
        music: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><path d="M9 15V9l6-2v8" stroke="#f8fafc" stroke-width="1.5" stroke-linecap="round"/></svg>',
        book: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><path d="M12 8v8M12 8c-1-1-2-1-3-1M12 8c1-1 2-1 3-1" stroke="#f8fafc" stroke-width="1.5" stroke-linecap="round"/></svg>',
        default: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="rgba(248,250,252,0.72)" stroke-width="2" fill="rgba(15,23,42,0.3)"/><rect x="7" y="10" width="10" height="4" rx="0.5" stroke="#f8fafc" stroke-width="1.5"/></svg>',
    };
}

function getIcon(containerName) {
    const iconSVGs = window.ThemeIcons || getDefaultIcons();
    const service = serviceOverrides[containerName];
    if (service && service.icon && iconSVGs[service.icon]) {
        return iconSVGs[service.icon];
    }
    return iconSVGs.default;
}

function getFriendlyName(containerName) {
    const service = serviceOverrides[containerName];
    if (service && service.name) {
        return service.name;
    }

    return containerName
        .replace(/[-_]/g, ' ')
        .replace(/\w\S*/g, (word) => word.replace(/^\w/, (c) => c.toUpperCase()));
}

function getBackgroundGradient(containerName) {
    const gradients = window.ThemeLoader ? window.ThemeLoader.getThemeGradients() : [
        'from-sky-700 to-cyan-700',
        'from-teal-700 to-emerald-700',
        'from-orange-700 to-amber-700',
        'from-indigo-700 to-sky-700',
        'from-emerald-700 to-teal-700',
        'from-cyan-700 to-blue-700',
    ];

    let hash = 0;
    for (let i = 0; i < containerName.length; i += 1) {
        hash = containerName.charCodeAt(i) + ((hash << 5) - hash);
    }

    return gradients[Math.abs(hash) % gradients.length];
}

function getWebUIPort(container) {
    if (!container.ports || container.ports.length === 0) {
        return null;
    }

    const tcpPorts = container.ports.filter((port) => port.protocol !== 'udp');
    const hostTcp = tcpPorts.find((port) => port.host_port);
    if (hostTcp) return hostTcp.host_port;

    const anyHost = container.ports.find((port) => port.host_port);
    if (anyHost) return anyHost.host_port;

    const tcpContainer = tcpPorts.find((port) => port.container_port);
    if (tcpContainer) return tcpContainer.container_port;

    const fallback = container.ports.find((port) => port.container_port);
    return fallback ? fallback.container_port : null;
}

function buildServiceCard(container) {
    const port = getWebUIPort(container);
    const icon = getIcon(container.name);
    const friendlyName = getFriendlyName(container.name);
    const gradient = getBackgroundGradient(container.name);

    const card = document.createElement('article');
    card.className = 'ph-service-card';
    card.innerHTML = `
        <div class="ph-service-banner bg-gradient-to-br ${gradient}">
            ${icon}
        </div>
        <div class="ph-service-content">
            <h3 class="ph-service-title"></h3>
            <p class="ph-service-port"></p>
            <a class="ph-service-link" target="_blank" rel="noopener noreferrer">Open Service</a>
        </div>
    `;

    const title = card.querySelector('.ph-service-title');
    const portLabel = card.querySelector('.ph-service-port');
    const openLink = card.querySelector('.ph-service-link');
    title.textContent = friendlyName;
    portLabel.textContent = `port:${port}`;
    openLink.href = `http://${window.location.hostname}:${port}`;

    return card;
}

async function fetchDockerWebServices() {
    try {
        renderState('Loading services...');
        const { response, payload } = await requestJson('/api/containers?stats=false');
        if (!response.ok) {
            throw new Error(payload?.error || `Request failed (${response.status})`);
        }
        const containers = payload;

        if (!Array.isArray(containers)) {
            throw new Error(containers.error || 'Invalid response while loading containers.');
        }

        const webServices = containers.filter((container) => container.status === 'running' && getWebUIPort(container));
        serviceCount.textContent = String(webServices.length);
        refreshTime.textContent = formatRefreshTime(new Date());

        if (!webServices.length) {
            renderState(
                'No running web services found.',
                'info',
                { href: '/containers.html', label: 'Manage Containers' }
            );
            return;
        }

        serviceGrid.innerHTML = '';
        webServices.forEach((container) => serviceGrid.appendChild(buildServiceCard(container)));
    } catch (error) {
        console.error('Error fetching Docker services:', error);
        renderState(`Error loading services: ${error.message}`, 'error');
    }
}

(async function initIndexPage() {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        return;
    }

    window.logout = logoutToLogin;

    await fetchDockerWebServices();
    window.setInterval(fetchDockerWebServices, 30000);
})();
