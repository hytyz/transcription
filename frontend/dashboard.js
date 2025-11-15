//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

document.addEventListener('DOMContentLoaded', () => {
    checkAuth()
        .then((result) => {
            if (!result || result.error) {
                window.location.href = '/login';
                return;
            }

            const anchor1 = document.getElementById("navbar-anchor1");
            const anchor2 = document.getElementById("navbar-anchor2");
            if (anchor1 && anchor2) {
                anchor1.textContent = "upload";
                anchor1.href = "/index.html";
                anchor2.textContent = "log out";
                anchor2.href = "/";
                anchor2.addEventListener("click", async (e) => {
                    e.preventDefault();
                    await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
                    window.location.href = "/";
                });
            }

            loadPlaceholderFiles();
        })
        .catch(() => { window.location.href = '/login'; });

    const root = document.getElementById("dashboard-files");
    console.log(root);
    if (!root) return;

    const expandButton = root.querySelector(".file-card-expand"); // this is broken
    const bodyElement = root.querySelector(".file-card-body");
    console.log(expandButton); // both return null
    console.log(bodyElement);

    if (expandButton && bodyElement) {
        expandButton.addEventListener("click", () => {
            const expanded = bodyElement.classList.toggle("expanded");
            expandButton.textContent = expanded ? "collapse" : "expand";
        });
    }
});

function loadPlaceholderFiles() {
    const container = document.getElementById("dashboard-files");
    if (!container) return;

    fetch("file.html")
        .then((r) => r.text())
        .then((html) => {
            let combined = "";
            for (let i = 0; i < 3; i++) combined += html;
            container.innerHTML = combined;
        })
        .catch((err) => { console.error("failed to load file cards", err); });
}