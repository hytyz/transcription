import { BASE_URL, AUTH_URL } from "../router.js";

async function createCardFromTemplate(jobid, createdAt, filename) {
    const templateHtml = await fetch("/templates/file.html").then(r => r.text());

    const temp = document.createElement("div");
    temp.innerHTML = templateHtml.trim();
    const card = temp.firstElementChild;
    card.dataset.jobid = jobid;

    const nameEl = card.querySelector("#file-card-name");
    const dateEl = card.querySelector(".file-card-date");
    const snippetEl = card.querySelector(".file-card-snippet");
    const expandBtn = card.querySelector(".file-card-expand");
    const bodyEl = card.querySelector(".file-card-body");

    nameEl.textContent = filename;
    dateEl.textContent = new Date(createdAt * 1000).toLocaleString('en-US', { year: 'numeric', month: 'long', day: 'numeric', hourCycle: 'h23', hour: '2-digit', minute: '2-digit' }).replace(' at ', ' ');

    let fullText = "";

    const cacheKey = `transcription_${jobid}`;
    const cached = sessionStorage.getItem(cacheKey);

    if (cached) {
        fullText = cached;
    } else {
        try {
            const res = await fetch(`${BASE_URL}/s3/transcriptions/${jobid}`);
            fullText = res.ok ? await res.text() : "(file missing)";
            sessionStorage.setItem(cacheKey, fullText);
        } catch { fullText = "(error fetching file)"; }
    }

    const snippetPreview = fullText.length > 500 ? fullText.slice(0, 500) + "…" : fullText;

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
    card.dataset.jobid = jobid;
    card.dataset.fullText = fullText;
    let strippedFilename;

    if (filename) {
        strippedFilename = filename.slice(0, filename.lastIndexOf("."));
    } else {
        strippedFilename = ""
    }
    card.dataset.downloadName = formatToYYYYMMDD(new Date(createdAt * 1000)) + "_" + strippedFilename;

    return card;
}

function formatToYYYYMMDD(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0'); // months are zero indexed because javascript is the best language ever
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}${month}${day}`;
}

function downloadText(text, filename) {
    // point of the blob is to prevent a repeated fetch to our s3 service when downloading
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);

    filename = filename.replace(/\./g, "");

    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.txt`;
    a.click();

    URL.revokeObjectURL(url);
}

async function deleteTranscription(jobid, card) {
    console.log("Deleting job:", jobid);

    // 1. delete from DB
    let dbRes;
    try {
        dbRes = await fetch(`${AUTH_URL}/transcriptions/delete`, {
            method: "DELETE",
            credentials: "include",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ jobid }),
        });

        if (!dbRes.ok) {
            const err = await dbRes.json().catch(() => ({}));
            alert("DB deletion failed: " + (err.error || dbRes.status));
            return;
        }
    } catch (err) {
        console.error("DB delete error:", err);
        alert("Network error when deleting from DB");
        return;
    }
    // 2. delete from S3
    let s3Res;
    try {
        s3Res = await fetch(`${BASE_URL}/s3/transcriptions/${jobid}`, {
            method: "DELETE",
            credentials: "include",
        });

        if (!s3Res.ok) {
            const err = await s3Res.json().catch(() => ({}));
            alert("S3 deletion failed: " + (err.message || s3Res.status));
            return;
        }
    } catch (err) {
        console.error("S3 delete error:", err);
        alert("Network error when deleting from S3");
        return;
    }
    // 3. If both succeeded we remove card
    if (card) {
        card.remove();
    }
    console.log(`Deleted transcription ${jobid} from DB + S3`);
}

