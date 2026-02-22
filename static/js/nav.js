/**
 * Shared Navigation Component
 * Provides consistent touch-first navigation across all pages.
 */

// Navigation configuration
const NAV_CONFIG = {
    items: [
        { label: 'Home', href: '/' },
        { label: 'System Health', href: '/system.html' },
        {
            label: 'My Apps',
            children: [
                { label: 'Containers', href: '/containers.html' },
                { label: 'Stacks', href: '/stacks.html' },
                { label: 'App Store', href: '/apps.html' }
            ]
        },
        {
            label: 'Storage',
            children: [
                { label: 'Disks', href: '/disks.html' },
                { label: 'Mounts', href: '/mounts.html' },
                { label: 'Pools', href: '/pools.html' },
                { label: 'Shares', href: '/shares.html' }
            ]
        },
        {
            label: 'Network',
            children: [
                { label: 'Host Network', href: '/network.html' },
                { label: 'Tailscale', href: '/tailscale.html' }
            ]
        },
        {
            label: 'Tools',
            children: [
                { label: 'CopyParty', href: '/tools.html' }
            ]
        },
        { label: 'Settings', href: '/settings.html' }
    ]
};

let navListenersBound = false;

function normalizeCurrentPage(currentPage) {
    if (currentPage === '/index.html') {
        return '/';
    }
    return currentPage;
}

function isItemActive(item, currentPage) {
    if (item.href) {
        return item.href === currentPage;
    }
    return item.children?.some((child) => child.href === currentPage) || false;
}

function renderDesktopLinks(currentPage) {
    return NAV_CONFIG.items.map((item, index) => {
        if (item.children) {
            const isActive = isItemActive(item, currentPage);
            const dropdownId = `nav-dropdown-${index}`;
            const childrenHtml = item.children.map((child) => `
                <a href="${child.href}" class="nav-dropdown-link ${child.href === currentPage ? 'nav-dropdown-link-active' : ''}">
                    ${child.label}
                </a>
            `).join('');

            return `
                <div class="nav-dropdown relative" data-nav-dropdown>
                    <button type="button"
                            class="nav-link ${isActive ? 'nav-active' : ''} flex items-center gap-1"
                            data-nav-dropdown-toggle
                            aria-expanded="false"
                            aria-controls="${dropdownId}">
                        ${item.label}
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div id="${dropdownId}"
                         class="nav-dropdown-menu absolute hidden bg-gray-800 border border-purple-700 rounded-lg shadow-xl py-1 min-w-[170px] z-50"
                         data-nav-dropdown-menu>
                        ${childrenHtml}
                    </div>
                </div>
            `;
        }

        const isActive = isItemActive(item, currentPage);
        return `
            <a href="${item.href}" class="nav-link ${isActive ? 'nav-active' : ''}">
                ${item.label}
            </a>
        `;
    }).join('');
}

function renderMobileLinks(currentPage) {
    return NAV_CONFIG.items.map((item, index) => {
        if (item.children) {
            const isActive = isItemActive(item, currentPage);
            const sectionId = `nav-mobile-section-${index}`;
            const sectionOpenClass = isActive ? '' : 'hidden';
            const expanded = isActive ? 'true' : 'false';
            const childrenHtml = item.children.map((child) => `
                <button type="button"
                        class="nav-mobile-sublink ${child.href === currentPage ? 'nav-active' : ''}"
                        data-nav-mobile-target="${child.href}">
                    ${child.label}
                </button>
            `).join('');

            return `
                <div class="nav-mobile-section">
                    <button type="button"
                            class="nav-mobile-link nav-mobile-section-toggle ${isActive ? 'nav-active' : ''}"
                            data-nav-mobile-section-toggle
                            aria-expanded="${expanded}"
                            aria-controls="${sectionId}">
                        <span>${item.label}</span>
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div id="${sectionId}" class="nav-mobile-submenu ${sectionOpenClass}" data-nav-mobile-submenu>
                        ${childrenHtml}
                    </div>
                </div>
            `;
        }

        const isActive = isItemActive(item, currentPage);
        return `
            <button type="button"
                    class="nav-mobile-link ${isActive ? 'nav-active' : ''}"
                    data-nav-mobile-target="${item.href}">
                <span>${item.label}</span>
            </button>
        `;
    }).join('');
}

