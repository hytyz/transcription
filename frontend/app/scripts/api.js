/**
 * fetches with csrf headers
 * includes x-requested-with header
 */
export async function apiFetch(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const stateChangingMethods = ['POST', 'PUT', 'DELETE', 'PATCH'];
    
    const headers = new Headers(options.headers || {});
    
    if (stateChangingMethods.includes(method)) {
        headers.set('X-Requested-With', 'XMLHttpRequest');
    }
    
    return fetch(url, {
        ...options,
        headers,
        credentials: 'include',
    });
}

export async function apiPost(url, body) {
    return apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

export async function apiPut(url, body) {
    return apiFetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

export async function apiDelete(url, body) {
    const options = {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) {
        options.body = JSON.stringify(body);
    }
    return apiFetch(url, options);
}
