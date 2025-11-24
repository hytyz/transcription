import { navigateTo, setAuthState, AUTH_URL } from "../router.js";

/**
 * initializes auth state by calling the /me endpoint
 * returns the parsed json payload if the session is valid, null otherwise
 * @param {string} [authUrl=AUTH_URL]
 * @returns {Promise<object|null>}
 */
async function initAuth(authUrl = AUTH_URL) {
    const res = await fetch(`${authUrl}/me`, { credentials: "include" });
    return res.ok ? await res.json() : null;
}

/**
 * sends credentials to the auth service and returns the parsed response
 * the server sets an http-only cookie when credentials are valid
 * @param {string} email
 * @param {string} password
 * @returns {Promise<object>}
 */
async function loginUser(email, password) {
    const res = await fetch(`${AUTH_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
    });

    return res.json();
}

/**
 * logs out the current user and resets client-side auth state
 * navigates to the home page after clearing the session cookie on the server
 * @returns {Promise<void>}
 */
async function logoutUser() {
    const res = await fetch(`${AUTH_URL}/logout`, {
        method: 'POST',
        credentials: 'include',
    });

    if (res.ok) {
        setAuthState(false)
        navigateTo('/');
        // window.location.reload();
    }
}

/**
 * attaches a submit handler to the login form
 * prevents default form submission; calls loginUser; 
 * updates ui and navigation on success; displays an inline error on failure
 * @returns {Promise<void>}
 */
async function login() {
    document.getElementById('auth-form').addEventListener('submit', async (e) => {
        // console.log("inside get element by id login form")
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        const result = await loginUser(email, password);
        // console.log(result)
        if (result.ok) {
            setAuthState(true)
            navigateTo('/dashboard');
        }
        else {
            console.log(result.error);
            const authError = document.getElementById('auth-error');
            authError.textContent = result.error;
            authError.style.display = "block"
        }
    });
}

/**
 * creates a new user account and returns the parsed response
 * the server sets an http-only cookie on success
 * @param {string} email
 * @param {string} password
 * @returns {Promise<object>}
 */
async function createUser(email, password) {
    const res = await fetch(`${AUTH_URL}/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
    });
    return res.json();
}

/**
 * attaches a submit handler to the registration form
 * prevents default form submission; calls createUser; 
 * sets auth state and navigates on success; displays an inline error on failure
 * @returns {Promise<void>}
 */
async function register() {
    document.getElementById('auth-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        const result = await createUser(email, password);

        if (result.ok) {
            setAuthState(true);
            navigateTo('/');
        }
        else {
            console.log(result.error);
            const authError = document.getElementById('auth-error');
            authError.textContent = result.error;
            authError.style.display = "block"
        }
    });
}

export { initAuth, loginUser, logoutUser, login, register };
