document.addEventListener("DOMContentLoaded", () => {
  const api_url = `${BASE_URL}/api`;
  let gpuURL = api_url;
  let s3URL = `${BASE_URL}/s3`;
  const WebSocketURL = "wss://pataka.tail2feabe.ts.net/ws/status";

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
    formData.append("jobid", String(crypto.randomUUID()));
    formData.append("file", file);

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
        alert("error starting transcription.");
        window.location.reload();
      }

      const data = await res.json();

      if (!data.jobid) {
        alert("no job id returned.");
        window.location.reload();
      }

      currentJobId = data.jobid;
      localStorage.setItem("currentJobId", currentJobId);

      // startPollingStatus();
      startWebSocket(currentJobId);

    } catch (err) {
      console.error("error starting transcription:", err);
      alert("error starting transcription.");
      window.location.reload();
    }
  }

  // function startPollingStatus() {
  //   if (pollInterval) clearInterval(pollInterval);

  //   pollInterval = setInterval(async () => {
  //     try {
  //       const res = await fetch(`${s3URL}/transcriptions/${currentJobId}`);
  //       if (!res.ok) return;

  //       // const data = await res.json();

  //       else {
  //         clearInterval(pollInterval);
  //         pollInterval = null;
  //         fetchTranscription();
  //       }
  //     } catch (err) {
  //       console.error("polling error:", err);
  //     }
  //   }, 10000);
  // }
  function startWebSocket(jobid) {
    const ws = new WebSocket(`${WebSocketURL}`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ jobid }));
      console.log("WS connected for job:", jobid);
    };

    ws.onmessage = async (event) => {
      const msg = JSON.parse(event.data);
      console.log("WS status:", msg);

      setTranscriptionStatus(msg.status + "...");

      if (msg.status === "completed") {
        ws.close();
        fetchTranscription();
      }

      if (msg.status === "error") {
        ws.close();
        alert("Transcription failed: " + msg.error);
      }
    };

    ws.onerror = (e) => console.error("WS error:", e);
    ws.onclose = () => console.log("WS closed");
  }

async function setTranscriptionStatus(status) {
    document.getElementById("progress-status").textContent = status;
}

  async function fetchTranscription() {
    try {
      const res = await fetch(`${s3URL}/transcriptions/${currentJobId}`);
      if (!res.ok) {
        alert("failed to fetch transcription.");
        dropButton.disabled = false;
        return;
      }
      console.log("fetch transcription response:");
      console.log(res);
      // console.log(await res.text());
      // const json = await res.json();
      let text = await res.text();
      // console.log("transcription text:");
      // console.log(text);
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