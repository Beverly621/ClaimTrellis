const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { readTheme, mount, KEY } = require("./theme.js");

function control(choice) {
  return {
    dataset: { themeChoice: choice },
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(_name, callback) { this.click = callback; },
  };
}

test("Light is the first-visit default and Night persists across pages", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  };
  const light = control("light");
  const night = control("night");
  const documentRef = {
    documentElement: { dataset: {} },
    querySelectorAll: () => [light, night],
    querySelector: () => null,
  };
  const theme = mount(documentRef, storage);
  assert.equal(theme.current(), "light");
  assert.equal(documentRef.documentElement.dataset.theme, "light");
  assert.equal(light.attributes["aria-pressed"], "true");
  night.click();
  assert.equal(values.get(KEY), "night");
  assert.equal(readTheme(storage), "night");
  assert.equal(night.attributes["aria-pressed"], "true");
  assert.equal(mount(documentRef, storage).current(), "night");
});

test("unknown or unavailable storage never prevents a Light theme", () => {
  assert.equal(readTheme({ getItem: () => "unknown" }), "light");
  assert.equal(readTheme({ getItem: () => { throw new Error("blocked"); } }), "light");
});

test("home and history set saved theme before loading their stylesheets", () => {
  for (const page of ["index.html", "history.html"]) {
    const html = readFileSync(join(__dirname, page), "utf8");
    assert.ok(html.indexOf('src="/assets/theme.js"') < html.indexOf('href="/assets/styles.css"'));
    assert.match(html, /data-theme-choice="light"/);
    assert.match(html, /data-theme-choice="night"/);
  }
});
