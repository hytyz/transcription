checkAuth().then((result) => {
    const anchor1 = document.getElementById("dashboard-anchor1");
    const anchor2 = document.getElementById("dashboard-anchor2");
    if (!result.payload.email) {
        anchor1.innerHTML = "login";
        anchor1.href = "/login.html";
        anchor2.innerHTML = "register";
        anchor2.href = "/register.html"
    }
    else {
        anchor1.innerHTML = "view files"; // TODO
        anchor1.href = "#";
        anchor2.innerHTML = "log out"; // TODO
        anchor2.href = "#";
    }
})
    .catch((error) => { console.log(error); });