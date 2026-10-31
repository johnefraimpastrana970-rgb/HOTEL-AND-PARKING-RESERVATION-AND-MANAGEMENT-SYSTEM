/*
 * NEXORA policy consent modal.
 *
 * window.NexoraConsent.open({ flow, missing }) resolves with a consent payload for the
 * API when the reader accepts, or with null when they choose Cancel. It cannot be
 * dismissed any other way. Reaching the end of a document is recorded as a reading-flow
 * signal only; the server still validates every submission and records the time itself.
 *
 * Requires legal-documents.js to be loaded first.
 */
(() => {
  const legalBase = new URL(".", document.currentScript.src);
  const PAGES = { terms: "terms-of-service.html", privacy: "privacy-policy.html" };
  const FLOWS = {
    signup: {
      title: "Before you create your account",
      intro: "Please read NEXORA's Terms of Service and Privacy Policy. You need to accept them to create an account.",
      cancel: "Cancel sign-up",
      accept: "Accept and create account",
    },
    login: {
      title: "Before you sign in",
      intro: "Please read NEXORA's Terms of Service and Privacy Policy. You need to accept them to sign in.",
      cancel: "Cancel sign-in",
      accept: "Accept and sign in",
    },
    renewal: {
      title: "We have updated our policies",
      intro: "Please review the current Terms of Service and Privacy Policy. You need to accept them to keep using your account.",
      cancel: "Log out",
      accept: "Accept and continue",
    },
  };
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

  function build(flow, missing) {
    const copy = FLOWS[flow] || FLOWS.login;
    const documents = window.NEXORA_LEGAL.documents;
    const state = new Map(documents.map((doc) => [doc.type, { progress: 0, read: false }]));

    const tabs = documents.map((doc, index) => element("button", {
      type: "button",
      role: "tab",
      class: "nxc-tab",
      id: `nxc-tab-${doc.type}`,
      "aria-controls": `nxc-panel-${doc.type}`,
      "aria-selected": String(index === 0),
      tabindex: index === 0 ? "0" : "-1",
      "data-type": doc.type,
      "data-read": "false",
    }, [
      element("span", { class: "nxc-tab-row" }, [
        element("span", {}, [
          doc.title,
          ...(missing.includes(doc.type) && flow === "renewal" ? [element("span", { class: "nxc-badge", text: "Updated" })] : []),
        ]),
        element("span", { class: "nxc-tab-state", text: "Not started" }),
      ]),
      element("span", { class: "nxc-meter", "aria-hidden": "true" }, [element("span")]),
    ]));

    const panels = documents.map((doc, index) => {
      const panel = element("section", {
        role: "tabpanel",
        class: "nxc-doc",
        id: `nxc-panel-${doc.type}`,
        "aria-labelledby": `nxc-tab-${doc.type}`,
        tabindex: "0",
        hidden: index !== 0,
        "data-type": doc.type,
      });
      const meta = element("p", { class: "nxc-doc-meta" }, [
        element("span", { text: `Version ${doc.version}` }),
        element("span", { text: `Effective ${doc.effective}` }),
        element("a", { href: new URL(PAGES[doc.type], legalBase).href, target: "_blank", rel: "noopener", text: "Open in a new tab" }),
      ]);
      const content = element("div");
      content.innerHTML = doc.html; // trusted, versioned text shipped with the site
      panel.append(meta, content, element("p", { class: "nxc-end", text: `End of the ${doc.title}.` }));
      return panel;
    });

    const progressbar = element("div", {
      role: "progressbar",
      "aria-label": "Reading progress for the open document",
      "aria-valuemin": "0",
      "aria-valuemax": "100",
      "aria-valuenow": "0",
      class: "nxc-meter",
      style: "margin:0 28px;border-radius:0;height:3px",
    }, [element("span")]);
    const jump = element("button", { type: "button", class: "nxc-jump" });
    const body = element("div", { class: "nxc-body", "data-at-end": "false" }, [...panels, element("div", { class: "nxc-fade", "aria-hidden": "true" }), jump]);
    const hint = element("p", { class: "nxc-hint", "aria-live": "polite" });
    const checkbox = element("input", { type: "checkbox", id: "nxc-accept", disabled: true, "aria-describedby": "nxc-hint-text" });
    hint.id = "nxc-hint-text";
    const checkLabel = element("label", { class: "nxc-check", for: "nxc-accept" }, [
      checkbox,
      element("span", { text: "I have read and agree to the NEXORA Terms of Service, and I acknowledge the NEXORA Privacy Policy." }),
    ]);
    const cancel = element("button", { type: "button", class: "nxc-btn nxc-cancel", text: copy.cancel });
    const accept = element("button", { type: "button", class: "nxc-btn nxc-continue", disabled: true, text: copy.accept });

    const dialog = element("div", {
      class: "nxc",
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "nxc-title",
      "aria-describedby": "nxc-intro",
    }, [
      element("header", { class: "nxc-head" }, [
        element("p", { class: "nxc-eyebrow", text: "NEXORA policies" }),
        element("h2", { id: "nxc-title", text: copy.title }),
        element("p", { id: "nxc-intro", text: copy.intro }),
      ]),
      element("div", { class: "nxc-tabs", role: "tablist", "aria-label": "Policy documents" }, tabs),
      progressbar,
      body,
      element("footer", { class: "nxc-foot" }, [hint, checkLabel, element("div", { class: "nxc-actions" }, [cancel, accept])]),
    ]);
    const overlay = element("div", { class: "nxc-overlay" }, [dialog]);
    return { overlay, dialog, documents, state, tabs, panels, body, progressbar, jump, hint, checkbox, accept, cancel };
  }

  function open({ flow = "login", missing = [] } = {}) {
    if (session) return session.promise;
    if (!window.NEXORA_LEGAL) {
      return Promise.reject(new Error("The NEXORA policy documents could not be loaded. Reload the page and try again."));
    }
    const ui = build(flow, missing);
    let resolvePromise;
    const promise = new Promise((resolve) => { resolvePromise = resolve; });
    const previouslyFocused = document.activeElement;
    const madeInert = [];
    const rootOverflow = document.documentElement.style.overflow;

    const activeType = () => ui.tabs.find((tab) => tab.getAttribute("aria-selected") === "true").dataset.type;
    const activePanel = () => ui.panels.find((panel) => panel.dataset.type === activeType());
    const allRead = () => [...ui.state.values()].every((entry) => entry.read);
    const nextUnread = () => ui.documents.find((doc) => !ui.state.get(doc.type).read);

    function render() {
      ui.tabs.forEach((tab) => {
        const entry = ui.state.get(tab.dataset.type);
        tab.dataset.read = String(entry.read);
        tab.querySelector(".nxc-meter > span").style.setProperty("--p", entry.progress);
        tab.querySelector(".nxc-tab-state").textContent = entry.read
          ? "Read ✓"
          : entry.progress > 0 ? `${entry.progress}% read` : "Not started";
      });
      const current = ui.state.get(activeType());
      ui.progressbar.setAttribute("aria-valuenow", String(current.progress));
      ui.progressbar.firstChild.style.setProperty("--p", current.progress);
      ui.body.dataset.atEnd = String(current.read);

      const unread = nextUnread();
      ui.jump.hidden = !unread;
      if (unread) {
        ui.jump.textContent = current.read ? `Read the ${unread.title} →` : "Scroll down ↓";
      }
      const ready = allRead();
      if (ui.checkbox.disabled === ready) {
        ui.checkbox.disabled = !ready;
        if (!ready) ui.checkbox.checked = false;
      }
      ui.accept.disabled = !(ready && ui.checkbox.checked);
      const message = ready
        ? ui.checkbox.checked ? "Thank you. Select the button below to continue." : "You have reached the end of both documents. Tick the box to accept."
        : `Scroll to the end of both documents to continue. Still to read: ${ui.documents.filter((doc) => !ui.state.get(doc.type).read).map((doc) => doc.title).join(" and ")}.`;
      if (ui.hint.textContent !== message || ui.hint.dataset.tone) {
        ui.hint.dataset.tone = "";
        ui.hint.textContent = message;
      }
    }

    function measure() {
      const panel = activePanel();
      if (!panel || !panel.clientHeight) return;
      const entry = ui.state.get(panel.dataset.type);
      const remaining = panel.scrollHeight - panel.clientHeight - panel.scrollTop;
      const ratio = panel.scrollHeight <= panel.clientHeight
        ? 1
        : (panel.scrollTop + panel.clientHeight) / panel.scrollHeight;
      entry.progress = Math.max(entry.progress, Math.min(100, Math.round(ratio * 100)));
      if (remaining <= 4) {
        entry.read = true;
        entry.progress = 100;
      }
      render();
    }

    function selectTab(type, focus = false) {
      ui.tabs.forEach((tab) => {
        const selected = tab.dataset.type === type;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (selected && focus) tab.focus();
      });
      ui.panels.forEach((panel) => { panel.hidden = panel.dataset.type !== type; });
      requestAnimationFrame(measure);
    }

    function warn(message) {
      ui.hint.dataset.tone = "warn";
      ui.hint.textContent = message;
      ui.dialog.classList.remove("nxc-nudge");
      void ui.dialog.offsetWidth;
      ui.dialog.classList.add("nxc-nudge");
    }

    function focusable() {
      return [...ui.dialog.querySelectorAll("button, a[href], input, [tabindex]:not([tabindex='-1'])")]
        .filter((node) => !node.disabled && !node.hidden && !node.closest("[hidden]"));
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        warn(`To leave without accepting, select "${ui.cancel.textContent}".`);
        return;
      }
      if (event.key === "Tab") {
        const nodes = focusable();
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (!ui.dialog.contains(document.activeElement)) {
          event.preventDefault();
          first.focus();
        } else if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    function finish(result) {
      document.removeEventListener("keydown", onKeydown, true);
      window.removeEventListener("resize", measure);
      madeInert.forEach((node) => node.removeAttribute("inert"));
      document.documentElement.style.overflow = rootOverflow;
      ui.overlay.remove();
      session = null;
      if (previouslyFocused && typeof previouslyFocused.focus === "function") previouslyFocused.focus();
      resolvePromise(result);
    }

    ui.panels.forEach((panel) => panel.addEventListener("scroll", measure, { passive: true }));
    ui.tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => selectTab(tab.dataset.type));
      tab.addEventListener("keydown", (event) => {
        const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: ui.tabs.length - 1 };
        if (!(event.key in moves)) return;
        event.preventDefault();
        const target = ui.tabs[(moves[event.key] + ui.tabs.length) % ui.tabs.length];
        selectTab(target.dataset.type, true);
      });
    });
    ui.jump.addEventListener("click", () => {
      const panel = activePanel();
      if (ui.state.get(panel.dataset.type).read) {
        const unread = nextUnread();
        if (unread) {
          selectTab(unread.type);
          ui.panels.find((item) => item.dataset.type === unread.type).focus();
        }
      } else {
        panel.scrollBy({ top: panel.clientHeight * 0.85 });
      }
    });
    ui.checkbox.addEventListener("change", render);
    ui.overlay.addEventListener("click", (event) => {
      if (event.target === ui.overlay) warn("Accept the policies to continue, or select Cancel to leave.");
    });
    ui.cancel.addEventListener("click", () => finish(null));
    ui.accept.addEventListener("click", () => {
      if (!allRead() || !ui.checkbox.checked) {
        render();
        return;
      }
      finish({
        accepted: true,
        documents: ui.documents.map((doc) => ({ type: doc.type, version: doc.version, reachedEnd: ui.state.get(doc.type).read })),
      });
    });

    [...document.body.children].forEach((node) => {
      if (!node.hasAttribute("inert") && node.tagName !== "SCRIPT") {
        node.setAttribute("inert", "");
        madeInert.push(node);
      }
    });
    document.body.append(ui.overlay);
    document.documentElement.style.overflow = "hidden";
    document.addEventListener("keydown", onKeydown, true);
    window.addEventListener("resize", measure);
    session = { promise };
    render();
    requestAnimationFrame(() => {
      measure();
      activePanel().focus();
    });
    return promise;
  }

  window.NexoraConsent = Object.freeze({ open });
})();
