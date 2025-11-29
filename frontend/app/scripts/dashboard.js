import { BASE_URL, AUTH_URL } from "../router.js";
import { translate, applyTranslations } from "./i18n.js";
import { apiDelete, apiPut, apiFetch } from "./api.js";

/**
 * builds a file card element from a template and inits its expand behavior
 * fetches and caches the transcription text in sessionStorage to avoid repeated network calls
 * sets dataset attributes for later actions like download and edit
 * @param {string} jobid
 * @param {number} createdAt unix seconds
 * @param {string} filename
 * @returns {Promise<HTMLElement>}
 */
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
    expandBtn.textContent = translate("file.expand");
    let fullText = "";

    const cacheKey = `transcription_${jobid}`;
    const cached = sessionStorage.getItem(cacheKey);

    if (cached) {
        fullText = cached;
    } else {
        try {
            const res = await fetch(`${BASE_URL}/s3/transcriptions/${jobid}`);
            fullText = res.ok ? await res.text() : translate("dashboard.fileMissing");
            sessionStorage.setItem(cacheKey, fullText);
        } catch { fullText = translate("dashboard.errorFetchingFile"); }
    }

    const snippetPreview = fullText.length > 500 ? fullText.slice(0, 500) + "…" : fullText;

    snippetEl.textContent = snippetPreview;

    expandBtn.addEventListener("click", () => {
        const expanded = bodyEl.classList.toggle("expanded");

        if (expanded) {
            snippetEl.textContent = fullText;
            expandBtn.textContent = translate("file.collapse");
        } else {
            snippetEl.textContent = snippetPreview;
            expandBtn.textContent = translate("file.expand");
        }
    });
    card.dataset.fullText = fullText;
    card.dataset.filename = filename || "";
    card.dataset.createdAt = createdAt;
    let strippedFilename;

    if (filename) {
        strippedFilename = filename.slice(0, filename.lastIndexOf("."));
    } else {
        strippedFilename = ""
    }
    card.dataset.downloadName = formatToYYYYMMDD(new Date(createdAt * 1000)) + "_" + strippedFilename;

    return card;
}

/**
 * formats a date to yyyymmdd
 * @param {Date} date
 * @returns {string}
 */