/**
 * Render the navigation bar
 * @param {string} currentPage - Current page path (e.g., '/disks.html')
 */
function renderNav(currentPage) {
    const nav = document.getElementById('main-nav');
    if (!nav) return;

    const normalizedCurrentPage = normalizeCurrentPage(currentPage);
    const desktopLinksHtml = renderDesktopLinks(normalizedCurrentPage);
    const mobileLinksHtml = renderMobileLinks(normalizedCurrentPage);

    nav.innerHTML = `
        <div class="container mx-auto px-4 nav-shell">
            <div class="hidden lg:flex items-center justify-between h-12">
                <div class="flex space-x-1 nav-links">
                    ${desktopLinksHtml}
                </div>
                <div class="flex items-center space-x-3">
                    <span id="logged-in-user" class="logged-in-user text-blue-200 text-sm" data-nav-username></span>
                    <button type="button" onclick="logout()" class="px-3 py-2 rounded-md text-red-300 hover:bg-red-800 hover:text-white font-medium text-sm">Logout</button>
                </div>
            </div>

            <div class="lg:hidden nav-mobile-header">
                <button type="button"
                        class="nav-menu-toggle"
                        data-nav-mobile-menu-toggle
                        aria-expanded="false"
                        aria-controls="nav-mobile-panel">
                    <span>Menu</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16"/>
                    </svg>
                </button>
                <div class="nav-user-actions">
                    <span class="logged-in-user text-blue-200 text-sm" data-nav-username></span>
                    <button type="button" onclick="logout()" class="nav-logout-btn">Logout</button>
                </div>
            </div>

            <div id="nav-mobile-panel" class="nav-mobile-panel hidden lg:hidden" data-nav-mobile-panel>
                <div class="nav-mobile-links">
                    ${mobileLinksHtml}
                </div>
            </div>
        </div>
    `;

    const username = sessionStorage.getItem('username') || '';
    document.querySelectorAll('[data-nav-username]').forEach((node) => {
        node.textContent = username;
    });

    setupNavigationInteractions();
}

function closeDesktopDropdowns(exceptButton = null) {
    document.querySelectorAll('[data-nav-dropdown]').forEach((dropdown) => {
        const toggle = dropdown.querySelector('[data-nav-dropdown-toggle]');
        const menu = dropdown.querySelector('[data-nav-dropdown-menu]');

        if (!toggle || !menu) {
            return;
        }
        if (exceptButton && toggle === exceptButton) {
            return;
        }

        toggle.setAttribute('aria-expanded', 'false');
        menu.classList.add('hidden');
    });
}

function openDesktopDropdown(button) {
    const dropdown = button.closest('[data-nav-dropdown]');
    if (!dropdown) {
        return;
    }

    const menu = dropdown.querySelector('[data-nav-dropdown-menu]');
    if (!menu) {
        return;
    }

    closeDesktopDropdowns(button);
    button.setAttribute('aria-expanded', 'true');
    menu.classList.remove('hidden');
}

function toggleDesktopDropdown(button) {
    const dropdown = button.closest('[data-nav-dropdown]');
    if (!dropdown) {
        return;
    }

    const menu = dropdown.querySelector('[data-nav-dropdown-menu]');
    if (!menu) {
        return;
    }

    const currentlyExpanded = button.getAttribute('aria-expanded') === 'true';
    closeDesktopDropdowns(button);

    if (currentlyExpanded) {
        button.setAttribute('aria-expanded', 'false');
        menu.classList.add('hidden');
        return;
    }

    openDesktopDropdown(button);
}

function setMobileSectionState(button, shouldOpen) {
    const sectionId = button.getAttribute('aria-controls');
    if (!sectionId) {
        return;
    }

    const section = document.getElementById(sectionId);
    if (!section) {
        return;
    }

    button.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    section.classList.toggle('hidden', !shouldOpen);
}

function closeMobileSections(exceptButton = null) {
    document.querySelectorAll('[data-nav-mobile-section-toggle]').forEach((button) => {
        if (exceptButton && button === exceptButton) {
            return;
        }
        setMobileSectionState(button, false);
    });
}

