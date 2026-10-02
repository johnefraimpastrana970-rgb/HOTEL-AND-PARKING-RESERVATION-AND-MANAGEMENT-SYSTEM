const loginBox = document.querySelector(".login-box");
const signupBox = document.querySelector(".signup-box");

const showSignup = document.getElementById("showSignup");
const showLogin = document.getElementById("showLogin");

const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");

const message = document.getElementById("message");
const usernameFields = [
    document.getElementById("loginUsername"),
    document.getElementById("signupUsername")
];
const disallowedUsernameCharacters = /[^A-Za-z0-9_@*]/g;

usernameFields.forEach((field) => {
    field.addEventListener("input", () => {
        const cursor = field.selectionStart;
        const cleanPrefix = field.value.slice(0, cursor).replace(disallowedUsernameCharacters, "");
        field.value = field.value.replace(disallowedUsernameCharacters, "");
        field.setSelectionRange(cleanPrefix.length, cleanPrefix.length);
    });
});

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

async function showButtonLoading(button, loadingText, onComplete) {
    const originalText = button.textContent.trim();

    button.textContent = loadingText;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.classList.add("is-loading");

    try {
        await onComplete();
    } catch (error) {
        showMessage(error.message || "The request could not be completed.");
    } finally {
        button.textContent = originalText;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.classList.remove("is-loading");
    }
}

function continueWithAccount(user) {
    const profile = {
        name: user.display_name || user.username,
        email: user.email
    };
    localStorage.setItem("test-site-profile", JSON.stringify(profile));
    showMessage(`Signed in as ${profile.name} (${user.role}).`);
    setTimeout(() => openReservationSite({ username: profile.name, email: profile.email }), 350);
}

function openReservationSite(profile = {}) {
    const destination = new URL(
        "../HOME PAGE/Test-Site_-reservation-prototype-2.html",
        window.location.href
    );

    destination.searchParams.set("authenticated", "1");
    if (profile.username) {
        destination.searchParams.set("username", profile.username.trim());
    }
    if (profile.email) {
        destination.searchParams.set("email", profile.email.trim());
    }
    window.location.replace(destination.href);
}


/* LOGIN */

loginForm.addEventListener("submit", (event) => {

    event.preventDefault();
    const username = document.getElementById("loginUsername").value;
    const password = document.getElementById("loginPassword").value;

    showButtonLoading(
        loginForm.querySelector("button[type='submit']"),
        "Logging in...",
        async () => {
            const user = await window.ReservationAPI.login({ username, password });
            continueWithAccount(user);
        }
    );

});


/* SIGN UP */

signupForm.addEventListener("submit", (event) => {

    event.preventDefault();

    const username = document.getElementById("signupUsername").value;
    const email = document.getElementById("signupEmail").value;
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
        async () => {
            const user = await window.ReservationAPI.register({
                username,
                displayName: username,
                email,
                password
            });
            continueWithAccount(user);
        }
    );

});