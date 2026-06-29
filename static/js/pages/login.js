// Self-contained: login must survive deletion of the shared /js/lib modules
// during legacy v1 removal (LR-004). These were the only helpers login used.
async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;
    try {
        payload = await response.json();
    } catch (_err) {
        payload = null;
    }
    return { response, payload };
}

function saveClientSession(username) {
    sessionStorage.setItem('loggedIn', 'true');
    sessionStorage.setItem('username', username);
}

function clearClientSession() {
    sessionStorage.removeItem('loggedIn');
    sessionStorage.removeItem('username');
}

const form = document.getElementById('login-form');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const submitButton = document.getElementById('login-button');
const alertEl = document.getElementById('login-error');
const cardEl = document.getElementById('login-card');
let isBusy = false;

function getFormValues() {
    return {
        username: usernameInput.value.trim(),
        password: passwordInput.value,
    };
}

function updateFormState() {
    const { username, password } = getFormValues();
    submitButton.disabled = isBusy || !username || !password;
}

function showError(message) {
    alertEl.textContent = message;
    alertEl.dataset.visible = 'true';
    usernameInput.setAttribute('aria-invalid', 'true');
    passwordInput.setAttribute('aria-invalid', 'true');

    cardEl.classList.remove('shake-animation');
    void cardEl.offsetWidth;
    cardEl.classList.add('shake-animation');
}

function clearError() {
    alertEl.textContent = '';
    alertEl.dataset.visible = 'false';
    usernameInput.setAttribute('aria-invalid', 'false');
    passwordInput.setAttribute('aria-invalid', 'false');
}

function setBusy(busy) {
    isBusy = Boolean(busy);
    if (isBusy) {
        submitButton.innerHTML = '<span class="ph-spinner" aria-hidden="true"></span><span>Signing in...</span>';
        updateFormState();
        return;
    }
    submitButton.innerHTML = '<span>Sign in</span>';
    updateFormState();
}

async function checkAuth() {
    const { response, payload } = await requestJson('/api/auth/check');
    if (!response.ok || !payload?.authenticated) {
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

    const { username, password } = getFormValues();

    if (!username || !password) {
        showError('Username and password are required.');
        if (!username) {
            usernameInput.focus();
        } else {
            passwordInput.focus();
        }
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

    [usernameInput, passwordInput].forEach((input) => {
        input.addEventListener('input', () => {
            clearError();
            updateFormState();
        });
    });

    clearError();
    updateFormState();
    form.addEventListener('submit', submitLogin);
    usernameInput.focus();
})();
