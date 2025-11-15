document.addEventListener("DOMContentLoaded", () => {
    checkAuth().then((res) => {
        const anchor1 = document.getElementById("navbar-anchor1");
        const anchor2 = document.getElementById("navbar-anchor2");
        // console.log(res);
        if (!res.payload) {
            anchor1.textContent = "login";
            anchor1.href = "/login";
            anchor2.textContent = "register";
            anchor2.href = "/register";
        } else {
            anchor1.textContent = "view files"; // TODO
            anchor1.href = "#";
            anchor2.textContent = "log out"; // TODO
            anchor2.href = "/";

            anchor2.addEventListener("click", async (e) => {
                e.preventDefault();
                await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
                window.location.href = "/";
            });
        }
    })
        .catch((error) => { console.log(error); });

    const textArea = document.getElementById("transcription-text");
    const filenameEl = document.getElementById("transcript-filename");
    const dateEl = document.getElementById("transcript-date");
    const downloadBtn = document.getElementById("download-transcript");

    const text = sessionStorage.getItem("transcriptionText") || "";
    const originalFilename = sessionStorage.getItem("transcriptionFilename") || "file";

    textArea.value = text;

    const baseFilename = originalFilename.replace(/^.*[\\/]/, "");
    filenameEl.textContent = baseFilename;

    const now = new Date();
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    const yyyymmdd = `${yyyy}${mm}${dd}`;
    dateEl.textContent = yyyymmdd;

    downloadBtn.addEventListener("click", () => {
        const baseNoExt = baseFilename.replace(/\.[^.]+$/, "");
        const downloadName = `${yyyymmdd}-${baseNoExt}.txt`;

        const blob = new Blob([textArea.value], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = downloadName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
});