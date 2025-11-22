import { initAuth, login, logoutUser, register } from "./scripts/auth.js";
import { dashboardScript } from "./scripts/dashboard.js";
import { setupUsagePage } from "./scripts/usage.js";
import { setupTranscribe } from "./scripts/transcribe.js";
import { setupTranscription } from "./scripts/transcription.js";
import { updateAnchorHref, applyAuthUI } from "./scripts/utils.js";
import { loadMessages, applyTranslations, translate } from "./scripts/i18n.js";

const viewCache = {}

// global auth state
let authState = false;

var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

// mom says we have reactjs at home

const routes = [
  { path: "/", view: "views/home.html", showNav: false, onload: setupTranscribe },
  { path: "/login", view: "views/login.html", onload: login },
  { path: "/register", view: "views/register.html", onload: register },
  { path: "/dashboard", view: "views/dashboard.html", requiresAuth: true, onload: dashboardScript },
  { path: "/usage", view: "views/usage.html", requiresAuth: true, onload: setupUsagePage },
  { path: "/transcription", view: "views/transcription.html", requiresAuth: false, onload: setupTranscription }
];

function matchRoute(path) {
  return routes.find(r => r.path === path) || routes[0];
}

export async function navigateTo(url) {
  history.pushState(null, null, url);
  await router();
}

async function router() {
  const match = matchRoute(location.pathname);

  // we have middleware at home
  if (match.requiresAuth && !authState) {
    return navigateTo("/login");
  }

  const fileToLoad = match.path === "/" ? "views/home.html" : match.view;

  let html;

  // we have a cache for the html files
  if (viewCache[fileToLoad]) {
    html = viewCache[fileToLoad];
  } else {
    html = await fetch(fileToLoad).then(r => r.text());
    viewCache[fileToLoad] = html;
  }
  document.getElementById("app").innerHTML = html;

  let navbar = document.getElementById("navbar")

  // hide navbar on some pages
  if (match.showNav === false) { navbar.style.display = "none"; }
  else { navbar.style.display = "flex"; }

  // update UI based on auth state
  applyAuthUI(authState);
  updateAnchorHref(match.path);

  applyTranslations(document);
  document.title = translate("app.title", document.title);

  if (match.onload) match.onload();
}

// intercept link clicks
document.addEventListener("click", (e) => {
  if (e.target.matches("[data-prevent-navigate]")) {
    e.preventDefault();
    return;
  }

  if (e.target.matches("[data-link]")) {
    e.preventDefault();
    console.log(e.target.href)
    navigateTo(e.target.href);
  }
  if (e.target.matches("[data-logout]")) {
    e.preventDefault();
    logoutUser();
  }
});

window.addEventListener("popstate", router);

// first load
await loadMessages("en");
authState = await initAuth(AUTH_URL);
router();

function setAuthState(state) { authState = state }

export { setAuthState, BASE_URL, AUTH_URL }