import { clearClientSession } from '/js/lib/session.js';

export async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;

    try {
        payload = await response.json();
    } catch (_err) {
        payload = null;
    }

    return { response, payload };
}

export async function requestApiResponse(url, options = {}) {
    const response = await fetch(url, options);

    if (response.status === 401) {
        clearClientSession();
        window.location.href = '/login.html';
        throw new Error('Authentication required');
    }

    return response;
}

export async function requestApiJson(url, options = {}) {
    const response = await requestApiResponse(url, options);
    let payload = null;

    try {
        payload = await response.json();
    } catch (_err) {
        payload = null;
    }

    if (!response.ok) {
        const error = new Error(payload?.error || payload?.stderr || `Request failed (${response.status})`);
        error.status = response.status;
        error.payload = payload;
        throw error;
    }

    return payload || {};
}
