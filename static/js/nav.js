/**
 * Shared Navigation Component
 * Provides consistent dropdown navigation across all pages.
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
                { label: 'Pools', href: '/pools.html' }
            ]
        },
        { label: 'Plugins', href: '/plugins.html' },
        { label: 'Settings', href: '/settings.html' }
    ]
};

/**
 * Render the navigation bar
 * @param {string} currentPage - Current page path (e.g., '/disks.html')
 */
function renderNav(currentPage) {
    const nav = document.getElementById('main-nav');
    if (!nav) return;

    // Normalize currentPage - handle both '/' and '/index.html'
    if (currentPage === '/index.html') {
        currentPage = '/';
    }

    const linksHtml = NAV_CONFIG.items.map(item => {
        if (item.children) {
            // Dropdown menu
            const isActive = item.children.some(c => c.href === currentPage);
            return `
                <div class="nav-dropdown relative">
                    <button class="nav-link ${isActive ? 'nav-active' : ''} flex items-center gap-1"
                            onclick="toggleDropdown(this)">
                        ${item.label}
                        <svg class="w-4 h-4 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </button>
                    <div class="nav-dropdown-menu absolute hidden bg-gray-800 border border-purple-700 rounded-lg shadow-xl mt-1 py-1 min-w-[160px] z-50">
                        ${item.children.map(child => `
                            <a href="${child.href}"
                               class="block px-4 py-2 text-sm ${child.href === currentPage ? 'text-white bg-purple-800' : 'text-blue-200 hover:bg-purple-700 hover:text-white'}">
                                ${child.label}
                            </a>
                        `).join('')}
                    </div>
                </div>
            `;
        } else {
            // Simple link
            const isActive = item.href === currentPage;
            return `
                <a href="${item.href}" class="nav-link ${isActive ? 'nav-active' : ''}">
                    ${item.label}
                </a>
            `;
        }
    }).join('');

    nav.innerHTML = `
        <div class="container mx-auto px-4">
            <div class="flex items-center justify-between h-12">
                <div class="flex space-x-1 nav-links">
                    ${linksHtml}
                </div>
                <div class="flex items-center space-x-3">
                    <span id="logged-in-user" class="text-blue-200 text-sm"></span>
                    <button onclick="logout()" class="px-3 py-2 rounded-md text-red-300 hover:bg-red-800 hover:text-white font-medium text-sm">Logout</button>
                </div>
            </div>
        </div>
    `;

    // Set username if available
    const username = sessionStorage.getItem('username');
    if (username) {
        const userEl = document.getElementById('logged-in-user');
        if (userEl) userEl.textContent = username;
    }

    // Setup hover behavior for dropdowns
    setupDropdownHover();
}

/**
 * Toggle dropdown menu (for click behavior)
 */
function toggleDropdown(button) {
    const dropdown = button.closest('.nav-dropdown');
    const menu = dropdown.querySelector('.nav-dropdown-menu');

    // Close other dropdowns
    document.querySelectorAll('.nav-dropdown-menu').forEach(m => {
        if (m !== menu) m.classList.add('hidden');
    });

    menu.classList.toggle('hidden');
}

/**
 * Setup hover behavior for dropdown menus
 */
function setupDropdownHover() {
    document.querySelectorAll('.nav-dropdown').forEach(dropdown => {
        const menu = dropdown.querySelector('.nav-dropdown-menu');

        dropdown.addEventListener('mouseenter', () => {
            menu.classList.remove('hidden');
        });

        dropdown.addEventListener('mouseleave', () => {
            menu.classList.add('hidden');
        });
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.nav-dropdown')) {
            document.querySelectorAll('.nav-dropdown-menu').forEach(m => {
                m.classList.add('hidden');
            });
        }
    });
}

/**
 * Inject nav styles into the page
 */
function injectNavStyles() {
    if (document.getElementById('nav-styles')) return;

    const style = document.createElement('style');
    style.id = 'nav-styles';
    style.textContent = `
        .nav-link {
            padding: 0.5rem 0.75rem;
            border-radius: 0.375rem;
            color: #bfdbfe;
            font-weight: 500;
            transition: all 0.15s ease;
            cursor: pointer;
            background: transparent;
            border: none;
        }
        .nav-link:hover {
            background-color: rgba(107, 33, 168, 0.8);
            color: white;
        }
        .nav-active {
            color: white;
            background-color: #1e40af;
            border: 1px solid #60a5fa;
        }
        .nav-dropdown-menu {
            left: 0;
            top: 100%;
        }
        .nav-dropdown button svg {
            transition: transform 0.2s ease;
        }
        .nav-dropdown:hover button svg {
            transform: rotate(180deg);
        }
    `;
    document.head.appendChild(style);
}

// Initialize navigation when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    injectNavStyles();
    renderNav(window.location.pathname);
});
