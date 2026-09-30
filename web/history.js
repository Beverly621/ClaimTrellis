(function (root) {
  const escape = (value = "") => String(value ?? "").replace(/[&<>'"]/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char],
  );

  function renderItem(audit) {
    const source = audit.source?.title || audit.citation || "Uploaded source";
    const relation = audit.judgment_result?.relation.choice || "Not evaluated";
    const date = new Date(audit.provenance.created_at).toLocaleString([], {
      dateStyle: "medium", timeStyle: "short",
    });
    return `<a class="history-item" href="/?audit=${encodeURIComponent(audit.audit_id)}#result"><time datetime="${escape(audit.provenance.created_at)}">${escape(date)}</time><span class="history-claim">${escape(audit.claim)}<small>${escape(source)}</small></span><span class="mono">${escape(relation)} · v${escape(audit.current_proposal_version)}</span><span class="status-badge status-${escape(audit.review_status)}">${escape(String(audit.review_status).replaceAll("_", " "))}</span></a>`;
  }

  async function mount(documentRef, auth) {
    const list = documentRef.querySelector("#history-list");
    const status = documentRef.querySelector("#history-status");
    const more = documentRef.querySelector("#history-more");
    let offset = 0;
    const limit = 100;

    async function load() {
      more.disabled = true;
      try {
        const audits = await auth.request(`/api/v1/audits?limit=${limit}&offset=${offset}`);
        if (!audits.length && offset === 0) {
          list.innerHTML = '<p class="empty">No audits in this workspace yet.</p>';
        } else {
          list.insertAdjacentHTML("beforeend", audits.map(renderItem).join(""));
        }
        offset += audits.length;
        more.hidden = audits.length < limit;
        status.textContent = `${offset} audit${offset === 1 ? "" : "s"} in this view`;
      } catch (error) {
        status.textContent = error.message;
        more.hidden = false;
        more.textContent = "Retry loading →";
      } finally {
        more.disabled = false;
      }
    }

    try {
      await auth.start();
      more.addEventListener("click", load);
      await load();
    } catch (error) {
      status.textContent = error.message;
      more.hidden = false;
      more.textContent = "Retry workspace →";
      more.addEventListener("click", () => mount(documentRef, auth), { once: true });
    }
  }

  const api = { renderItem, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document !== "undefined") mount(document, root.ClaimTrellisAuth);
})(typeof window !== "undefined" ? window : globalThis);
