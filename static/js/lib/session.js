export function saveClientSession(username) {
    sessionStorage.setItem('loggedIn', 'true');
    sessionStorage.setItem('username', username);
}

export function clearClientSession() {
    sessionStorage.removeItem('loggedIn');
    sessionStorage.removeItem('username');
}
