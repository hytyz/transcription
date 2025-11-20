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


    // await new Promise(resolve => setTimeout(resolve, 5000)); // for testing loader

    try {
        const res = await fetch(`${AUTH_URL}/transcriptions/`, {
            credentials: "include"
        });
        const data = await res.json();

        allTranscriptions = data.transcriptions || [];
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

    // create element from template
    const temp = document.createElement("div");
    temp.innerHTML = templateHtml.trim();
    const card = temp.firstElementChild;


    const nameEl = card.querySelector("#file-card-name");
    const dateEl = card.querySelector(".file-card-date");
    const snippetEl = card.querySelector(".file-card-snippet");
    const expandBtn = card.querySelector(".file-card-expand");
    const bodyEl = card.querySelector(".file-card-body");

    // fill in metadata into cards
    nameEl.textContent = filename;
    dateEl.textContent = new Date(createdAt).toLocaleString();

    // get transcript text
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

    // collapse behavior 
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

    return card;
}

