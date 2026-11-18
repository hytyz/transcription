import { navigateTo, API_URL, POLL_INTERVAL_MS } from "../router.js";
import { translate } from "./i18n.js";
import { apiFetch, apiPost } from "./api.js";

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

    async function readError(res) {
        const body = await res.json().catch(() => ({}));
        return body.error || res.status;
    }

    async function uploadFile(file, progressBar) {
        const startRes = await apiPost(`${API_URL}/upload/start`, {
            filename: file.name,
            size: file.size,
            contentType: file.type,
        });
        if (!startRes.ok) throw new Error(await readError(startRes));
        const { jobid, partSize } = await startRes.json();
        if (!jobid) throw new Error(translate("transcribe.error.noJobId"));

        const parts = [];
        const totalParts = Math.max(1, Math.ceil(file.size / partSize));
        progressBar.max = file.size;
        progressBar.value = 0;

        for (let partNumber = 1; partNumber <= totalParts; partNumber++) {
            const chunk = file.slice((partNumber - 1) * partSize, partNumber * partSize);
            setTranscriptionStatus(`${translate("transcribe.status.uploading")} ${Math.floor(((partNumber - 1) / totalParts) * 100)}%`);
            const partRes = await apiFetch(`${API_URL}/upload/${jobid}/${partNumber}`, { method: "PUT", body: chunk });
            if (!partRes.ok) throw new Error(await readError(partRes));
            parts.push(await partRes.json());
            progressBar.value = Math.min(file.size, partNumber * partSize);
        }

        const completeRes = await apiPost(`${API_URL}/upload/${jobid}/complete`, { parts });
        if (!completeRes.ok) throw new Error(await readError(completeRes));
        return jobid;
    }

    async function startTranscription(file) {
        try {
            dropButton.disabled = true;
            uploadSection.style.display = "none";
            authNav.style.display = "none";
            uploadCard.style.display = "block";

            filenameLabel.textContent = file.name || "filename";
            sessionStorage.setItem("transcriptionFilename", file.name);
            const sizeMB = file.size / (1024 * 1024);
            fileSizeLabel.textContent = `${sizeMB.toFixed(1)} MB`;

            const progressBar = document.getElementById('progress-bar');
            currentJobId = await uploadFile(file, progressBar);
            sessionStorage.setItem("currentJobId", currentJobId);

            progressBar.removeAttribute('value');
            progressBar.removeAttribute('max');

            pollStatus(currentJobId);

        } catch (err) {
            console.error("error starting transcription:", err);
            alert(translate("transcribe.error.start") + " " + err.message);
            window.location.reload();
        }
    }

    function describeStatus(job) {
        if (job.status === "queued" && job.ahead > 0) {
            return `${translate("transcribe.status.queued", "queued")} (${job.ahead} ${translate("transcribe.status.ahead")})`;
        }
        const progress = job.progress != null ? ` ${job.progress}%` : "";
        return translate(`transcribe.status.${job.status}`, job.status) + "..." + progress;
    }

    async function pollStatus(jobid) {
        let job;
        try {
            const res = await apiFetch(`${API_URL}/jobs/${jobid}`, { cache: "no-store" });
            if (!res.ok) throw new Error(await readError(res));
            job = await res.json();
        } catch (err) {
            console.error("status check failed:", err);
            setTimeout(() => pollStatus(jobid), POLL_INTERVAL_MS * 2);
            return;
        }

        setTranscriptionStatus(describeStatus(job));

        if (job.status === "completed") {
            sessionStorage.setItem("currentJobId", jobid);
            navigateTo("/transcription");
            return;
        }

        if (job.status === "error") {
            alert(translate("transcribe.error.failedPrefix") + " " + job.error);
            window.location.reload();
            return;
        }

        setTimeout(() => pollStatus(jobid), POLL_INTERVAL_MS);
    }

    async function setTranscriptionStatus(status) {
        document.getElementById("progress-status").textContent = status;
    }
}

export { setupTranscribe }