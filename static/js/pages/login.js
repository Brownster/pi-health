import { requestJson } from '/js/lib/http.js';
import { saveClientSession, clearClientSession } from '/js/lib/session.js';

const form = document.getElementById('login-form');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const submitButton = document.getElementById('login-button');
const alertEl = document.getElementById('login-error');
const cardEl = document.getElementById('login-card');

function showError(message) {
    alertEl.textContent = message;
    alertEl.dataset.visible = 'true';

    cardEl.classList.remove('shake-animation');
    void cardEl.offsetWidth;
    cardEl.classList.add('shake-animation');
}

function clearError() {
    alertEl.textContent = '';
    alertEl.dataset.visible = 'false';
}

function setBusy(isBusy) {
    submitButton.disabled = isBusy;
    if (isBusy) {
        submitButton.innerHTML = '<span class="ph-spinner" aria-hidden="true"></span><span>Signing in...</span>';
        return;
    }
    submitButton.innerHTML = '<span>Sign in</span>';
}

async function checkAuth() {
    const { response, payload } = await requestJson('/api/auth/check');
    if (!response.ok) {
        return;
    }

    const username = payload?.username ?? '';
    if (username) {
        saveClientSession(username);
    }
    window.location.href = '/';
}

async function submitLogin(event) {
    event.preventDefault();
    clearError();

    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!username || !password) {
        showError('Username and password are required.');
        return;
    }

    setBusy(true);

    try {
        const { response, payload } = await requestJson('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });

        if (!response.ok) {
            showError(payload?.error || 'Invalid username or password.');
            passwordInput.value = '';
            passwordInput.focus();
            return;
        }

        saveClientSession(payload?.username || username);
        window.location.href = '/';
    } catch (_error) {
        clearClientSession();
        showError('Connection error. Please try again.');
    } finally {
        setBusy(false);
    }
}

(async function initLoginPage() {
    try {
        await checkAuth();
    } catch (_error) {
        // User is not authenticated yet.
    }

    form.addEventListener('submit', submitLogin);
    usernameInput.focus();
})();
