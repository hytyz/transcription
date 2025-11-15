//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

document.addEventListener('DOMContentLoaded', () => {
    checkAuth()
        .then((result) => {
            if (!result || result.error) {
                window.location.href = 'login.html';
                return;
            }
            const email = result.payload.email;
            document.getElementById('userEmail').textContent = email;
        })
        .catch(() => { window.location.href = 'login.html'; });
});

