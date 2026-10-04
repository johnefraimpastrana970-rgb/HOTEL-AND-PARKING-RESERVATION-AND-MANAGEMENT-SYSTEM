const loginBox = document.querySelector(".login-box");
const signupBox = document.querySelector(".signup-box");

const showSignup = document.getElementById("showSignup");
const showLogin = document.getElementById("showLogin");

const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");

const message = document.getElementById("message");
const adminPortal = new URLSearchParams(window.location.search).get("portal") === "admin";
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
    const isSignup = button.closest("#signupForm") !== null;

    button.textContent = loadingText;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.classList.add("is-loading");
    if (isSignup) {
        button.classList.add("is-signing-up");
    }

    try {
        await onComplete();
    } catch (error) {
        showMessage(error.message || "The request could not be completed.");
    } finally {
        button.textContent = originalText;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.classList.remove("is-loading");
        button.classList.remove("is-signing-up");
    }
}

async function continueWithAccount(user, openLoginDoor = false) {
    if (adminPortal && user.role !== "Admin") {
        showMessage("This account does not have administrator access.");
        return false;
    }

    const profile = {
        name: user.display_name || user.username,
        email: user.email
    };
    localStorage.setItem("test-site-profile", JSON.stringify(profile));
    const destination =
        adminPortal || user.role === "Admin" || user.role.endsWith("Personnel")
            ? "admin"
            : "reservation";
    sessionStorage.setItem("nexora-welcome", JSON.stringify({
        username: user.username || profile.name,
        name: profile.name,
        email: profile.email,
        destination
    }));
    if (openLoginDoor) {
        document.body.classList.add("login-door-opening");
        const doorDuration = window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? 20
            : 1050;
        await new Promise((resolve) => window.setTimeout(resolve, doorDuration));
    }
    window.location.replace(new URL("welcome.html", window.location.href).href);
    return true;
}

if (adminPortal) {
    document.title = "Admin sign in | Central Channel";
    document.querySelector(".top-bar .title").textContent = "Administrator Portal";
    document.querySelector(".login-box h1").textContent = "Admin sign in";
    document.querySelector(".login-box .subtitle").textContent = "Sign in with an administrator account";
    document.querySelector(".login-box .switch").hidden = true;
    signupBox.hidden = true;

    if (new URLSearchParams(window.location.search).get("reason") === "role") {
        showMessage("That account does not have administrator access. Sign in with the Admin account.");
    }
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
            await continueWithAccount(user, true);
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
            await continueWithAccount(user);
        }
    );

});