function closeMobileMenu() {
    const panel = document.querySelector('[data-nav-mobile-panel]');
    const toggle = document.querySelector('[data-nav-mobile-menu-toggle]');

    if (panel) {
        panel.classList.add('hidden');
    }
    if (toggle) {
        toggle.setAttribute('aria-expanded', 'false');
    }
}

function toggleMobileMenu(button) {
    const panel = document.querySelector('[data-nav-mobile-panel]');
    if (!panel) {
        return;
    }

    const shouldOpen = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !shouldOpen);
    button.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
}

function setupNavigationInteractions() {
    const nav = document.getElementById('main-nav');
    if (!nav || navListenersBound) {
        return;
    }

    navListenersBound = true;

    nav.addEventListener('click', (event) => {
        const desktopToggle = event.target.closest('[data-nav-dropdown-toggle]');
        if (desktopToggle) {
            event.preventDefault();
            toggleDesktopDropdown(desktopToggle);
            return;
        }

        const mobileMenuToggle = event.target.closest('[data-nav-mobile-menu-toggle]');
        if (mobileMenuToggle) {
            event.preventDefault();
            toggleMobileMenu(mobileMenuToggle);
            return;
        }

        const mobileSectionToggle = event.target.closest('[data-nav-mobile-section-toggle]');
        if (mobileSectionToggle) {
            event.preventDefault();
            const isOpen = mobileSectionToggle.getAttribute('aria-expanded') === 'true';
            closeMobileSections(mobileSectionToggle);
            setMobileSectionState(mobileSectionToggle, !isOpen);
            return;
        }

        const mobileLink = event.target.closest('[data-nav-mobile-target]');
        if (mobileLink) {
            const targetHref = mobileLink.getAttribute('data-nav-mobile-target');
            closeMobileSections();
            closeMobileMenu();
            if (targetHref) {
                window.location.href = targetHref;
            }
            return;
        }
    });

    nav.querySelectorAll('[data-nav-dropdown]').forEach((dropdown) => {
        dropdown.addEventListener('mouseenter', () => {
            if (!window.matchMedia('(hover: hover)').matches || window.innerWidth < 1024) {
                return;
            }
            const toggle = dropdown.querySelector('[data-nav-dropdown-toggle]');
            if (toggle) {
                openDesktopDropdown(toggle);
            }
        });

        dropdown.addEventListener('mouseleave', () => {
            if (!window.matchMedia('(hover: hover)').matches || window.innerWidth < 1024) {
                return;
            }
            const toggle = dropdown.querySelector('[data-nav-dropdown-toggle]');
            const menu = dropdown.querySelector('[data-nav-dropdown-menu]');
            if (toggle && menu) {
                toggle.setAttribute('aria-expanded', 'false');
                menu.classList.add('hidden');
            }
        });
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('[data-nav-dropdown]')) {
            closeDesktopDropdowns();
        }
        if (!event.target.closest('#main-nav')) {
            closeMobileSections();
            closeMobileMenu();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') {
            return;
        }
        closeDesktopDropdowns();
        closeMobileSections();
        closeMobileMenu();
    });

    window.addEventListener('resize', () => {
        if (window.innerWidth >= 1024) {
            closeMobileSections();
            closeMobileMenu();
        }
    });
}

/**
 * Backwards-compatible dropdown toggle for any older inline handlers.
 */
function toggleDropdown(button) {
    toggleDesktopDropdown(button);
}

/**
 * Inject nav styles into the page
 */
