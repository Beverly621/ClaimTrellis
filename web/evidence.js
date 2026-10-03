// A reading-only projection of the canonical selected passage. Never use this
// text for provider input, hashes, or persisted audit data.
(function (root) {
  const STOPWORDS = new Set(
    "a an and are as at be by for from has have in is it of on or that the their this to was were with using".split(" "),
  );
  const tokens = (text) =>
    (text.toLowerCase().match(/[a-z][a-z0-9'-]{1,}|\d+(?:\.\d+)?/g) || []).filter(
      (token) => !STOPWORDS.has(token),
    );

  function sentences(text) {
    const starts = [0];
    const boundary = /[.!?]["'’”\]]?\s+(?=[A-Z0-9])/g;
    for (const match of text.matchAll(boundary)) {
      const before = text.slice(0, match.index + 1);
      if (/(?:\bFig|\bDr|\bProf|\bet al)\.$/i.test(before)) continue;
      starts.push(match.index + match[0].length);
    }
    return starts.map((start, index) => {
      const end = starts[index + 1] ?? text.length;
      const raw = text.slice(start, end);
      const leading = raw.match(/^\s*/)[0].length;
      const trailing = raw.match(/\s*$/)[0].length;
      return { start: start + leading, end: end - trailing };
    }).filter((span) => span.end > span.start);
  }

  function primarySpan(claim, text) {
    const spans = sentences(text);
    const query = [...new Set(tokens(claim))];
    if (spans.length < 2 || query.length === 0) return { start: 0, end: text.length };
    let best = null;
    for (const span of spans) {
      const words = new Set(tokens(text.slice(span.start, span.end)));
      const overlap = query.filter((word) => words.has(word)).length;
      const score = overlap / Math.sqrt(Math.max(1, words.size));
      if (overlap && (!best || score > best.score)) best = { ...span, score };
    }
    return best ? { start: best.start, end: best.end } : { start: 0, end: text.length };
  }

  function blocks(text) {
    // Partition, rather than rewrite, the source. Concatenating raw blocks
    // reproduces the canonical passage byte-for-byte.
    const boundaries = new Set([0, text.length]);
    for (const match of text.matchAll(/\n\s*\n|\n(?=\s*(?:Fig(?:ure)?\.?\s*\d+|Table\s+\d+)\b)/gi)) {
      boundaries.add(match.index + match[0].length);
    }
    const ordered = [...boundaries].sort((a, b) => a - b);
    let ranges = ordered.slice(0, -1).map((start, index) => [start, ordered[index + 1]]);
    if (ranges.length === 1 && text.length > 550) {
      const spans = sentences(text);
      if (spans.length > 1) {
        ranges = [];
        let start = 0;
        for (const span of spans.slice(1)) {
          if (span.start - start < 420) continue;
          ranges.push([start, span.start]);
          start = span.start;
        }
        ranges.push([start, text.length]);
      }
    }
    return ranges.filter(([start, end]) => end > start).map(([start, end]) => {
      const value = text.slice(start, end);
      const figure = value.match(/^\s*(?:Fig(?:ure)?\.?\s*(\d+[A-Za-z]?)\s*[|.:]?)/i);
      const table = value.match(/^\s*(?:Table\s+(\d+[A-Za-z]?)\s*[|.:]?)/i);
      return {
        text: value,
        start,
        end,
        label: figure ? `Figure ${figure[1]} caption` : table ? `Table ${table[1]} caption` : null,
      };
    });
  }

  function build(claim, passage, source = {}) {
    const text = passage.text;
    const primary = primarySpan(claim, text);
    const supporting = blocks(text);
    const location = supporting.find((block) =>
      block.start <= primary.start && primary.start < block.end,
    )?.label || null;
    const locator = [];
    if (Number.isInteger(passage.page) && passage.page > 0) locator.push(["Page", passage.page]);
    if (Number.isInteger(passage.start_char) && Number.isInteger(passage.end_char)) {
      locator.push(["Characters", `${passage.start_char}–${passage.end_char}`]);
    }
    if (passage.section) locator.push(["Section", passage.section]);
    if (Number.isInteger(passage.paragraph)) locator.push(["Paragraph", passage.paragraph]);
    if (passage.locator) {
      locator.push(["Locator", passage.locator]);
    }
    if (source.title) locator.push(["Source", source.title]);
    if (source.access_tier && source.access_tier !== "unknown") {
      locator.push(["Scope", source.access_tier.replaceAll("_", " ")]);
    }
    if (location) locator.push(["Location", location]);
    return { primary: text.slice(primary.start, primary.end), supporting, locator, location };
  }

  const escape = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char],
  );

  function render(claim, passage, source, suffix = "") {
    if (!passage) return '<p class="muted">No passage retrieved.</p>';
    const view = build(claim, passage, source);
    const contextCount = view.supporting.length;
    const primaryId = "primary-passage-title" + (suffix ? "-" + escape(suffix) : "");
    const locatorId = "source-locator-title" + (suffix ? "-" + escape(suffix) : "");
    return `<div class="evidence-reading">
      <section class="primary-passage" aria-labelledby="${primaryId}">
        <h5 id="${primaryId}"><span aria-hidden="true">📌</span> Primary passage</h5>
        <p class="primary-text">${escape(view.primary)}</p>
        ${view.location ? `<p class="evidence-location">${escape(view.location)}</p>` : ""}
      </section>
      <details class="supporting-context">
        <summary><span><span aria-hidden="true">📖</span> Supporting context <small>${contextCount} source block${contextCount === 1 ? "" : "s"} · ${passage.text.length.toLocaleString()} characters</small></span><span class="context-toggle" aria-hidden="true">Show context</span></summary>
        <div class="context-blocks">${view.supporting.map((block) => `<div class="context-block">${block.label ? `<h6>${escape(block.label)}</h6>` : ""}<p>${escape(block.text)}</p></div>`).join("")}</div>
      </details>
      <section class="source-locator" aria-labelledby="${locatorId}">
        <h5 id="${locatorId}"><span aria-hidden="true">🧭</span> Source locator</h5>
        <dl>${view.locator.map(([key, value]) => `<div><dt>${escape(key)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>
      </section>
    </div>`;
  }

  const api = { build, render, sentences };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.EvidenceView = api;
})(typeof window !== "undefined" ? window : globalThis);
