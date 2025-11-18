
document.addEventListener("DOMContentLoaded", async () => {
    checkAuth()
        .then((res) => {
            const anchor1 = document.getElementById("navbar-anchor1");
            const anchor2 = document.getElementById("navbar-anchor2");

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
                    anchor1.textContent = "view files";
                    anchor1.href = "/dashboard";
                }
                if (anchor2) {
                    anchor2.textContent = "log out";
                    anchor2.href = "/";

                    anchor2.addEventListener("click", async (e) => {
                        e.preventDefault();
                        await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
                        window.location.href = "/";
                    });
                }
            }
        })
        .catch((error) => {
            console.log(error);
        });

    const root = document.getElementById("file-card-root");
    if (!root) return;

    const resp = await fetch("file.html");
    const cardHtml = await resp.text();
    root.innerHTML = cardHtml;

    const text = sessionStorage.getItem("transcriptionText") || "";
    const originalFilename = sessionStorage.getItem("transcriptionFilename") || "file";

    const baseFilename = originalFilename.replace(/^.*[\\/]/, "");

    const nameEl = root.querySelector(".file-card-name");
    if (nameEl) nameEl.textContent = baseFilename;

    const now = new Date();
    const yyyy = now.getFullYear();
    const monthName = now.toLocaleString("en-US", { month: "long" });
    const dd = String(now.getDate()).padStart(2, "0");
    const formattedDate = `${yyyy}, ${monthName} ${dd}`;
    const yyyymmdd = `${yyyy}${String(now.getMonth() + 1).padStart(2, "0")}${dd}`;

    const dateEl = root.querySelector(".file-card-date");
    if (dateEl) dateEl.textContent = formattedDate;

    const snippetEl = root.querySelector(".file-card-snippet");
    if (snippetEl) snippetEl.textContent = text;

    const downloadBtn = root.querySelector(".download-button");
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

    const expandButton = root.querySelector(".file-card-expand");
    const bodyElement = root.querySelector(".file-card-body");

    if (expandButton && bodyElement) {
        expandButton.addEventListener("click", () => {
            const expanded = bodyElement.classList.toggle("expanded");
            expandButton.textContent = expanded ? "collapse" : "expand";
        });
    }
});
