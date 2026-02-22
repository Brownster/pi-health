const DEFAULT_COLORS = {
    success: 'bg-green-600',
    error: 'bg-red-600',
    warning: 'bg-yellow-700',
    info: 'bg-blue-600',
};

function prepareNotificationArea(area) {
    if (!area) {
        return;
    }
    // This class activates responsive notification positioning from layout.js.
    area.classList.add('ph-notification-area');
}

export function showNotification(message, type = 'info', options = {}) {
    const {
        areaId = 'notification-area',
        duration = 3000,
        baseClass = 'p-3 rounded shadow-lg transform transition-all duration-300 opacity-0 text-white',
        animate = true,
        colorMap = DEFAULT_COLORS,
    } = options;

    const area = document.getElementById(areaId);
    if (!area) {
        return;
    }
    prepareNotificationArea(area);

    const notification = document.createElement('div');
    notification.className = baseClass;
    notification.classList.add('ph-notification-item');
    notification.classList.add(colorMap[type] || colorMap.info || DEFAULT_COLORS.info);
    notification.textContent = message;
    area.appendChild(notification);

    if (!animate) {
        window.setTimeout(() => notification.remove(), duration);
        return;
    }

    window.setTimeout(() => notification.classList.replace('opacity-0', 'opacity-100'), 10);
    window.setTimeout(() => {
        notification.classList.replace('opacity-100', 'opacity-0');
        window.setTimeout(() => notification.remove(), 300);
    }, duration);
}
