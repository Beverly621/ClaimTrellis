(function (root) {
  const KEY = "claimtrellis-theme-v2";
  function readTheme(storage) {
    try {
      return storage?.getItem(KEY) === "night" ? "night" : "light";
    } catch {
      return "light";
    }
  }
  function availableStorage() {
    try {
      return root.localStorage;
    } catch {
      return null;
    }
  }
  function mount(documentRef, storage) {
    let theme = readTheme(storage);
    const controls = documentRef.querySelectorAll("[data-theme-choice]");
    function apply(value) {
      theme = value === "night" ? "night" : "light";
      documentRef.documentElement.dataset.theme = theme;
      const themeColor = documentRef.querySelector('meta[name="theme-color"]');
      themeColor?.setAttribute("content", theme === "night" ? "#0a1118" : "#edf3f6");
      controls.forEach((control) => {
        control.setAttribute("aria-pressed", String(control.dataset.themeChoice === theme));
      });
    }
    controls.forEach((control) =>
      control.addEventListener("click", () => {
        apply(control.dataset.themeChoice);
        try {
          storage?.setItem(KEY, theme);
        } catch {
          // Theme remains usable without storage.
        }
      }),
    );
    apply(theme);
    return { current: () => theme };
  }
  const api = { readTheme, mount, KEY };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document !== "undefined") {
    const storage = availableStorage();
    document.documentElement.dataset.theme = readTheme(storage);
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => mount(document, storage), { once: true });
    } else {
      mount(document, storage);
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
