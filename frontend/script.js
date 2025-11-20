//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

document.title = "YTYZ transcription";

async function checkAuth() {
  const res = await fetch(`${AUTH_URL}/me`, { credentials: 'include' });
  console.log(res);
  return res.json();
}

