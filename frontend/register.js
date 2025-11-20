//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

async function createUser(email, password) {
    const res = await fetch(`${AUTH_URL}/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
    });
    return res.json();
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('auth-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        const result = await createUser(email, password);
        if (result.ok) window.location.href = 'index.html';
        else console.log(result.error);
    });
});