function formatToYYYYMMDD(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0'); // months are zero indexed
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}${month}${day}`;
}

/**
 * starts a client-side download for provided text as a .txt file
 * uses a blob url
 * @param {string} text
 * @param {string} filename without extension
 */
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

/**
 * deletes a transcription from the database first, then from object storage
 * displays localized alerts on failures; removes the card from the dom on success
 * @param {string} jobid
 * @param {HTMLElement} [card]
 * @returns {Promise<void>}
 */
async function deleteTranscription(jobid, card) {
    console.log("deleting job:", jobid);

    let dbRes;
    try {
        dbRes = await apiDelete(`${AUTH_URL}/transcriptions/delete`, { jobid });

        if (!dbRes.ok) {
            const err = await dbRes.json().catch(() => ({}));
            alert(translate("dashboard.delete.dbFailedPrefix") + " " + (err.error || dbRes.status));
            return;
        }
    } catch (err) {
        console.error("DB delete error:", err);
        alert(translate("dashboard.delete.dbNetworkError"));
        return;
    }
    let s3Res;
    try {
        s3Res = await apiFetch(`${BASE_URL}/s3/transcriptions/${jobid}`, {
            method: "DELETE",
        });

        if (!s3Res.ok) {
            const err = await s3Res.json().catch(() => ({}));
            alert(translate("dashboard.delete.s3FailedPrefix") + " " + (err.message || s3Res.status));
            return;
        }
    } catch (err) {
        console.error("s3 delete error:", err);
        alert(translate("dashboard.delete.s3NetworkError"));
        return;
    }
    if (card) {
        card.remove();
    }
    console.log(`deleted transcription ${jobid} from db and s3`);

    if (window.location.pathname === "/transcription") {
        window.location.href = "/";
    }
}

/**
 * opens a modal that lets the user relabel speakers in a transcript
 * extracts unique speaker labels from lines that match [hh:mm:ss] NAME:
 * renders an input row for each label; validates replacements
 * applies global whole-word replacements; uploads the updated text; updates cache and the ui card
 * also includes a rename file option
 * @param {string} jobid
 * @param {string} currentText
 * @param {string} currentFilename
 * @param {number} createdAt unix timestamp in seconds
 * @returns {Promise<void>}
 */
async function openModifyModal(jobid, currentText, currentFilename, createdAt) {
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

    const modalHtml = await fetch("/templates/modal.html").then(r => r.text());

    const wrapper = document.createElement("div");
    wrapper.innerHTML = modalHtml.trim();
    const modal = wrapper.firstElementChild;
    document.body.appendChild(modal);

    applyTranslations(modal);

    const tableBody = modal.querySelector("#speakers-modal tbody");
    const applyBtn = modal.querySelector("#relabel-speakers-btn");

    const renameInput = modal.querySelector("#rename-input");

    let strippedFilename = currentFilename || "";
    if (strippedFilename.includes(".")) {
        strippedFilename = strippedFilename.slice(0, strippedFilename.lastIndexOf("."));
    }
    renameInput.value = strippedFilename;
    renameInput.placeholder = translate("modal.renamePlaceholder", "new file name");

    tableBody.innerHTML = "";
    speakers.forEach(sp => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${sp}</td>
            <td><input type="text" placeholder="ytyz" data-old="${sp}" /></td>
        `;
        tableBody.appendChild(tr);
    });

    applyBtn.addEventListener("click", async () => {
        let didRename = false;
        let didRelabel = false;

        const newName = renameInput.value.trim();
        
        if (newName && newName !== strippedFilename) {
            if (!/^[A-Za-z0-9 _\-]+$/.test(newName)) {
                alert(translate("modal.rename.error.invalid"));
                return;
            }

            const newFilename = newName + ".txt";

            try {
                const resp = await apiPut(`${AUTH_URL}/transcriptions/rename`, { jobid, filename: newFilename });

                if (!resp.ok) {
                    alert(translate("modal.rename.error.failed"));
                    return;
                }
                didRename = true;
            } catch (err) {
                console.error("rename error:", err);
                alert(translate("modal.rename.error.failed"));
                return;
            }

            const card = document.querySelector(`.file-card[data-jobid="${jobid}"]`);
            if (card) {
                const nameEl = card.querySelector("#file-card-name");
                if (nameEl) {
                    nameEl.textContent = newFilename;
                }
                card.dataset.downloadName = formatToYYYYMMDD(new Date(createdAt * 1000)) + "_" + newName;
                card.dataset.filename = newFilename;
            }
        }

        const inputs = tableBody.querySelectorAll("input[data-old]");
        const replacements = {};

        inputs.forEach(inp => {
            const oldLabel = inp.dataset.old;
            const newLabel = inp.value.trim();

            if (newLabel) {
                if (!/^[A-Za-z0-9 ]+$/.test(newLabel)) {
                    alert(translate("modal.error.invalidSpeakerPrefix") + " " + newLabel + " " + translate("modal.error.invalidSpeakerSuffix"));
                    return;
                }
                replacements[oldLabel] = newLabel;
            }
        });

        if (Object.keys(replacements).length > 0) {
            let updatedText = currentText;
            for (const [oldSp, newSp] of Object.entries(replacements)) {
                const re = new RegExp(`\\b${oldSp}\\b`, "g");
                updatedText = updatedText.replace(re, newSp);
            }

            // PUT updated file to s3 
            try {
                const form = new FormData();
                form.append("jobid", jobid);
                form.append("file", new Blob([updatedText], { type: "text/plain" }), `${jobid}.txt`);

                const resp = await apiFetch(`${BASE_URL}/s3/transcriptions`, {
                    method: "PUT",
                    body: form
                });

                if (!resp.ok) {
                    alert(translate("modal.error.updateFile"));
                    return;
                }
                didRelabel = true;
            } catch (err) {
                console.error(err);
                alert(translate("modal.error.updateFile"));
                return;
            }

            sessionStorage.setItem(`transcription_${jobid}`, updatedText);

            const card = document.querySelector(`.file-card[data-jobid="${jobid}"]`);
            if (card) {
                card.dataset.fullText = updatedText;

                const snippetEl = card.querySelector(".file-card-snippet");
                const expandBtn = card.querySelector(".file-card-expand");
                const bodyEl = card.querySelector(".file-card-body");

                if (snippetEl) {
                    const snippetPreview = updatedText.length > 500
                        ? updatedText.slice(0, 500) + "…"
                        : updatedText;

                    if (bodyEl && bodyEl.classList.contains("expanded")) {
                        snippetEl.textContent = updatedText;
                        if (expandBtn) expandBtn.textContent = translate("file.collapse");
                    } else {
                        snippetEl.textContent = snippetPreview;
                        if (expandBtn) expandBtn.textContent = translate("file.expand");
                    }
                }
            }
        }

        if (!didRename && !didRelabel) {
            alert(translate("modal.error.noChanges", "please make at least one change"));
            return;
        }

        document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
    });

    const cancelBtn = modal.querySelector(".cancel-btn");
    cancelBtn.addEventListener("click", e => {
        e.preventDefault();
        document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
    });

    modal.addEventListener("click", e => {
        if (e.target.classList.contains("modal-overlay")) {
            e.preventDefault();
            document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
        }
    });
}

