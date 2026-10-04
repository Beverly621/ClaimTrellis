const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const html = readFileSync(join(__dirname, "index.html"), "utf8");
const app = readFileSync(join(__dirname, "app.js"), "utf8");
const css = readFileSync(join(__dirname, "styles.css"), "utf8");

test("hero entries share sizing and retain distinct accessible labels", () => {
  assert.match(html, /class="button account-entry" id="hero-secondary"/);
  assert.match(css, /\.hero \.actions > button \{[^}]*width: 240px;[^}]*min-height: 48px;/);
  assert.match(html, /aria-hidden="true">📮<\/span> Sign in<\/button>/);
});

test("removed hero divider/copy and entry arrows do not return on auth updates", () => {
  for (const copy of ["INDEPENDENT RESEARCH INSTRUMENT", "FIELD NOTES / 001", "A paper trail for the claims that matter."]) {
    assert.equal(html.includes(copy), false);
  }
  assert.equal(html.includes('class="hero-top"'), false);
  for (const id of ["hero-primary", "hero-secondary", "header-action"]) {
    const button = html.match(new RegExp(`id="${id}"[^>]*>(.*?)</button>`, "s"))[1];
    assert.equal(button.includes("↗"), false);
  }
  const renderAuth = app.slice(app.indexOf("const primary = auth.kind"), app.indexOf('$("#workspace-identity").hidden'));
  assert.equal(renderAuth.includes("↗"), false);
  assert.equal(renderAuth.includes("✉"), false);
});
