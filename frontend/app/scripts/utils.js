// we have conditional rendering at home ahh
function applyAuthUI(authState) {
    const authedElements = document.querySelectorAll("[data-if-auth]")
    const guestElements = document.querySelectorAll("[data-if-guest]")
    if (!authState) {
        authedElements.forEach(el => el.style.display = "none");
        guestElements.forEach(el => el.style.display = "inline");
    } else {
        authedElements.forEach(el => el.style.display = "inline");
        guestElements.forEach(el => el.style.display = "none");
    }
}

function updateAnchorHref(path) {
    if (path == "/dashboard") {
        let anchors = document.querySelectorAll("[data-dashboard-anchor1]")
        let anchor = anchors[0]
        anchor.innerHTML = "upload"
        anchor.href = "/upload"
    }
}

export { updateAnchorHref, applyAuthUI }