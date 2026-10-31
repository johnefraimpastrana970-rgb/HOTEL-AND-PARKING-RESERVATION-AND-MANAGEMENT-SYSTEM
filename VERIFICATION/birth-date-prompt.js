/*
 * NEXORA date-of-birth prompt, shown at sign-in to customers who have none on file.
 *
 * window.NexoraBirthDate.open({ save }) calls save("YYYY-MM-DD") when the customer
 * continues and resolves true once it succeeds, or resolves null when they choose
 * Log out. Like the consent modal it cannot be dismissed any other way. The server
 * validates the date and works out the age; this page only collects it.
 *
 * Uses the dialog styles in LEGAL/consent-modal.css, which must be loaded first.
 */
(() => {
  let session = null;

  const element = (tag, attributes = {}, children = []) => {
    const node = document.createElement(tag);
    Object.entries(attributes).forEach(([name, value]) => {
      if (name === "text") node.textContent = value;
      else if (value !== false && value != null) node.setAttribute(name, value === true ? "" : value);
    });
    node.append(...children);
    return node;
  };

  const localToday = () => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  };

  // Mirrors the server's rule, including 29 February birthdays in common years.
  function ageOn(birth, today) {
    const [by, bm, bd] = birth.split("-").map(Number);
    const [ty, tm, td] = today.split("-").map(Number);
    const leap = (year) => year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const birthday = bm === 2 && bd === 29 && !leap(ty) ? [2, 28] : [bm, bd];
    return ty - by - (tm < birthday[0] || (tm === birthday[0] && td < birthday[1]) ? 1 : 0);
  }

  function open({ save } = {}) {
    if (session) return session;
    const today = localToday();
    const input = element("input", {
      type: "date", id: "nxb-date", required: true, min: "1900-01-01", max: today,
      autocomplete: "bday", "aria-describedby": "nxb-help nxb-hint",
    });
    const hint = element("p", { class: "nxc-hint", id: "nxb-hint", "aria-live": "polite" });
    const cancel = element("button", { type: "button", class: "nxc-btn nxc-cancel", text: "Log out" });
    const accept = element("button", { type: "submit", class: "nxc-btn nxc-continue", text: "Save and continue" });
    const form = element("form", { class: "nxb-form", novalidate: true }, [
      element("label", { class: "nxb-label", for: "nxb-date", text: "Date of birth" }),
      input,
      element("p", {
        class: "nxb-help",
        id: "nxb-help",
        text: "Choose your date of birth using the date picker. NEXORA bookings are for adults aged 18 or over. We use your date of birth only to check your age. Once saved, only a NEXORA administrator can reopen it for changes.",
      }),
      hint,
      element("div", { class: "nxc-actions" }, [cancel, accept]),
    ]);
    const dialog = element("div", {
      class: "nxc nxb", role: "dialog", "aria-modal": "true", "aria-labelledby": "nxb-title", "aria-describedby": "nxb-intro",
    }, [
      element("header", { class: "nxc-head" }, [
        element("p", { class: "nxc-eyebrow", text: "Age check" }),
        element("h2", { id: "nxb-title", text: "Add your date of birth" }),
        element("p", { id: "nxb-intro", text: "We need this once before you continue." }),
      ]),
      form,
    ]);
    const overlay = element("div", { class: "nxc-overlay" }, [dialog]);
    const madeInert = [];
    const rootOverflow = document.documentElement.style.overflow;
    let resolvePromise;
    const promise = new Promise((resolve) => { resolvePromise = resolve; });

    function say(message, tone = "") {
      hint.dataset.tone = tone;
      hint.textContent = message;
    }

    function check() {
      const value = input.value;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Select a valid date of birth.";
      if (value > today) return "Your date of birth cannot be in the future.";
      if (value < "1900-01-01") return "Enter a date of birth after 1 January 1900.";
      return "";
    }

    function warn(message) {
      say(message, "warn");
      dialog.classList.remove("nxc-nudge");
      void dialog.offsetWidth;
      dialog.classList.add("nxc-nudge");
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        warn('Add your date of birth, or select "Log out".');
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = [input, cancel, accept].filter((node) => !node.disabled);
      const index = nodes.indexOf(document.activeElement);
      if (index === -1 || (event.shiftKey && index === 0) || (!event.shiftKey && index === nodes.length - 1)) {
        event.preventDefault();
        nodes[event.shiftKey ? nodes.length - 1 : 0].focus();
      }
    }

    function finish(result) {
      document.removeEventListener("keydown", onKeydown, true);
      madeInert.forEach((node) => node.removeAttribute("inert"));
      document.documentElement.style.overflow = rootOverflow;
      overlay.remove();
      session = null;
      resolvePromise(result);
    }

    input.addEventListener("input", () => {
      const problem = check();
      if (problem) say("");
      else if (ageOn(input.value, today) < 18) {
        say("You can still sign in, but NEXORA bookings are only for adults aged 18 or over.", "warn");
      } else say("");
    });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) warn('Add your date of birth, or select "Log out".');
    });
    cancel.addEventListener("click", () => finish(null));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const problem = check();
      if (problem) {
        warn(problem);
        input.focus();
        return;
      }
      accept.disabled = cancel.disabled = true;
      accept.textContent = "Saving...";
      try {
        await save(input.value);
        finish(true);
      } catch (error) {
        warn(error.message || "Your date of birth could not be saved. Please try again.");
        accept.disabled = cancel.disabled = false;
        accept.textContent = "Save and continue";
      }
    });

    [...document.body.children].forEach((node) => {
      if (!node.hasAttribute("inert") && node.tagName !== "SCRIPT") {
        node.setAttribute("inert", "");
        madeInert.push(node);
      }
    });
    document.body.append(overlay);
    document.documentElement.style.overflow = "hidden";
    document.addEventListener("keydown", onKeydown, true);
    requestAnimationFrame(() => input.focus());
    session = promise;
    return promise;
  }

  window.NexoraBirthDate = Object.freeze({ open, ageOn });
})();
