var BASE_URL = "https://polina-gateway.fly.dev";
var AUTH_URL = `${BASE_URL}/auth`;

let allTranscriptions = [];
let nextIndex = 0;
const PAGE_SIZE = 5;

document.addEventListener("DOMContentLoaded", () => {
    checkAuth()
        .then(async (result) => {
            if (!result || result.error) {
                window.location.href = "/login";
                return;
            }
            // setupNavbar();
            loadTranscriptions();
        })
        .catch(() => window.location.href = "/login");
});

function setupNavbar() {
    const a1 = document.getElementById("navbar-anchor1");
    const a2 = document.getElementById("navbar-anchor2");

    if (!a1 || !a2) return;

    a1.textContent = "upload";
    a1.href = "/index.html";

    a2.textContent = "log out";
    a2.href = "/";
    a2.addEventListener("click", async (e) => {
        e.preventDefault();
        await fetch(`${AUTH_URL}/logout`, { method: "POST", credentials: "include" });
        window.location.href = "/";
    });
}

async function loadTranscriptions() {
    const container = document.getElementById("dashboard-files");
    if (!container) return;

    try {
        const res = await fetch(`${AUTH_URL}/transcriptions/`, {
            credentials: "include"
        });
        const data = await res.json();

        allTranscriptions = data.transcriptions || [];

        if (allTranscriptions.length === 0) {
            container.innerHTML = "";
            const anchor = document.createElement("a");
            anchor.textContent = "no transcriptions found. click here to upload.";
            anchor.href = "/index.html";
            anchor.style.textAlign = "center";
            container.appendChild(anchor);
            return;
        }

        nextIndex = 0;

        container.innerHTML = "";
        renderNextPage();
    } catch (e) {
        console.error("Failed to load metadata", e);
        container.innerHTML = `<p>Error loading transcriptions.</p>`;
    }
}

async function renderNextPage() {
    const container = document.getElementById("dashboard-files");

    const slice = allTranscriptions.slice(nextIndex, nextIndex + PAGE_SIZE);

    for (const item of slice) {
        const card = await createCardFromTemplate(item.jobid, item.created_at, item.filename);
        container.appendChild(card);
    }

    nextIndex += slice.length;

    const oldBtn = document.getElementById("load-more-btn");
    if (oldBtn) oldBtn.remove();

    if (nextIndex < allTranscriptions.length) {
        const btn = document.createElement("a");
        btn.id = "load-more-btn";
        btn.textContent = "Load more";
        btn.className = "load-more-btn";
        btn.addEventListener("click", renderNextPage);
        container.appendChild(btn);
    }
}

async function createCardFromTemplate(jobid, createdAt, filename) {
    const templateHtml = await fetch("file.html").then(r => r.text());

    const temp = document.createElement("div");
    temp.innerHTML = templateHtml.trim();
    const card = temp.firstElementChild;

    const nameEl = card.querySelector("#file-card-name");
    const dateEl = card.querySelector(".file-card-date");
    const snippetEl = card.querySelector(".file-card-snippet");
    const expandBtn = card.querySelector(".file-card-expand");
    const bodyEl = card.querySelector(".file-card-body");

    nameEl.textContent = filename;
    dateEl.textContent = new Date(createdAt * 1000).toLocaleString();

    let fullText = "";
    try {
        const res = await fetch(`${BASE_URL}/s3/transcriptions/${jobid}`);
        fullText = res.ok ? await res.text() : "(file missing)";
    } catch {
        fullText = "(error fetching file)";
    }

    const snippetPreview =
        fullText.length > 500 ? fullText.slice(0, 500) + "…" : fullText;

    snippetEl.textContent = snippetPreview;

    expandBtn.addEventListener("click", () => {
        const expanded = bodyEl.classList.toggle("expanded");

        if (expanded) {
            snippetEl.textContent = fullText;
            expandBtn.textContent = "collapse";
        } else {
            snippetEl.textContent = snippetPreview;
            expandBtn.textContent = "expand";
        }
    });

    card.dataset.fullText = fullText;
    card.dataset.downloadName = formatToYYYYMMDD(new Date(createdAt * 1000)) + "_" + filename;

    return card;
}

function formatToYYYYMMDD(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0'); // months are zero indexed because javascript is the best language ever
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}${month}${day}`;
}

function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);

    filename = filename.replace(/\./g, "");

    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.txt`;
    a.click();

    URL.revokeObjectURL(url);
}

document.addEventListener("click", (e) => {
    if (e.target.closest(".download-button")) {
        const card = e.target.closest(".file-card");
        if (!card) return;

        const text = card.dataset.fullText || "";
        const filename = card.dataset.downloadName || "transcript";

        downloadText(text, filename);
    }
});
