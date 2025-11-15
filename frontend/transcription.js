document.addEventListener("DOMContentLoaded", () => {
  const textArea = document.getElementById("transcription-text");

  const text = sessionStorage.getItem("transcriptionText") || "";
  const jobId = sessionStorage.getItem("transcriptionJobId") || "";

  textArea.value = text;
  console.log("job id " + jobId);
});