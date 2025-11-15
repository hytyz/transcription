document.addEventListener("DOMContentLoaded", () => {
  const api_url = `${BASE_URL}/api`;
  let gpuURL = api_url;

  const audioFileInput = document.getElementById("audio-file");
  const dropButton = document.querySelector(".drop-button");
  const uploadSection = document.querySelector(".upload-section");
  const authNav = document.querySelector(".auth-nav");
  const uploadCard = document.getElementById("upload-progress-card");
  const filenameLabel = document.getElementById("upload-filename");
  const fileSizeLabel = document.getElementById("upload-file-size");

  let currentJobId = null;
  let pollInterval = null;

  dropButton.addEventListener("click", () => { audioFileInput.click(); });

  audioFileInput.addEventListener("change", () => {
    const file = audioFileInput.files[0];
    if (file) { startTranscription(file); }
  });

  async function startTranscription(file) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("model", "medium");
    formData.append("out_format", "txt");

    try {
      dropButton.disabled = true;
      uploadSection.style.display = "none";
      authNav.style.display = "none";
      uploadCard.style.display = "block";

      filenameLabel.textContent = file.name || "filename";
      sessionStorage.setItem("transcriptionFilename", file.name);
      const sizeMB = file.size / (1024 * 1024);
      fileSizeLabel.textContent = `${sizeMB.toFixed(1)} MB`;

      const res = await fetch(`${gpuURL}/transcribe`, { method: "POST", body: formData });

      if (!res.ok) {
        alert("error starting transcription.");
        window.location.reload();
      }

      const data = await res.json();

      if (!data.job_id) {
        alert("no job id returned.");
        window.location.reload();
      }

      currentJobId = data.job_id;

      startPollingStatus();
    } catch (err) {
      console.error("error starting transcription:", err);
      alert("error starting transcription.");
      window.location.reload();
    }
  }

  function startPollingStatus() {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${gpuURL}/status`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.status === "idle" && data.current_job_id === currentJobId) {
          clearInterval(pollInterval);
          pollInterval = null;
          fetchTranscription();
        }
      } catch (err) {
        console.error("polling error:", err);
      }
    }, 10000);
  }

  async function fetchTranscription() {
    try {
      const res = await fetch(`${gpuURL}/transcription`);
      if (!res.ok) {
        alert("failed to fetch transcription.");
        dropButton.disabled = false;
        return;
      }
      const json = await res.json();
      let text = json.raw_text || "";
      text = text.replace(/\\n/g, "\n");

      sessionStorage.setItem("transcriptionText", text);
      sessionStorage.setItem("transcriptionJobId", currentJobId);
      window.location.href = "transcription.html";
    } catch (err) {
      console.error("error getting transcription:", err);
      alert("failed to fetch transcription.");
      dropButton.disabled = false;
    }
  }
});