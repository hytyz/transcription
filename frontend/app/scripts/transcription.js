import { createCardFromTemplate, activateDownloadButtons, formatToYYYYMMDD } from "./dashboard.js";

// date.now() gives milliseconds since epoch
async function setupTranscription() {
    const root = document.getElementById("file-card-root");
    if (!root) return;
    let currentJobId = sessionStorage.getItem("currentJobId");
    let currentFileName = sessionStorage.getItem("transcriptionFilename")
    const transcriptionCard = await createCardFromTemplate(currentJobId, (Date.now()/1000), currentFileName)
    root.appendChild(transcriptionCard)
    activateDownloadButtons();
}

export { setupTranscription }