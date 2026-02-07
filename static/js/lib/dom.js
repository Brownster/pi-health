import { clearElement } from '/js/lib/states.js';

export function setNodeContent(containerOrId, node) {
    const container = typeof containerOrId === 'string'
        ? document.getElementById(containerOrId)
        : containerOrId;

    if (!container) {
        return;
    }

    clearElement(container);
    container.appendChild(node);
}
