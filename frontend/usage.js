//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

async function getUsage() {
    const res = await fetch(`${AUTH_URL}/usage`);
    return res.json();
}

document.addEventListener('DOMContentLoaded', () => {
    const usageTable = document.getElementById('usage-table');
    const msg = document.getElementById('msg');

    getUsage()
        .then((data) => {
            if (data.error) {
                msg.textContent = `${data.error}`;
                console.log(err.message);
                return;
            }
            const tbody = usageTable.querySelector('tbody');
            tbody.innerHTML = '';
            data.users.forEach((u) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${u.email}</td><td>${u.api_usage}</td>`;
                tbody.appendChild(tr);
            });
            msg.textContent = '';
        })
        .catch((err) => { msg.textContent = 'failed to load usage: ' + err.message; console.log(err.message); })
});

