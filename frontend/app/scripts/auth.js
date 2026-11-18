import { navigateTo, setAuthState, AUTH_URL } from "../router.js";
import { apiPost } from "./api.js";

async function initAuth(authUrl = AUTH_URL) {
    const res = await fetch(`${authUrl}/me`, { credentials: "include" });
    return res.ok ? await res.json() : null;
}

/**
 * sends credentials to the auth service and returns the parsed response
 * the server sets an http-only cookie when credentials are valid
 */
async function loginUser(email, password) {
    const res = await apiPost(`${AUTH_URL}/login`, { email, password });
    return res.json();
}

async function logoutUser() {
    const res = await apiPost(`${AUTH_URL}/logout`, {});

    if (res.ok) {
        setAuthState(false)
        navigateTo('/');
        // window.location.reload();
    }
}

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
            if (authError) {
                authError.textContent = result.error;
                authError.style.display = "block";
            }
        }
    });
}

async function createUser(email, password) {
    const res = await apiPost(`${AUTH_URL}/create`, { email, password });
    return res.json();
}

function validatePassword(password) {
    if (password.length < 8) {
        return { valid: false, reason: 'password must be at least 8 characters' };
    }
    return { valid: true };
}

async function register() {
    document.getElementById('auth-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        const authError = document.getElementById('auth-error');

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            if (authError) {
                authError.textContent = 'invalid email format';
                authError.style.display = 'block';
            }
            return;
        }

        const passwordCheck = validatePassword(password);
        if (!passwordCheck.valid) {
            if (authError) {
                authError.textContent = passwordCheck.reason;
                authError.style.display = 'block';
            }
            return;
        }

        const result = await createUser(email, password);

        if (result.ok) {
            setAuthState(true);
            navigateTo('/');
        }
        else {
            console.log(result.error);
            if (authError) {
                authError.textContent = result.error;
                authError.style.display = "block";
            }
        }
    });
}

export { initAuth, loginUser, logoutUser, login, register };
