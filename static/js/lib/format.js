export function escapeHtml(value) {
    if (value === null || value === undefined) {
        return '';
    }

    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function encodeDataAttr(value) {
    return escapeHtml(String(value ?? ''));
}

export function formatBytes(bytes, decimals = 2) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) {
        return '0 B';
    }

    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    const i = Math.min(Math.floor(Math.log(value) / Math.log(k)), sizes.length - 1);

    return `${parseFloat((value / Math.pow(k, i)).toFixed(decimals))} ${sizes[i]}`;
}
