//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

async function getUsage() {
    const res = await fetch(`${AUTH_URL}/usage`);
    return res.json();
}

document.addEventListener('DOMContentLoaded', () => {
    const usageTable: HTMLElement | null = document.getElementById('usage-table');
    const msg: HTMLElement | null = document.getElementById('msg');

    getUsage()
        .then((data) => {
            if (data.error) {
                if (msg) { msg.textContent = `${data.error}`; }
                console.log(data.error);
                return;
            }
            if (!usageTable) {
                if (msg) { msg.textContent = 'failed to load usage: missing usage table element'; }
                console.log('usage table element not found');
                return;
            }
            const tbody = usageTable.querySelector('tbody');
            if (!tbody) {
                if (msg) { msg.textContent = 'failed to load usage: table body not found'; }
                console.log('tbody element not found in usage table');
                return;
            }
            tbody.innerHTML = '';
            interface User {
                email: string;
                api_usage: number;
            }

            interface UsageResponse {
                users: User[];
                error?: string;
            }

            const usageData = data as UsageResponse;
            usageData.users.forEach((u: User) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${u.email}</td><td>${u.api_usage}</td>`;
                tbody.appendChild(tr);
            });
            if (msg) {
                msg.textContent = '';
            }
        })
        .catch((err) => { if (msg) { msg.textContent = 'failed to load usage: ' + err.message; } console.log(err.message); })
});

