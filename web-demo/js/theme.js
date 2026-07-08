// Manual light/dark override for the topbar toggle. A saved choice is written to
// <html data-theme> (also done inline in index.html to avoid a flash on load) and
// persisted; with no saved choice we fall back to the OS preference, which the
// stylesheet handles on its own via prefers-color-scheme.

const KEY = "deputy-theme";
const root = document.documentElement;
const media = window.matchMedia("(prefers-color-scheme: dark)");

function persist(theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* private mode / storage disabled — the toggle still works for this session */
  }
}

function effectiveTheme() {
  return root.dataset.theme || (media.matches ? "dark" : "light");
}

export function initTheme(button) {
  if (!button) return;

  const sync = () => {
    const dark = effectiveTheme() === "dark";
    button.textContent = dark ? "\u2600\uFE0E" : "\u263D\uFE0E";
    button.setAttribute("aria-pressed", String(dark));
    button.title = dark ? "Switch to light theme" : "Switch to dark theme";
  };

  button.addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    persist(next);
    sync();
  });

  media.addEventListener?.("change", () => {
    if (!root.dataset.theme) sync();
  });

  sync();
}
