import { translate } from "./i18n.js";

/**
 * shows or hides dom elements based on the auth state
 * elements with data-if-auth are shown only when authenticated
 * elements with data-if-guest are shown only when unauthenticated
 * @param {boolean} authState
 */
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

/**
 * updates a dashboard anchor link depending on the current route
 * changes the links on navbar on the dashboard to point to the upload view
 * @param {string} path
 */
function updateAnchorHref(path) {
    if (path == "/dashboard") {
        let anchors = document.querySelectorAll("[data-dashboard-anchor1]")
        let anchor = anchors[0]
        anchor.innerHTML = translate("navbar.upload");
        anchor.href = "/upload"
    }
}

export { updateAnchorHref, applyAuthUI }