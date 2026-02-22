const DEFAULT_BODY_CLASS = 'bg-gray-900 text-blue-100 font-sans min-h-screen';
const DEFAULT_NAV_CLASS = 'bg-purple-900 shadow-md';
const DEFAULT_NOTIFICATION_CLASS = 'fixed top-4 right-4 z-50 w-72 flex flex-col items-end';
const DEFAULT_FOOTER_CLASS = 'text-center text-xs text-gray-500 py-6';
const NOTIFICATION_STYLE_ID = 'ph-notification-area-styles';

function applyClassList(element, classNames) {
    if (!element || !classNames) {
        return;
    }
    element.className = classNames;
}

function ensureBodyClasses(classNames) {
    if (!classNames) {
        return;
    }

    classNames.split(/\s+/).filter(Boolean).forEach((name) => {
        document.body.classList.add(name);
    });
}

function ensureHeader(beforeNode) {
    let header = document.querySelector('header[data-shell-header="dashboard"]');
    if (header) {
        return header;
    }

    header = document.querySelector('header');
    if (header) {
        header.dataset.shellHeader = 'dashboard';
        return header;
    }

    const created = document.createElement('header');
    created.dataset.shellHeader = 'dashboard';
    created.className = 'bg-gradient-to-r from-purple-900 to-blue-900 shadow-lg relative overflow-hidden';
    created.innerHTML = `
        <div class="absolute inset-0 overflow-hidden">
            <img src="/theme-banner" alt="Dashboard" class="w-full h-full object-cover opacity-40 blur-sm" style="filter: hue-rotate(-10deg) saturate(1.15);">
        </div>
        <div class="container mx-auto px-8 py-12 relative"></div>
    `;

    document.body.insertBefore(created, beforeNode || document.body.firstChild);
    return created;
}

function ensureNav(beforeNode, navClass) {
    let nav = document.getElementById('main-nav');
    if (!nav) {
        nav = document.createElement('nav');
        nav.id = 'main-nav';
        document.body.insertBefore(nav, beforeNode);
    }

    applyClassList(nav, navClass || DEFAULT_NAV_CLASS);
    nav.dataset.shellNav = 'dashboard';
    return nav;
}

function injectNotificationStyles() {
    if (document.getElementById(NOTIFICATION_STYLE_ID)) {
        return;
    }

    const style = document.createElement('style');
    style.id = NOTIFICATION_STYLE_ID;
    style.textContent = `
        #notification-area.ph-notification-area {
            position: fixed !important;
            top: auto !important;
            left: max(0.5rem, env(safe-area-inset-left, 0px)) !important;
            right: max(0.5rem, env(safe-area-inset-right, 0px)) !important;
            bottom: max(0.75rem, env(safe-area-inset-bottom, 0px)) !important;
            width: auto !important;
            max-width: none !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: stretch !important;
            gap: 0.5rem !important;
            pointer-events: none;
        }
        #notification-area.ph-notification-area > * {
            width: 100%;
            max-width: 100%;
            margin: 0 !important;
            pointer-events: auto;
        }
        @media (min-width: 768px) {
            #notification-area.ph-notification-area {
                top: 1rem !important;
                right: 1rem !important;
                bottom: auto !important;
                left: auto !important;
                width: min(22rem, calc(100vw - 2rem)) !important;
                align-items: flex-end !important;
            }
            #notification-area.ph-notification-area > * {
                width: auto;
                max-width: 100%;
            }
        }
    `;
    document.head.appendChild(style);
}

function prepareNotificationArea(notificationArea) {
    if (!notificationArea) {
        return;
    }
    injectNotificationStyles();
    notificationArea.classList.add('ph-notification-area');
}

function ensureNotification(afterNode, notificationClass) {
    let notificationArea = document.getElementById('notification-area');
    if (!notificationArea) {
        notificationArea = document.createElement('div');
        notificationArea.id = 'notification-area';
        if (afterNode?.nextSibling) {
            document.body.insertBefore(notificationArea, afterNode.nextSibling);
        } else {
            document.body.appendChild(notificationArea);
        }
    }

    applyClassList(notificationArea, notificationClass || DEFAULT_NOTIFICATION_CLASS);
    prepareNotificationArea(notificationArea);
    notificationArea.dataset.shellNotifications = 'dashboard';
    return notificationArea;
}

function ensureFooter(main, { includeFooter, footerText, footerClass } = {}) {
    if (!includeFooter) {
        return null;
    }

    let footer = document.querySelector('footer[data-shell-footer="dashboard"]');
    if (!footer) {
        footer = document.createElement('footer');
        footer.dataset.shellFooter = 'dashboard';
        if (main?.nextSibling) {
            document.body.insertBefore(footer, main.nextSibling);
        } else {
            document.body.appendChild(footer);
        }
    }

    applyClassList(footer, footerClass || DEFAULT_FOOTER_CLASS);
    footer.textContent = footerText || `Pi-Health UI`;
    return footer;
}

export function ensureDashboardShell(options = {}) {
    const main = document.querySelector('main');
    if (!main) {
        return null;
    }

    const bodyClass = options.bodyClass || DEFAULT_BODY_CLASS;
    ensureBodyClasses(bodyClass);

    const header = ensureHeader(main);
    const nav = ensureNav(main, options.navClass);
    const notifications = ensureNotification(nav, options.notificationClass);
    const footer = ensureFooter(main, options);

    return {
        body: document.body,
        header,
        nav,
        notifications,
        main,
        footer,
    };
}
