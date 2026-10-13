(() => {
    const settingsStorageKey = "test-site-settings";
    const root = document.documentElement;
    const button = document.getElementById("themeBtn");
    let settings = {};

    try {
        settings = JSON.parse(localStorage.getItem(settingsStorageKey) || "{}");
    } catch (error) {
        console.error("Could not load the saved theme preference.", error);
    }

    function applyTheme(theme, save = false, animate = false) {
        const previousTheme = root.dataset.theme;
        root.dataset.theme = theme;
        button.setAttribute("aria-pressed", String(theme === "dark"));
        button.setAttribute(
            "aria-label",
            `Switch to ${theme === "dark" ? "light" : "dark"} mode`,
        );

        if (
            animate &&
            previousTheme !== theme &&
            !window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ) {
            const transition = theme === "dark" ? "sunset" : "sunrise";
            root.removeAttribute("data-theme-transition");
            void root.offsetWidth;
            root.dataset.themeTransition = transition;
        }

        if (save) {
            try {
                settings = { ...settings, theme };
                localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
            } catch (error) {
                console.error("Could not save the theme preference.", error);
            }
        }
    }

    root.addEventListener("animationend", (event) => {
        if (event.target.matches(".sunset-orb")) {
            root.removeAttribute("data-theme-transition");
        }
    });

    applyTheme(settings.theme === "dark" ? "dark" : "light");
    button.addEventListener("click", () => {
        applyTheme(root.dataset.theme === "dark" ? "light" : "dark", true, true);
    });
})();
