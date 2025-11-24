import { createCardFromTemplate, activateDownloadButtons } from "./dashboard.js";

/**
 * renders a single transcription card for the job created in the current session
 * reads job id and file name from sessionStorage; uses current time for the card date
 * @returns {Promise<void>}
 */
async function setupTranscription() {
    // date.now() gives milliseconds since epoch
    const root = document.getElementById("file-card-root");
    if (!root) return;
    let currentJobId = sessionStorage.getItem("currentJobId");
    let currentFileName = sessionStorage.getItem("transcriptionFilename")
    const transcriptionCard = await createCardFromTemplate(currentJobId, (Date.now() / 1000), currentFileName)
    root.appendChild(transcriptionCard)
    activateDownloadButtons();
}

export { setupTranscription }