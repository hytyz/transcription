function loadNavbar() {
    const root = document.getElementById("navbar");
    if (!root) return Promise.resolve();
    return fetch("navbar.html")
        .then(r => r.text())
        .then(html => { root.innerHTML = html; }).then(() => {
            const anchor1 = document.getElementById("navbar-anchor1");
            const anchor2 = document.getElementById("navbar-anchor2")
            if (!anchor1 || !anchor2) return
            anchor1.textContent = "dashboard"
            anchor1.href = "/dashboard"
            anchor2.textContent = "log out"
            anchor2.href = "/"
            anchor2.addEventListener("click", async (e) => {
                e.preventDefault();
                await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
                window.location.href = "/";
            })
            });
}


loadNavbar();