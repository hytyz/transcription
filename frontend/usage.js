// const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;



async function getUsageForCurrentUser() {
    try {
        const res = await fetch(`${AUTH_URL}/myusage/`, {
            credentials: "include"
        });
        if (res.status !== 200) {window.location.href = "/login"; return;}

        return data = await res.json();
        
    } catch (e) {
        console.error("Failed to load usage", e);
    }
}

document.addEventListener('DOMContentLoaded', () => {

    const usageTable = document.getElementById('usage-table');
    // const usageSummary = document.getElementById('usage-summary');
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

            // data.users: [{ email: string, api_usage: number }]
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
});


function setupNavbar() {
    const anchor1 = document.getElementById("navbar-anchor1");
    const anchor2 = document.getElementById("navbar-anchor2");
    anchor1.textContent = "view files";
    anchor1.href = "/dashboard";
    anchor2.textContent = "log out";
    anchor2.href = "/";
    anchor2.addEventListener("click", async (e) => {
        e.preventDefault();
        await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
        window.location.href = "/";
    });
}