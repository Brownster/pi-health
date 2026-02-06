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
