(() => {
  const container = document.getElementById("legalDocument");
  const doc = window.NEXORA_LEGAL.documents.find((item) => item.type === container.dataset.document);
  const heading = document.createElement("h1");
  heading.textContent = doc.title;
  const meta = document.createElement("p");
  meta.className = "legal-meta";
  meta.textContent = `Version ${doc.version} · Effective ${doc.effective}`;
  const content = document.createElement("div");
  content.innerHTML = doc.html; // trusted, versioned text shipped with the site
  container.append(heading, meta, content);
})();
