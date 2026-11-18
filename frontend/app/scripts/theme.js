const STORAGE_KEY = "theme";

function preferredTheme() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === "light" || stored === "dark") return stored;
    } catch {}
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
}

function setupTheme() {
    const theme = preferredTheme();
    applyTheme(theme);

    const toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    toggle.checked = theme === "dark";
    toggle.addEventListener("change", () => {
        const next = toggle.checked ? "dark" : "light";
        applyTheme(next);
        try { localStorage.setItem(STORAGE_KEY, next); } catch {}
    });
}

export { setupTheme };