async function openModifyModal(jobid, currentText) {
    // console.log("opening Modal")
    // browsers love caching stuff
    document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
    // extract unique speakers from lines: [hh:mm:ss] SPEAKER:
    const lineRegex = /^\[\d{2}:\d{2}:\d{2}\]\s+([^:]+):/gm;
    const speakerSet = new Set();
    let match;

    while ((match = lineRegex.exec(currentText)) !== null) {
        speakerSet.add(match[1].trim());
    }

    const speakers = [...speakerSet];

    //load the modal template
    const modalHtml = await fetch("/templates/modal.html").then(r => r.text());

    //insert modal into DOM
    const wrapper = document.createElement("div");
    wrapper.innerHTML = modalHtml.trim();
    const modal = wrapper.firstElementChild;
    document.body.appendChild(modal);

    const tableBody = modal.querySelector("#speakers-modal tbody");
    const applyBtn = modal.querySelector("#relabel-speakers-btn");

    // populate rows old label | new label input
    tableBody.innerHTML = "";
    speakers.forEach(sp => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${sp}</td>
            <td><input type="text" placeholder="ytyz" data-old="${sp}" /></td>
        `;
        tableBody.appendChild(tr);
    });

    // when user clicks apply, process renaming
    applyBtn.addEventListener("click", async () => {
        // collect replacements
        const inputs = tableBody.querySelectorAll("input[data-old]");
        const replacements = {};

        inputs.forEach(inp => {
            const oldLabel = inp.dataset.old;
            const newLabel = inp.value.trim();

            if (newLabel) {
                if (!/^[A-Za-z0-9 ]+$/.test(newLabel)) {
                    alert(`Invalid speaker name: "${newLabel}". Letters, numbers, spaces only.`);
                    document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
                    return;
                }
                replacements[oldLabel] = newLabel;
            }
        });


        // if nothing provided, do nothing
        if (Object.keys(replacements).length === 0) {
            alert("Please enter at least one new label.");
            document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
            return;
        }

        // build updated transcript
        let updatedText = currentText;
        for (const [oldSp, newSp] of Object.entries(replacements)) {
            const re = new RegExp(`\\b${oldSp}\\b`, "g");
            updatedText = updatedText.replace(re, newSp);
        }

        // PUT updated file to S3 microservice 
        try {
            const form = new FormData();
            form.append("jobid", jobid);
            form.append("file", new Blob([updatedText], { type: "text/plain" }), `${jobid}.txt`);

            const resp = await fetch(`${BASE_URL}/s3/transcriptions`, {
                method: "PUT",
                body: form
            });

            if (!resp.ok) {
                alert("Failed to update file");
                return;
            }
        } catch (err) {
            console.error(err);
            alert("Error updating file.");
            return;
        }


        // 8. write to sessionStorage cache
        sessionStorage.setItem(`transcription_${jobid}`, updatedText);

        // 9. update card.dataset.fullText live
        const card = document.querySelector(`.file-card[data-jobid="${jobid}"]`);
        if (card) {
            card.dataset.fullText = updatedText;

            // update snippet preview if card is expanded or collapsed
            const snippetEl = card.querySelector(".file-card-snippet");
            const expandBtn = card.querySelector(".file-card-expand");
            const bodyEl = card.querySelector(".file-card-body");

            if (snippetEl) {
                const snippetPreview = updatedText.length > 500
                    ? updatedText.slice(0, 500) + "…"
                    : updatedText;

                if (bodyEl && bodyEl.classList.contains("expanded")) {
                    // currently expanded ⇒ show full text
                    snippetEl.textContent = updatedText;
                    if (expandBtn) expandBtn.textContent = "collapse";
                } else {
                    // collapsed ⇒ show snippet only
                    snippetEl.textContent = snippetPreview;
                    if (expandBtn) expandBtn.textContent = "expand";
                }
            }
        }


        window.location.reload();

        // close modal
        modal.remove();
        document.querySelectorAll(".modal-overlay").forEach(m => m.remove());


    });

    // Optional: close modal on background click
    const overlay = document.querySelector(".modal-overlay");

    modal.addEventListener("click", (e) => {
        if (e.target.classList.contains("modal-overlay") || e.target.classList.contains("cancel-btn")) {
            e.preventDefault();
            // modal.remove()
            // overlay.remove();
            document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
        }

    }, { once: true });

    
}


function activateDownloadButtons() {
    document.addEventListener("click", (e) => {
        // single event listener is a clean pattern imo
        const downloadBtn = e.target.closest(".download-button");
        const deleteBtn = e.target.closest(".delete-button");
        const modifyBtn = e.target.closest(".edit-button");

        // download button
        if (downloadBtn) {
            const card = downloadBtn.closest(".file-card");
            if (!card) return;

            const text = card.dataset.fullText || "";
            const filename = card.dataset.downloadName || "transcript";
            downloadText(text, filename);
            return;
        }
        // delete btn
        if (deleteBtn) {
            const card = deleteBtn.closest(".file-card");
            if (!card) return;

            const jobid = card.dataset.jobid;
            deleteTranscription(jobid, card);
            return;
        }
        // update speaker names 
        if (modifyBtn) {
            const card = modifyBtn.closest(".file-card");
            if (!card) return;

            const jobid = card.dataset.jobid;
            const currentText = card.dataset.fullText;
            openModifyModal(jobid, currentText);
            return;
        }
    });
}

function interceptSelectAll() {

    let lastClickInsideCard = null;

    // last click location
    document.addEventListener("mousedown", (e) => {
        lastClickInsideCard = e.target.closest(".file-card-body") || null;
        // console.log(e.target.closest(".file-card-body"))
    });

    // console.log("select all interception")
    document.addEventListener("keydown", (e) => {
        const isSelectAll = (e.key.toLowerCase() === "a" && (e.ctrlKey || e.metaKey));
        if (!isSelectAll) return;

        if (!lastClickInsideCard) return; // click was not on a card

        const selection = window.getSelection();

        // prefer expanded text if expanded fallback to snippet
        const cardTextEl =
            lastClickInsideCard.querySelector(".file-card-body.expanded")
            || lastClickInsideCard.querySelector(".file-card-snippet");

        if (!cardTextEl) return;

        e.preventDefault();
        e.stopPropagation();

        const range = document.createRange();
        range.selectNodeContents(cardTextEl);

        selection.removeAllRanges();
        selection.addRange(range);
    });

}

function dashboardScript() {

    let allTranscriptions = [];
    let nextIndex = 0;
    const PAGE_SIZE = 5;

    const sentinel = document.getElementById("scroll-sentinel");

    loadTranscriptions();

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

            await renderNextPage();

            setupInfiniteScroll();
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
    }

    function setupInfiniteScroll() {
        const observer = new IntersectionObserver(async (entries) => {
            const bottom = entries[0].isIntersecting;

            if (bottom && nextIndex < allTranscriptions.length) {
                await renderNextPage();
            }
        }, {
            root: null,
            rootMargin: "200px", // load before hitting bottom of page
            threshold: 0
        });

        observer.observe(sentinel);
    }

    activateDownloadButtons();
    interceptSelectAll();
}

export { dashboardScript, downloadText, formatToYYYYMMDD, createCardFromTemplate, activateDownloadButtons };