/**
 * fetches with csrf headers
 * includes x-requested-with header
 * 
 * @param {string} url url to fetch
 * @param {RequestInit} [options={}] fetch options
 * @returns {Promise<Response>}
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

/**
 * makes a json POST request with csrf
 * @param {string} url 
 * @param {object} body 
 * @returns {Promise<Response>}
 */
export async function apiPost(url, body) {
    return apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

/**
 * makes a json PUT request with csrf
 * @param {string} url 
 * @param {object} body 
 * @returns {Promise<Response>}
 */
export async function apiPut(url, body) {
    return apiFetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

/**
 * makes a json DELETE request with csrf
 * @param {string} url 
 * @param {object} [body] 
 * @returns {Promise<Response>}
 */
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
