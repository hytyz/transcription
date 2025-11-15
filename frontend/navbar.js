function loadNavbar() {
    const root = document.getElementById("navbar");
    if (!root) return Promise.resolve();
    return fetch("navbar.html")
        .then(r => r.text())
        .then(html => { root.innerHTML = html; });
}
loadNavbar();