function injectNavStyles() {
    if (document.getElementById('nav-styles')) return;

    const style = document.createElement('style');
    style.id = 'nav-styles';
    style.textContent = `
        .nav-shell {
            padding-top: 0.125rem;
            padding-bottom: 0.125rem;
        }
        .nav-link {
            padding: 0.5rem 0.75rem;
            border-radius: 0.375rem;
            color: var(--theme-nav-link-color, #bfdbfe);
            font-weight: 500;
            transition: all var(--theme-transition-speed, 0.15s) ease;
            cursor: pointer;
            background: transparent;
            border: none;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
        }
        .nav-link:hover {
            background-color: var(--theme-nav-active-bg, rgba(107, 33, 168, 0.8));
            color: var(--theme-nav-link-hover, white);
        }
        .nav-active {
            color: var(--theme-nav-active-color, white) !important;
            background-color: var(--theme-nav-active-bg, #1e40af) !important;
            border: 1px solid var(--theme-nav-active-border, #60a5fa) !important;
        }
        .nav-dropdown-menu {
            left: 0;
            top: calc(100% + 0.25rem);
            background-color: var(--theme-nav-dropdown-bg, #1f2937);
            border-color: var(--theme-nav-dropdown-border, #6b21a8);
        }
        .nav-dropdown-link {
            display: block;
            padding: 0.5rem 0.9rem;
            font-size: 0.875rem;
            color: var(--theme-nav-link-color, #bfdbfe);
            text-decoration: none;
        }
        .nav-dropdown-link:hover {
            background-color: var(--theme-nav-active-bg, rgba(107, 33, 168, 0.8));
            color: var(--theme-nav-link-hover, white);
        }
        .nav-dropdown-link-active {
            color: var(--theme-nav-active-color, white) !important;
            background-color: var(--theme-nav-active-bg, #1e40af) !important;
        }
        [data-nav-dropdown-toggle] svg,
        [data-nav-mobile-section-toggle] svg {
            transition: transform 0.2s ease;
        }
        [data-nav-dropdown-toggle][aria-expanded='true'] svg,
        [data-nav-mobile-section-toggle][aria-expanded='true'] svg {
            transform: rotate(180deg);
        }
        .nav-mobile-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.65rem;
            min-height: 3rem;
            padding-top: 0.25rem;
            padding-bottom: 0.25rem;
        }
        .nav-menu-toggle {
            border: 1px solid var(--theme-nav-active-border, #60a5fa);
            border-radius: 0.5rem;
            color: var(--theme-nav-link-color, #bfdbfe);
            background: rgba(17, 24, 39, 0.35);
            min-height: 2.75rem;
            padding: 0.45rem 0.65rem;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            font-weight: 600;
            font-size: 0.875rem;
            line-height: 1;
        }
        .nav-user-actions {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            min-width: 0;
        }
        .nav-user-actions [data-nav-username] {
            max-width: 8.25rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .nav-logout-btn {
            border: none;
            border-radius: 0.375rem;
            color: #fca5a5;
            background: transparent;
            padding: 0.4rem 0.6rem;
            font-weight: 600;
            font-size: 0.8125rem;
            line-height: 1.2;
        }
        .nav-logout-btn:hover {
            background: #991b1b;
            color: #fff;
        }
        .nav-mobile-panel {
            border-top: 1px solid rgba(148, 163, 184, 0.3);
            margin-top: 0.25rem;
            padding-top: 0.5rem;
            padding-bottom: 0.65rem;
        }
        .nav-mobile-links {
            display: grid;
            gap: 0.25rem;
        }
        .nav-mobile-link {
            width: 100%;
            min-height: 2.75rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border: none;
            border-radius: 0.5rem;
            background: transparent;
            color: var(--theme-nav-link-color, #bfdbfe);
            text-decoration: none;
            padding: 0.55rem 0.7rem;
            font-weight: 500;
            font-size: 0.95rem;
        }
        .nav-mobile-link:hover {
            background-color: var(--theme-nav-active-bg, rgba(107, 33, 168, 0.8));
            color: var(--theme-nav-link-hover, white);
        }
        .nav-mobile-submenu {
            display: grid;
            gap: 0.2rem;
            padding-left: 0.45rem;
            padding-bottom: 0.35rem;
        }
        .nav-mobile-sublink {
            display: block;
            width: 100%;
            min-height: 2.75rem;
            text-decoration: none;
            border-radius: 0.4rem;
            border: none;
            background: transparent;
            text-align: left;
            color: var(--theme-nav-link-color, #bfdbfe);
            padding: 0.45rem 0.7rem;
            font-size: 0.9rem;
            font-weight: 500;
        }
        .nav-mobile-sublink:hover {
            background-color: var(--theme-nav-active-bg, rgba(107, 33, 168, 0.8));
            color: var(--theme-nav-link-hover, white);
        }
    `;
    document.head.appendChild(style);
}

// Initialize navigation when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    injectNavStyles();
    renderNav(window.location.pathname);
});
