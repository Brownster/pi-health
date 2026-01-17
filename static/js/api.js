/**
 * Pi-Health API utilities
 * Provides fetch wrapper with auth handling and common utilities
 */

/**
 * Fetch wrapper that handles authentication errors
 * Redirects to login page on 401 responses
 */
async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);

    if (response.status === 401) {
        window.location.href = '/login.html';
        throw new Error('Authentication required');
    }

    return response;
}

/**
 * Fetch JSON from API with auth handling
 */
async function apiGet(url) {
    const response = await apiFetch(url);
    return response.json();
}

/**
 * POST JSON to API with auth handling
 */
async function apiPost(url, data = {}) {
    const response = await apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    return response.json();
}

/**
 * DELETE to API with auth handling
 */
async function apiDelete(url) {
    const response = await apiFetch(url, { method: 'DELETE' });
    return response.json();
}

// ============================================
// Toast Notification System
// ============================================

/**
 * Toast notification container - created once on first use
 */
let toastContainer = null;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2';
        toastContainer.style.cssText = 'max-width: 400px;';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

/**
 * Show a toast notification
 * @param {string} message - The message to display
 * @param {string} type - 'success', 'error', 'info', or 'warning'
 * @param {number} duration - Auto-dismiss duration in ms (default 4000, 0 to disable)
 */
function showToast(message, type = 'info', duration = 4000) {
    const container = getToastContainer();

    const colors = {
        success: 'bg-green-600 border-green-500',
        error: 'bg-red-600 border-red-500',
        warning: 'bg-yellow-600 border-yellow-500',
        info: 'bg-blue-600 border-blue-500'
    };

    const icons = {
        success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>',
        error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>',
        warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
        info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
    };

    const toast = document.createElement('div');
    toast.className = `${colors[type] || colors.info} border-l-4 text-white px-4 py-3 rounded shadow-lg flex items-center gap-3 transform transition-all duration-300 translate-x-full opacity-0`;
    toast.innerHTML = `
        <span class="flex-shrink-0">${icons[type] || icons.info}</span>
        <span class="flex-grow text-sm">${message}</span>
        <button onclick="this.parentElement.remove()" class="flex-shrink-0 ml-2 hover:opacity-75">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        </button>
    `;

    container.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.remove('translate-x-full', 'opacity-0');
    });

    // Auto-dismiss
    if (duration > 0) {
        setTimeout(() => {
            toast.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    return toast;
}

// Convenience functions
function toastSuccess(message, duration) { return showToast(message, 'success', duration); }
function toastError(message, duration) { return showToast(message, 'error', duration); }
function toastWarning(message, duration) { return showToast(message, 'warning', duration); }
function toastInfo(message, duration) { return showToast(message, 'info', duration); }

// ============================================
// Loading Spinner Utilities
// ============================================

/**
 * Show a loading spinner inside a button
 * @param {HTMLElement} button - The button element
 * @param {string} loadingText - Optional text to show while loading
 * @returns {Function} - Call this function to restore the button
 */
function buttonLoading(button, loadingText = null) {
    const originalContent = button.innerHTML;
    const originalDisabled = button.disabled;

    button.disabled = true;
    button.innerHTML = `
        <svg class="animate-spin h-4 w-4 inline-block mr-2" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        ${loadingText || 'Loading...'}
    `;

    return function restore() {
        button.innerHTML = originalContent;
        button.disabled = originalDisabled;
    };
}

/**
 * Create a loading overlay for a container
 * @param {HTMLElement} container - The container to overlay
 * @returns {HTMLElement} - The overlay element (call .remove() to hide)
 */
function showLoadingOverlay(container) {
    const overlay = document.createElement('div');
    overlay.className = 'absolute inset-0 bg-gray-900 bg-opacity-50 flex items-center justify-center z-10';
    overlay.innerHTML = `
        <svg class="animate-spin h-8 w-8 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
    `;

    // Ensure container has relative positioning
    if (getComputedStyle(container).position === 'static') {
        container.style.position = 'relative';
    }

    container.appendChild(overlay);
    return overlay;
}
