import { navigateTo, setAuthState, AUTH_URL } from "../router.js";

async function initAuth(authUrl = AUTH_URL) {
    const res = await fetch(`${authUrl}/me`, { credentials: "include" });
    return res.ok ? await res.json() : null;
}


async function loginUser(email, password) {
    const res = await fetch(`${AUTH_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
    });

    return res.json();
}


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

async function login() {
    document.getElementById('auth-form').addEventListener('submit', async (e) => {
        // console.log("inside get element by id login form")
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        const result = await loginUser(email, password);
        // console.log(result)
        if (result.ok) {
            authError.textContent = "";
            authError.style.display = "none"
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

async function createUser(email, password) {
    const res = await fetch(`${AUTH_URL}/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
    });
    return res.json();
}

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
        else console.log(result.error);
    });
}


export { initAuth, loginUser, logoutUser, login, register };


