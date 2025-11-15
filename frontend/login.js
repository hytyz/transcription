//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

async function loginUser(email, password) {
    console.log(AUTH_URL);
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
    // console.log("inside event listener");
    document.getElementById('auth-form').addEventListener('submit', async (e) => {
        console.log("inside get element by id login form")
        e.preventDefault();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        // msg.textContent = 'logging in';
        const result = await loginUser(email, password);
        if (result.ok) window.location.href = 'dashboard.html';
        else console.log(result.error);
    });
});

