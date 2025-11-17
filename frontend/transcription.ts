import { checkAuth } from './script.js'


document.addEventListener("DOMContentLoaded", async () => {
    checkAuth().then((res) => {
        const anchor1 = document.getElementById("navbar-anchor1") as HTMLAnchorElement | null;
        const anchor2 = document.getElementById("navbar-anchor2") as HTMLAnchorElement | null;
        // console.log(res);
        if (!res.payload) {
            if (anchor1) {
                anchor1.textContent = "login";
                anchor1.href = "/login";
            }
            if (anchor2) {
                anchor2.textContent = "register";
                anchor2.href = "/register";
            }
        } else {
            if (anchor1) {
                anchor1.textContent = "view files"; // TODO
                anchor1.href = "/dashboard";
            }
            if (anchor2) {
                anchor2.textContent = "log out"; // TODO
                anchor2.href = "/";

                anchor2.addEventListener("click", async (e) => {
                    e.preventDefault();
                    await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
                    window.location.href = "/";
                });
            }
        }
    })
        .catch((error) => { console.log(error); });
    const root = document.getElementById("file-card-root");
    if (!root) return;
    const rootEl = root as HTMLElement;

    const resp = await fetch("file.html");
    const cardHtml = await resp.text();
    rootEl.innerHTML = cardHtml;

    const text = sessionStorage.getItem("transcriptionText") || "";
    const originalFilename = sessionStorage.getItem("transcriptionFilename") || "file";
    const baseFilename = originalFilename.replace(/^.*[\\/]/, "");
    const nameEl = rootEl.querySelector(".file-card-name") as HTMLElement | null;
    if (nameEl) nameEl.textContent = baseFilename;

    const now = new Date();
    const yyyy = now.getFullYear();
    const monthName = now.toLocaleString("en-US", { month: "long" });
    const dd = String(now.getDate()).padStart(2, "0");
    const formattedDate = `${yyyy}, ${monthName} ${dd}`;
    const yyyymmdd = `${yyyy}${String(now.getMonth() + 1).padStart(2, "0")}${dd}`;

    const dateEl = rootEl.querySelector(".file-card-date") as HTMLElement | null;
    if (dateEl) dateEl.textContent = formattedDate;
    const snippetEl = rootEl.querySelector(".file-card-snippet") as HTMLElement | null;
    if (snippetEl) snippetEl.textContent = text;

    const downloadBtn = rootEl.querySelector(".download-button") as HTMLElement | null;
    if (downloadBtn) {
        downloadBtn.addEventListener("click", () => {
            const baseNoExt = baseFilename.replace(/\.[^.]+$/, "");
            const downloadName = `${yyyymmdd}-${baseNoExt}.txt`;

            const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = downloadName;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }
    
    const expandButton = rootEl.querySelector(".file-card-expand") as HTMLElement | null;
    const bodyElement = rootEl.querySelector(".file-card-body") as HTMLElement | null;

    if (expandButton && bodyElement) {
        expandButton.addEventListener("click", () => {
            const expanded = bodyElement.classList.toggle("expanded");
            expandButton.textContent = expanded ? "collapse" : "expand";
        });
    }
});