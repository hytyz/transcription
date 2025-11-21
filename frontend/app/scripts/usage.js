import { navigateTo, AUTH_URL } from "../router.js";

function setupUsagePage() {

    async function getUsageForCurrentUser() {
        try {
            const res = await fetch(`${AUTH_URL}/myusage/`, { credentials: "include" });
            if (res.status !== 200) { navigateTo("/login"); return; }
            return data = await res.json();
        } catch (e) {
            console.error("Failed to load usage", e);
        }
    }
    const usageTable = document.getElementById('usage-table');
    const msg = document.getElementById('msg');

    getUsageForCurrentUser().then((res) => {
        document.getElementById('total-api-calls').textContent = res.usage
        document.getElementById('user-email').textContent = res.email
    });

    fetch(`${AUTH_URL}/usage`, { credentials: 'include', })
        .then(async (res) => {
            if (res.status !== 200) {
                usageTable.style.display = 'none';
                console.log('user is not admin');
                return;
            }
            const data = await res.json();
            const tbody = usageTable.querySelector('tbody');
            if (!tbody) {
                if (msg) {
                    msg.textContent = 'failed to load usage: table body not found';
                }
                console.log('tbody element not found in usage table');
                return;
            }
            tbody.innerHTML = '';
            data.users.forEach((u) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${u.email}</td><td>${u.api_usage}</td>`;
                tbody.appendChild(tr);
            });

            if (msg) msg.textContent = '';
        })
        .catch((err) => {
            if (msg) {
                msg.textContent = 'failed to load usage: ' + err.message;
            }
            console.log(err.message);
        });
}
export { setupUsagePage };