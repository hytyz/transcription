document.addEventListener('DOMContentLoaded', () => {
    checkAuth()
        .then((result) => {
            if (!result || result.error) {
                window.location.href = 'login.html';
                return;
            }
            const email = result.payload.email;
            document.getElementById('userEmail').textContent = email;
        })
        .catch(() => { window.location.href = 'login.html'; });
});

