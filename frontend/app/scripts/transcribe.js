import { navigateTo } from "../router.js";
import { translate } from "./i18n.js";

const BASE_URL = "https://polina-gateway.fly.dev"
const api_url = `${BASE_URL}/api`;
let gpuURL = api_url;
const WebSocketURL = "wss://pataka.tail2feabe.ts.net/ws/status";

function setupTranscribe() {
    const audioFileInput = document.getElementById("audio-file");
    const dropButton = document.querySelector(".drop-button");
    const uploadSection = document.querySelector(".upload-section");
    const authNav = document.querySelector(".auth-nav");
    const uploadCard = document.getElementById("upload-progress-card");
    const filenameLabel = document.getElementById("upload-filename");
    const fileSizeLabel = document.getElementById("upload-file-size");

    let currentJobId = null;

    dropButton.addEventListener("click", () => { audioFileInput.click(); });

    audioFileInput.addEventListener("change", () => {
        const file = audioFileInput.files[0];
        if (file) { startTranscription(file); }
    });

    async function startTranscription(file) {
        const buffer = await file.arrayBuffer();
        const clonedFile = new File([buffer], file.name, { type: file.type });

        const formData = new FormData();
        formData.append("jobid", String(crypto.randomUUID()));
        formData.append("file", clonedFile);

        try {
            dropButton.disabled = true;
            uploadSection.style.display = "none";
            authNav.style.display = "none";
            uploadCard.style.display = "block";

            filenameLabel.textContent = file.name || "filename";
            sessionStorage.setItem("transcriptionFilename", file.name);
            const sizeMB = file.size / (1024 * 1024);
            fileSizeLabel.textContent = `${sizeMB.toFixed(1)} MB`;

            const res = await fetch(`${gpuURL}/upload`, { method: "POST", body: formData, credentials: "include" });

            if (!res.ok) {
                alert(translate("transcribe.error.start") + " " + res);
                window.location.reload();
            }

            const data = await res.json();

            if (!data.jobid) {
                alert(translate("transcribe.error.noJobId") + " " + res);
                window.location.reload();
            }

            currentJobId = data.jobid;
            sessionStorage.setItem("currentJobId", currentJobId);

            startWebSocket(currentJobId);

        } catch (err) {
            console.error("error starting transcription:", err);
            alert(translate("transcribe.error.start") + " " + res);
            window.location.reload();
        }
    }
    
    function startWebSocket(jobid) {
        const ws = new WebSocket(`${WebSocketURL}`);

        ws.onopen = () => {
            ws.send(JSON.stringify({ jobid }));
            console.log("ws connected for job:", jobid);
        };

        ws.onmessage = async (event) => {
            const msg = JSON.parse(event.data);
            console.log("WS status:", msg);

            setTranscriptionStatus(msg.status + "...");

            if (msg.status === "completed") {
                ws.close();
                sessionStorage.setItem("currentJobId", jobid)
                navigateTo("/transcription")
            }

            if (msg.status === "error") {
                ws.close();
                alert(t("transcribe.error.failedPrefix") + " " + msg.error);
            }
        };

        ws.onerror = (e) => console.error("ws error:", e);
        ws.onclose = () => console.log("ws closed");
    }

    async function setTranscriptionStatus(status) {
        document.getElementById("progress-status").textContent = status;
    }
}

export { setupTranscribe }