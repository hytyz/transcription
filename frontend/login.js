async function loginUser(email, password) {
    const res = await fetch(`${AUTH_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
    });
    return res.json();
}

document.addEventListener('DOMContentLoaded', () => {
    // const msg = document.getElementById('msg');

    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        // msg.textContent = 'logging in';
        const result = await loginUser(email, password);
        if (result.ok) window.location.href = 'dashboard.html';
        else console.log(result.error);
    });
});

