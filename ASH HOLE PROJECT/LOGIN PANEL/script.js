const loginBox = document.querySelector(".login-box");
const signupBox = document.querySelector(".signup-box");

const showSignup = document.getElementById("showSignup");
const showLogin = document.getElementById("showLogin");

const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");

const message = document.getElementById("message");

window.addEventListener("pointermove", (event) => {
    const x = (event.clientX / window.innerWidth) * 100;
    const y = (event.clientY / window.innerHeight) * 100;

    document.body.style.setProperty("--mx", x.toFixed(2));
    document.body.style.setProperty("--my", y.toFixed(2));
});


/* SWITCH TO SIGN UP */

showSignup.addEventListener("click", () => {

    loginBox.classList.remove("active");
    signupBox.classList.add("active");

    loginBox.style.opacity = "0";
    loginBox.style.pointerEvents = "none";
    loginBox.style.transform = "translateX(-30px) scale(0.98)";

    signupBox.style.opacity = "1";
    signupBox.style.pointerEvents = "auto";
    signupBox.style.transform = "translateX(0) scale(1)";

});


/* SWITCH TO LOGIN */

showLogin.addEventListener("click", () => {

    signupBox.classList.remove("active");
    loginBox.classList.add("active");

    signupBox.style.opacity = "0";
    signupBox.style.pointerEvents = "none";
    signupBox.style.transform = "translateX(30px) scale(0.98)";

    loginBox.style.opacity = "1";
    loginBox.style.pointerEvents = "auto";
    loginBox.style.transform = "translateX(0) scale(1)";

});


/* SHOW MESSAGE */

function showMessage(text) {

    message.textContent = text;

    message.classList.add("show");

    setTimeout(() => {
        message.classList.remove("show");
    }, 2500);
}

function showButtonLoading(button, loadingText, onComplete) {
    const originalText = button.textContent.trim();

    button.textContent = loadingText;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.classList.add("is-loading");

    setTimeout(() => {
        button.textContent = originalText;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.classList.remove("is-loading");
        onComplete();
    }, 900);
}

function openReservationSite() {
    const destination = new URL(
        "../HOME PAGE/Test-Site_-reservation-prototype-2.html",
        window.location.href
    );

    destination.searchParams.set("authenticated", "1");
    window.location.replace(destination.href);
}


/* LOGIN */

loginForm.addEventListener("submit", (event) => {

    event.preventDefault();

    showButtonLoading(
        loginForm.querySelector("button[type='submit']"),
        "Logging in...",
        () => {
            showMessage("Login request submitted.");
            setTimeout(openReservationSite, 500);
        }
    );

});


/* SIGN UP */

signupForm.addEventListener("submit", (event) => {

    event.preventDefault();

    const password =
        document.getElementById("signupPassword").value;

    const confirmPassword =
        document.getElementById("confirmPassword").value;


    /* CHECK PASSWORD */

    if (password !== confirmPassword) {

        showMessage("Passwords do not match.");

        return;
    }


    showButtonLoading(
        signupForm.querySelector("button[type='submit']"),
        "Creating account...",
        () => {
            showMessage("Account registration submitted.");
            setTimeout(openReservationSite, 500);
        }
    );

});