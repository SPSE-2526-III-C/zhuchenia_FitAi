// =========================
// FITAI GLOBAL JS
// =========================


// -------------------------
// Flash message auto-hide
// -------------------------
setTimeout(() => {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        alert.style.transition = "0.5s";
        alert.style.opacity = "0";
        setTimeout(() => alert.remove(), 500);
    });
}, 3000);


// -------------------------
// Confirm delete workout
// -------------------------
function confirmDelete() {
    return confirm("Naozaj chceš odstrániť tento tréning?");
}


// -------------------------
// Smooth scroll (future UX)
// -------------------------
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener("click", function (e) {
        e.preventDefault();

        const target = document.querySelector(this.getAttribute("href"));

        if (target) {
            target.scrollIntoView({
                behavior: "smooth"
            });
        }
    });
});


// -------------------------
// Button click animation
// -------------------------
document.querySelectorAll('.btn').forEach(btn => {
    btn.addEventListener('click', function () {

        this.style.transform = "scale(0.96)";

        setTimeout(() => {
            this.style.transform = "scale(1)";
        }, 100);

    });
});


// -------------------------
// Console branding (just for fun)
// -------------------------
console.log("%cFitAI loaded 💪", "color: #00c3ff; font-size: 16px; font-weight: bold");
