//const BASE_URL = window.location.origin;
var BASE_URL = "https://polina-gateway.fly.dev"; // gateway base URL
var AUTH_URL = `${BASE_URL}/auth`;

checkAuth().then((res) => {
    const anchor1 = document.getElementById("dashboard-anchor1");
    const anchor2 = document.getElementById("dashboard-anchor2");
    // console.log(res);
    if (!res.payload) {
        anchor1.innerHTML = "login";
        anchor1.href = "/login";
        anchor2.innerHTML = "register";
        anchor2.href = "/register"
    }
    else {
        anchor1.innerHTML = "view files"; // TODO
        anchor1.href = "#";
        anchor2.innerHTML = "log out"; // TODO
        anchor2.href = "#";
        anchor2.addEventListener('click', async () => {
            await fetch(`${AUTH_URL}/logout`, { method: "POST" });
            window.location.href = '/login';
        });
    }
})
    .catch((error) => { console.log(error); });