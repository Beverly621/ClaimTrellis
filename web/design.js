/* Original ClaimTrellis motion: no third-party scripts, fonts, or tracking. */
(() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const toggle = document.querySelector("#motion-toggle");
  let paused = reduced.matches;
  const applyMotion = () => {
    document.body.classList.toggle("motion-paused", paused);
    document.body.classList.toggle("motion-enabled", !paused);
    toggle.setAttribute("aria-pressed", String(paused));
    toggle.textContent = paused ? "Resume motion ▷" : "Pause motion Ⅱ";
  };
  toggle.addEventListener("click", () => {
    paused = !paused;
    applyMotion();
  });
  reduced.addEventListener("change", () => {
    paused = reduced.matches;
    applyMotion();
  });
  applyMotion();
  document.querySelectorAll(".mobile-nav a").forEach((link) => {
    link.addEventListener("click", () =>
      link.closest("details").removeAttribute("open"),
    );
  });
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.remove("waiting");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.1 },
  );
  document.querySelectorAll(".reveal").forEach((el) => {
    el.classList.add("waiting");
    observer.observe(el);
  });
  if (matchMedia("(pointer:fine)").matches) {
    document.querySelectorAll(".magnetic").forEach((el) => {
      el.addEventListener("pointermove", (event) => {
        if (paused) return;
        const rect = el.getBoundingClientRect();
        el.style.transform = `translate(${(event.clientX - rect.left - rect.width / 2) * 0.08}px,${(event.clientY - rect.top - rect.height / 2) * 0.12}px)`;
      });
      el.addEventListener("pointerleave", () => {
        el.style.transform = "";
      });
    });
  }
  const relations = [
    [
      "supports",
      "Supports",
      "The source directly supports the material claim, with its boundaries intact.",
      "Accuracy improved on task A.",
      "Accuracy improved on task A.",
      "The claim and reported result align.",
      "↗",
    ],
    [
      "partially_supports",
      "Partially supports",
      "The source supports a material part of the claim, but its scope is narrower.",
      "Accuracy improved across all tasks.",
      "Accuracy improved on task A only.",
      "One reported task cannot establish an all-task claim.",
      "◐",
    ],
    [
      "contradicts",
      "Contradicts",
      "The source states or directly implies an incompatible result.",
      "Accuracy improved on task A.",
      "Accuracy decreased on task A.",
      "The reported direction differs from the claim.",
      "↘",
    ],
    [
      "not_addressed",
      "Not addressed",
      "The available evidence does not address the claim either way.",
      "Accuracy improved on task A.",
      "The study measured processing time only.",
      "The reported measure does not address accuracy.",
      "—",
    ],
    [
      "insufficient_context",
      "Insufficient context",
      "The excerpt lacks enough context to make a reliable comparison.",
      "Accuracy improved on task A.",
      "An improvement was observed…",
      "The task and outcome are not identified.",
      "…",
    ],
    [
      "source_unavailable",
      "Source unavailable",
      "The source content needed for comparison cannot be accessed or read.",
      "Accuracy improved on task A.",
      "Source content unavailable.",
      "No source comparison can be made.",
      "∅",
    ],
  ];
  const list = document.querySelector("#relation-options");
  const detail = document.querySelector("#relation-detail");
  const select = (index) => {
    const [key, title, definition, claim, evidence, reason, symbol] =
      relations[index];
    list.querySelectorAll("button").forEach((button, i) => {
      button.setAttribute("aria-selected", String(i === index));
      button.tabIndex = i === index ? 0 : -1;
    });
    detail.setAttribute("aria-labelledby", "relation-" + key);
    detail.innerHTML = `<span class="micro accent">RELATION / 0${index + 1}</span><span class="relation-symbol" aria-hidden="true">${symbol}</span><h3>${title}</h3><p>${definition}</p><dl><dt>ILLUSTRATIVE CLAIM</dt><dd>${claim}</dd><dt>ILLUSTRATIVE EVIDENCE</dt><dd>${evidence}</dd><dt>WHY THIS RELATION</dt><dd>${reason}</dd></dl><p class="locator" style="margin-top:24px">Synthetic example · no provider probability asserted.</p>`;
  };
  relations.forEach(([key], index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.id = "relation-" + key;
    button.className = "relation-option";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "relation-detail");
    button.innerHTML = `<span>0${index + 1}</span>${key}<b aria-hidden="true">→</b>`;
    button.addEventListener("click", () => select(index));
    button.addEventListener("keydown", (event) => {
      let next = index;
      if (["ArrowDown", "ArrowRight"].includes(event.key))
        next = (index + 1) % 6;
      else if (["ArrowUp", "ArrowLeft"].includes(event.key))
        next = (index + 5) % 6;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = 5;
      else return;
      event.preventDefault();
      select(next);
      list.children[next].focus();
    });
    list.append(button);
  });
  select(0);
})();
