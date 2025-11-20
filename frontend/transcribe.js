// let ffmpeg;
// let ffmpegReady = false;

// async function loadFFmpeg() {
//   const { createFFmpeg, fetchFile } = FFmpeg; // global if using CDN

//   ffmpeg = createFFmpeg({
//     log: true, // or false
//   });

//   if (!ffmpegReady) {
//     await ffmpeg.load();
//     ffmpegReady = true;
//   }

//   return { fetchFile };
// }

async function convertToWav(inputFile) {
  const { fetchFile } = await loadFFmpeg();

  const inputName = inputFile.name;
  const outputName = "output.wav";

  // Write original file into ffmpeg FS
  ffmpeg.FS("writeFile", inputName, await fetchFile(inputFile));

  // Run ffmpeg command
  await ffmpeg.run(
    "-i", inputName,
    "-ac", "1",
    "-ar", "16000",
    outputName
  );

  // Read back the WAV bytes
  const data = ffmpeg.FS("readFile", outputName);

  // Convert Uint8Array → Blob → File
  return new File([data.buffer], outputName, { type: "audio/wav" });
}


document.addEventListener("DOMContentLoaded", () => {
  const api_url = `${BASE_URL}/api`;
  let gpuURL = api_url;
  let s3URL = `${BASE_URL}/s3`;

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
      // Convert before uploading
    // console.log("Converting to WAV...");
    // const wavFile = await convertToWav(file);
    const formData = new FormData();
    formData.append("jobid", String(crypto.randomUUID())); 
    formData.append("file", file);
    // formData.append("model", "medium");
    // formData.append("out_format", "txt");

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
        const res = await fetch(`${s3URL}/transcriptions/${currentJobId}`);
        if (!res.ok) return;

        // const data = await res.json();

        else {
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
      console.log("transcription text:");
      console.log(text);
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