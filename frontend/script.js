//const BASE_URL = window.location.origin;
const BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
const AUTH_URL = `${BASE_URL}/auth`;

document.querySelector('title').innerHTML = "YTYZ transcription";

async function checkAuth() {
  const res = await fetch(`${AUTH_URL}/me`, { credentials: 'include' });
  return res.json();
  //{"payload":{"email":"admin@admin.com","iat":1763163505,"exp":1763167105}}
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  return match ? decodeURIComponent(match[2]) : null;
}