import { navigateTo, BASE_URL, AUTH_URL } from "../router.js";

function setupUsagePage() {

    async function getUsageForCurrentUser() {
        try {
            const res = await fetch(`${AUTH_URL}/myusage/`, { credentials: "include" });
            if (res.status !== 200) { navigateTo("/login"); return; }
            let data;
            return data = await res.json();
        } catch (e) {
            console.error("failed to load usage", e);
        }
    }
    const usageTable = document.getElementById('usage-table');
    const apiTable = document.getElementById('api-table');
    const msg = document.getElementById('msg');

    getUsageForCurrentUser().then((res) => {
       console.log(res)
       document.getElementById('total-api-calls').textContent = res.usage 
       if (res.usage > 20){ 
           document.getElementById('total-api-calls').textContent = `${res.usage} (warning usage is above 20)`
       }
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
                if (msg) { msg.textContent = translate("usage.error.tableBodyNotFound"); }
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
        }).then(() => {
            fetch(`${BASE_URL}/__usage`).then(async (res) => {
                if (res.status != 200) { console.log("failed") }
                let data = await res.json()
                const tbody = apiTable.querySelector('tbody');
                if (!tbody) {
                    if (msg) { msg.textContent = translate("usage.error.display"); }
                    console.log('tbody element not found in usage table');
                    return;
                }
                tbody.innerHTML = '';
                Object.entries(data).forEach(([key, val]) => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td>${key}</td><td>${val}</td>`;
                    tbody.appendChild(tr);
                });

            })
        }
        )
        .catch((err) => {
            if (msg) { msg.textContent = translate("usage.error.generalPrefix") + " " + err.message; }
            console.log(err.message);
        });
}
export { setupUsagePage };