/**
 * enables delegated click handling for download, delete, and edit actions on file cards
 * reads dataset attributes from the nearest .file-card to execute the action
 */
let eventListenersAdded = false;
function activateDownloadButtons() {
    if (eventListenersAdded) return;
    eventListenersAdded = true;
    document.addEventListener("click", (e) => {
        const downloadBtn = e.target.closest(".download-button");
        const deleteBtn = e.target.closest(".delete-button");
        const modifyBtn = e.target.closest(".edit-button");

        if (downloadBtn) {
            const card = downloadBtn.closest(".file-card");
            if (!card) return;

            const text = card.dataset.fullText || "";
            const filename = card.dataset.downloadName || translate("file.defaultDownloadName");
            downloadText(text, filename);
            return;
        }

        if (deleteBtn) {
            const card = deleteBtn.closest(".file-card");
            if (!card) return;

            if (!confirm("delete this transcription?")) return;

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
            const currentFilename = card.dataset.filename || "";
            const createdAt = parseInt(card.dataset.createdAt, 10) || Math.floor(Date.now() / 1000);
            openModifyModal(jobid, currentText, currentFilename, createdAt);
            return;
        }
    });
}

/**
 * overrides ctrl+a when focus is inside a file card
 * selects only the visible text region of that card
 */
function interceptSelectAll() {

    let lastClickInsideCard = null;

    // last click location
    document.addEventListener("mousedown", (e) => {
        lastClickInsideCard = e.target.closest(".file-card-body") || null;
    });

    document.addEventListener("keydown", (e) => {
        const isSelectAll = (e.key.toLowerCase() === "a" && (e.ctrlKey || e.metaKey));
        if (!isSelectAll) return;

        if (!lastClickInsideCard) return; // click was not on a card

        const selection = window.getSelection();

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

/**
 * renders the dashboard
 * loads transcription metadata; renders cards in pages;
 * sets up infinite scroll; enables download, delete, and edit behaviours
 */
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
                credentials: "include",
                cache: "no-store"
            });
            const data = await res.json();

            allTranscriptions = data.transcriptions || [];

            if (allTranscriptions.length === 0) {
                container.innerHTML = "";
                const anchor = document.createElement("a");
                anchor.textContent = translate("dashboard.emptyState");
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
            container.innerHTML = `<p>${translate("dashboard.errorLoading")}</p>`;
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