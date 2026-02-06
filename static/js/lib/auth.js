import { requestJson } from '/js/lib/http.js';
import { clearClientSession, saveClientSession } from '/js/lib/session.js';

export async function ensureAuthenticated({ redirectTo = '/login.html' } = {}) {
    const localFlag = sessionStorage.getItem('loggedIn');
    if (!localFlag) {
        window.location.href = redirectTo;
        return false;
    }

    const { response, payload } = await requestJson('/api/auth/check');
    if (!response.ok || !payload?.authenticated) {
        clearClientSession();
        window.location.href = redirectTo;
        return false;
    }

    if (payload?.username) {
        saveClientSession(payload.username);
    }
    return true;
}

export async function logoutToLogin({ redirectTo = '/login.html' } = {}) {
    try {
        await fetch('/api/logout', { method: 'POST' });
    } catch (_error) {
        // Ignore logout transport errors and clear session client-side.
    }

    clearClientSession();
    window.location.href = redirectTo;
}
