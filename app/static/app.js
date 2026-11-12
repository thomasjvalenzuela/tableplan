/* TablePlan — front end (vanilla JS, no build step) */
"use strict";

// ------------------------------------------------------------------ icons
const P = {
  home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/>',
  cal: '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  cart: '<path d="M3 4h2.5l2.2 10.5h10.6L20.5 7H6.4"/><circle cx="9.5" cy="19" r="1.4"/><circle cx="17" cy="19" r="1.4"/>',
  box: '<path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5z"/><path d="M4 8.5 12 13l8-4.5M12 13v7"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  share: '<path d="M12 3v12M7.5 7.5 12 3l4.5 4.5"/><path d="M5 12v6.5A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  shuffle: '<path d="M16 4h4v4M4 20 20 4M20 16v4h-4M15 15l5 5M4 4l5 5"/>',
  sparkle: '<path d="M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.5l-1.8-5.9L4.5 10.8 10.2 9z"/><path d="M19 3v3M17.5 4.5h3"/>',
  camera: '<path d="M4 8h3l2-2.5h6L17 8h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  link: '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/>',
  snow: '<path d="M12 2.5v19M4 7l16 10M20 7 4 17"/><path d="m9.5 4.5 2.5 2 2.5-2M9.5 19.5l2.5-2 2.5 2"/>',
  fridge: '<rect x="5.5" y="2.5" width="13" height="19" rx="2.5"/><path d="M5.5 10h13M9 6v1.5M9 13v3"/>',
  shelf: '<path d="M3.5 7h17M3.5 13h17M3.5 19h17"/><rect x="6" y="3" width="3" height="4"/><rect x="11" y="9" width="4" height="4"/><rect x="15" y="15" width="3" height="4"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m4 7 8 6 8-6"/>',
  print: '<path d="M7 9V3.5h10V9"/><rect x="3.5" y="9" width="17" height="8" rx="2"/><path d="M7 14h10v6.5H7z"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  bolt: '<path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  chevL: '<path d="m15 18-6-6 6-6"/>',
  chevR: '<path d="m9 18 6-6-6-6"/>',
  chevU: '<path d="m6 15 6-6 6 6"/>',
  chevD: '<path d="m6 9 6 6 6-6"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 19V7.5A1.5 1.5 0 0 1 5.5 6H10"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  leaf: '<path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14z"/><path d="M5 19 13 11"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4"/>',
  open: '<path d="M4 20h16M6 16l2-9h8l2 9M10 7V4h4v3"/>',
  dish: '<path d="M3 15h18M5 15a7 7 0 0 1 14 0M12 8V6M10 6h4M4 18h16"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.6c2.3.2 4 1.7 4.5 4.4"/>',
  chef: '<path d="M7 14.5V20h10v-5.5"/><path d="M7 14.5a4 4 0 0 1-1-7.9A5 5 0 0 1 12 3.5a5 5 0 0 1 6 3.1 4 4 0 0 1-1 7.9z"/><path d="M7 17h10"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
  scan: '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M8 8v8M11 8v8M13.5 8v8M16 8v8"/>',
  dollar: '<path d="M12 3v18M16.5 7.5C16 6 14.3 5 12 5s-4.5 1.2-4.5 3.4c0 4.8 9 2.6 9 7.2 0 2.2-2 3.4-4.5 3.4s-4.3-1.1-4.8-2.8"/>',
  edit: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  more: '<circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V6A2.5 2.5 0 0 0 13 3.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/>',
  down: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
  store: '<path d="M4 9.5 5.5 4h13L20 9.5"/><path d="M4 9.5a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0 2.7 2.7 0 0 0 5.3 0"/><path d="M5.5 12v8h13v-8M10 20v-4.5h4V20"/>',
  shield: '<path d="M12 3.5 5 6v5.5c0 4.3 3 7.7 7 9 4-1.3 7-4.7 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
  github: '<path d="M12 2.5a9.5 9.5 0 0 0-3 18.5c.5.1.7-.2.7-.5v-1.7c-2.6.6-3.2-1.2-3.2-1.2-.4-1.1-1-1.4-1-1.4-.9-.6 0-.6 0-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.6.3-1.1.6-1.3-2.1-.2-4.3-1-4.3-4.7 0-1 .4-1.9 1-2.6-.1-.2-.4-1.2.1-2.6 0 0 .8-.3 2.6 1a9 9 0 0 1 4.8 0c1.8-1.3 2.6-1 2.6-1 .5 1.4.2 2.4.1 2.6.6.7 1 1.6 1 2.6 0 3.7-2.2 4.5-4.3 4.7.3.3.6.9.6 1.8v2.6c0 .3.2.6.7.5A9.5 9.5 0 0 0 12 2.5z"/>',
};
const ic = (n, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24">${P[n] || ""}</svg>`;

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Recipe text, image credits and links come from scraped pages and AI output, so treat every server value as untrusted:
// esc() it into HTML, run URLs through safeUrl() (defined in setup.js as _safeUrl), and build path segments with enc().
const safeUrl = _safeUrl;
const enc = (v) => encodeURIComponent(String(v ?? ""));
// A CSS url("…") token for inline style attributes: the URL is vetted, the characters that could end the token are
// percent-encoded, and the whole thing is HTML-escaped for the attribute. Returns "" for unsafe URLs.
const cssUrl = (u) => { const s = safeUrl(u, true); return s ? `url('${esc(s.replace(/['"()\\\s]/g, (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0").toUpperCase()))}')` : ""; };
const bgStyle = (u) => { const c = cssUrl(u); return c ? `style="background-image:${c}"` : ""; };
// External link attributes (href + target + rel), or "" when the URL isn't http(s)/same-origin.
const extLink = (u) => { const s = safeUrl(u); return s ? `href="${esc(s)}" target="_blank" rel="noopener noreferrer"` : ""; };
// Look = theme (Mono, Midnight, Blossom, Forest) + mode (System, Light, Dark). Your account's choice, with this device's
// copy as the fallback; a cookie lets the server set it on the page before the first paint (no flash).
const LOOKS = { mono: ["Mono", "#FFFFFF", "#000000", "#0A0A0A"], midnight: ["Midnight", "#FFFFFF", "#050B1A", "#0B1F4D"],
  blossom: ["Blossom", "#FFF5F7", "#0D070B", "#B8235E"], forest: ["Forest", "#F3FAF6", "#07120E", "#176B50"] };
const lsGet = (k) => { try { return localStorage.getItem(k) || ""; } catch (_) { return ""; } };
const currentTheme = () => state.cfg?.settings?.theme || lsGet("tp.theme") || "system";            // the mode
const currentLook = () => { const p = state.cfg?.settings?.palette || lsGet("tp.palette"); return LOOKS[p] ? p : "mono"; };
function applyTheme(mode = currentTheme(), look = currentLook()) {
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") root.dataset.mode = mode; else delete root.dataset.mode;
  if (look && look !== "mono") root.dataset.theme = look; else delete root.dataset.theme;
  const [, light, dark] = LOOKS[look] || LOOKS.mono;
  const metas = $$('meta[name="theme-color"]');
  metas.forEach((m) => {
    const isDark = /dark/.test(m.getAttribute("media") || "");
    m.setAttribute("content", mode === "light" ? light : mode === "dark" ? dark : isDark ? dark : light);
  });
  try {
    localStorage.setItem("tp.theme", mode); localStorage.setItem("tp.palette", look);
    document.cookie = `tp_look=${look}.${mode}; Path=/; Max-Age=31536000; SameSite=Strict${location.protocol === "https:" ? "; Secure" : ""}`;
  } catch (_) {}
}
function setTheme(mode, look) { if (state.cfg?.settings) { if (mode) state.cfg.settings.theme = mode; if (look) state.cfg.settings.palette = look; } applyTheme(mode || currentTheme(), look || currentLook()); }
// Large titles collapse into a compact blurred bar once they scroll away.
function updateCompactBar() {
  const bar = document.getElementById("cbar"); if (!bar) return;
  const h = document.querySelector("#app h1.title, #app .rd2 h1");
  const show = !!h && !$("#cook") && h.getBoundingClientRect().bottom < (parseFloat(getComputedStyle(bar).height) || 46);
  if (show) bar.firstElementChild.textContent = h.textContent.trim();
  bar.classList.toggle("on", show);
}
window.addEventListener("scroll", updateCompactBar, { passive: true });
const BUILD = (() => { try { return new URL(document.currentScript.src).searchParams.get("v") || ""; } catch (_) { return ""; } })();
const app = $("#app");
const state = { tab: "home", cfg: null, summary: null, listId: localStorage.getItem("tp.list") || null, pantryFilter: "all", plan: null };

async function api(method, path, body) {
  const headers = { "X-TablePlan": "1" };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (res.status === 401 && data && data.auth && !path.startsWith("/api/login")) { renderLogin(() => location.reload()); throw new Error("Sign in required"); }
  if (!res.ok) { const e = new Error((data && data.error) || `Request failed (${res.status})`); e.status = res.status; e.data = data; throw e; }
  return data;
}

const pad = (n) => String(n).padStart(2, "0");
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const fmt = (d, o) => d.toLocaleDateString(undefined, o);
const dayName = (s) => { const d = parseISO(s), t = today(); const diff = Math.round((d - t) / 864e5);
  return diff === 0 ? "Today" : diff === 1 ? "Tomorrow" : fmt(d, { weekday: "short" }); };
const cap = (s) => (s || "").charAt(0).toUpperCase() + (s || "").slice(1);
const imgUrl = (r, size = "min") => (r && r.id && r.has_image !== false ? `/img/${enc(r.id)}?size=${enc(size)}${r.image_v ? "&v=" + enc(r.image_v) : ""}` : null);

function expiryPill(item) {
  const d = item.days_left;
  if (d === null || d === undefined) return `<span class="pill none">No date</span>`;
  if (d < 0) return `<span class="pill bad">Expired</span>`;
  if (d === 0) return `<span class="pill bad">Today</span>`;
  if (d === 1) return `<span class="pill soon">Tomorrow</span>`;
  if (d <= 3) return `<span class="pill soon">${d} days</span>`;
  if (d <= 6) return `<span class="pill ok">${d} days</span>`;
  return `<span class="pill ok">${fmt(parseISO(item.expires_on), { month: "short", day: "numeric" })}</span>`;
}
const locIcon = { fridge: ["fridge", "bg-blue"], freezer: ["snow", "bg-teal"], pantry: ["shelf", "bg-orange"] };

// ------------------------------------------------------------------ toast & sheets
let toastTimer;
function toast(msg, actionLabel, action) {
  let t = $(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.innerHTML = `<span>${esc(msg)}</span>${actionLabel ? `<button>${esc(actionLabel)}</button>` : ""}`;
  if (actionLabel) $("button", t).onclick = () => { t.classList.remove("on"); action(); };
  requestAnimationFrame(() => t.classList.add("on"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), actionLabel ? 8000 : 3200);
}
const fail = (e) => toast(e.message || String(e));
const c_native = () => state.cfg?.backend === "native";
// Inventory places: fridge, freezer, pantry and shelves like the spice cabinet → [[key, label], …]
const invPlaces = () => ((state.cfg?.settings?.locations) || [{ key: "fridge", label: "Fridge" }, { key: "freezer", label: "Freezer" }, { key: "pantry", label: "Pantry" }]).map((p) => [p.key, p.label]);
// "17:40" → "5:40" (the board is compact; AM/PM only when it's not the evening)
const clock12 = (t) => { const m = /^(\d{1,2}):(\d{2})$/.exec(t || ""); if (!m) return t || ""; const h = +m[1]; return `${((h + 11) % 12) + 1}:${m[2]}${h < 12 ? " AM" : ""}`; };

function openSheet(title, html, { onMount, wide } = {}) {
  closeSheet(true);
  const layer = $("#layer");
  layer.innerHTML = `<div class="scrim"></div><div class="sheet" role="dialog" aria-modal="true">
    <div class="grabber"></div><div class="sheet-h"><h3>${esc(title)}</h3><button class="x" aria-label="Close">${ic("x")}</button></div>
    <div class="sheet-body">${html}</div></div>`;
  const scrim = $(".scrim", layer), sheet = $(".sheet", layer);
  scrim.onclick = () => closeSheet();
  $(".x", sheet).onclick = () => closeSheet();
  // swipe down to dismiss
  let y0 = null;
  $(".grabber", sheet).parentElement.addEventListener("touchstart", (e) => { if (sheet.scrollTop <= 0) y0 = e.touches[0].clientY; }, { passive: true });
  sheet.addEventListener("touchmove", (e) => { if (y0 !== null) { const dy = e.touches[0].clientY - y0; if (dy > 0) sheet.style.transform = `translateY(${dy}px)`; } }, { passive: true });
  sheet.addEventListener("touchend", (e) => { if (y0 === null) return; const dy = e.changedTouches[0].clientY - y0; y0 = null; sheet.style.transform = ""; if (dy > 110) closeSheet(); });
  requestAnimationFrame(() => { scrim.classList.add("on"); sheet.classList.add("on"); });
  document.body.style.overflow = "hidden";
  if (onMount) onMount(sheet);
  return sheet;
}
function closeSheet(instant) {
  const layer = $("#layer");
  if (!layer.firstChild) return;
  document.body.style.overflow = "";
  if (instant) { layer.innerHTML = ""; return; }
  $(".scrim", layer)?.classList.remove("on");
  $(".sheet", layer)?.classList.remove("on");
  setTimeout(() => { layer.innerHTML = ""; }, 280);
}
const sheetBody = () => $("#layer .sheet-body");

// ------------------------------------------------------------------ tabs / router
const TABS = [["home", "Home", "home"], ["recipes", "Recipes", "book"], ["meals", "Plan", "cal"], ["list", "Shopping", "cart"], ["pantry", "Inventory", "box"]];
const REPO = "https://github.com/thomasjvalenzuela/tableplan";
function renderTabs() {
  const v = state.cfg?.version || "";
  $("#tabs").innerHTML = `<div class="nav-brand"><img src="/static/icon-180.png" alt="">TablePlan</div>` +
    TABS.map(([id, label, icon]) => `<button class="tab ${state.tab === id ? "on" : ""}" data-tab="${esc(id)}">${ic(icon)}<span>${label}</span></button>`).join("") +
    `<div style="flex:1" class="desktop-only"></div><button class="tab desktop-only ${upd() ? "dot" : ""}" id="nav-settings">${ic("gear")}<span>Settings</span></button>
     <div class="nav-foot"><span>Version ${esc(v)}</span><a ${extLink(state.cfg?.repo_url) || extLink(REPO)} aria-label="TablePlan on GitHub" title="TablePlan on GitHub">${ic("github")}</a></div>`;
  $$("#tabs .tab[data-tab]").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
  $("#nav-settings").onclick = () => openSettings();
}
function go(tab) {
  state.tab = tab;
  document.body.classList.remove("selecting");
  if (location.hash !== "#" + tab) history.pushState(null, "", "#" + tab);
  lastHash = location.hash;
  renderTabs();
  window.scrollTo(0, 0);
  const done = ({ home: renderHome, recipes: renderRecipes, meals: renderMeals, list: renderList, pantry: renderPantry }[tab] || renderHome)();
  // async renders can leave the old page's scroll offset behind (scroll anchoring); start each tab at the top
  Promise.resolve(done).then(() => { if (location.hash.slice(1) === tab || (!location.hash && tab === "home")) window.scrollTo(0, 0); }, () => {});
}
let lastHash = null;
function route() {
  setTimeout(updateCompactBar, 60);
  if (location.hash === lastHash && document.getElementById("app").childElementCount) return;
  lastHash = location.hash;
  document.body.classList.remove("selecting");
  const h = decodeURIComponent(location.hash.slice(1));
  if (h.startsWith("recipe/")) { window.scrollTo(0, 0); return renderRecipe(h.slice(7)); }
  if (h.startsWith("edit/")) return renderRecipeEditor(h.slice(5));
  if (h === "diary") { window.scrollTo(0, 0); return renderDiary(); }
  if (h === "spending") { window.scrollTo(0, 0); return renderSpending(); }
  if (h.startsWith("make/use/")) { window.scrollTo(0, 0); return renderMake("use_up", h.slice(9)); }
  if (h === "make" || h.startsWith("make/")) { window.scrollTo(0, 0); return renderMake({ use: "use_up", almost: "almost", ideas: "ideas" }[h.slice(5)] || "ready"); }
  if (h === "recipes/ai") { rstate.filter = "ai"; state.tab = "recipes"; renderTabs(); window.scrollTo(0, 0); return renderRecipes(); }
  if (h === "inventory/expiring") { window.scrollTo(0, 0); return renderExpiring(); }
  go(TABS.some((t) => t[0] === h) ? h : "home");
}
const upd = () => !!state.update?.update_available;
const topbar = (extra = "") => `${storageBar()}${updateBar()}<div class="topbar">${extra}<button class="round-btn ${upd() ? "dot" : ""}" id="btn-settings" aria-label="Settings">${ic("gear")}</button></div>`;
// Shown on every screen when the data folder would be wiped by a container rebuild.
const DOCS_BACKUPS = "https://github.com/thomasjvalenzuela/tableplan/blob/main/docs/install.md#backups";
function storageBar() {
  if (state.cfg?.storage?.persistent !== false) return "";
  return `<div class="storage-bar" role="alert"><span class="sb-ic">⚠️</span><span>Your data isn't on a persistent volume and will be lost when this container is rebuilt. <a ${extLink(DOCS_BACKUPS)}>See docs/install.md#backups</a></span></div>`;
}
function updateBar() {
  if (!upd()) return "";
  let snooze = null; try { snooze = JSON.parse(localStorage.getItem("tp.updSnooze") || "null"); } catch (_) {}
  if (snooze && snooze.v === state.update.latest && Date.now() < snooze.until) return "";
  return `<div class="update-bar" id="upd-bar"><span>${ic("refresh")}<b>TablePlan ${esc(state.update.latest)} is available</b></span><span><button id="upd-how">How to update</button><button id="upd-later" aria-label="Later">${ic("x")}</button></span></div>`;
}
function bindUpdateBar() {
  $("#upd-how") && ($("#upd-how").onclick = () => openUpdateHelp());
  $("#upd-later") && ($("#upd-later").onclick = () => { try { localStorage.setItem("tp.updSnooze", JSON.stringify({ v: state.update.latest, until: Date.now() + 864e5 })); } catch (_) {} $("#upd-bar")?.remove(); });
}
// The build this page loaded (index.html links app.js?v=<version>); when the server moves on, reload.
function staleBuild(server) {
  if (!BUILD || !server || server === BUILD) return;
  const busy = !!$("#layer")?.firstChild || !!$("#cook");
  let tried = "";
  try { tried = sessionStorage.getItem("tp.reloadFor") || ""; } catch (_) {}
  if (!busy && tried !== server) {
    try { sessionStorage.setItem("tp.reloadFor", server); } catch (_) {}
    location.reload();
    return;
  }
  if (!$("#stale-pill")) {
    document.body.insertAdjacentHTML("beforeend", `<button class="stale-pill" id="stale-pill">TablePlan was updated · Reload</button>`);
    $("#stale-pill").onclick = () => location.reload();
  }
}
async function checkUpdate() {
  try {
    const was = upd(), u = await api("GET", "/api/version");
    state.update = u;
    staleBuild(u.version);
    if (u.update_available && !was) {
      if (!$("#upd-bar") && $(".topbar")) { $(".topbar").insertAdjacentHTML("beforebegin", updateBar()); bindUpdateBar(); }
      $("#btn-settings")?.classList.add("dot"); renderTabs();
    }
  } catch (_) {}
}
function bindTopbar() { $("#btn-settings") && ($("#btn-settings").onclick = openSettings); bindUpdateBar(); }
const loading = () => `<div class="spinner"></div>`;

// ------------------------------------------------------------------ HOME
async function renderHome() {
  app.innerHTML = topbar(`<button class="round-btn" id="btn-add" aria-label="Add recipe">${ic("plus")}</button>`) +
    `<h1 class="title">Today</h1><div class="subtitle">${esc(fmt(new Date(), { weekday: "long", month: "long", day: "numeric" }))}</div>${loading()}`;
  bindTopbar(); $("#btn-add").onclick = openAddRecipe;
  let s, list = null;
  try {
    [s, list] = await Promise.all([api("GET", "/api/summary"), api("GET", "/api/list").catch(() => null)]);
    state.summary = s;
  } catch (e) { const sp = app.querySelector(".spinner"); if (sp) sp.outerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  if (state.tab !== "home" || !app.querySelector(".spinner")) return;
  const todayISO = isoDate(today());
  const byDate = (iso) => s.week.filter((e) => e.date === iso).sort((a, b) => (a.entry_type === "dinner" ? -1 : b.entry_type === "dinner" ? 1 : order(a.entry_type) - order(b.entry_type)));
  const tonightAll = byDate(todayISO), tonight = tonightAll[0];

  let html = "";
  if (!s.mealie_ok) html += `<button class="banner" id="fix-mealie">${esc(s.error)}</button>`;
  html += zoomNudge();
  if (+s.review_count) html += `<button class="nudge" id="home-review"><span class="ic bg-ink">${ic("book")}</span><span><b>${esc(plural(+s.review_count, "recipe"))} ${+s.review_count === 1 ? "needs" : "need"} a quick look</b><small>Scanned recipes waiting for a name or an answer</small></span><span class="sdot warn" aria-hidden="true"></span><span class="chev">${ic("chevR")}</span></button>`;
  if (+s.review_items) html += `<button class="nudge" id="home-inv-review"><span class="ic bg-ink">${ic("scan")}</span><span><b>${esc(plural(+s.review_items, "item"))} to review</b><small>Scanned items the product databases didn't know</small></span><span class="sdot warn" aria-hidden="true"></span><span class="chev">${ic("chevR")}</span></button>`;
  html += homeContextCard(s, tonight);
  html += homeStats(s, list);
  html += `<section class="home-card budget-w" id="home-budget" hidden aria-label="Grocery budget"></section>`;
  html += `<section class="home-card cl-w" id="home-cl" hidden aria-label="Getting started"></section>`;

  // 1. Shopping: the next few things to buy, soonest meal first
  const toBuy = ((list && list.items) || []).filter((i) => !i.checked);
  const soonest = (i) => (i.uses && i.uses.length ? i.uses[0].date : "9999");
  const top = toBuy.slice().sort((a, b) => soonest(a).localeCompare(soonest(b))).slice(0, 5);
  const showStores = ((list && list.stores) || []).length && toBuy.some((i) => i.store_id != null);
  html += `<section class="home-card shop-w" aria-label="Shopping list"><div class="hc-h"><h2>Shopping list <span>· ${esc(plural(toBuy.length, "item"))} to buy</span></h2><button class="link-btn" data-go="list">View all ›</button></div>
    ${top.length ? `<div class="shop-rows">${top.map((i) => `<div class="shop-row" data-sid="${esc(i.id)}"><button class="check sq" data-buy="${esc(i.id)}" aria-label="Got ${esc(itemTitle(i))}">${ic("check")}</button>
      <div class="main"><div class="a">${esc(itemTitle(i))}</div><div class="b">${esc([itemSub(i), showStores ? storeName(list, i.store_id) : ""].filter(Boolean).join(" · "))}</div></div>
      ${i.uses && i.uses.length ? `<span class="for-tag">for ${esc(wkShort(i.uses[0].date))}</span>` : ""}</div>`).join("")}</div>`
      : `<div class="all-set">You're all set for this week ✓</div>`}</section>`;

  // 2. This week: today + 6 days, dinner first
  html += `<section class="home-week" aria-label="This week"><div class="hc-h"><h2>This week</h2><button class="link-btn" data-go="meals">Plan ›</button></div><div class="wk">`;
  for (let i = 0; i < 7; i++) {
    const iso = isoDate(addDays(today(), i)), all = byDate(iso), e = all[0];
    const img = e ? imgUrl(e.recipe) : null;
    html += e ? `<button class="wk-day ${e.cooked ? "cooked" : ""}" data-entry="${esc(e.id)}"><span class="wk-d">${esc(i === 0 ? "Today" : wkShort(iso))}</span><span class="wk-n">${esc(parseISO(iso).getDate())}</span>
        <span class="wk-plate ${img ? "" : "ph"}" ${img ? bgStyle(img) : ""}>${img ? "" : ic("dish")}${e.cooked ? `<span class="wk-ok" aria-label="cooked">✓</span>` : +e.missing ? `<span class="wk-dot" aria-label="Missing ${esc(e.missing)}"></span>` : ""}</span>
        <span class="wk-name">${esc(entryName(e))}</span>${all.length > 1 ? `<span class="wk-more">+${esc(all.length - 1)} more</span>` : ""}</button>`
      : `<button class="wk-day empty" data-plan-day="${esc(iso)}"><span class="wk-d">${esc(i === 0 ? "Today" : wkShort(iso))}</span><span class="wk-n">${esc(parseISO(iso).getDate())}</span><span class="wk-plate ph">${ic("plus")}</span><span class="wk-name muted">Add</span></button>`;
  }
  html += `</div></section>`;

  // 3. Tonight: only when something is planned today
  if (tonight && tonight.recipe) {
    const img = imgUrl(tonight.recipe, "full"), miss = +tonight.missing || 0;
    html += `<section class="tonight" aria-label="Tonight"><div class="tn-band"><h2>Tonight</h2><span>${esc(fmt(new Date(), { weekday: "long", month: "short", day: "numeric" }))}${tonightAll.length > 1 ? ` · +${esc(tonightAll.length - 1)} more` : ""}</span></div>
      <button class="tn-plate ${img ? "" : "ph"}" id="tn-open" ${img ? bgStyle(img) : ""} aria-label="Open ${esc(entryName(tonight))}">${img ? "" : "🍽️"}</button>
      <div class="tn-name">${esc(entryName(tonight))}</div>
      <div class="tn-acts">${tonight.cooked ? `<span class="pill ok">Cooked ✓</span>` : miss ? `<button class="btn sec small" id="tn-miss">${ic("cart")} Missing ${esc(miss)}</button>` : `<button class="btn small" id="tn-cook">${ic("play")} Start cooking</button>`}</div></section>`;
  }

  html += `<section class="home-card diary-w" id="home-diary" hidden aria-label="Cooking diary"></section>`;
  app.querySelector(".spinner").outerHTML = `<div class="home fade-in">${html}</div>`;
  homeChecklist($("#home-cl"));
  homeBudget($("#home-budget"));
  $("#home-review") && ($("#home-review").onclick = () => openReview());
  $("#home-inv-review") && ($("#home-inv-review").onclick = () => openReviewItems(renderHome));
  setReviewBadge(+s.review_count || 0);
  api("GET", "/api/diary?limit=3").then((d) => {
    const box = $("#home-diary"); if (!box || !(d.entries || []).length) return;
    box.hidden = false;
    box.innerHTML = `<div class="hc-h"><h2>Cooking diary</h2><button class="link-btn" id="diary-all">View all ›</button></div>${diaryTimeline(d.entries)}`;
    $("#diary-all").onclick = () => { location.hash = "diary"; };
    bindDiaryTimeline(box);
  }).catch(() => {});
  $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  $("#stat-exp") && ($("#stat-exp").onclick = () => { location.hash = "inventory/expiring"; });
  $("#fix-mealie") && ($("#fix-mealie").onclick = () => openSetupSection("mealie", "Recipe library", reloadCfg));
  $$(".wk-day[data-entry]").forEach((b) => (b.onclick = () => { const e = s.week.find((x) => String(x.id) === b.dataset.entry); if (e?.recipe?.slug) openRecipe(e.recipe.slug); else openEntry(e); }));
  $$("[data-plan-day]").forEach((b) => (b.onclick = () => openPicker(b.dataset.planDay, "dinner", null, { seq: true })));
  $$("[data-buy]").forEach((b) => (b.onclick = async () => {
    const row = b.closest(".shop-row"); row.classList.add("done"); b.classList.add("on");
    try {
      const r = await api("PATCH", `/api/list/items/${enc(b.dataset.buy)}`, { checked: true });
      toast(`Got ${row.querySelector(".a").textContent}`, "Undo", async () => {
        try {
          if (r && r.pantry_item) await api("POST", `/api/lists/${enc(list.id)}/items/${enc(b.dataset.buy)}/undo`, { pantry_item_id: r.pantry_item.id });
          else await api("PATCH", `/api/list/items/${enc(b.dataset.buy)}`, { checked: false });
          renderHome();
        } catch (x) { fail(x); }
      });
    } catch (e) { row.classList.remove("done"); b.classList.remove("on"); fail(e); }
  }));
  const open = () => tonight?.recipe?.slug && openRecipe(tonight.recipe.slug);
  $("#tn-open") && ($("#tn-open").onclick = open);
  $("#tn-cook") && ($("#tn-cook").onclick = open);
  $("#tn-miss") && ($("#tn-miss").onclick = open);
  bindContextCard(s);
}
// Stat tiles: big number, small label, a tiny tag.
function homeStats(s, list) {
  const exp = (s.expiring || []), gone = exp.filter((i) => +i.days_left < 0).length;
  const soon = exp.filter((i) => i.days_left != null && +i.days_left >= 0 && +i.days_left <= 3);
  const toBuy = ((list && list.items) || []).filter((i) => !i.checked);
  const week = (s.week || []).filter((e) => e.recipe && !e.cooked && !e.skipped);
  const mins = week.reduce((n, e) => n + (+(e.recipe.eta?.shown || e.recipe.minutes) || 0), 0);
  const hrs = mins >= 60 ? `${Math.round(mins / 6) / 10} h` : `${mins} min`;
  return `<div class="stats" role="group" aria-label="At a glance">
    ${soon.length ? `<button class="stat" id="stat-exp"><b>${esc(soon.length)}</b><span>expiring soon</span><i class="warn">See what to use</i></button>`
      : `<button class="stat" data-go="pantry"><b>${esc(s.pantry_count || 0)}</b><span>in inventory</span>${gone ? `<i class="bad">${esc(gone)} expired</i>` : `<i>all fresh</i>`}</button>`}
    <button class="stat" data-go="list"><b>${esc(toBuy.length)}</b><span>to buy</span><i>${esc(plural(new Set(toBuy.flatMap((i) => (i.uses || []).map((u) => u.date))).size, "day"))}</i></button>
    <button class="stat" data-go="meals"><b>${esc(mins ? hrs : week.length)}</b><span>${mins ? "cooking this week" : "meals this week"}</span><i>${esc(plural(week.length, "meal"))}</i></button></div>`;
}
const storeName = (list, id) => (id == null ? "" : ((list.stores || []).find((x) => String(x.id) === String(id)) || {}).name || "");
// At most one nudge on Home, most useful first: missing ingredients > kitchen check-in (time-bound) > plan running out > stock your kitchen
function homeContextCard(s, tonight) {
  const tomorrow = isoDate(addDays(today(), 1)), todayISO = isoDate(today());
  const soon = (s.week || []).filter((e) => (e.date === todayISO || e.date === tomorrow) && e.recipe && !e.cooked && !e.skipped && +e.missing)
    .sort((a, b) => a.date.localeCompare(b.date) || order(a.entry_type) - order(b.entry_type)).slice(0, 2);
  if (soon.length) {
    const when = (e) => (e.date === todayISO ? (e.entry_type === "dinner" ? "tonight" : `today's ${e.entry_type}`) : (e.entry_type === "dinner" ? "tomorrow" : `tomorrow's ${e.entry_type}`));
    return `<div class="nudge-stack">${soon.map((e) => `<button class="nudge" data-miss-slug="${esc(e.recipe?.slug || "")}"><span class="ic bg-orange">${ic("cart")}</span><span><b>Missing ${esc(plural(+e.missing, "item"))} for ${esc(when(e))}</b><small>${esc(entryName(e))}${(e.missing_items || []).length ? ` · ${esc(e.missing_items.slice(0, 3).join(", "))}${e.missing_items.length > 3 ? "…" : ""}` : ""}</small></span><span class="sdot warn" aria-hidden="true"></span><span class="chev">${ic("chevR")}</span></button>`).join("")}</div>`;
  }
  if (s.pantry_checkin?.due) {
    return `<button class="nudge" id="home-ci"><span class="ic bg-green">${ic("box")}</span><span><b>Kitchen check-in</b><small>A few items might be gone or running low. Swipe through them, about a minute.</small></span><span class="chev">${ic("chevR")}</span></button>`;
  }
  const st = s.plan_status;
  if (st && st.reminder_days && st.days_left <= st.reminder_days) {
    return `<button class="nudge" id="ctx-plan"><span class="ic bg-orange">${ic("cal")}</span><span><b>${st.days_left ? `Your plan runs out in ${esc(plural(st.days_left, "day"))}` : "Nothing planned yet"}</b><small>Pick the next meals, one day at a time.</small></span><span class="chev">${ic("chevR")}</span></button>`;
  }
  let hidden = 0;
  try { hidden = +localStorage.getItem("tp.stockCardHidden") || 0; } catch (_) {}
  if ((s.pantry_count || 0) < 10 && Date.now() - hidden > 30 * 864e5) {
    return `<div class="nudge stock-card" id="ctx-stock"><span class="ic bg-blue">${ic("scan")}</span><span><b>Stock your kitchen</b><small>Scan what you have so recipes and lists know what's at home.</small>
      <span class="stock-btns">${[["pantry", "Pantry"], ["fridge", "Fridge"], ["freezer", "Freezer"]].map(([k, l]) => `<button class="pill-btn" data-stock="${k}">${ic("scan")} ${l}</button>`).join("")}</span></span>
      <button class="x" id="ctx-stock-x" aria-label="Hide for now">${ic("x")}</button></div>`;
  }
  return "";
}
function bindContextCard(s) {
  $$("[data-miss-slug]").forEach((b) => (b.onclick = () => { const slug = b.dataset.missSlug; if (slug) openRecipe(slug); else go("list"); }));
  $("#ctx-plan") && ($("#ctx-plan").onclick = () => planSequential());
  $("#home-ci") && ($("#home-ci").onclick = () => openCheckin(renderHome));
  $$("[data-stock]").forEach((b) => (b.onclick = () => { SS.loc = b.dataset.stock; try { localStorage.setItem("tp.scanLoc", SS.loc); } catch (_) {} startStockUp(renderHome); }));
  $("#ctx-stock-x") && ($("#ctx-stock-x").onclick = () => { try { localStorage.setItem("tp.stockCardHidden", String(Date.now())); } catch (_) {} $("#ctx-stock")?.remove(); });
}
const entryName = (e) => (e.recipe && e.recipe.name) || e.title || "Note";
function relExpiry(it) {
  const d = it.days_left;
  if (it.expiry_label && d != null && d >= 0) return it.expiry_label;   // "Opened · use within 5 days", "Use by Nov 12"
  if (d === null || d === undefined) return "No use-by date";
  if (d < 0) return `Expired ${-d} day${d === -1 ? "" : "s"} ago`;
  if (d === 0) return "Use today";
  if (d === 1) return "Use by tomorrow";
  return `Use within ${d} days`;
}

// ------------------------------------------------------------------ PLAN (rolling board with drag & drop)
// Only dinner is planned on the board for now; add "breakfast"/"lunch" here and every slot, menu and picker follows.
const PLAN_TYPES = ["dinner"];   // sequential planning and the "Plan my 2 weeks" flow stay dinner-first
const MEAL_TYPES = [["breakfast", "Breakfast"], ["lunch", "Lunch"], ["dinner", "Dinner"], ["side", "Side"], ["dessert", "Dessert"], ["snack", "Snack"]];
const ORDER = { breakfast: 0, lunch: 1, dinner: 2, side: 3, dessert: 4, snack: 5, drink: 6 };
const plannedTypes = () => { const t = (state.cfg?.settings?.meal_types || []).filter((x) => ORDER[x] != null); return t.length ? t.sort((a, b) => ORDER[a] - ORDER[b]) : ["dinner"]; };
const firstOpenType = (entries) => [...plannedTypes(), "side", "dessert", "lunch", "breakfast", "snack"].find((t) => !entries.some((e) => e.entry_type === t)) || "dinner";
const order = (t) => ORDER[t] ?? 9;
const horizon = () => Math.min(28, Math.max(7, +state.cfg?.settings?.plan_horizon_days || 14));
const shortDate = (s) => fmt(parseISO(s), { month: "short", day: "numeric" });
const wkShort = (s) => fmt(parseISO(s), { weekday: "short" });
const dayLong = (s) => { const n = dayName(s); return n === "Today" || n === "Tomorrow" ? n : fmt(parseISO(s), { weekday: "long" }); };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
// After a plan change, repaint whatever is on screen: the board in place (keeps scroll), otherwise the whole tab.
const replan = () => (state.tab === "meals" && $("#board") ? drawBoard() : refresh());

async function renderMeals() {
  const H = horizon(), start = isoDate(today()), end = isoDate(addDays(today(), H - 1));
  app.innerHTML = topbar(`<button class="round-btn" id="btn-pmore" aria-label="More planning options" aria-haspopup="menu">${ic("more")}</button><button class="round-btn" id="btn-share" aria-label="Share or print the plan">${ic("share")}</button>`) +
    `<h1 class="title">Plan</h1><div class="subtitle" id="plan-sub">&nbsp;</div>
    <div class="toolbar"><button class="pill-btn ink" id="fill">${ic("plus")} Plan my ${H === 14 ? "2 weeks" : `${H} days`}</button>
      <button class="pill-btn" id="to-list">${ic("cart")} Shopping list<span id="list-n"></span></button></div>
    <div id="plan-cta"></div><div id="past" class="past"></div>
    <div id="board" class="board">${loading()}</div>
    <p class="hint board-hint"><span class="mobile-only">Touch and hold a meal, then drag it to another day.</span><span class="desktop-only">Drag a meal onto another day to move it there. Drop it on a meal of the same type to swap the two.</span></p>`;
  bindTopbar();
  $("#btn-share").onclick = () => openShare("plan", { start, end, label: `Next ${H} days` });
  $("#fill").onclick = () => planSequential();
  $("#btn-pmore").onclick = () => popover($("#btn-pmore"), `<button data-act="auto">${ic("sparkle")} Fill empty days automatically</button>`, (el) => {
    $("[data-act=auto]", el).onclick = () => { closePop(); fillEmpty(start, H); };
  });
  $("#to-list").onclick = () => go("list");
  await drawBoard();
}

async function drawBoard() {
  const H = horizon(), t0 = today(), start = isoDate(t0), end = isoDate(addDays(t0, H - 1));
  const board = $("#board");
  if (!board) return;
  let data, status, list, past;
  try {
    [data, status, list, past] = await Promise.all([
      api("GET", `/api/plan?start=${enc(start)}&end=${enc(end)}`),
      api("GET", "/api/plan/status").catch(() => null),
      api("GET", "/api/list").catch(() => null),
      api("GET", `/api/plan?start=${enc(isoDate(addDays(t0, -7)))}&end=${enc(isoDate(addDays(t0, -1)))}`).catch(() => null),
    ]);
  } catch (e) { board.innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  if (!document.body.contains(board)) return;
  state.plan = data;
  const byDay = {};   // date -> entries, breakfast first
  (data.entries || []).forEach((e) => (byDay[e.date] = byDay[e.date] || []).push(e));
  Object.values(byDay).forEach((l) => l.sort((a, b) => order(a.entry_type) - order(b.entry_type) || a.id - b.id));
  const primary = plannedTypes().includes("dinner") ? "dinner" : plannedTypes()[0];
  const hasPrimary = (d) => (byDay[d] || []).some((e) => e.entry_type === primary);

  // header: "Planned through …" and the list count
  let through = status ? status.planned_through : null;
  if (!status) { for (let i = 0; i < H && hasPrimary(isoDate(addDays(t0, i))); i++) through = isoDate(addDays(t0, i)); }
  const empty = Array.from({ length: H }, (_, i) => isoDate(addDays(t0, i))).filter((d) => !hasPrimary(d)).length;
  const low = status && status.reminder_days && status.days_left <= status.reminder_days;
  $("#plan-sub").innerHTML = (through ? `<span class="${low ? "warn" : ""}">Planned through ${esc(fmt(parseISO(through), { weekday: "short", month: "short", day: "numeric" }))}</span>` : "Nothing planned yet") +
    (empty ? ` · ${esc(plural(empty, "empty day"))}` : "");
  $("#fill").disabled = !empty;
  planCost();
  const cta = $("#plan-cta");
  if (cta) {
    cta.innerHTML = (data.entries || []).length ? "" : `<div class="plan-cta"><b>Nothing planned yet</b><span>Pick a recipe for each day, one at a time.</span><button class="btn" id="plan-cta-go">Plan my ${H === 14 ? "2 weeks" : `${H} days`}</button></div>`;
    $("#plan-cta-go") && ($("#plan-cta-go").onclick = () => planSequential());
  }
  const n = list && Array.isArray(list.items) ? list.items.filter((x) => !x.checked).length : null;
  $("#list-n").textContent = n === null ? "" : ` (${n})`;
  drawPast(((past && past.entries) || []).filter((e) => PLAN_TYPES.includes(e.entry_type) && e.recipe?.slug && !e.cooked && !e.skipped));

  const types = plannedTypes(), showType = types.length > 1 || (data.entries || []).some((e) => e.entry_type !== "dinner");
  const card = (e, iso) => {
    const r = e.recipe || {}, img = imgUrl(r), miss = e.cooked ? 0 : +e.missing || 0;
    return `<div class="bcard ${e.cooked ? "cooked" : ""}" data-entry="${esc(e.id)}" data-type="${esc(e.entry_type)}" tabindex="0" role="button" aria-label="${esc(cap(e.entry_type))}: ${esc(entryName(e))}, ${esc(dayLong(iso))}${e.cooked ? ", cooked" : ""}. Open recipe">
      <div class="thumb ${img ? "" : "ph"}" ${img ? bgStyle(img) : ""}>${img ? "" : ic("dish")}${e.cooked ? `<span class="cooked-badge" aria-hidden="true">✓</span>` : ""}</div>
      <div class="main">${showType ? `<div class="mtype">${esc(cap(e.entry_type))}</div>` : ""}<div class="a">${esc(entryName(e))}</div>
        <div class="b">${e.start_by && !e.cooked && iso >= isoDate(today()) ? `${ic("clock")}<span class="start-by" title="Start by ${esc(clock12(e.start_by))} to eat at ${esc(clock12(e.eat_at))}">Start ${esc(clock12(e.start_by))}</span>` : r.eta ? `${ic("clock")}<span>${esc(r.eta.label)}</span>` : r.minutes ? `${ic("clock")}<span>${esc(r.minutes)} min</span>` : ""}${miss ? `<span class="pill soon miss-chip">Missing ${esc(miss)}</span>` : ""}${e.cooked ? `<span class="pill ok">Cooked</span>` : r.slug ? `<button class="cook-pill" data-cook="${esc(e.id)}" aria-label="Mark ${esc(entryName(e))} as cooked">✓ Cook</button>` : ""}</div></div>
      <button class="bmore" data-more="${esc(e.id)}" aria-label="More options for ${esc(entryName(e))}">${ic("more")}</button></div>`;
  };
  let html = "";
  for (let i = 0; i < H; i++) {
    const iso = isoDate(addDays(t0, i)), wd = parseISO(iso).getDay(), list = byDay[iso] || [];
    html += `<div class="bday ${i === 0 ? "today" : ""} ${wd === 0 || wd === 6 ? "wkend" : ""}" data-date="${esc(iso)}">
      <div class="bday-h"><b>${esc(dayName(iso))}</b><span>${esc(shortDate(iso))}</span>${list.length ? `<button class="bday-add" data-add="${esc(iso)}" aria-label="Add another recipe to ${esc(dayLong(iso))}">${ic("plus")}</button>` : ""}</div>
      <div class="bday-meals">${list.map((e) => card(e, iso)).join("")}`;
    types.filter((t) => !list.some((e) => e.entry_type === t)).forEach((t) => {
      html += `<button class="bempty" data-pick="${esc(iso)}" data-type="${esc(t)}">${ic("plus")}<span>Add ${esc(t)}</span></button>`;
    });
    html += `</div></div>`;
  }
  board.innerHTML = html;
  const find = (id) => (data.entries || []).find((e) => String(e.id) === String(id));
  board.onclick = (ev) => {
    if (Date.now() < DND.quietUntil) return;
    const more = ev.target.closest("[data-more]"), pick = ev.target.closest("[data-pick]"), card = ev.target.closest(".bcard");
    const cook = ev.target.closest("[data-cook]"), add = ev.target.closest("[data-add]");
    if (cook) {   // the board's ✓ Cook needs a second tap (or a long press), so it can't happen by accident
      const e = find(cook.dataset.cook); if (!e) return;
      if (cook.dataset.armed === "1") { clearTimeout(cook._t); cookEntry(e, cook); return; }
      cook.dataset.armed = "1"; cook.classList.add("armed"); const label = cook.innerHTML; cook.textContent = "Tap again to mark cooked";
      cook._t = setTimeout(() => { cook.dataset.armed = ""; cook.classList.remove("armed"); cook.innerHTML = label; }, 3000);
      return;
    }
    if (add) return openPicker(add.dataset.add, firstOpenType(byDay[add.dataset.add] || []), null, { anyType: true });
    if (more) return entryMenu(more, find(more.dataset.more));
    if (pick) return openPicker(pick.dataset.pick, pick.dataset.type);
    if (card) { const e = find(card.dataset.entry); if (e?.recipe?.slug) openRecipe(e.recipe.slug); else if (e) entryMenu($(".bmore", card), e); }
  };
  board.onkeydown = (ev) => { const card = ev.target.closest?.(".bcard"); if (card && ev.target === card && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); card.click(); } };
  board.oncontextmenu = (ev) => { if (ev.target.closest(".bcard")) ev.preventDefault(); };
  board.addEventListener("pointerdown", (ev) => {   // long-press ✓ Cook also marks it cooked
    const cook = ev.target.closest("[data-cook]"); if (!cook) return;
    const t = setTimeout(() => { const e = find(cook.dataset.cook); cook.dataset.armed = "1"; DND.quietUntil = Date.now() + 500; try { navigator.vibrate?.(15); } catch (_) {} if (e) cookEntry(e, cook); }, 650);
    const stop = () => { clearTimeout(t); window.removeEventListener("pointerup", stop); window.removeEventListener("pointercancel", stop); };
    window.addEventListener("pointerup", stop); window.addEventListener("pointercancel", stop);
  });
  boardDnD(board, (id, from, to, swapWith) => moveEntry(find(id), to, true, swapWith));
}

// ---------- cooked: take what a recipe used out of the pantry (with Undo) and tick off the plan entry
function cookedMessage(r) {
  const parts = [...(r.deducted || []).map((d) => d.used), ...(r.unknown || []).map((n) => n.toLowerCase())];
  if (!parts.length) return "Cooked";
  return `Cooked · used ${parts.slice(0, 3).join(", ")}${parts.length > 3 ? "…" : ""}`;
}
async function markCooked(slug, body, after) {
  const r = await api("POST", `/api/recipe/${enc(slug)}/cooked`, body || {});
  if (r.diary_id) state.justCooked = { diary_id: r.diary_id, slug };   // the recipe page asks "How was it?"
  toast(cookedMessage(r), "Undo", async () => {
    try { await api("POST", "/api/cooked/undo", { undo_token: r.undo_token }); state.justCooked = null; toast("Undone"); if (after) after(); } catch (x) { fail(x); }
  });
  if (after) after();
  return r;
}
async function cookEntry(e, btn) {
  if (!e?.recipe?.slug) return;
  if (btn) btn.disabled = true;
  try { await markCooked(e.recipe.slug, { plan_id: e.id }, replan); }
  catch (x) { fail(x); if (btn) btn.disabled = false; }
}
async function skipEntry(e, btn) {
  if (btn) btn.disabled = true;
  try {
    await api("POST", `/api/plan/${enc(e.id)}/skip`, {});
    toast(`Skipped ${entryName(e)}`, "Undo", async () => {
      try { await api("POST", `/api/plan/${enc(e.id)}/skip`, { skipped: false }); replan(); } catch (x) { fail(x); }
    });
  } catch (x) { fail(x); }
  replan();
}
function drawPast(entries) {
  const box = $("#past");
  if (!box) return;
  if (!entries.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="past-h">Earlier this week</div>` + entries.map((e) =>
    `<div class="past-row" data-pentry="${esc(e.id)}"><div class="main"><b>${esc(entryName(e))}</b><span>${esc(dayLong(e.date))}, ${esc(shortDate(e.date))}</span></div>
      <span class="q">Cooked?</span><button class="cook-pill" data-pcook="${esc(e.id)}" aria-label="Yes, I cooked ${esc(entryName(e))}">✓</button>
      <button class="skip-btn" data-pskip="${esc(e.id)}">Skip</button></div>`).join("");
  const find = (id) => entries.find((x) => String(x.id) === String(id));
  box.onclick = (ev) => {
    const c = ev.target.closest("[data-pcook]"), sk = ev.target.closest("[data-pskip]");
    if (c) cookEntry(find(c.dataset.pcook), c);
    if (sk) skipEntry(find(sk.dataset.pskip), sk);
  };
}

// ---------- drag & drop: mouse drags after a few pixels; touch needs a ~300 ms hold so normal scrolling still works
const DND = { s: null, quietUntil: 0 };
document.addEventListener("touchmove", (e) => { if (DND.s && DND.s.active) e.preventDefault(); }, { passive: false });
function boardDnD(board, onDrop) {
  if (board.dataset.dnd) return;
  board.dataset.dnd = "1";
  board.addEventListener("pointerdown", (e) => {
    const card = e.target.closest(".bcard");
    if (!card || e.target.closest(".bmore, .cook-pill") || (e.pointerType === "mouse" && e.button !== 0) || DND.s) return;
    const s = DND.s = { card, id: card.dataset.entry, from: card.closest(".bday").dataset.date, pid: e.pointerId,
      x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, touch: e.pointerType !== "mouse", active: false, target: null };
    if (s.touch) { s.timer = setTimeout(begin, 300); card.classList.add("pressing"); }
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  });
  function begin() {
    const s = DND.s;
    if (!s || s.active) return;
    s.active = true;
    const r = s.card.getBoundingClientRect();
    s.dx = s.x - r.left; s.dy = s.y - r.top;
    const g = s.ghost = s.card.cloneNode(true);
    g.classList.remove("pressing"); g.classList.add("ghost"); g.removeAttribute("tabindex"); g.setAttribute("aria-hidden", "true");
    g.style.width = r.width + "px"; g.style.height = r.height + "px";
    document.body.appendChild(g);
    s.card.classList.remove("pressing"); s.card.classList.add("dragging");
    document.body.classList.add("dnd");
    try { navigator.vibrate?.(12); } catch (_) {}
    place();
    const scroll = () => {
      if (DND.s !== s || !s.active) return;
      const edge = 70, bottom = window.innerHeight - (window.innerWidth >= 1024 ? 0 : 90);
      const v = s.y < edge ? -Math.ceil((edge - s.y) / 5) : s.y > bottom - edge ? Math.ceil((s.y - bottom + edge) / 5) : 0;
      if (v) { window.scrollBy(0, v); place(); }
      s.raf = requestAnimationFrame(scroll);
    };
    s.raf = requestAnimationFrame(scroll);
  }
  function place() {
    const s = DND.s;
    s.ghost.style.transform = `translate(${s.x - s.dx}px,${s.y - s.dy}px) rotate(-1.5deg) scale(1.03)`;
    const el = document.elementFromPoint(s.x, s.y), day = el && el.closest(".bday");
    const t = day && board.contains(day) ? day : null;
    const over = el && el.closest(".bcard");   // a meal of the same type on another day: the two swap
    const sw = over && over !== s.card && over.dataset.type === s.card.dataset.type && t && t.dataset.date !== s.from ? over : null;
    if (sw !== s.swap) { s.swap?.classList.remove("swap-on"); s.swap = sw; sw?.classList.add("swap-on"); }
    if (t !== s.target) { s.target?.classList.remove("drop-on"); s.target = t; if (t && t.dataset.date !== s.from) t.classList.add("drop-on"); }
  }
  function move(e) {
    const s = DND.s;
    if (!s || e.pointerId !== s.pid) return;
    s.x = e.clientX; s.y = e.clientY;
    if (!s.active) {
      const d = Math.hypot(s.x - s.x0, s.y - s.y0);
      if (s.touch) { if (d > 10) cancel(); return; }   // moved before the hold finished: it's a scroll
      if (d < 6) return;
      begin();
    }
    e.preventDefault();
    place();
  }
  function up(e) {
    const s = DND.s;
    if (!s || e.pointerId !== s.pid) return;
    const to = s.active && s.target ? s.target.dataset.date : null;
    if (s.active) DND.quietUntil = Date.now() + 350;   // swallow the click that follows a drop
    if (to && to !== s.from) {
      // optimistic: put the card on the new day (or trade places with the meal it was dropped on), then sync
      const dest = $(".bday-meals", s.target), src = s.card.closest(".bday-meals"), sw = s.swap;
      if (sw) src.appendChild(sw);
      dest.prepend(s.card);
      s.target.classList.add("dropped"); const t = s.target; setTimeout(() => t.classList.remove("dropped"), 600);
      onDrop(s.id, s.from, to, sw ? sw.dataset.entry : null);
    }
    cleanup();
  }
  function cancel() { cleanup(); }
  function cleanup() {
    const s = DND.s;
    if (!s) return;
    clearTimeout(s.timer); cancelAnimationFrame(s.raf);
    s.ghost?.remove(); s.target?.classList.remove("drop-on"); s.swap?.classList.remove("swap-on");
    s.card.classList.remove("dragging", "pressing");
    document.body.classList.remove("dnd");
    window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", cancel);
    DND.s = null;
  }
}

// ---------- plan actions (no confirmations: everything is undoable from the toast)
async function moveEntry(e, to, fromDrag, swapWith) {
  if (!e || !to || e.date === to) return;
  const from = e.date;
  try {
    const r = await api("POST", "/api/plan/move", swapWith ? { id: e.id, date: to, swap_with: +swapWith } : { id: e.id, date: to });
    toast(`Moved to ${dayLong(to)}${r && r.swapped_with ? " · swapped days" : ""}`, "Undo", async () => {
      try { await api("POST", "/api/plan/move", r && r.swapped_with ? { id: e.id, date: from, swap_with: r.swapped_with } : { id: e.id, date: from }); replan(); } catch (x) { fail(x); }
    });
  } catch (x) { fail(x); }
  replan();
}
async function removeEntry(e) {
  if (!e) return;
  try {
    const r = await api("DELETE", `/api/plan/${enc(e.id)}`);
    const undo = (r && r.undo) || { date: e.date, recipe_id: e.recipe?.id, entry_type: e.entry_type };
    toast(`Removed ${entryName(e)}${r && r.removed ? ` · ${plural(r.removed, "item")} off your list` : ""}`, undo.recipe_id ? "Undo" : null, async () => {
      try { await api("POST", "/api/plan/assign", undo); replan(); } catch (x) { fail(x); }
    });
  } catch (x) { fail(x); }
  replan();
}
async function assignRecipe(date, recipeId, type = "dinner", replaceId = null) {
  const r = await api("POST", "/api/plan/assign", { date, recipe_id: recipeId, entry_type: type, ...(replaceId != null ? { replace_id: replaceId } : {}) });
  const n = (r && r.added) || 0, skipped = (r && r.skipped) || [];
  toast(`Added to ${wkShort(date)}${n ? ` · ${plural(n, "item")} on your list` : skipped.length ? " · you have everything" : ""}`, n ? "View list" : null, () => go("list"));
  return r;
}

// ---------- inline popover menus (anchored to a button, not a modal)
let POP = null;
function closePop() {
  if (!POP) return;
  const p = POP; POP = null;
  document.removeEventListener("pointerdown", p.outside, true); document.removeEventListener("keydown", p.key); window.removeEventListener("scroll", p.scroll);
  p.el.classList.remove("on"); setTimeout(() => p.el.remove(), 150);
  p.anchor?.setAttribute("aria-expanded", "false");
}
// Height of the status-bar inset (env(safe-area-inset-top)), measured via a hidden probe.
function safeTop() {
  let p = document.querySelector(".safe-probe");
  if (!p) { p = document.createElement("div"); p.className = "safe-probe"; p.setAttribute("aria-hidden", "true"); document.body.appendChild(p); }
  return p.offsetHeight || 0;
}
function popover(anchor, html, onMount) {
  if (POP && POP.anchor === anchor) return closePop();
  closePop();
  const el = document.createElement("div");
  el.className = "pop"; el.setAttribute("role", "menu"); el.innerHTML = html;
  document.body.appendChild(el);
  const p = POP = { el, anchor };
  p.place = () => {
    const r = anchor.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
    el.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + "px";
    const top = safeTop() + 8;
    el.style.top = (r.bottom + 6 + h > window.innerHeight - 8 ? Math.max(top, r.top - h - 6) : r.bottom + 6) + "px";
  };
  p.place();
  p.outside = (e) => { if (!el.contains(e.target) && !anchor.contains(e.target)) closePop(); };
  p.key = (e) => { if (e.key === "Escape") { closePop(); anchor.focus?.(); } };
  p.scroll = () => closePop();
  setTimeout(() => { if (POP !== p) return; document.addEventListener("pointerdown", p.outside, true); document.addEventListener("keydown", p.key); window.addEventListener("scroll", p.scroll, { passive: true }); }, 0);
  anchor.setAttribute("aria-expanded", "true");
  requestAnimationFrame(() => el.classList.add("on"));
  onMount && onMount(el, p);
  $("button", el)?.focus({ preventScroll: true });
  return el;
}
function entryMenu(anchor, e) {
  if (!e) return;
  const main = () => `<button data-act="open" ${e.recipe?.slug ? "" : "disabled"}>${ic("book")} Open recipe</button>
    <button data-act="swap">${ic("shuffle")} Swap</button><button data-act="move">${ic("cal")} Move to…</button>
    <button data-act="eat">${ic("clock")} Eat at ${esc(e.eat_at ? clock12(e.eat_at) : "…")}</button>
    ${e.cooked ? `<button data-act="uncook">${ic("refresh")} Not cooked yet (undo)</button>` : ""}
    <button data-act="rm" class="red">${ic("trash")} Remove</button>`;
  popover(anchor, main(), (el, p) => {
    const bind = () => {
      $$("[data-act]", el).forEach((b) => (b.onclick = () => {
        const a = b.dataset.act;
        if (a === "open") { closePop(); openRecipe(e.recipe.slug); }
        if (a === "swap") { closePop(); openPicker(e.date, e.entry_type, e); }
        if (a === "rm") { closePop(); removeEntry(e); }
        if (a === "uncook") {
          closePop();
          api("POST", `/api/plan/${enc(e.id)}/uncook`).then((r) => { toast(r.restored ? `Not cooked · ${plural(r.restored, "ingredient")} put back` : "Marked not cooked"); replan(); }).catch(fail);
        }
        if (a === "eat") {
          el.innerHTML = `<div class="pop-h">When do you want to eat ${esc(entryName(e))}?</div>
            <form class="eat-form"><input type="time" id="eat-t" value="${esc(e.eat_at || "18:30")}" step="300" aria-label="Eat at"><button class="btn small" type="submit">Save</button></form>
            ${e.eat_at_custom ? `<button data-reset-eat>Use my usual ${esc(e.entry_type)} time</button>` : ""}`;
          const save = async (t) => { closePop(); try { await api("PUT", `/api/plan/${enc(e.id)}/eat-at`, { eat_at: t }); renderMeals(); } catch (x) { fail(x); } };
          $(".eat-form", el).onsubmit = (ev) => { ev.preventDefault(); save($("#eat-t", el).value || null); };
          $("[data-reset-eat]", el) && ($("[data-reset-eat]", el).onclick = () => save(null));
        }
        if (a === "move") {
          const H = horizon(), plan = state.plan?.entries || [];
          el.innerHTML = `<div class="pop-h">Move ${esc(entryName(e))} to</div><div class="pop-scroll">${Array.from({ length: H }, (_, i) => isoDate(addDays(today(), i))).filter((d) => d !== e.date).map((d) => {
            const o = plan.filter((x) => x.date === d);
            return `<button data-to="${esc(d)}"><b>${esc(dayName(d))}</b> <span class="muted">${esc(shortDate(d))}</span><small>${o.length ? `with ${esc(o.map(entryName).slice(0, 2).join(", "))}` : "empty"}</small></button>`;
          }).join("")}</div>`;
          p.place();
          $$("[data-to]", el).forEach((x) => (x.onclick = () => { closePop(); moveEntry(e, x.dataset.to); }));
          $("[data-to]", el)?.focus();
        }
      }));
    };
    bind();
  });
}

// ---------- recipe picker for a day: "Not on plan" first, one-by-one sequential mode, or pick several and arrange
const horizonDates = () => Array.from({ length: horizon() }, (_, i) => isoDate(addDays(today(), i)));
const recipeCats = (r) => r.categories || [];
async function planSequential(type = "dinner") {
  let data;
  try { data = await api("GET", `/api/plan?start=${enc(horizonDates()[0])}&end=${enc(horizonDates().slice(-1)[0])}`); } catch (e) { return fail(e); }
  const taken = new Set((data.entries || []).filter((e) => e.entry_type === type).map((e) => e.date));
  const empty = horizonDates().filter((d) => !taken.has(d));
  if (!empty.length) return toast("Every day is planned");
  openPicker(empty[0], type, null, { seq: true });
}
async function openPicker(date, type = "dinner", replacing = null, opts = {}) {
  const pk = { q: "", f: "open", cat: "", recipes: null, last: {}, inPlan: {}, takenBy: {}, multi: false, sel: [], seq: !!opts.seq && !replacing,
    date, added: 0, items: 0, msg: "", preview: null, type };
  const takenSet = () => (pk.takenBy[pk.type] = pk.takenBy[pk.type] || new Set());
  const titleFor = (d) => pk.seq
    ? `${fmt(parseISO(d), { weekday: "short", month: "short", day: "numeric" })} · day ${Math.round((parseISO(d) - today()) / 864e5) + 1} of ${horizon()}`
    : `${replacing ? "Swap" : cap(pk.type)} · ${dayLong(d)}, ${shortDate(d)}`;
  openSheet(titleFor(date),
    `${replacing ? "" : `<div class="seg pk-types" id="pk-type" role="radiogroup" aria-label="Meal">${MEAL_TYPES.map(([k, l]) => `<button data-t="${k}" role="radio" aria-checked="${k === type}" class="${k === type ? "on" : ""}">${esc(l)}</button>`).join("")}</div>`}
    <div class="search">${ic("search")}<input id="pk-q" type="search" placeholder="Search recipes" autocomplete="off" enterkeyhint="search"></div>
    <div class="chips pk-chips" id="pk-f">${[["open", "Not on plan"], ["all", "All"], ["fav", "♥ Favorites"]].map(([k, l]) => `<button class="filter ${k === pk.f ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div>
    <div class="chips pk-chips" id="pk-c"></div>
    <div class="pk-tools">${replacing ? "" : `<button class="link-btn" id="pk-multi" aria-pressed="false">Select several</button>`}
      ${pk.seq ? `<span class="grow"></span><button class="link-btn" id="pk-skip">Skip day</button><button class="link-btn strong" id="pk-done">Done</button>` : ""}</div>
    <div class="pk-msg" id="pk-msg" role="status" aria-live="polite"></div>
    <div id="pk-list">${loading()}</div>
    <div class="pk-bar" id="pk-bar" hidden><span id="pk-n">0 selected</span><span class="grow"></span>
      <button class="pill-btn" id="pk-order">Fill in order</button><button class="pill-btn ink" id="pk-ai">${ic("sparkle")} Arrange with AI</button></div>`, {
    onMount() {
      let t;
      $("#pk-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { pk.q = e.target.value; draw(); }, 100); };
      $("#pk-q").onkeydown = (e) => { if (e.key === "Enter") { const first = $("#pk-list [data-rid]"); if (first) first.click(); } };
      $$("#pk-f [data-f]").forEach((b) => (b.onclick = () => { pk.f = b.dataset.f; $$("#pk-f .filter").forEach((x) => x.classList.toggle("on", x === b)); draw(); }));
      $$("#pk-type [data-t]").forEach((b) => (b.onclick = () => {
        pk.type = b.dataset.t;
        $$("#pk-type [data-t]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); });
        const h = $("#layer .sheet-h h3"); if (h) h.textContent = titleFor(pk.date);
      }));
      $("#pk-multi") && ($("#pk-multi").onclick = () => {
        pk.multi = !pk.multi; pk.sel = []; pk.preview = null;
        $("#pk-multi").textContent = pk.multi ? "Cancel selection" : "Select several";
        $("#pk-multi").setAttribute("aria-pressed", String(pk.multi));
        draw();
      });
      $("#pk-skip") && ($("#pk-skip").onclick = () => advance(`Skipped ${wkShort(pk.date)}`));
      $("#pk-done") && ($("#pk-done").onclick = () => finishSeq());
      $("#pk-order").onclick = () => arrange(false);
      $("#pk-ai").onclick = () => arrange(true);
      if (matchMedia("(pointer:fine)").matches) setTimeout(() => $("#pk-q")?.focus(), 250);
    },
  });
  const todayISO = isoDate(today()), hz = horizonDates(), lastDay = hz[hz.length - 1];
  try {
    const [rs, hist] = await Promise.all([
      api("GET", "/api/recipes"),
      api("GET", `/api/plan?start=${enc(isoDate(addDays(today(), -60)))}&end=${enc(isoDate(addDays(today(), horizon() + 14)))}`).catch(() => ({ entries: [] })),
    ]);
    pk.recipes = rs.recipes || [];
    (hist.entries || []).forEach((e) => {
      if (e.date >= todayISO && e.date <= lastDay) (pk.takenBy[e.entry_type] = pk.takenBy[e.entry_type] || new Set()).add(e.date);
      const id = e.recipe?.id; if (!id) return;
      if (e.date < todayISO) { if (!pk.last[id] || e.date > pk.last[id]) pk.last[id] = e.date; }
      else if (e.date <= lastDay && (!pk.inPlan[id] || e.date < pk.inPlan[id])) pk.inPlan[id] = e.date;
    });
  } catch (e) { const l = $("#pk-list"); if (l) l.innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  // category chips: only categories some recipe uses, in settings order; "Main dish" first pick for dinner
  const cats = (state.cfg?.settings?.categories || []).filter((c) => pk.recipes.some((r) => recipeCats(r).includes(c)));
  if (type === "dinner" && cats.includes("Main dish")) pk.cat = "Main dish";
  const cbox = $("#pk-c");
  if (cbox) {
    cbox.innerHTML = cats.length ? [["", "Any category"], ...cats.map((c) => [c, c])].map(([k, l]) => `<button class="filter sm ${k === pk.cat ? "on" : ""}" data-c="${esc(k)}">${esc(l)}</button>`).join("") : "";
    cbox.hidden = !cats.length;
    $$("[data-c]", cbox).forEach((b) => (b.onclick = () => { pk.cat = b.dataset.c; $$("[data-c]", cbox).forEach((x) => x.classList.toggle("on", x === b)); draw(); }));
  }
  const ago = (d) => { const n = Math.round((today() - parseISO(d)) / 864e5); return n < 14 ? `${plural(n, "day")} ago` : n < 60 ? `${Math.round(n / 7)} weeks ago` : `${Math.round(n / 30)} months ago`; };
  const empties = () => hz.filter((d) => !takenSet().has(d));
  const setMsg = (m) => { const el = $("#pk-msg"); if (el) el.textContent = m || ""; };
  const finishSeq = () => {
    closeSheet(); replan();
    if (pk.added) toast(`Plan filled · ${plural(pk.items, "item")} added to your list`, pk.items ? "View list" : null, () => go("list"));
  };
  const advance = (msg) => {
    const rest = empties().filter((d) => d > pk.date);
    const next = rest[0] || empties().find((d) => d !== pk.date);
    if (!next) return finishSeq();
    pk.date = next;
    const h = $("#layer .sheet-h h3"); if (h) h.textContent = titleFor(next);
    setMsg(msg); pk.q = ""; const qi = $("#pk-q"); if (qi) qi.value = "";
    draw(); $("#pk-list")?.scrollTo?.(0, 0);
  };
  const draw = () => {
    const box = $("#pk-list");
    if (!box || !pk.recipes) return;
    const bar = $("#pk-bar");
    if (bar) { bar.hidden = !pk.multi || !!pk.preview; $("#pk-n").textContent = `${pk.sel.length} selected`; $("#pk-order").disabled = $("#pk-ai").disabled = !pk.sel.length; }
    if (pk.preview) return drawPreview();
    const q = pk.q.trim().toLowerCase();
    let list = pk.recipes.filter((r) => (!q || r.name.toLowerCase().includes(q) || (r.tags || []).some((x) => x.toLowerCase().includes(q)))
      && (pk.f !== "fav" || r.favorite) && (pk.f !== "open" || !pk.inPlan[r.id]) && (!pk.cat || recipeCats(r).includes(pk.cat)));
    const key = (r) => (pk.inPlan[r.id] ? "2" : "1") + (pk.last[r.id] || "0000");   // never planned, then oldest; already planned last
    if (pk.f === "all") list.sort((a, b) => a.name.localeCompare(b.name));
    else list.sort((a, b) => key(a).localeCompare(key(b)) || a.name.localeCompare(b.name));
    if (!pk.recipes.length) { box.innerHTML = `<div class="empty"><div class="em">📖</div>No recipes yet. Add one from the Recipes tab.</div>`; return; }
    if (!list.length) {
      box.innerHTML = `<div class="empty">${pk.f === "fav" && !q ? "No favorites yet. Tap ♡ on a recipe to add it." : pk.f === "open" && !q ? "Every recipe is already on the plan. Tap All to plan one again." : "No recipes match."}</div>`;
      return;
    }
    box.innerHTML = `<div class="group pk-group">${list.slice(0, 150).map((r) => {
      const img = imgUrl(r), cur = replacing && replacing.recipe && String(replacing.recipe.id) === String(r.id);
      const on = pk.sel.includes(r.id);
      const when = pk.inPlan[r.id] ? `On ${wkShort(pk.inPlan[r.id])}` : pk.last[r.id] ? `Last had ${ago(pk.last[r.id])}` : "Not planned lately";
      return `<button class="row ${on ? "sel" : ""}" data-rid="${esc(r.id)}" ${cur ? "disabled" : ""} ${pk.multi ? `aria-pressed="${on}"` : ""}>${pk.multi ? `<span class="selc ${on ? "on" : ""}" aria-hidden="true">${on ? ic("check") : ""}</span>` : ""}<div class="thumb ${img ? "" : "ph"}" ${img ? bgStyle(img) : ""}>${img ? "" : "🍽️"}</div>
        <div class="main"><div class="a">${esc(r.name)}${r.favorite ? ' <span class="heart-s">♥</span>' : ""}</div><div class="b">${r.minutes ? `${esc(r.minutes)} min · ` : ""}${esc(cur ? "Planned now" : when)}</div></div></button>`;
    }).join("")}</div>`;
    $$("#pk-list [data-rid]").forEach((b) => (b.onclick = async () => {
      if (b.disabled) return;
      const rid = b.dataset.rid;
      if (pk.multi) {
        pk.sel = pk.sel.includes(rid) ? pk.sel.filter((x) => x !== rid) : [...pk.sel, rid];
        return draw();
      }
      $$("#pk-list [data-rid]").forEach((x) => (x.disabled = true));
      b.classList.add("picked");
      try {
        if (pk.seq) {
          const r = await api("POST", "/api/plan/assign", { date: pk.date, recipe_id: rid, entry_type: pk.type });
          pk.added++; pk.items += (r && r.added) || 0; takenSet().add(pk.date); pk.inPlan[rid] = pk.inPlan[rid] && pk.inPlan[rid] < pk.date ? pk.inPlan[rid] : pk.date;
          const name = (pk.recipes.find((x) => x.id === rid) || {}).name || "it";
          advance(`Added ${name} to ${wkShort(pk.date)}`);
        } else { await assignRecipe(pk.date, rid, replacing ? replacing.entry_type : pk.type, replacing ? replacing.id : null); closeSheet(); replan(); }
      } catch (e) { fail(e); $$("#pk-list [data-rid]").forEach((x) => (x.disabled = false)); b.classList.remove("picked"); }
    }));
  };
  const arrange = async (ai) => {
    const days = empties();
    if (!days.length) return toast("Every day is planned");
    const ids = pk.sel.slice();
    let plan;
    if (ai) {
      $("#pk-ai").disabled = true; $("#pk-ai").textContent = "Arranging…";
      try { plan = (await api("POST", "/api/plan/arrange", { recipe_ids: ids, start: hz[0], end: hz[hz.length - 1], entry_type: pk.type })).assignments; }
      catch (e) { fail(e); } finally { $("#pk-ai").innerHTML = `${ic("sparkle")} Arrange with AI`; $("#pk-ai").disabled = false; }
      if (!plan) return;
    } else plan = days.slice(0, ids.length).map((d, i) => ({ date: d, recipe_id: ids[i] }));
    pk.preview = { plan, extra: Math.max(0, ids.length - days.length) };
    draw();
  };
  const drawPreview = () => {
    const { plan, extra } = pk.preview, byId = Object.fromEntries(pk.recipes.map((r) => [r.id, r]));
    $("#pk-list").innerHTML = `${extra ? `<p class="hint">${esc(plural(pk.sel.length, "recipe"))} selected but only ${esc(plural(plan.length, "empty day"))}: using the first ${esc(plan.length)}.</p>` : ""}
      <div class="group pk-preview">${plan.map((a) => `<div class="row"><div class="main"><div class="a">${esc((byId[a.recipe_id] || {}).name || "Recipe")}</div><div class="b">${esc(dayLong(a.date))}, ${esc(shortDate(a.date))}</div></div></div>`).join("")}</div>
      <div class="btn-row"><button class="btn sec" id="pv-back">Back</button><button class="btn" id="pv-apply">Apply</button></div>`;
    $("#pv-back").onclick = () => { pk.preview = null; draw(); };
    $("#pv-apply").onclick = async () => {
      const btn = $("#pv-apply"); btn.disabled = true;
      const made = []; let items = 0;
      try {
        for (const [i, a] of plan.entries()) {
          btn.textContent = `Planning ${i + 1} of ${plan.length}…`;
          const r = await api("POST", "/api/plan/assign", { date: a.date, recipe_id: a.recipe_id, entry_type: pk.type });
          if (r?.entry?.id != null) made.push(r.entry.id);
          items += (r && r.added) || 0;
        }
      } catch (e) { fail(e); }
      closeSheet(); replan();
      toast(`Planned ${plural(made.length, "day")}${items ? ` · ${plural(items, "item")} on your list` : ""}`, made.length ? "Undo" : null, async () => {
        try { for (const id of made) await api("DELETE", `/api/plan/${enc(id)}`); replan(); } catch (x) { fail(x); }
      });
    };
  };
  draw();
}

function fillEmpty(start, days) {
  const s = state.cfg.settings;
  const g = { start, days, meal_types: [...PLAN_TYPES], no_repeat_days: s.no_repeat_days, prefer_expiring: s.prefer_expiring,
    include_tags: [...(s.include_tags || [])], exclude_tags: [...(s.exclude_tags || [])], fill_empty_only: true };
  openSheet("Fill empty days", loading(), { onMount: () => runGenerate(g) });
}

function openEntry(e) {
  if (!e) return;
  const r = e.recipe || {};
  const img = imgUrl(r, "full");
  openSheet(entryName(e), `
    ${img && cssUrl(img) ? `<div style="height:190px;border-radius:14px;background:#ddd ${cssUrl(img)} center/cover;margin-bottom:12px"></div>` : ""}
    <div class="muted" style="margin:-4px 2px 14px">${esc(cap(e.entry_type))} · ${esc(fmt(parseISO(e.date), { weekday: "long", month: "long", day: "numeric" }))}</div>
    ${r.slug ? `<button class="btn" id="open-r">${ic("book")} Open recipe</button><div style="height:10px"></div>` : ""}
    <div class="btn-row"><button class="btn sec" id="swap">${ic("shuffle")} Swap</button><button class="btn red" id="rm">${ic("trash")} Remove</button></div>`, {
    onMount() {
      $("#open-r") && ($("#open-r").onclick = () => { closeSheet(true); openRecipe(r.slug); });
      $("#rm").onclick = () => { closeSheet(); removeEntry(e); };
      $("#swap").onclick = () => { closeSheet(true); openPicker(e.date, e.entry_type, e); };
    },
  });
}
const refresh = () => go(state.tab);

// ---------- generator
async function openGenerate(opts = {}) {
  const s = state.cfg.settings;
  const g = {
    start: opts.start || isoDate(today()), days: opts.days || 7,
    meal_types: [...(s.meal_types || ["dinner"])], no_repeat_days: s.no_repeat_days, prefer_expiring: s.prefer_expiring,
    include_tags: [...(s.include_tags || [])], exclude_tags: [...(s.exclude_tags || [])], fill_empty_only: s.fill_empty_only !== false,
  };
  const draw = () => {
    const presets = [[7, "Week"], [14, "2 Wks"], [30, "Month"]];
    sheetBody().innerHTML = `
      <div class="group">
        <div class="field"><label>Starting</label><input type="date" id="g-start" value="${esc(g.start)}"></div>
        <div class="field"><label>How long</label><div class="seg" style="margin:0;flex:1;max-width:230px">${presets.map(([n, l]) => `<button data-days="${n}" class="${g.days === n ? "on" : ""}">${l}</button>`).join("")}</div></div>
      </div>
      <div class="group-label">Which meals should I plan?</div>
      <div class="group"><div class="tag-cloud" id="g-types">${["breakfast", "lunch", "dinner", "side"].map((t) => `<button class="tag ${g.meal_types.includes(t) ? "on" : ""}" data-t="${t}">${cap(t)}</button>`).join("")}</div></div>
      <div class="group-label">Preferences</div>
      <div class="group">
        <div class="field"><label>No repeats for<small class="lh">The same recipe won't show up again within this many days.</small></label><input type="number" id="g-nr" min="0" max="90" value="${esc(g.no_repeat_days)}"> <span class="muted">days</span></div>
        <div class="field"><label>Use food before it goes bad<small class="lh">Favors recipes that use pantry items close to their use-by date.</small></label><label class="toggle"><input type="checkbox" id="g-exp" ${g.prefer_expiring ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>Only fill empty days<small class="lh">Leaves meals you already picked alone. Turn off to replace everything.</small></label><label class="toggle"><input type="checkbox" id="g-fill" ${g.fill_empty_only ? "checked" : ""}><span></span></label></div>
        <button class="row" id="g-tags"><div class="main"><div class="a">Kinds of recipes</div><div class="b">${tagSummary(g)} · only use or skip tags like Vegetarian or Soup</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <div style="height:16px"></div>
      <button class="btn" id="g-go">${ic("sparkle")} Suggest meals</button><p class="hint" style="text-align:center">You can swap or remove any suggestion before saving.</p>`;
    $("#g-start").onchange = (e) => (g.start = e.target.value);
    $$("[data-days]").forEach((b) => (b.onclick = () => { g.days = +b.dataset.days; draw(); }));
    $$("#g-types .tag").forEach((b) => (b.onclick = () => { const t = b.dataset.t; g.meal_types = g.meal_types.includes(t) ? g.meal_types.filter((x) => x !== t) : [...g.meal_types, t]; draw(); }));
    $("#g-nr").onchange = (e) => (g.no_repeat_days = +e.target.value || 0);
    $("#g-exp").onchange = (e) => (g.prefer_expiring = e.target.checked);
    $("#g-fill").onchange = (e) => (g.fill_empty_only = e.target.checked);
    $("#g-tags").onclick = () => pickTags(g, draw);
    $("#g-go").onclick = () => runGenerate(g);
  };
  openSheet("Plan meals for me", "", { onMount: draw });
}
const tagSummary = (g) => {
  const a = g.include_tags.length ? `Only: ${g.include_tags.join(", ")}` : "Any recipe";
  return esc(a + (g.exclude_tags.length ? ` · Skip: ${g.exclude_tags.join(", ")}` : ""));
};
async function pickTags(g, back) {
  sheetBody().innerHTML = loading();
  let tags = [];
  try { tags = (await api("GET", "/api/recipes")).tags; } catch (e) { fail(e); }
  const draw = () => {
    sheetBody().innerHTML = `<p class="hint" style="margin:0 4px 10px">Tap once to <b>only</b> use a tag, twice to <b>skip</b> it, again to clear.</p>
      <div class="group"><div class="tag-cloud">${tags.length ? tags.map((t) => `<button class="tag ${g.include_tags.includes(t) ? "on" : g.exclude_tags.includes(t) ? "off" : ""}" data-t="${esc(t)}">${esc(t)}</button>`).join("") : '<span class="muted">No tags in Mealie yet.</span>'}</div></div>
      <div style="height:14px"></div><button class="btn" id="t-done">Done</button>`;
    $$(".tag[data-t]").forEach((b) => (b.onclick = () => {
      const t = b.dataset.t;
      if (g.include_tags.includes(t)) { g.include_tags = g.include_tags.filter((x) => x !== t); g.exclude_tags.push(t); }
      else if (g.exclude_tags.includes(t)) g.exclude_tags = g.exclude_tags.filter((x) => x !== t);
      else g.include_tags.push(t);
      draw();
    }));
    $("#t-done").onclick = back;
  };
  draw();
}
async function runGenerate(g) {
  if (!g.meal_types.length) return toast("Pick at least one meal");
  sheetBody().innerHTML = loading();
  let res;
  try { res = await api("POST", "/api/plan/generate", g); } catch (e) { fail(e); return openGenerate(g); }
  const props = res.proposals;
  const draw = () => {
    if (!props.length) {
      sheetBody().innerHTML = `<div class="empty" style="color:var(--sub)"><div class="em">✅</div>Every slot in that range is already planned.</div><button class="btn sec" id="p-back">Back</button>`;
      $("#p-back").onclick = () => openGenerate(g); return;
    }
    const byDay = {};
    props.forEach((p, i) => (byDay[p.date] = byDay[p.date] || []).push([p, i]));
    let html = res.warnings.map((w) => `<div class="hint" style="margin:0 4px 10px">⚠️ ${esc(w)}</div>`).join("");
    Object.keys(byDay).sort().forEach((d) => {
      html += `<div class="group-label">${esc(fmt(parseISO(d), { weekday: "short", month: "short", day: "numeric" }))}</div><div class="group">`;
      byDay[d].forEach(([p, i]) => {
        const img = imgUrl(p.recipe);
        html += `<div class="row"><div class="thumb ${img ? "" : "ph"}" ${img ? bgStyle(img) : ""}>${img ? "" : ic("dish")}</div>
          <div class="main"><div class="a">${esc(p.recipe.name)}${p.recipe.uses_expiring ? '<span class="badge">uses expiring</span>' : ""}</div><div class="b">${esc(cap(p.entry_type))}</div></div>
          <button class="round-btn" style="background:rgba(118,118,128,.14);color:var(--text)" data-rr="${i}" aria-label="Swap">${ic("shuffle")}</button>
          <button class="round-btn" style="background:rgba(118,118,128,.14);color:var(--sub)" data-del="${i}" aria-label="Remove">${ic("x")}</button></div>`;
      });
      html += `</div>`;
    });
    html += `<div style="height:16px"></div><div class="btn-row"><button class="btn sec" id="p-again">${ic("refresh")} Redo</button><button class="btn" id="p-save">${ic("check")} Save ${props.length}</button></div>
      `;
    sheetBody().innerHTML = html;
    $$("[data-rr]").forEach((b) => (b.onclick = async () => {
      const p = props[+b.dataset.rr];
      try {
        const n = await api("POST", "/api/plan/reroll", { ...g, date: p.date, entry_type: p.entry_type, exclude_ids: [p.recipe.id],
          planned: props.map((x) => ({ date: x.date, recipe_id: x.recipe.id, entry_type: x.entry_type })) });
        props[+b.dataset.rr] = n; draw();
      } catch (e) { fail(e); }
    }));
    $$("[data-del]").forEach((b) => (b.onclick = () => { props.splice(+b.dataset.del, 1); draw(); }));
    $("#p-again").onclick = () => runGenerate(g);
    $("#p-save").onclick = async (ev) => {
      ev.target.disabled = true;
      try {
        // assign = put on the plan + add ingredients to the ongoing list (it replaces that day's meal of the same type)
        let added = 0;
        for (const p of props) { const r = await api("POST", "/api/plan/assign", { date: p.date, recipe_id: p.recipe.id, entry_type: p.entry_type }); added += (r && r.added) || 0; }
        closeSheet(); toast(`Added ${plural(props.length, "meal")} to your plan${added ? ` · ${plural(added, "item")} on your list` : ""}`, added ? "View list" : null, () => go("list")); refresh();
      } catch (e) { ev.target.disabled = false; fail(e); }
    };
  };
  draw();
}

// ------------------------------------------------------------------ SHOPPING LIST (one ongoing list, grouped by store, then aisle)
const L = { data: null, filter: localStorage.getItem("tp.store") || "all", quietUntil: 0, pantry: {} };
const storeLabel = (id) => (id == null ? "Any store" : ((L.data?.stores || []).find((s) => String(s.id) === String(id)) || {}).name || "Any store");
const itemTitle = (it) => (it.food ? cap(it.food) : it.text);
const itemSub = (it) => (it.food ? it.qty || (it.text && it.text.toLowerCase() !== it.food.toLowerCase() ? it.text : "") : it.qty || "");
const setStoreFilter = (f) => { L.filter = f; try { localStorage.setItem("tp.store", f); } catch (_) {} };

async function renderList() {
  app.innerHTML = topbar(`<button class="round-btn" id="btn-share" aria-label="Share">${ic("share")}</button>`) + `<h1 class="title">Shopping</h1><div id="lists">${loading()}</div>`;
  bindTopbar();
  if (!(await loadList())) return;
  $("#btn-share").onclick = () => openShare("list", { id: L.data.id, name: L.data.name || "Shopping list" });
  drawList();
}
async function loadList() {
  try { L.data = await api("GET", "/api/list"); }
  catch (e) { const b = $("#lists"); if (b) b.innerHTML = `<div class="banner">${esc(e.message)}</div>`; return false; }
  L.data.items = L.data.items || []; L.data.stores = L.data.stores || []; L.data.recently_checked = L.data.recently_checked || [];
  state.listId = L.data.id;
  try { localStorage.setItem("tp.list", L.data.id); } catch (_) {}
  return state.tab === "list" && !!$("#lists");
}
const reloadList = async (focusAdd) => { if (await loadList()) drawList(focusAdd); };

function drawList(focusAdd) {
  const box = $("#lists"), d = L.data;
  if (!box || !d) return;
  const stores = d.stores, items = d.items;
  if (L.filter !== "all" && L.filter !== "none" && !stores.some((s) => String(s.id) === L.filter)) setStoreFilter("all");
  const inFilter = (it) => L.filter === "all" || (L.filter === "none" ? it.store_id == null : String(it.store_id) === L.filter);
  const count = (f) => items.filter((it) => !it.checked && (f === "all" || (f === "none" ? it.store_id == null : String(it.store_id) === f))).length;
  const shown = items.filter(inFilter), toBuy = shown.filter((it) => !it.checked).length, anyLeft = items.some((it) => !it.checked);
  const addTo = L.filter !== "all" && L.filter !== "none" ? storeLabel(L.filter) : "";

  let html = `<div class="chips store-bar" id="st-bar" role="tablist">
      ${[["all", "All"], ...stores.map((s) => [String(s.id), s.name]), ["none", "Any store"]].map(([k, l]) =>
        `<button class="filter ${L.filter === k ? "on" : ""}" data-sf="${esc(k)}" role="tab" aria-selected="${L.filter === k}">${esc(l)}<span class="n">${count(k) || ""}</span></button>`).join("")}
      <button class="filter add" id="st-add">${ic("plus")} Store</button></div>
    <form class="quick-add" id="qa-form" autocomplete="off"><span class="qa-ic">${ic("plus")}</span>
      <input id="qa" name="qa" placeholder="${esc(addTo ? `Add to ${addTo}…` : "Add an item…")}" enterkeyhint="done" maxlength="200" aria-label="Add an item">
      <button type="submit" class="qa-go" aria-label="Add">${ic("check")}</button></form>
    <div class="qa-sug" id="qa-sug" role="listbox" aria-label="Suggestions" hidden></div>
    <div class="chips usual" id="qa-usual" aria-label="Usual items"></div>
    <div class="subtitle list-sub">${listSubtitle(toBuy, anyLeft)}</div><div class="list-cost" id="list-cost"></div>
    <div class="toolbar"><button class="pill-btn" id="l-trip">${ic("cart")} Log a grocery trip</button><button class="pill-btn" id="l-browse">${ic("list") || ic("plus")} Browse common items</button></div>`;

  // store → aisle grouping (stores in their saved order, "Any store" last)
  const order = [...stores.map((s) => String(s.id)), "none"];
  const byStore = new Map(order.map((k) => [k, []]));
  shown.forEach((it) => { const k = it.store_id == null ? "none" : String(it.store_id); if (!byStore.has(k)) byStore.set(k, []); byStore.get(k).push(it); });
  for (const [k, arr] of byStore) {
    if (!arr.length) continue;
    if (L.filter === "all") html += `<div class="store-h" data-sk="${esc(k)}"><h2>${esc(k === "none" ? "Any store" : storeLabel(k))}</h2><span>${arr.length}</span></div>`;
    const aisles = new Map();
    arr.forEach((it) => { const a = it.aisle || "Other"; if (!aisles.has(a)) aisles.set(a, []); aisles.get(a).push(it); });
    for (const [a, its] of aisles) html += `<div class="group-label section">${esc(a)}</div><div class="group shop">${its.map(listRow).join("")}</div>`;
  }
  if (!shown.length) html += `<div class="empty"><div class="em">🛒</div>${items.length ? "Nothing on the list for this store." : "Your list is empty.<br>Plan a meal and its ingredients land here, or type above."}</div>`;
  if (d.recently_checked.length) {
    html += `<details class="recent"><summary>Recently checked <span class="muted">${d.recently_checked.length}</span></summary><div class="group shop">${d.recently_checked.map((it) =>
      `<button class="row done" data-uncheck="${esc(it.id)}"><span class="emo">${esc(it.emoji || "🛒")}</span><div class="main"><div class="a">${esc(itemTitle(it))}</div><div class="b">${it.have ? "Had it · " : ""}Tap to put it back on the list</div></div><span class="check sq on">${ic("check")}</span></button>`).join("")}</div></details>`;
  }
  box.innerHTML = html;

  $$("#st-bar [data-sf]").forEach((b) => (b.onclick = () => { setStoreFilter(b.dataset.sf); drawList(); }));
  $("#st-add").onclick = () => addStoreInline();
  $("#l-trip").onclick = () => openTrip(() => reloadList());
  $("#qa-form").onsubmit = (e) => { e.preventDefault(); quickAdd(); };
  $("#l-browse").onclick = () => browseCommon();
  bindSuggest();
  drawUsual();
  $("#qa").onpaste = (e) => {
    const t = e.clipboardData?.getData("text") || "";
    if (t.includes("\n")) { e.preventDefault(); quickAdd(t.split(/\r?\n/)); }
  };
  if (focusAdd) $("#qa").focus();
  const on = $("#st-bar .filter.on"); on && on.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  $$("#lists [data-uncheck]").forEach((b) => (b.onclick = async () => {
    try { await api("PATCH", `/api/list/items/${enc(b.dataset.uncheck)}`, { checked: false }); reloadList(); } catch (e) { fail(e); }
  }));
  bindListRows(box);
  listCosts();
}
// Which planned meals need this item: "Tue · Chicken Milanese 1 tbsp" tags (two, then "+N more" expands)
function usesHtml(it, recs) {
  const u = it.uses || [];
  if (!u.length) return recs && recs.length && !it.manual ? `<div class="r">${esc(recs.join(" · "))}</div>` : "";
  const tag = (x) => `<span class="use-tag">${esc(wkShort(x.date))} · ${esc(x.recipe_name)}${x.qty_text ? ` <b>${esc(x.qty_text)}</b>` : ""}</span>`;
  return `<div class="uses-tags">${u.slice(0, 2).map(tag).join("")}${u.length > 2 ? `<button class="use-more" data-uses-more aria-expanded="false">+${esc(u.length - 2)} more</button><span class="use-rest" hidden>${u.slice(2).map(tag).join("")}</span>` : ""}</div>`;
}
function listRow(it) {
  const sub = itemSub(it), recs = (it.recipes || []).filter(Boolean);
  if (it.checked) {
    return `<div class="row li checked ${it.have ? "had" : ""}" data-id="${esc(it.id)}"><div class="li-in">
      <span class="emo">${esc(it.emoji || "🛒")}</span>
      <div class="main" data-check><div class="a">${esc(itemTitle(it))}</div>${sub ? `<div class="b">${esc(sub)}</div>` : ""}${it.bought ? `<div class="b bought">${esc(it.bought)}</div>` : ""}</div>
      ${it.have ? `<span class="have-tag">have</span>` : ""}
      <button class="check sq on" data-check aria-label="Put ${esc(itemTitle(it))} back on the list" aria-pressed="true">${ic("check")}</button>
    </div></div>`;
  }
  return `<div class="row li" data-id="${esc(it.id)}">
    <div class="li-under" aria-hidden="true">${ic("check")} I have it</div>
    <div class="li-in">
      <span class="emo">${esc(it.emoji || "🛒")}</span>
      <div class="main" data-check><div class="a">${esc(itemTitle(it))}</div>${sub ? `<div class="b">${esc(sub)}</div>` : ""}${usesHtml(it, recs)}${it.manual && !(it.uses || []).length ? `<div class="uses-tags"><span class="use-tag mine">Added by you</span></div>` : ""}${it.last ? `<div class="b last-hint">${esc(it.last)}</div>` : ""}</div>
      <button class="have-btn" data-have title="I already have this">Have</button>
      <button class="store-chip ${it.store_id == null ? "none" : ""}" data-store aria-haspopup="menu" aria-label="Store: ${esc(storeLabel(it.store_id))}">${esc(storeLabel(it.store_id))}</button>
      <button class="check sq" data-check aria-label="Got ${esc(itemTitle(it))}">${ic("check")}</button>
    </div></div>`;
}
const findItem = (id) => L.data.items.find((x) => String(x.id) === String(id));
function bindListRows(box) {
  box.onclick = (e) => {
    if (Date.now() < L.quietUntil) return;
    const row = e.target.closest(".row.li"); if (!row) return;
    const it = findItem(row.dataset.id); if (!it) return;
    const more = e.target.closest("[data-uses-more]");
    if (more) { e.stopPropagation(); more.nextElementSibling.hidden = false; more.remove(); return; }
    if (it.checked) return uncheckItem(it, row);
    if (e.target.closest("[data-store]")) return storeMenu(e.target.closest("[data-store]"), it);
    if (e.target.closest("[data-have]")) return haveItem(it, row);
    if (e.target.closest("[data-check]")) return checkItem(it, row);
  };
  // touch: swipe left or long-press for "I have this"
  box.onpointerdown = (e) => {
    if (e.pointerType === "mouse") return;
    const row = e.target.closest(".row.li"); if (!row || row.classList.contains("checked") || e.target.closest("button")) return;
    const inner = $(".li-in", row), x0 = e.clientX, y0 = e.clientY, pid = e.pointerId;
    let mode = null, dx = 0;
    const timer = setTimeout(() => { if (!mode) { mode = "press"; L.quietUntil = Date.now() + 600; try { navigator.vibrate?.(12); } catch (_) {} done(); haveItem(findItem(row.dataset.id), row); } }, 550);
    const mv = (ev) => {
      if (ev.pointerId !== pid) return;
      const ddx = ev.clientX - x0, ddy = ev.clientY - y0;
      if (!mode) {
        if (Math.abs(ddx) > 10 && Math.abs(ddx) > Math.abs(ddy)) { mode = "swipe"; clearTimeout(timer); row.classList.add("swiping"); }
        else if (Math.abs(ddy) > 10) { clearTimeout(timer); mode = "scroll"; return done(); }
        else return;
      }
      if (mode === "swipe") { dx = Math.min(0, ddx); inner.style.transform = `translateX(${dx}px)`; row.classList.toggle("armed", dx < -80); }
    };
    const end = (ev) => {
      if (ev.pointerId !== pid) return;
      clearTimeout(timer);
      if (mode === "swipe") {
        L.quietUntil = Date.now() + 350;
        if (dx < -80) { inner.style.transform = "translateX(-100%)"; haveItem(findItem(row.dataset.id), row); }
        else inner.style.transform = "";
        row.classList.remove("swiping", "armed");
      }
      done();
    };
    const done = () => { clearTimeout(timer); window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", end); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
  };
  box.oncontextmenu = (e) => { if (e.target.closest(".row.li")) e.preventDefault(); };
}
// A ticked row stays where it is (struck through) for a few hours; tapping it again puts it back.
const listSubtitle = (n, anyLeft) => (n ? `${plural(n, "item")} to buy · tick when it's in the cart` : anyLeft ? "Nothing for this store" : "All done 🎉");
function refreshCounts() {
  const sub = $(".list-sub");
  const inFilter = (it) => L.filter === "all" || (L.filter === "none" ? it.store_id == null : String(it.store_id) === L.filter);
  if (sub) sub.textContent = listSubtitle(L.data.items.filter((x) => !x.checked && inFilter(x)).length, L.data.items.some((x) => !x.checked));
  $$("#st-bar [data-sf]").forEach((b) => { const k = b.dataset.sf, c = L.data.items.filter((x) => !x.checked && (k === "all" || (k === "none" ? x.store_id == null : String(x.store_id) === k))).length; $(".n", b).textContent = c || ""; });
  const sh = $$(".store-h");
  sh.forEach((h) => { const g = []; let el = h.nextElementSibling; while (el && !el.classList.contains("store-h") && !el.classList.contains("empty") && el.tagName !== "DETAILS") { g.push(el); el = el.nextElementSibling; } const n = g.reduce((t, e) => t + $$(".row.li:not(.checked)", e).length, 0); const sp = $("span", h); if (sp) sp.textContent = n; });
}
function redrawRow(it, row) {
  const tmp = document.createElement("div");
  tmp.innerHTML = listRow(it);
  const fresh = tmp.firstElementChild;
  row.replaceWith(fresh);
  refreshCounts();
  return fresh;
}
async function uncheckItem(it, row) {
  if (!it || row.classList.contains("busy")) return;
  row.classList.add("busy");
  try {
    const pid = L.pantry[it.id];
    if (pid) await api("POST", `/api/lists/${enc(L.data.id)}/items/${enc(it.id)}/undo`, { pantry_item_id: pid });
    else await api("PATCH", `/api/list/items/${enc(it.id)}`, { checked: false });
    delete L.pantry[it.id];
    Object.assign(it, { checked: false, have: false, checked_at: null });
    redrawRow(it, row);
  } catch (e) { row.classList.remove("busy"); fail(e); }
}
async function checkItem(it, row) {
  if (!it) return;
  if (it.checked) return uncheckItem(it, row);
  if (row.classList.contains("busy")) return;
  Object.assign(it, { checked: true, have: false, checked_at: new Date().toISOString() });
  row = redrawRow(it, row);
  row.classList.add("busy");
  try {
    const r = await api("PATCH", `/api/list/items/${enc(it.id)}`, { checked: true });
    row.classList.remove("busy");
    const p = r && r.pantry_item;
    if (p) L.pantry[it.id] = p.id;
    toast(p ? `${p.name} → ${cap(p.location)}` : `Got ${itemTitle(it)}`, "Undo", () => { const rw = $(`#lists .row.li[data-id="${CSS.escape(String(it.id))}"]`); if (rw) uncheckItem(it, rw); else reloadList(); });
  } catch (e) { Object.assign(it, { checked: false, checked_at: null }); redrawRow(it, row); fail(e); }
}
async function haveItem(it, row) {
  if (!it || it.checked || row.classList.contains("busy")) return;
  Object.assign(it, { checked: true, have: true, checked_at: new Date().toISOString() });
  row = redrawRow(it, row);
  row.classList.add("busy");
  try {
    await api("POST", `/api/list/items/${enc(it.id)}/have`);
    row.classList.remove("busy");
    toast(`Have ${itemTitle(it)}`, "Undo", () => { const rw = $(`#lists .row.li[data-id="${CSS.escape(String(it.id))}"]`); if (rw) uncheckItem(it, rw); else reloadList(); });
  } catch (e) { Object.assign(it, { checked: false, have: false, checked_at: null }); redrawRow(it, row); fail(e); }
}
// "Always have": never put this food on the list again (salt, oil…); removes it everywhere now, with Undo
async function alwaysHave(name, after) {
  try {
    const r = await api("POST", "/api/staples/add", { name });
    if (state.cfg?.settings) state.cfg.settings.staples = r.staples;
    toast(`${r.name} won't be added again`, "Undo", async () => {
      try { const u = await api("POST", "/api/staples/remove", { name: r.name, restore: r.restore }); if (state.cfg?.settings) state.cfg.settings.staples = u.staples; after && after(); } catch (x) { fail(x); }
    });
    after && after();
  } catch (e) { fail(e); }
}
function storeMenu(anchor, it) {
  const opts = [...L.data.stores.map((s) => [String(s.id), s.name]), ["", "Any store"]];
  const cur = it.store_id == null ? "" : String(it.store_id);
  popover(anchor, `<div class="pop-h">Buy ${esc(itemTitle(it))} at</div>${opts.map(([k, l]) =>
    `<button data-st="${esc(k)}" role="menuitemradio" aria-checked="${k === cur}" class="${k === cur ? "cur" : ""}">${esc(l)}${k === cur ? ic("check") : ""}</button>`).join("")}
    ${it.food ? `<div class="pop-sep"></div><button data-always>${ic("check")} Always have ${esc(itemTitle(it).toLowerCase())}</button>` : ""}`, (el) => {
    $("[data-always]", el) && ($("[data-always]", el).onclick = () => { closePop(); alwaysHave(it.food, () => reloadList()); });
    $$("[data-st]", el).forEach((b) => (b.onclick = async () => {
      closePop();
      const sid = b.dataset.st === "" ? null : b.dataset.st;
      if ((sid ?? "") === cur) return;
      const prev = it.store_id;
      const target = L.data.stores.find((s) => String(s.id) === sid);
      it.store_id = target ? target.id : null;
      drawList();
      try {
        await api("PATCH", `/api/list/items/${enc(it.id)}`, { store_id: it.store_id });
        toast(it.store_id == null ? `${itemTitle(it)} · any store` : `${itemTitle(it)} → ${storeLabel(it.store_id)} · remembered next time`);
      } catch (e) { it.store_id = prev; drawList(); fail(e); }
    }));
  });
}
// ---------- faster adding: autocomplete (your items → your foods → common groceries), usual items, browse by aisle
const QA = { t: null, items: [], i: -1 };
function bindSuggest() {
  const inp = $("#qa"), box = $("#qa-sug"); if (!inp || !box) return;
  const hide = () => { box.hidden = true; QA.items = []; QA.i = -1; inp.setAttribute("aria-expanded", "false"); };
  const draw = () => {
    if (!QA.items.length) return hide();
    box.hidden = false; inp.setAttribute("aria-expanded", "true");
    box.innerHTML = QA.items.map((x, k) => `<button type="button" class="qa-opt ${k === QA.i ? "on" : ""}" role="option" data-k="${k}"><b>${esc(x.name)}</b>
      <small>${esc([x.source === "history" ? "You've added this" : x.source === "food" ? "" : x.aisle, x.size ? `usually ${x.size}` : "", x.last || ""].filter(Boolean).join(" · "))}</small></button>`).join("");
    $$("[data-k]", box).forEach((b) => (b.onmousedown = (e) => e.preventDefault()));
    $$("[data-k]", box).forEach((b) => (b.onclick = () => pick(QA.items[+b.dataset.k])));
  };
  const pick = (x) => { const m = /^\s*(\d+(?:[./]\d+)?)\s+/.exec(inp.value); hide(); quickAdd([`${m ? m[1] + " " : ""}${x.name}`]); };
  inp.oninput = () => {
    clearTimeout(QA.t);
    const q = inp.value.replace(/^\s*\d+(?:[./]\d+)?\s*/, "").trim();
    if (q.length < 2) return hide();
    QA.t = setTimeout(async () => { try { QA.items = (await api("GET", `/api/grocery/suggest?q=${enc(inp.value)}`)).items || []; QA.i = -1; if (document.activeElement === inp) draw(); } catch (_) {} }, 140);
  };
  inp.onkeydown = (e) => {
    if (box.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); QA.i = Math.min(QA.items.length - 1, QA.i + 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); QA.i = Math.max(-1, QA.i - 1); draw(); }
    else if (e.key === "Enter" && QA.i >= 0) { e.preventDefault(); pick(QA.items[QA.i]); }
    else if (e.key === "Escape") hide();
  };
  inp.onblur = () => setTimeout(hide, 150);
  inp.setAttribute("role", "combobox"); inp.setAttribute("aria-autocomplete", "list"); inp.setAttribute("aria-controls", "qa-sug");
}
async function drawUsual() {
  const box = $("#qa-usual"); if (!box) return;
  let u; try { u = await api("GET", "/api/grocery/usual"); } catch (_) { return; }
  if (!$("#qa-usual")) return;
  box.innerHTML = (u.items || []).map((n) => `<button class="filter sm" data-usual="${esc(n)}">${ic("plus")} ${esc(n)}</button>`).join("");
  $$("[data-usual]", box).forEach((b) => (b.onclick = () => quickAdd([b.dataset.usual])));
}
// "Browse common items": a photo/emoji grid by aisle, with what's already at home. Tap to pick, long-press for how many.
async function browseCommon() {
  openSheet("Common items", loading(), { wide: true });
  let d; try { d = await api("GET", "/api/grocery/catalog"); } catch (e) { return fail(e); }
  const picked = new Map();   // name -> quantity
  const all = d.aisles.flatMap((a) => a.items);
  const body = sheetBody(); if (!body) return;
  const tile = (it) => `<button class="bc-tile" data-bc="${esc(it.name)}" data-w="${esc((it.name + " " + it.food).toLowerCase())}" aria-pressed="false" aria-label="${esc(it.name)}${it.home ? `, ${it.home} at home` : ""}">
      <span class="bc-pic">${it.photo ? `<img src="/img/ing?name=${encodeURIComponent(it.name)}" alt="" loading="lazy">` : `<span class="bc-emo">${esc(it.emoji)}</span>`}</span>
      ${it.home ? `<span class="bc-home">${esc(it.home)} at home${it.left ? ` · ${esc(it.left)}` : ""}</span>` : ""}
      <span class="bc-q" aria-hidden="true">${ic("plus")}</span><span class="bc-n">${esc(it.name)}</span></button>`;
  body.innerHTML = `<div class="search">${ic("search")}<input id="bc-q" placeholder="Filter, e.g. milk" autocomplete="off" aria-label="Filter common items"></div>
    <p class="hint" style="margin:6px 2px">Tap to pick, long-press to choose how many.</p>
    <div id="bc-list">${d.aisles.map((a) => `<div class="group-label bc-h">${esc(a.aisle)}${a.home ? ` <span class="bc-ah">${esc(a.home)} at home</span>` : ""}</div><div class="bc-grid bc-aisle">${a.items.map(tile).join("")}</div>`).join("")}</div>
    <div class="bc-bar"><button class="btn" id="bc-add" disabled>Add to list</button></div>`;
  const btn = $("#bc-add");
  const sync = () => { const n = picked.size; btn.disabled = !n; btn.textContent = n ? `Add ${plural(n, "item")} to list` : "Add to list"; };
  const mark = (b) => {
    const q = picked.get(b.dataset.bc) || 0;
    b.classList.toggle("on", q > 0); b.setAttribute("aria-pressed", String(q > 0));
    $(".bc-q", b).innerHTML = q > 1 ? `×${q}` : q ? ic("check") : ic("plus");
  };
  const qtyPicker = (b) => {
    const n = b.dataset.bc; let q = picked.get(n) || 1;
    popover(b, `<div class="bc-stepper" role="group" aria-label="How many ${esc(n)}"><button data-s="-1" aria-label="Fewer">−</button><b id="bc-qn">${q}</b><button data-s="1" aria-label="More">+</button><button class="btn small" data-ok>Done</button></div>`, (el) => {
      $$("[data-s]", el).forEach((x) => (x.onclick = () => { q = Math.max(0, Math.min(24, q + +x.dataset.s)); $("#bc-qn", el).textContent = q; }));
      $("[data-ok]", el).onclick = () => { closePop(); q ? picked.set(n, q) : picked.delete(n); mark(b); sync(); };
    });
  };
  $$("[data-bc]", body).forEach((b) => {
    let t = 0, long = false;
    b.onpointerdown = () => { long = false; clearTimeout(t); t = setTimeout(() => { long = true; try { navigator.vibrate?.(15); } catch (_) {} qtyPicker(b); }, 500); };
    b.onpointerup = b.onpointerleave = b.onpointercancel = () => clearTimeout(t);
    b.oncontextmenu = (e) => e.preventDefault();
    b.onclick = () => { if (long) { long = false; return; } const n = b.dataset.bc; picked.has(n) ? picked.delete(n) : picked.set(n, 1); mark(b); sync(); };
  });
  $("#bc-q").oninput = (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$("[data-bc]", body).forEach((b) => (b.hidden = q && !b.dataset.w.includes(q)));
    $$(".bc-aisle", body).forEach((g) => { const any = $$("[data-bc]", g).some((b) => !b.hidden); g.hidden = !any; g.previousElementSibling.hidden = !any; });
  };
  btn.onclick = async () => { const items = [...picked].map(([n, q]) => (q > 1 ? `${q} ${n}` : n)); closeSheet(); await quickAdd(items); };
  void all;
}
async function quickAdd(lines) {
  const inp = $("#qa");
  const items = (lines || [inp.value]).map((x) => String(x).trim()).filter(Boolean).slice(0, 100);
  if (!items.length) return;
  const sid = L.filter !== "all" && L.filter !== "none" ? (L.data.stores.find((s) => String(s.id) === L.filter) || {}).id : undefined;
  inp.disabled = true;
  try {
    await api("POST", "/api/list/items", sid != null ? { items, store_id: sid } : { items });
    inp.value = "";
    toast(items.length === 1 ? `Added ${items[0]}` : `Added ${items.length} items`);
    await reloadList(true);
  } catch (e) { fail(e); inp.disabled = false; inp.focus(); }
}
function addStoreInline() {
  const btn = $("#st-add");
  if (!btn) return;
  if (L.data.stores.length >= 12) return toast("You can have up to 12 stores", "Manage", () => { openSettings(); });
  btn.outerHTML = `<form class="filter add-form" id="st-new-f"><input id="st-new" maxlength="40" placeholder="Store name" aria-label="New store name" enterkeyhint="done"></form>`;
  const inp = $("#st-new");
  inp.focus();
  let busy = false;
  const cancel = () => { if (!busy) drawList(); };
  inp.onblur = () => setTimeout(cancel, 120);
  inp.onkeydown = (e) => { if (e.key === "Escape") { e.preventDefault(); cancel(); } };
  $("#st-new-f").onsubmit = async (e) => {
    e.preventDefault();
    const name = inp.value.trim().slice(0, 40);
    if (!name) return cancel();
    if (L.data.stores.some((s) => s.name.toLowerCase() === name.toLowerCase())) { toast(`${name} is already a store`); return cancel(); }
    busy = true;
    try {
      const r = await saveStores([...L.data.stores.map((s) => ({ id: s.id, name: s.name })), { name }]);
      L.data.stores = r;
      const made = r.find((s) => s.name === name);
      if (made) setStoreFilter(String(made.id));
      toast(`Added ${name}`);
    } catch (x) { fail(x); }
    busy = false;
    drawList();
  };
}
// PUT /api/stores replaces the store list (existing ids are kept); returns the saved list.
async function saveStores(list) {
  const r = await api("PUT", "/api/stores", list);
  const out = Array.isArray(r) ? r : Array.isArray(r?.stores) ? r.stores : await api("GET", "/api/stores");
  return out.slice().sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
}

// ------------------------------------------------------------------ INVENTORY (the "pantry" route): list or slot grid
const isPhone = () => matchMedia("(max-width: 700px)").matches;
const invView = () => { try { return localStorage.getItem("tp.invView") || (isPhone() ? "grid" : "list"); } catch (_) { return "list"; } };
function stackText(it) {
  if (it.qty != null) return it.unit ? (it.left_text || "").replace(/ left$/, "") : `×${+(+it.qty).toFixed(2)}`;
  return "";
}
function durability(it) {
  const left = Math.max(0, Math.min(1, +it.amount_left || 0));
  const exp = it.days_left != null && it.days_left <= 1;
  const color = exp || left <= 0.25 ? "var(--red)" : left <= 0.5 || (it.days_left != null && it.days_left <= 3) ? "var(--orange)" : "var(--green)";
  return `<span class="dura" aria-hidden="true"><i style="width:${Math.round(left * 100)}%;background:${color}"></i></span>`;
}
const INV = { sel: null };   // Select mode on Inventory: a Set of item ids
const invMark = (it) => (INV.sel ? `<span class="selc ${INV.sel.has(it.id) ? "on" : ""}" aria-hidden="true">${INV.sel.has(it.id) ? ic("check") : ""}</span>` : "");
function slotHtml(it) {
  const st = stackText(it), on = INV.sel && INV.sel.has(it.id);
  return `<button class="slot ${on ? "sel" : ""}" data-id="${esc(it.id)}" ${INV.sel ? `aria-pressed="${!!on}"` : ""} aria-label="${esc(it.name)}${st ? `, ${esc(st)}` : ""}${it.days_left != null ? `, ${esc(relExpiry(it))}` : ""}">${invMark(it)}
    ${it.image ? `<img src="${esc(it.image)}" alt="">` : `<span class="slot-emo">${esc(it.emoji || "🥫")}</span>`}
    ${st ? `<b class="stack">${esc(st)}</b>` : ""}${it.review ? `<span class="rv-badge">Review later</span>` : ""}${durability(it)}<span class="slot-name">${esc(it.name)}</span></button>`;
}
async function renderPantry() {
  const view = invView();
  if (!state.invKeepSel) INV.sel = null;
  state.invKeepSel = false;
  document.body.classList.toggle("selecting", !!INV.sel);
  app.innerHTML = topbar(`<div class="seg mini-seg" id="inv-view" role="tablist" aria-label="View"><button data-v="grid" class="${view === "grid" ? "on" : ""}" role="tab" aria-selected="${view === "grid"}">Grid</button><button data-v="list" class="${view === "list" ? "on" : ""}" role="tab" aria-selected="${view === "list"}">List</button></div><span class="grow"></span><button class="text-btn" id="p-select">${INV.sel ? "Cancel" : "Select"}</button><button class="round-btn" id="p-more" aria-label="More" aria-haspopup="menu">${ic("more")}</button><button class="round-btn" id="btn-addp" aria-label="Add">${ic("plus")}</button>`) +
    `<h1 class="title">Inventory</h1>
    <div class="toolbar"><button class="pill-btn ink" id="p-scan">${ic("scan")} Stock up</button><button class="pill-btn" id="p-exp">${ic("clock")} Expiring<span class="pb-n" id="p-exp-n" hidden></span></button></div>
    <div id="inv-items">${loading()}</div><div class="sel-bar" id="inv-bar" hidden></div>`;
  bindTopbar();
  $("#p-select").onclick = () => { INV.sel = INV.sel ? null : new Set(); state.invKeepSel = true; renderPantry(); };
  $("#p-scan").onclick = () => startStockUp(renderPantry);
  $("#p-exp").onclick = () => { location.hash = "inventory/expiring"; };
  $("#p-more").onclick = () => popover($("#p-more"), `<button data-a="trip">${ic("cart")} Log a grocery trip</button><button data-a="ci">${ic("check")} Kitchen check-in</button><button data-a="share">${ic("share")} Share or print</button>${c_native() ? `<button data-a="export">${ic("file")} Export</button>` : ""}`, (el) => {
    $$("[data-a]", el).forEach((b) => (b.onclick = () => { closePop(); ({ trip: () => openTrip(renderPantry), ci: () => openCheckin(renderPantry), share: () => openShare("pantry", {}), export: () => openExport() })[b.dataset.a](); }));
  });
  $("#btn-addp").onclick = () => openAddPantry(renderPantry);
  $$("#inv-view [data-v]").forEach((b) => (b.onclick = () => { try { localStorage.setItem("tp.invView", b.dataset.v); } catch (_) {} renderPantry(); }));
  let items;
  try { items = (await api("GET", "/api/pantry")).items; } catch (e) { if ($("#inv-items")) $("#inv-items").innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  if (!$("#inv-items")) return;   // navigated away while loading
  const f = state.pantryFilter;
  const counts = { all: items.length, fridge: 0, freezer: 0, pantry: 0 };
  items.forEach((i) => counts[i.location]++);
  const shown = f === "all" ? items : items.filter((i) => i.location === f);
  const soon = items.filter((i) => i.days_left !== null && i.days_left <= 3).length;
  if (soon && $("#p-exp-n")) { $("#p-exp-n").textContent = soon; $("#p-exp-n").hidden = false; $("#p-exp").setAttribute("aria-label", `Expiring, ${soon} to use soon or past date`); }
  const toReview = items.filter((i) => i.review).length;
  let html = `<div class="subtitle">${items.length} items${soon ? ` · ${soon} to use soon` : ""}</div>${toReview ? `<button class="nudge" id="inv-review"><span class="ic bg-ink">${ic("scan")}</span><span><b>${esc(plural(toReview, "item"))} to review</b><small>Add a name, size or photo so the next scan is instant</small></span><span class="sdot warn" aria-hidden="true"></span><span class="chev">${ic("chevR")}</span></button>` : ""}
    <div class="seg">${[["all", "All"], ["fridge", "Fridge"], ["freezer", "Freezer"], ["pantry", "Pantry"]].map(([k, l]) =>
      `<button data-f="${k}" class="${f === k ? "on" : ""}">${l}${counts[k] ? ` ${counts[k]}` : ""}</button>`).join("")}</div>`;
  if (!shown.length) {
    html += `<div class="empty"><div class="em">🥬</div>${items.length ? "Nothing here." : "Your inventory is empty.<br>Scan what you have, or check items off your shopping list and they'll show up here with use-by dates."}</div>`;
  } else if (view === "grid") {
    const hot = shown.filter((i) => i.days_left != null).sort((a, b) => a.days_left - b.days_left).slice(0, 9);
    if (hot.length >= 3) html += `<div class="hotbar-h">Use soonest</div><div class="hotbar">${hot.map(slotHtml).join("")}</div>`;
    const known = new Set(invPlaces().map(([k]) => k));
    for (const [k, l] of invPlaces()) {   // a section per place: fridge, freezer, pantry, then shelves like the spice cabinet
      const its = shown.filter((i) => (i.place && known.has(i.place) ? i.place : i.location) === k);
      if (its.length) html += `<div class="slots-h">${esc(l)} <span>${its.length}</span></div><div class="slots">${its.map(slotHtml).join("")}</div>`;
    }
  } else {
    html += `<div class="group" style="margin-top:12px">${shown.map((it) => {
      const left = Math.round(it.amount_left * 100);
      return `<button class="row ${INV.sel && INV.sel.has(it.id) ? "sel" : ""}" data-id="${esc(it.id)}" ${INV.sel ? `aria-pressed="${INV.sel.has(it.id)}"` : ""}>${invMark(it)}${it.image ? `<img class="sb-img" src="${esc(it.image)}" alt="">` : `<span class="emo">${esc(it.emoji || "🥫")}</span>`}
        <div class="main"><div class="a">${esc(it.name)}${it.review ? ` <span class="rv-badge inline">Review later</span>` : ""}</div>${it.product ? `<div class="b">${esc(it.product)}</div>` : ""}<div class="b">${it.place_label ? `${esc(it.place_label)} · ` : ""}${it.opened_on ? "Opened" : "Sealed"}${it.qty != null ? ` · ${esc(it.left_text)}` : left < 100 ? ` · ${left}% left` : ""}${it.quantity_text && it.quantity_text !== it.name ? ` · ${esc(it.quantity_text)}` : ""}</div>
        ${left < 100 ? `<div class="meter"><i style="width:${left}%;background:${left <= 25 ? "var(--orange)" : "var(--green)"}"></i></div>` : ""}</div>${expiryPill(it)}</button>`;
    }).join("")}</div>`;
  }
  $("#inv-items").innerHTML = html;
  $$("[data-f]").forEach((b) => (b.onclick = () => { state.pantryFilter = b.dataset.f; renderPantry(); }));
  $("#inv-review") && ($("#inv-review").onclick = () => openReviewItems(renderPantry));
  $$("#inv-items [data-id]").forEach((b) => (b.onclick = () => {
    const it = items.find((i) => String(i.id) === b.dataset.id);
    if (!INV.sel) return openPantryItem(it, renderPantry);
    INV.sel.has(it.id) ? INV.sel.delete(it.id) : INV.sel.add(it.id);
    state.invKeepSel = true; renderPantry();
  }));
  drawInvBar(shown);
}
// Select mode bar: move, mark used up, set a date, delete (with Undo; deleted items are purged once Undo is gone)
function drawInvBar(shown) {
  const bar = $("#inv-bar"); if (!bar) return;
  if (!INV.sel) { bar.hidden = true; return; }
  bar.hidden = false;
  const n = INV.sel.size, ids = [...INV.sel];
  const bulk = async (body, msg) => {
    try { await api("POST", "/api/pantry/bulk", { ids, ...body }); if (msg) toast(msg); INV.sel = new Set(); state.invKeepSel = true; renderPantry(); }
    catch (e) { fail(e); }
  };
  bar.innerHTML = `<div class="sel-row"><b>${esc(n)} selected</b><button class="text-btn" id="ib-all">Select all</button><span class="grow"></span><button class="text-btn strong" id="ib-done">Done</button></div>
    <div class="sel-row ib-acts">
      <span class="ib-group"><span class="muted small">Move to</span>${invPlaces().map(([k, l]) => `<button class="chip-s" data-mv="${esc(k)}" ${n ? "" : "disabled"}>${esc(l)}</button>`).join("")}</span>
      <button class="chip-s" id="ib-used" ${n ? "" : "disabled"}>Used up</button>
      <label class="chip-s ib-date">Exp <input type="date" id="ib-date" ${n ? "" : "disabled"} aria-label="Use-by date for the selected items"></label>
      ${c_native() ? `<button class="chip-s" id="ib-exp" ${n ? "" : "disabled"}>Export selected</button>` : ""}
      <button class="chip-s danger" id="ib-del" ${n ? "" : "disabled"}>Delete</button></div>`;
  $("#ib-all").onclick = () => { shown.forEach((i) => INV.sel.add(i.id)); state.invKeepSel = true; renderPantry(); };
  $("#ib-done").onclick = () => { INV.sel = null; renderPantry(); };
  $("#ib-exp") && ($("#ib-exp").onclick = () => openExport(ids));
  $$("[data-mv]", bar).forEach((b) => (b.onclick = () => bulk({ action: "move", location: b.dataset.mv }, `Moved ${plural(n, "item")} to ${b.textContent}`)));
  $("#ib-used").onclick = () => bulk({ action: "used" }, `${plural(n, "item")} marked used up`);
  $("#ib-date").onchange = (e) => e.target.value && bulk({ action: "set_date", expires_on: e.target.value, source: "package" }, `Use-by date set for ${plural(n, "item")}`);
  $("#ib-del").onclick = async () => {
    try {
      await api("POST", "/api/pantry/bulk", { ids, action: "delete" });
      let undone = false;
      toast(`Deleted ${plural(n, "item")}`, "Undo", async () => {
        undone = true;
        try { await api("POST", "/api/pantry/bulk", { ids, action: "restore" }); state.invKeepSel = false; renderPantry(); } catch (x) { fail(x); }
      });
      setTimeout(() => { if (!undone) api("POST", "/api/pantry/bulk", { ids, action: "purge" }).catch(() => {}); }, 6500);
      INV.sel = new Set(); state.invKeepSel = true; renderPantry();
    } catch (e) { fail(e); }
  };
}

const PANTRY_UNITS = [["", "count"], ["tsp", "tsp"], ["tbsp", "tbsp"], ["cup", "cup"], ["fl oz", "fl oz"], ["pint", "pint"],
  ["quart", "quart"], ["gallon", "gallon"], ["ml", "ml"], ["l", "l"], ["oz", "oz"], ["lb", "lb"], ["g", "g"], ["kg", "kg"],
  ["piece", "piece"], ["clove", "clove"], ["can", "can"], ["slice", "slice"], ["stick", "stick"], ["jar", "jar"], ["bag", "bag"],
  ["box", "box"], ["package", "package"], ["bottle", "bottle"], ["loaf", "loaf"], ["dozen", "dozen"]];
function openPantryItem(it, after) {
  if (!it) return;
  const act = async (body, msg) => {
    try { const r = await api("PATCH", `/api/pantry/${enc(it.id)}`, body); if (msg) toast(msg); return r; } catch (e) { fail(e); return null; }
  };
  const draw = (it) => {
    const left = Math.round(it.amount_left * 100);
    const rule = it.rule;
    const ruleLine = rule ? `${rule.name}` : "No match — set one so opened items get a countdown";
    const srcLabel = { package: "printed date", manual: "set by you", opened: "countdown since opening", frozen: "countdown since freezing", none: "" }[it.expiry_source] || "";
    sheetBody().innerHTML = `
      ${c_native() ? `<div class="pi-photo"><span class="pi-pic ${it.image ? "has-img" : ""}">${it.image ? `<img src="${esc(it.image)}" alt="">` : `<span>${esc(it.emoji || "🥫")}</span>`}${it.image ? fillSliderHtml(it.amount_left, true) : ""}</span>
        <div class="pi-photo-acts">${it.image ? `<button class="chip-s" id="pi-cut">✂️ Cut out background</button>${it.image_cut ? `<button class="chip-s" id="pi-orig">Use original photo</button>` : ""}` : ""}
          <label class="chip-s">${ic("camera")} ${it.image ? "New photo" : "Add a photo"}<input type="file" accept="image/*" id="pi-file" hidden></label></div></div>` : ""}
      ${it.review ? `<button class="nudge" id="pi-details"><span class="ic bg-ink">${ic("scan")}</span><span><b>Add details</b><small>The product databases didn't know barcode ${esc(it.upc || "")}</small></span><span class="chev">${ic("chevR")}</span></button>` : ""}
      <div style="display:flex;align-items:center;gap:10px;margin:-4px 2px 12px">${expiryPill(it)}<span class="muted">${esc(relExpiry(it))}${srcLabel ? ` · ${esc(srcLabel)}` : ""}</span></div>
      <div class="group"><div class="kv">
        <div><small>Bought</small><b>${esc(fmt(parseISO(it.purchased_on), { month: "short", day: "numeric" }))}</b></div>
        <div><small>Opened</small><b>${it.opened_on ? esc(fmt(parseISO(it.opened_on), { month: "short", day: "numeric" })) : "—"}</b></div>
        <div><small>Use by</small><b>${it.expires_on ? esc(fmt(parseISO(it.expires_on), { month: "short", day: "numeric" })) : "—"}</b></div>
      </div></div>
      ${(it.reserved || []).length ? `<div class="group"><div class="reserve" style="padding-top:12px">${it.reserved.map((r) => `Reserved: <b>${esc(r.qty_text || "some")}</b> for ${esc(wkShort(r.date))} · ${esc(r.recipe)}`).join("<br>")}${it.free_text ? `<br>Free: <b>${esc(it.free_text)}</b>` : ""}</div></div>` : ""}
      <div class="group-label">How much did you use?</div>
      <div class="big-actions">
        <button data-use="0.25">${ic("open")}¼</button><button data-use="0.5">${ic("open")}½</button>
        <button data-use="0.75">${ic("open")}¾</button><button data-use="1">${ic("check")}All</button>
      </div>
      ${it.image && c_native() ? "" : `<div class="pi-hfill">${fillSliderHtml(it.amount_left, false)}</div>`}
      <div class="group"><div class="amount"><span class="muted">Left</span><b id="pi-lv">${it.qty != null ? esc(it.left_text.replace(/ left$/, "")) : `${left}%`}</b></div>
        <div class="amount-edit"><span class="muted">Amount</span><input type="number" inputmode="decimal" min="0" step="any" id="pi-qty" placeholder="—" value="${it.qty != null ? esc(+(+it.qty).toFixed(3)) : ""}" aria-label="Amount left">
          <select id="pi-unit" aria-label="Unit">${PANTRY_UNITS.map(([v, l]) => `<option value="${esc(v)}" ${v === (it.unit || "") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
          <button class="pill-btn" id="pi-amt">Save</button></div></div>
      ${!it.opened_on && it.location !== "freezer" ? `<p class="hint">Using some marks it opened and starts a countdown${rule && (it.location === "fridge" ? rule.opened_fridge : rule.opened_pantry || rule.opened_fridge) ? ` (${esc(it.location === "fridge" ? rule.opened_fridge : rule.opened_pantry || rule.opened_fridge)} days)` : ""}.</p>` : ""}
      <div class="group-label">Stored in</div>
      <div class="tag-cloud" id="pi-loc" role="radiogroup" aria-label="Stored in">${invPlaces().map(([k, l]) => `<button class="tag ${(it.place || it.location) === k ? "on" : ""}" data-loc="${esc(k)}" role="radio" aria-checked="${(it.place || it.location) === k}">${esc(l)}</button>`).join("")}</div>
      <div class="group" style="margin-top:12px">
        <div class="field"><label>Use-by date</label><input type="date" id="pi-date" value="${esc(it.expires_on || "")}"></div>
        <button class="row" id="pi-rule"><div class="main"><div class="a">Shelf life</div><div class="b">${esc(ruleLine)}</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <p class="hint">TablePlan never guesses a date for sealed food. Enter the printed date, or it starts a countdown when you open or freeze it.${it.keeps_hint ? ` ${esc(it.keeps_hint)}.` : ""}</p>
      <div style="height:14px"></div>
      <div class="btn-row"><button class="btn red" id="pi-toss">${ic("trash")} Toss</button>${!it.opened_on && it.location !== "freezer" ? `<button class="btn sec" id="pi-open">${ic("open")} Opened</button>` : ""}</div>`;
    const done = () => { closeSheet(); after && after(); };
    $$("[data-use]").forEach((b) => (b.onclick = async () => {
      const used = +b.dataset.use;
      const newLeft = used >= 1 ? 0 : Math.max(0, +(it.amount_left - used).toFixed(2));
      const r = await act({ action: "use", left: newLeft });
      if (!r) return;
      if (newLeft <= 0 || r.status !== "active") { toast(`${it.name} finished`, "Undo", async () => { await act({ action: "restore" }); after && after(); }); done(); }
      else { toast(`${Math.round(newLeft * 100)}% left · use by ${r.expires_on ? fmt(parseISO(r.expires_on), { month: "short", day: "numeric" }) : "—"}`); draw(r); after && after(); }
    }));
    // the amount-left slider (on the photo, or across the card): snaps to Empty, ¼, ½, ¾ and Full; Undo; 0 offers the list
    const fs = $(".pi-pic .fs") || $(".pi-hfill .fs");
    bindFillSlider(fs, it.amount_left, (v) => { const lv = $("#pi-lv"); if (lv) lv.textContent = fillText(v) + (it.full_qty ? ` · ${fmtQty(v * it.full_qty)}${it.unit ? ` ${it.unit}` : ""}` : ""); }, async (v) => {
      if (Math.abs(v - it.amount_left) < 0.005) return;
      const prev = it.amount_left;
      const r = await act(v <= 0.005 ? { action: "use", left: 0 } : { action: "fill", left: v });
      if (!r) return;
      const undo = async () => { if (r.status !== "active") await act({ action: "restore" }); const u = await act({ action: "fill", left: prev }); if (u && sheetBody()) draw(u); after && after(); };
      after && after();
      if (r.status !== "active") {
        sheetBody().innerHTML = `<div class="pi-done"><span class="ci-ic">${ic("check")}</span><b>${esc(it.name)} finished</b><span>Want it back on the list?</span>
          <div class="btn-row"><button class="btn sec" id="pd-undo">Undo</button><button class="btn" id="pd-list">${ic("cart")} Add to list</button></div></div>`;
        $("#pd-undo").onclick = () => undo();
        $("#pd-list").onclick = async () => { try { await api("POST", "/api/list/items", { items: [it.name] }); toast(`${it.name} added to your list`, "View", () => { closeSheet(); go("list"); }); closeSheet(); } catch (x) { fail(x); } };
        return;
      }
      toast(`${it.name}: ${fillText(r.amount_left).toLowerCase()}`, "Undo", undo);
      draw(r);
    });
    $("#pi-amt").onclick = async () => {
      const q = $("#pi-qty").value.trim();
      const r = await act({ action: "amount", qty: q === "" ? null : q, unit: $("#pi-unit").value }, q === "" ? "Amount cleared" : "Amount saved");
      if (r) { draw(r); after && after(); }
    };
    $$("#pi-loc [data-loc]").forEach((b) => (b.onclick = async () => { const r = await act({ action: "move", location: b.dataset.loc }, `Moved to ${b.textContent}`); if (r) { draw(r); after && after(); } }));
    $("#pi-date").onchange = async (e) => { const r = await act({ action: "set_date", expires_on: e.target.value }, "Date saved"); if (r) { draw(r); after && after(); } };
    $("#pi-rule").onclick = () => pickRule(it, async (rule) => { const r = await act({ action: "rule", rule_id: rule ? rule.id : null }, rule ? "Shelf life updated" : null); draw(r || it); after && after(); });
    $("#pi-toss").onclick = async () => { const r = await act({ action: "toss" }); if (r) { toast(`${it.name} tossed`, "Undo", async () => { await act({ action: "restore" }); after && after(); }); done(); } };
    $("#pi-details") && ($("#pi-details").onclick = () => { closeSheet(true); openItemDetails(it, after); });
    const photoDone = (r) => { if (r && r.id) { it = r; draw(r); after && after(); } };
    $("#pi-cut") && ($("#pi-cut").onclick = () => openCutout(it, (r) => { toast("Background removed"); after && after(); openPantryItem(r, after); }));
    $("#pi-orig") && ($("#pi-orig").onclick = async () => { try { photoDone(await api("POST", `/api/pantry/${enc(it.id)}/photo/restore`, {})); toast("Original photo back"); } catch (e) { fail(e); } });
    $("#pi-file") && ($("#pi-file").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try { photoDone(await api("POST", `/api/pantry/${enc(it.id)}/photo`, { image: await squarePhoto(f, 1024) })); toast("Photo saved"); } catch (x) { fail(x); }
    });
    $("#pi-open") && ($("#pi-open").onclick = async () => { const r = await act({ action: "open" }, "Marked opened"); if (r) { draw(r); after && after(); } });
  };
  openSheet(it.name, "", { onMount: () => draw(it) });
}

function ruleDesc(r) {
  const parts = [];
  const f = (v, l) => v && parts.push(`${l} ${v < 60 ? v + "d" : Math.round(v / 30) + "mo"}`);
  f(r.sealed_fridge, "fridge"); f(r.opened_fridge, "opened"); f(r.sealed_pantry, "pantry"); f(r.opened_pantry, "opened (pantry)"); f(r.freezer, "freezer");
  return parts.join(" · ") || "no data";
}
function pickRule(it, cb) {
  sheetBody().innerHTML = `<div class="search">${ic("search")}<input id="rq" placeholder="Search shelf-life database" value="${esc(it.name.split(/[ ,]/)[0])}"></div><div id="rres">${loading()}</div>`;
  const q = $("#rq");
  let t;
  const run = async () => {
    try {
      const { rules } = await api("GET", `/api/rules?q=${encodeURIComponent(q.value)}`);
      $("#rres").innerHTML = `<div class="group">${rules.map((r) => `<button class="row" data-r="${esc(r.id)}"><div class="main"><div class="a">${esc(r.name)} ${r.source === "custom" ? '<span class="badge">house</span>' : r.source === "usda" ? '<span class="badge" style="background:rgba(0,122,255,.14);color:var(--blue)">USDA</span>' : ""}</div><div class="b">${esc(ruleDesc(r))}</div></div></button>`).join("") || '<div class="row"><div class="main muted">No matches</div></div>'}</div>
        <p class="hint">Not listed? Add a house rule in Settings → Shelf life.</p>`;
      $$("#rres [data-r]").forEach((b) => (b.onclick = () => cb(rules.find((r) => String(r.id) === b.dataset.r))));
    } catch (e) { fail(e); }
  };
  q.oninput = () => { clearTimeout(t); t = setTimeout(run, 220); };
  run(); q.focus();
}

function openAddPantry(after) {
  const f = { name: "", location: "", package_date: "", quantity_text: "" };
  openSheet("Add to Inventory", `
    <div class="group"><div class="field"><input class="full" type="text" id="ap-name" placeholder="Item (e.g. Heavy cream)" autocomplete="off"></div>
      <div class="field"><input class="full" type="text" id="ap-qty" placeholder="Size (optional, e.g. 1 pint)"></div></div>
    <p class="hint" id="ap-match">Shelf life is looked up automatically.</p>
    <div class="group-label">Stored in</div>
    <div class="tag-cloud" id="ap-loc" role="radiogroup" aria-label="Put it in"><button class="tag" data-loc="">Auto</button>${invPlaces().map(([k, l]) => `<button class="tag" data-loc="${esc(k)}">${esc(l)}</button>`).join("")}</div>
    <div class="group" style="margin-top:12px"><div class="field"><label>Printed date</label><input type="date" id="ap-date"></div></div>
    <p class="hint">Optional — the date printed on the package. Without one, there's no date until you open it.</p>
    <div style="height:14px"></div><button class="btn" id="ap-save">Add</button>`, {
    onMount() {
      const locBtns = $$("#ap-loc button");
      const setLoc = (l) => { f.location = l; locBtns.forEach((b) => b.classList.toggle("on", b.dataset.loc === l)); };
      setLoc("");
      locBtns.forEach((b) => (b.onclick = () => setLoc(b.dataset.loc)));
      let t;
      $("#ap-name").oninput = (e) => {
        f.name = e.target.value; clearTimeout(t);
        t = setTimeout(async () => {
          if (!f.name.trim()) return ($("#ap-match").textContent = "Shelf life is looked up automatically.");
          try { const { rule } = await api("GET", `/api/pantry/match?name=${encodeURIComponent(f.name)}`);
            $("#ap-match").textContent = rule ? `Matched “${rule.name}” — ${ruleDesc(rule)}` : "No shelf-life match yet — you can set a date or pick a rule after adding."; } catch (_) {}
        }, 250);
      };
      $("#ap-qty").oninput = (e) => (f.quantity_text = e.target.value);
      $("#ap-date").onchange = (e) => (f.package_date = e.target.value);
      $("#ap-save").onclick = async () => {
        if (!f.name.trim()) return toast("Enter an item name");
        try { const p = await api("POST", "/api/pantry", f); closeSheet(); toast(`${p.name} → ${cap(p.location)}${p.expires_on ? ` · use by ${fmt(parseISO(p.expires_on), { month: "short", day: "numeric" })}` : ""}`); after && after(); }
        catch (e) { fail(e); }
      };
      setTimeout(() => $("#ap-name").focus(), 300);
    },
  });
}

// ------------------------------------------------------------------ add recipe (imports run through Mealie in the background)
function openAddRecipe(prefill) {
  const c = state.cfg;
  api("GET", "/api/setup/ai").then((a) => { state.setup = { ...(state.setup || {}), ai: a }; const h = $("#ar-aihint"); if (h && a.enabled) h.textContent = "Usually takes 20–60 seconds. Check the ingredients afterwards."; }).catch(() => {});
  const imgs = [];
  openSheet("Add a Recipe", `
    <div class="seg" id="ar-mode"><button data-m="link" class="on">Link</button><button data-m="scan">Scan</button><button data-m="photo">Screenshot</button><button data-m="paste">Paste</button><button data-m="type">Type it</button></div>
    <div id="ar-body"></div>
    <div id="ar-result"></div>`, {
    onMount() {
      const body = $("#ar-body");
      const drawLink = () => {
        body.innerHTML = `<div class="group" style="margin-top:12px"><div class="field"><input class="full" type="url" id="ar-url" placeholder="Recipe site, Instagram, TikTok, YouTube or Google Doc link" autocomplete="off"></div></div>
          <div style="height:12px"></div><button class="btn" id="ar-go">${ic("link")} Import</button>
          <p class="hint">Recipe sites import in seconds. Videos read the caption first; if the recipe is only spoken, AI listens to it (needs your OpenAI key, ~30–90 s). Google Docs must be shared as “Anyone with the link”.</p>`;
        $("#ar-go").onclick = () => { const u = $("#ar-url").value.trim(); if (!/^https?:\/\//i.test(u) || !safeUrl(u)) return toast("Paste a full link starting with https://"); run("link", () => api("POST", "/api/import/url", { url: u })); };
        if (navigator.clipboard && navigator.clipboard.readText) {
          $("#ar-url").addEventListener("focus", async () => { try { const t = await navigator.clipboard.readText(); if (/^https?:\/\//.test(t) && !$("#ar-url").value) $("#ar-url").value = t.trim(); } catch (_) {} }, { once: true });
        }
      };
      const drawPhoto = () => {
        body.innerHTML = `<label class="drop" style="margin-top:12px">${ic("camera")}<div style="margin-top:6px"><b>Choose screenshots, photos or a PDF</b><br><span class="muted">Up to 8 files: a recipe card, cookbook page or a screenshot of a post</span><br><span class="muted desktop-only">or drag & drop / paste them here</span></div>
          <input type="file" id="ar-files" accept="image/*,application/pdf" multiple hidden></label>
          <div class="thumbs" id="ar-thumbs"></div>
          <div style="height:12px"></div><button class="btn" id="ar-go" ${imgs.length ? "" : "disabled"}>${ic("sparkle")} Read recipe with AI</button>
          <p class="hint" id="ar-aihint">${state.setup?.ai?.enabled === false ? "AI import isn't set up yet. Add your OpenAI key in Settings → AI recipe import." : "Usually takes 20–60 seconds. Check the ingredients afterwards."}</p>`;
        const thumbs = () => { $("#ar-thumbs").innerHTML = imgs.map((im) => im.type === "application/pdf" ? `<div class="pdf-thumb">📄<small>${esc(im.name)}</small></div>` : `${safeUrl(im.data, true) ? `<img src="${esc(safeUrl(im.data, true))}" alt="">` : ""}`).join(""); $("#ar-go").disabled = !imgs.length; };
        const addFiles = async (files) => {
          for (const f of [...files].slice(0, 8 - imgs.length)) {
            if (f.type === "application/pdf") {
              if (f.size > 15e6) { toast("That PDF is over 15 MB"); continue; }
              imgs.push({ name: f.name, type: f.type, data: await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(f); }) });
            } else imgs.push({ name: f.name, type: "image/jpeg", data: await shrink(f) });
          }
          thumbs();
        };
        $("#ar-files").onchange = (e) => addFiles(e.target.files);
        dropZone($("#ar-body .drop"), addFiles, /^(image\/|application\/pdf)/);
        thumbs();
        $("#ar-go").onclick = () => run("photo", () => api("POST", "/api/import/images", { images: imgs }));
      };
      const run = async (kind, fn) => {
        const btn = $("#ar-go"); btn.disabled = true; const label = btn.innerHTML; btn.innerHTML = "Importing…";
        $("#ar-result").innerHTML = "";
        const prog = importProgress($("#ar-result"), kind);
        const added = (r) => {
          $("#ar-body").innerHTML = "";
          $("#ar-mode").style.display = "none";
          $("#ar-result").innerHTML = `<div class="wstatus ok" style="margin-top:4px"><b>Added “${esc(r.name || r.slug)}”</b>
            <span>${r.ingredients ? `${esc(r.ingredients)} ingredients` : ""}${r.servings ? ` · serves ${esc(r.servings)}` : ""}</span></div>
            <div class="btn-row" style="margin-top:12px"><button class="btn sec" id="ar-again">${ic("plus")} Add another</button><button class="btn" id="ar-open">${ic("book")} Open recipe</button></div>`;
          $("#ar-again").onclick = () => openAddRecipe();
          $("#ar-open").onclick = () => { closeSheet(true); openRecipe(r.slug); };
          if (state.tab === "recipes") rstate.list = null;
        };
        try { const r = await fn(); prog.done(); added(r); }
        catch (e) {
          prog.stop(); btn.disabled = false; btn.innerHTML = label;
          if (e.data && e.data.duplicate) return duplicateCard($("#ar-result"), e, (r) => added(r));   // looks like one we have: ask
          $("#ar-result").innerHTML = `<div class="banner" style="margin-top:12px">${esc(e.message)}</div>`;
        }
      };
      const drawPaste = () => {
        body.innerHTML = `<div class="group" style="margin-top:12px"><textarea class="full-area" id="ar-text" rows="10" placeholder="Paste the whole recipe: title, ingredients and steps. From Notes, a Google Doc, an email or a text message."></textarea></div>
          <div style="height:12px"></div><button class="btn" id="ar-go">${ic("file")} Import text</button>
          <p class="hint">Works without AI when the text has “Ingredients” and “Instructions” headings. With AI, any layout works.</p>`;
        $("#ar-go").onclick = () => { const t = $("#ar-text").value.trim(); if (t.length < 20) return toast("Paste the recipe text first"); run("link", () => api("POST", "/api/import/text", { text: t })); };
      };
      const drawType = () => {
        body.innerHTML = `<div class="group" style="margin-top:12px"><div class="field"><input class="full" id="ar-name" placeholder="Recipe name, e.g. Grandma's lasagna" autocomplete="off"></div></div>
          <div style="height:12px"></div><button class="btn" id="ar-go">${ic("edit")} Start writing</button><p class="hint">You'll add ingredients and steps on the next screen.</p>`;
        $("#ar-go").onclick = async () => {
          const name = $("#ar-name").value.trim(); if (!name) return toast("Give it a name");
          try { const r = await api("POST", "/api/recipes/new", { name }); closeSheet(true); location.hash = "edit/" + encodeURIComponent(r.slug); } catch (e) { fail(e); }
        };
      };
      $$("#ar-mode button").forEach((bt) => (bt.onclick = () => { if (bt.dataset.m === "scan") return openRecipeCamera(); $$("#ar-mode button").forEach((x) => x.classList.toggle("on", x === bt)); ({ link: drawLink, photo: drawPhoto, paste: drawPaste, type: drawType })[bt.dataset.m](); }));
      drawLink();
      // Shared/deep-linked URLs are only prefilled. Anyone can craft a /?url= link, so importing always takes a tap.
      if (typeof prefill === "string" && prefill) {
        $("#ar-url").value = prefill;
        $("#ar-body").insertAdjacentHTML("afterbegin", `<div class="banner info" style="margin-top:12px">Import this link? Check it, then tap <b>Import</b>.<br><small style="word-break:break-all">${esc(prefill)}</small></div>`);
      }
    },
  });
}
// Import progress: real elapsed time plus an estimate learned from this device's past imports.
function importProgress(box, kind) {
  const key = "tp.eta." + kind;
  let eta = +(localStorage.getItem(key) || (kind === "photo" ? 40 : 8));
  const stages = kind === "photo"
    ? [[0, "Uploading your screenshot…"], [0.12, "Reading the text with AI…"], [0.55, "Writing up the recipe…"], [0.85, "Saving to your library…"]]
    : [[0, "Opening the page…"], [0.3, "Finding the recipe…"], [0.7, "Saving to your library…"]];
  box.innerHTML = `<div class="importing"><div class="pot">🍳</div><div class="stage" id="ip-stage"></div>
    <div class="meter big"><i id="ip-bar"></i></div><div class="muted small" id="ip-time"></div></div>`;
  const t0 = Date.now();
  const tick = () => {
    const sec = (Date.now() - t0) / 1000, f = sec / eta;
    const pct = f < 1 ? f * 90 : 90 + 9 * (1 - Math.exp(-(f - 1) * 2));
    const stage = stages.filter(([at]) => f >= at).pop()[1];
    if (!$("#ip-bar")) return clearInterval(iv);
    $("#ip-bar").style.width = pct.toFixed(1) + "%";
    $("#ip-stage").textContent = stage;
    const left = Math.ceil(eta - sec);
    $("#ip-time").textContent = `${Math.floor(sec)}s · ` + (left > 0 ? `about ${left}s left` : "almost done, a little longer than usual…");
  };
  const iv = setInterval(tick, 250); tick();
  return {
    done() { clearInterval(iv); const took = (Date.now() - t0) / 1000; try { localStorage.setItem(key, String(Math.round(eta * 0.6 + took * 0.4))); } catch (_) {} },
    stop() { clearInterval(iv); },
  };
}
// Drag & drop (and paste) files onto a zone. onFiles receives an array of File objects.
function dropZone(el, onFiles, accept = /^image\//) {
  if (!el) return;
  const take = (files) => { const ok = [...files].filter((f) => accept.test(f.type)); if (ok.length) onFiles(ok); else if (files.length) toast("That file type isn't supported here"); };
  ["dragenter", "dragover"].forEach((ev) => el.addEventListener(ev, (e) => { e.preventDefault(); el.classList.add("dragging"); }));
  ["dragleave", "dragend"].forEach((ev) => el.addEventListener(ev, () => el.classList.remove("dragging")));
  el.addEventListener("drop", (e) => { e.preventDefault(); el.classList.remove("dragging"); take(e.dataTransfer?.files || []); });
  const sheet = el.closest(".sheet") || document;
  const onPaste = (e) => { if (!document.body.contains(el)) return document.removeEventListener("paste", onPaste); const f = [...(e.clipboardData?.files || [])]; if (f.length) { e.preventDefault(); take(f); } };
  document.addEventListener("paste", onPaste);
}
// Downscale photos in the browser (max 1800px) so uploads stay fast on cellular.
function shrink(file) {
  return new Promise((resolve) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, 1800 / Math.max(img.width, img.height));
      const cv = document.createElement("canvas"); cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height); URL.revokeObjectURL(url);
      resolve(cv.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => { const r = new FileReader(); r.onload = () => resolve(r.result); r.readAsDataURL(file); };
    img.src = url;
  });
}

// ------------------------------------------------------------------ share / export / print
function printIt(url) { window.open(url + (url.includes("?") ? "&" : "?") + "auto=1", "_blank"); }
const CH_LABEL = { telegram: "Telegram", ntfy: "ntfy", email: "email" };
const anyChannel = () => Object.values(state.cfg.channels || {}).some(Boolean);
async function sendIt(body, channel = "all") {
  if (!anyChannel()) return toast("Notifications aren't set up yet", "Set up", () => openSetupSection("notify", "Notifications", reloadCfg));
  toast("Sending…");
  try { const r = await api("POST", "/api/send", { ...body, channel }); toast(`Sent to ${r.sent.map((c) => CH_LABEL[c] || c).join(" & ")}${r.errors.length ? ` · ${r.errors.length} failed` : ""}`); }
  catch (e) { fail(e); }
}
const emailIt = (body) => sendIt(body, "email");
function sendItems(body) {
  const ch = state.cfg.channels || {};
  const out = [];
  if (ch.telegram) out.push(["share", "Send to Telegram", () => sendIt(body, "telegram")]);
  if (ch.ntfy) out.push(["share", "Send to ntfy", () => sendIt(body, "ntfy")]);
  if (ch.email) out.push(["mail", "Email it", () => sendIt(body, "email")]);
  if (!out.length) out.push(["share", "Send to my phone…", () => openSetupSection("notify", "Notifications", reloadCfg)]);
  return out;
}
async function shareText(url, title) {
  try { const txt = await (await fetch(url)).text(); await navigator.share({ title, text: txt }); }
  catch (e) { if (e.name !== "AbortError") fail(e); }
}
function openShare(kind, o) {
  let items = [], title = "Share";
  if (kind === "list") {
    title = o.name || "Shopping list";
    items = [...sendItems({ kind: "list", id: o.id }), ["print", "Print", () => printIt(`/print/list/${enc(o.id)}`)],
      ["file", "Text file", `/export/list/${enc(o.id)}.txt`], ["file", "Spreadsheet (CSV)", `/export/list/${enc(o.id)}.csv`]];
    if (navigator.share) items.unshift(["share", "Send via…", () => shareText(`/export/list/${enc(o.id)}.txt`, title)]);
  } else if (kind === "plan") {
    title = `Meal plan · ${o.label}`;
    const q = `start=${enc(o.start)}&end=${enc(o.end)}`;
    items = [...sendItems({ kind: "plan", start: o.start, end: o.end }), ["print", "Print", () => printIt(`/print/plan?${q}`)],
      ["cal", "Add to calendar (.ics)", `/export/plan.ics?${q}`], ["file", "Spreadsheet (CSV)", `/export/plan.csv?${q}`]];
    if (navigator.share) items.unshift(["share", "Send via…", () => shareText(`/export/plan.txt?${q}`, "Meal plan")]);
  } else if (kind === "pantry") {
    title = "Inventory";
    items = [...sendItems({ kind: "pantry" }), ["print", "Print", () => printIt("/print/pantry")], ["file", "Spreadsheet (CSV)", "/export/pantry.csv"]];
  }
  openSheet(title, `<div class="share-grid">${items.map(([i, l, a], n) =>
    typeof a === "string" ? `<a href="${esc(safeUrl(a))}" download>${ic(i)} ${esc(l)}</a>` : `<button data-n="${n}">${ic(i)} ${esc(l)}</button>`).join("")}</div>
    ${state.cfg.channels?.telegram ? `<p class="hint">Telegram messages go to ${esc(state.cfg.telegram_chat || "your chat")}.</p>` : ""}${state.cfg.email_ready ? `<p class="hint">Email goes to ${esc((state.cfg.mail_to || []).join(", "))}.</p>` : ""}`, {
    onMount() { $$("[data-n]").forEach((b) => (b.onclick = () => { closeSheet(); items[+b.dataset.n][2](); })); },
  });
}

// ------------------------------------------------------------------ settings
async function openSettings() {
  const c = state.cfg, s = { ...c.settings };
  const save = async (patch) => { try { Object.assign(s, patch); c.settings = await api("PUT", "/api/settings", patch); } catch (e) { fail(e); } };
  const draw = async () => {
    let counts = {};
    try { counts = (await api("GET", "/api/rules?q=")).counts; } catch (_) {}
    let up = {};
    try { up = await api("GET", "/api/version"); } catch (_) {}
    const hh = c.household || {}, st = c.storage || {};
    sheetBody().innerHTML = `
      ${up.update_available ? `<button class="update-banner" id="st-up">${ic("refresh")}<span><b>Update available: ${esc(up.latest)}</b><small>Update it from the ZimaOS App Store</small></span></button>` : ""}
      <div class="group-label">Setup</div>
      <div class="group">
        <button class="row" data-sec="household"><span class="ic bg-orange" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("home")}</span><div class="main"><div class="a">Household</div><div class="b">${esc(hh.name || "Household")} · cooking for ${esc(hh.people || 2)}${hh.scale === false ? " · scaling off" : ""}</div></div><span class="chev">${ic("chevR")}</span></button>
        ${c.backend === "native" ? "" : `<button class="row" data-sec="mealie"><span class="ic bg-purple" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("book")}</span><div class="main"><div class="a">Recipe library (Mealie)</div><div class="b">${c.connected ? "Connected" : "Not connected"}</div></div><span class="chev">${ic("chevR")}</span></button>`}
        <button class="row" data-sec="ai"><span class="ic bg-indigo" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("sparkle")}</span><div class="main"><div class="a">AI recipe import</div><div class="b">OpenAI key for screenshots, photos & videos</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" data-sec="notify"><span class="ic bg-blue" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("mail")}</span><div class="main"><div class="a">Notifications</div><div class="b">${Object.entries(c.channels || {}).filter(([, v]) => v).map(([k]) => esc(cap(CH_LABEL[k] || k))).join(", ") || "Not set up · Telegram, ntfy or email"}</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" id="st-account"><span class="ic bg-gray" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("users")}</span><div class="main"><div class="a">Your account</div><div class="b">${c.me ? `Signed in as ${esc(c.me.name)}${c.me.admin ? " · admin" : ""}` : "Not set up · anyone on your Wi-Fi can open TablePlan"}</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" id="st-members"><span class="ic bg-teal" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("users")}</span><div class="main"><div class="a">Members</div><div class="b">${c.me ? (c.me.admin ? "Add people, reset sign-ins" : "Who's in this household") : "Everyone gets their own sign-in"}</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" id="st-checklist"><span class="ic bg-green" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("check")}</span><div class="main"><div class="a">Getting started checklist</div><div class="b">Your setup steps, ticked as you go</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <div class="group-label">Appearance</div>
      <div class="group"><div class="field"><label>Mode<small class="lh">Saved for you${c.me ? " with your account" : " on this device"}. “System” follows your phone or computer.</small></label></div>
        <div style="padding:0 14px 12px"><div class="seg" id="st-mode" role="radiogroup" aria-label="Mode">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => `<button data-mode="${v}" role="radio" aria-checked="${currentTheme() === v}" class="${currentTheme() === v ? "on" : ""}">${l}</button>`).join("")}</div></div>
        <div class="field"><label>Theme</label></div>
        <div class="looks" id="st-looks" role="radiogroup" aria-label="Theme">${Object.entries(LOOKS).map(([k, [l, bgL, bgD, ink]]) => `<button class="look ${currentLook() === k ? "on" : ""}" data-look="${k}" role="radio" aria-checked="${currentLook() === k}"><span class="sw" aria-hidden="true"><i style="background:${bgL}"></i><i style="background:${ink}"></i><i style="background:${bgD}"></i></span><b>${l}</b></button>`).join("")}</div></div>
      <div class="group-label">Cooking</div>
      <div class="group">
        <div class="field"><label>Recipe style</label><select id="st-style"><option value="classic" ${s.recipe_style !== "steps" ? "selected" : ""}>Classic</option><option value="steps" ${s.recipe_style === "steps" ? "selected" : ""}>Step-by-step</option></select></div>
        <div class="field"><label>Stovetop</label><select id="st-stove">${["gas", "electric", "induction"].map((v) => `<option value="${v}" ${s.stove === v ? "selected" : ""}>${cap(v)}</option>`).join("")}</select></div>
        <div class="field"><label>Oven</label><select id="st-oven">${[["conventional", "Conventional"], ["convection", "Convection / fan"], ["air_fryer", "Air fryer"], ["toaster_oven", "Toaster oven"]].map(([v, l]) => `<option value="${v}" ${s.oven === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <div class="field"><label>Temperatures</label><select id="st-tu"><option value="F" ${s.temp_unit !== "C" ? "selected" : ""}>°F</option><option value="C" ${s.temp_unit === "C" ? "selected" : ""}>°C</option></select></div>
      </div>
      <p class="hint"><b>Classic</b> lists ingredients, then instructions. <b>Step-by-step</b> puts each ingredient inside the step that uses it, adds preheating at the right moment, and gives you timers.</p>
      <div class="group-label">Planning</div>
      <div class="group">
        ${[["breakfast", "Breakfast"], ["lunch", "Lunch"], ["dinner", "Dinner"]].map(([k, l]) => `<div class="field"><label for="st-eat-${k}">${l} at${k === "dinner" ? '<small class="lh">The plan shows when to start cooking so it’s ready on time.</small>' : ""}</label><input type="time" step="300" id="st-eat-${k}" data-eat="${k}" value="${esc((s.eat_times || {})[k] || "")}"></div>`).join("")}
        <div class="field"><label>Tell me when to start cooking<small class="lh">A message at the start time for today’s planned meals.</small></label><label class="toggle"><input type="checkbox" id="st-startrem" ${s.start_reminder ? "checked" : ""}><span></span></label></div>
        ${c.backend === "native" ? `<div class="field"><label>Day-before heads-up<small class="lh">A message a day ahead when a planned meal is missing ingredients.</small></label><label class="toggle"><input type="checkbox" id="st-mdb" ${s.missing_alert_daybefore ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>Morning check<small class="lh">That morning, for meals still missing something.</small></label><span class="row-ctl"><input type="time" id="st-mtime" value="${esc(s.missing_alert_time || "08:00")}" aria-label="Morning check time" ${s.missing_alert_morning ? "" : "disabled"}><label class="toggle"><input type="checkbox" id="st-mmo" ${s.missing_alert_morning ? "checked" : ""}><span></span></label></span></div>` : ""}
        <div class="field"><label>Plan ahead<small class="lh">How many days the Plan board shows and keeps filled.</small></label><select id="st-hz">${[7, 14, 21, 28].map((v) => `<option value="${v}" ${(+s.plan_horizon_days || 14) === v ? "selected" : ""}>${v} days</option>`).join("")}</select></div>
        <div class="field"><label>Remind me before the plan runs out<small class="lh">A message when only this many planned days are left.</small></label><select id="st-rem">${[[0, "Off"], [1, "1 day"], [2, "2 days"], [3, "3 days"], [5, "5 days"], [7, "7 days"]].map(([v, l]) => `<option value="${v}" ${(s.plan_reminder_days ?? 3) === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      </div>
      <div class="group-label">Meal planning</div>
      <p class="hint" style="margin-top:-2px">Meals I plan <span class="muted">(each day shows these; the + adds any meal)</span></p>
      <div class="group">
        <div class="tag-cloud" id="st-types">${MEAL_TYPES.map(([t, l]) => `<button class="tag ${s.meal_types.includes(t) ? "on" : ""}" data-t="${t}">${l}</button>`).join("")}</div>
        <div class="field"><label>No repeats for (days)<small class="lh">The same recipe won't come back within this many days.</small></label><input type="number" id="st-nr" value="${esc(s.no_repeat_days)}" min="0" max="90"></div>
        <div class="field"><label>Use food before it goes bad<small class="lh">Plans favor recipes using items close to their use-by date.</small></label><label class="toggle"><input type="checkbox" id="st-exp" ${s.prefer_expiring ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>Warn me this many days early<small class="lh">Items show as “use soon” when they're this close to their use-by date.</small></label><input type="number" id="st-win" value="${esc(s.expiring_window_days)}" min="1" max="14"></div>
        <div class="field"><label>Plan next week automatically on<small class="lh">TablePlan fills next week's empty days for you at 8 AM.</small></label><select id="st-auto">${[["", "Off"], ["sun", "Sunday"], ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"]].map(([v, l]) => `<option value="${v}" ${s.auto_plan_day === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <div class="field"><label>Send me the plan<small class="lh">Get the new week's plan on your phone or by email.</small></label><label class="toggle"><input type="checkbox" id="st-aemail" ${s.auto_plan_email ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>Daily “use soon” reminder<small class="lh">A morning message listing food that's about to expire.</small></label><label class="toggle"><input type="checkbox" id="st-xa" ${s.expiry_alert ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>Reminder time</label><select id="st-xh">${[6,7,8,9,10,12,15,17,18,19].map((h) => `<option value="${h}" ${+s.expiry_alert_hour === h ? "selected" : ""}>${((h + 11) % 12) + 1}:00 ${h < 12 ? "AM" : "PM"}</option>`).join("")}</select></div>
      </div>
      <p class="hint">Auto-plan runs at 8 AM on that day, fills empty days for the following week, and keeps anything you've already planned. Plans and alerts go to every notification channel you've set up.</p>


      <div class="group-label">Recipes</div>
      <div class="group"><button class="row" id="st-cats"><span class="ic bg-orange" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("book")}</span><div class="main"><div class="a">Categories</div><div class="b">${esc((s.categories || []).slice(0, 4).join(", "))}${(s.categories || []).length > 4 ? "…" : ""}</div></div><span class="chev">${ic("chevR")}</span></button>
        ${c.backend === "native" ? `<button class="row" id="st-foods"><span class="ic bg-green" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("leaf")}</span><div class="main"><div class="a">Foods</div><div class="b">One name per food, so recipes, list and inventory match</div></div><span class="chev">${ic("chevR")}</span></button>` : ""}</div>
      <div class="group-label">Shopping</div>
      <div class="group"><button class="row" id="st-stores"><span class="ic bg-teal" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("store")}</span><div class="main"><div class="a">Stores</div><div class="b" id="st-stores-b">Rename, reorder or remove the stores on your list</div></div><span class="chev">${ic("chevR")}</span></button></div>
      <div class="group-label">Inventory</div>
      <div class="group"><button class="row" id="st-staples"><div class="main"><div class="a">Always have</div><div class="b">${esc((s.staples || []).slice(0, 4).join(", "))}${(s.staples || []).length > 4 ? "…" : ""}</div></div><span class="chev">${ic("chevR")}</span></button></div>
      <div class="group">
        <div class="field"><label for="st-ci">Kitchen check-in</label><select id="st-ci">${[[0, "Off"], [7, "Weekly"], [14, "Every 2 weeks"]].map(([v, l]) => `<option value="${v}" ${+s.pantry_check_days === v || (v === 14 && +s.pantry_check_days > 14) ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <div class="field ${+s.pantry_check_days ? "" : "hidden"}" id="st-ci-when"><label for="st-ci-day">Check-in on</label><select id="st-ci-day">${["sun", "mon", "tue", "wed", "thu", "fri", "sat"].map((d) => `<option value="${d}" ${(s.checkin_day || "sun") === d ? "selected" : ""}>${esc(cap(d))} evening</option>`).join("")}</select></div>
      </div>
      <p class="hint">Weekly is recommended: a quick “still have it?” review keeps use-by dates and shopping lists honest.</p>
      <div class="group-label">AI</div>
      <div class="group">
        <div class="field"><label>Polish imported recipes<small class="lh">Rewrites steps so they're clear and complete. Never changes amounts. About 1¢ per recipe.</small></label><label class="toggle"><input type="checkbox" id="st-polish" ${s.polish_imports !== false ? "checked" : ""}><span></span></label></div>
      </div>
      ${c.backend === "native" ? `<div class="group"><button class="row" id="st-prices"><span class="ic bg-green" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("cart")}</span><div class="main"><div class="a">Prices & budget</div><div class="b">${s.budget && s.budget.amount ? `$${esc(s.budget.amount)} a ${esc(s.budget.period)} · spending, price sources` : "Grocery budget, spending and where prices come from"}</div></div><span class="chev">${ic("chevR")}</span></button></div>` : ""}
      ${c.backend === "native" ? `<div class="group"><button class="row" id="st-photos"><span class="ic bg-orange" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("camera")}</span><div class="main"><div class="a">Recipe photos</div><div class="b">Optional Unsplash and Pexels keys for more photo choices</div></div><span class="chev">${ic("chevR")}</span></button></div>` : ""}
      ${c.backend === "native" ? `<div class="group"><button class="row" id="st-ideas"><span class="ic bg-green" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("sparkle")}</span><div class="main"><div class="a">Recipe ideas</div><div class="b">Real recipes only · sources, keys and blocked sites</div></div><span class="chev">${ic("chevR")}</span></button></div>` : ""}
      <div class="group"><button class="row" id="st-ai"><span class="ic bg-purple" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("dollar")}</span><div class="main"><div class="a">AI spending</div><div class="b">${s.ai_budget ? `Budget $${esc(s.ai_budget)}/month` : "See what OpenAI costs you"}</div></div><span class="chev">${ic("chevR")}</span></button></div>
      <div class="group-label">Import</div>
      <div class="group"><button class="row" id="st-share"><span class="ic bg-pink" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff;background:#E1306C">${ic("share")}</span><div class="main"><div class="a">Share to TablePlan from your phone</div><div class="b">Send Instagram, TikTok and recipe links straight in</div></div><span class="chev">${ic("chevR")}</span></button></div>
      <div class="group-label">Shelf life data</div>
      <div class="group">
        <div class="row"><div class="main"><div class="a">USDA FoodKeeper</div><div class="b">${counts.usda ? `${esc(counts.usda)} foods · synced ${esc((c.usda_synced_at || "").replace("T", " "))}` : "Not synced yet — using starter table"}</div></div></div>
        <button class="row" id="st-sync"><div class="main"><div class="a" style="color:var(--blue)">${counts.usda ? "Re-sync now" : "Sync now"}</div></div></button>
        <button class="row" id="st-rules"><div class="main"><div class="a">House rules & edits</div><div class="b">${esc(counts.custom || 0)} custom · ${esc(counts.starter || 0)} starter</div></div><span class="chev">${ic("chevR")}</span></button>
        ${c.backend === "native" ? `<button class="row" id="st-pans"><div class="main"><div class="a">Pans I have</div><div class="b">${(s.pans || []).length ? esc((s.pans || []).map((p) => p.label).slice(0, 3).join(", ")) + ((s.pans || []).length > 3 ? "…" : "") : "Optional: suggests a pan that fits when you scale"}</div></div><span class="chev">${ic("chevR")}</span></button>` : ""}
        <button class="row" id="st-bctest"><div class="main"><div class="a">Test barcode lookup</div><div class="b">See what each product database says about a code</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>

      <div class="group-label">Your data</div>
      <div class="group"><button class="row" id="st-backups"><span class="ic ${st.persistent === false || (st.integrity && st.integrity !== "ok") ? "bg-red" : "bg-green"}" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("shield")}</span><div class="main"><div class="a">Backups</div><div class="b">${esc(backupSummary(st))}</div></div><span class="chev">${ic("chevR")}</span></button></div>
      ${st.persistent === false ? `<p class="hint" style="color:var(--red)">This container isn't using a persistent volume. Download a backup now and see <a ${extLink(DOCS_BACKUPS)}>docs/install.md#backups</a>.</p>` : ""}
      <div class="group-label">Help</div>
      <div class="group">
        <button class="row" id="st-wn"><div class="main"><div class="a">What's new</div><div class="b">Everything added recently</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" id="st-tour"><div class="main"><div class="a">Replay tour</div><div class="b">A one-minute walk through the app</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <div class="group-label">Advanced</div>
      <div class="group">
        ${c.backend === "native" ? `<button class="row" id="st-mimport"><div class="main"><div class="a">Import from Mealie</div><div class="b">Copy recipes, photos, plans and lists from an old Mealie</div></div><span class="chev">${ic("chevR")}</span></button>` : `<a class="row" ${extLink(c.mealie_url)} style="text-decoration:none"><div class="main"><div class="a">Mealie admin</div><div class="b">Not needed day to day. TablePlan handles everything.</div></div><span class="chev">${ic("ext")}</span></a>`}
        <button class="row" id="st-wizard"><div class="main"><div class="a">Run setup wizard again</div></div><span class="chev">${ic("chevR")}</span></button>
        ${c.auth_required ? `<button class="row" id="st-logout"><div class="main"><div class="a" style="color:var(--red)">Sign out on this device</div></div></button>` : ""}
      </div>
      ${c.backend === "native" && isAdmin() ? `<div class="group-label danger-label">Danger zone</div>
      <div class="group danger-zone" id="st-danger">${DANGER.map(([k, l, d]) => `<button class="row" data-reset="${k}"><div class="main"><div class="a">${k === "everything" ? "Reset everything" : k === "demo" ? "Wipe demo data" : `Reset ${esc(l.toLowerCase())}`}</div><div class="b">${esc(d)}</div></div><span class="chev">${ic("chevR")}</span></button><div class="danger-confirm" data-for="${k}" hidden></div>`).join("")}</div>
      <p class="hint">A backup is saved first every time, under Settings → Backups.</p>` : ""}
      <p class="hint" style="text-align:center;margin-top:18px">TablePlan ${esc(up.version || c.version || "")}${up.latest && !up.update_available ? " · up to date" : ""} · your data stays on your server<span class="desktop-only"><br><a ${extLink(c.repo_url) || extLink(REPO)} style="color:var(--sub)">Source code (AGPL-3.0)</a></span></p>`;
    $$("#st-types .tag").forEach((b) => (b.onclick = async () => { const t = b.dataset.t; const mt = s.meal_types.includes(t) ? s.meal_types.filter((x) => x !== t) : [...s.meal_types, t]; if (!mt.length) return; await save({ meal_types: mt }); b.classList.toggle("on"); }));
    $("#st-nr").onchange = (e) => save({ no_repeat_days: +e.target.value || 0 });
    $("#st-exp").onchange = (e) => save({ prefer_expiring: e.target.checked });
    $("#st-win").onchange = (e) => save({ expiring_window_days: Math.max(1, +e.target.value || 3) });
    $("#st-auto").onchange = (e) => save({ auto_plan_day: e.target.value });
    $("#st-aemail").onchange = (e) => save({ auto_plan_email: e.target.checked });
    $("#st-xa").onchange = (e) => { save({ expiry_alert: e.target.checked }); if (e.target.checked && !anyChannel()) toast("Set up Notifications so alerts can reach you", "Set up", () => openSetupSection("notify", "Notifications", reloadCfg)); };
    $("#st-xh").onchange = (e) => save({ expiry_alert_hour: +e.target.value });
    $("#st-style").onchange = (e) => save({ recipe_style: e.target.value });
    $("#st-stove").onchange = (e) => save({ stove: e.target.value });
    $("#st-oven").onchange = (e) => save({ oven: e.target.value });
    $("#st-tu").onchange = (e) => save({ temp_unit: e.target.value });
    $("#st-ci").onchange = (e) => { save({ pantry_check_days: +e.target.value }); $("#st-ci-when").classList.toggle("hidden", !+e.target.value); };
    $("#st-ci-day").onchange = (e) => save({ checkin_day: e.target.value });
    $("#st-hz").onchange = async (e) => { await save({ plan_horizon_days: +e.target.value }); if (state.tab === "meals") replan(); };
    $("#st-rem").onchange = (e) => save({ plan_reminder_days: +e.target.value });
    $$("[data-eat]").forEach((i) => (i.onchange = () => { const et = { ...(s.eat_times || {}) }; if (i.value) et[i.dataset.eat] = i.value; else delete et[i.dataset.eat]; save({ eat_times: et }); }));
    const needCh = (on) => { if (on && !anyChannel()) toast("Set up Notifications so alerts can reach you", "Set up", () => openSetupSection("notify", "Notifications", reloadCfg)); };
    $("#st-mdb") && ($("#st-mdb").onchange = (e) => { save({ missing_alert_daybefore: e.target.checked }); needCh(e.target.checked); });
    $("#st-mmo") && ($("#st-mmo").onchange = (e) => { save({ missing_alert_morning: e.target.checked }); $("#st-mtime").disabled = !e.target.checked; needCh(e.target.checked); });
    $("#st-mtime") && ($("#st-mtime").onchange = (e) => { if (/^\d\d:\d\d$/.test(e.target.value)) save({ missing_alert_time: e.target.value }); });
    $("#st-startrem").onchange = (e) => { save({ start_reminder: e.target.checked }); if (e.target.checked && !anyChannel()) toast("Set up Notifications so reminders can reach you", "Set up", () => openSetupSection("notify", "Notifications", reloadCfg)); };
    $("#st-stores").onclick = () => storesManager(draw);
    $("#st-account").onclick = () => accountView(draw);
    $("#st-members").onclick = () => membersView(draw);
    $("#st-checklist").onclick = () => checklistSheet();
    $$("#st-mode [data-mode]").forEach((b) => (b.onclick = () => { setTheme(b.dataset.mode); save({ theme: b.dataset.mode }); $$("#st-mode [data-mode]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); }); }));
    $$("#st-looks [data-look]").forEach((b) => (b.onclick = () => { setTheme(null, b.dataset.look); save({ palette: b.dataset.look }); $$("#st-looks [data-look]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); }); }));
    bindDanger();
    $("#st-cats").onclick = () => categoriesManager(draw);
    $("#st-staples").onclick = () => staplesManager(draw);
    $("#st-foods") && ($("#st-foods").onclick = () => foodsManager(draw));
    $("#st-polish").onchange = (e) => { save({ polish_imports: e.target.checked }); if (e.target.checked && !c.ai_key) toast("Polishing needs an OpenAI key", "Add key", () => openSetupSection("ai", "AI recipe import", reloadCfg)); };
    $("#st-backups").onclick = () => backupsView(draw);
    api("GET", "/api/stores").then((ss) => { const b = $("#st-stores-b"); if (b && Array.isArray(ss) && ss.length) b.textContent = ss.map((x) => x.name).join(", "); }).catch(() => {});
    $("#st-ai").onclick = () => openAiSpending();
    const titles = { household: "Household", mealie: "Recipe library", ai: "AI recipe import", notify: "Notifications" };
    $$("[data-sec]").forEach((b) => (b.onclick = () => openSetupSection(b.dataset.sec, titles[b.dataset.sec], reloadCfg)));
    $("#st-mimport") && ($("#st-mimport").onclick = () => openMealieImport());
    $("#st-share").onclick = () => openShareSetup();
    $("#st-wn").onclick = () => openWhatsNewAll(draw);
    $("#st-wizard").onclick = () => { closeSheet(true); runWizard(() => location.reload()); };
    $("#st-logout") && ($("#st-logout").onclick = async () => { await api("POST", "/api/logout"); location.reload(); });
    $("#st-up") && ($("#st-up").onclick = () => openUpdateHelp());
    $("#st-sync").onclick = async (ev) => {
      ev.currentTarget.querySelector(".a").textContent = "Syncing…";
      try { const r = await api("POST", "/api/rules/sync-usda"); c.usda_synced_at = r.synced_at; toast(`Synced ${r.products} foods from USDA`); } catch (e) { fail(e); }
      draw();
    };
    $("#st-rules").onclick = () => rulesBrowser(draw);
    $("#st-bctest").onclick = () => openBarcodeTest();
    $("#st-tour").onclick = () => { closeSheet(true); go("home"); setTimeout(() => startTour(0), 300); };
    $("#st-pans") && ($("#st-pans").onclick = () => openPansSettings());
    $("#st-prices") && ($("#st-prices").onclick = () => openPricesSettings());
    $("#st-photos") && ($("#st-photos").onclick = () => openPhotoSettings());
    $("#st-ideas") && ($("#st-ideas").onclick = () => openIdeasSettings());
  };
  openSheet("Settings", loading(), { onMount: draw });
}

// ---------- Settings → Stores (rename, reorder with up/down, delete, add; every change saves right away)
async function storesManager(back) {
  let stores = [];
  try { stores = (await api("GET", "/api/stores")).slice().sort((a, b) => (a.position ?? 0) - (b.position ?? 0)); } catch (e) { fail(e); }
  const commit = async (next, msg, undoTo) => {
    try {
      stores = await saveStores(next.map((s) => (s.id != null ? { id: s.id, name: s.name } : { name: s.name })));
      if (L.data) L.data.stores = stores;
      if (msg) toast(msg, undoTo ? "Undo" : null, async () => { stores = await saveStores(undoTo); if (L.data) L.data.stores = stores; draw(); });
    } catch (e) { fail(e); }
    draw();
  };
  const draw = () => {
    if (!sheetBody()) return;
    sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="sm-back">${ic("chevL")} Settings</button></div>
      <div class="group-label" style="margin-top:4px">Stores</div>
      <div class="group" id="sm-list">${stores.map((s, i) => `<div class="field store-row" data-i="${i}">
        <input class="full" type="text" value="${esc(s.name)}" maxlength="40" aria-label="Store name" data-name>
        <button class="mini" data-up ${i ? "" : "disabled"} aria-label="Move ${esc(s.name)} up">${ic("chevU")}</button>
        <button class="mini" data-down ${i < stores.length - 1 ? "" : "disabled"} aria-label="Move ${esc(s.name)} down">${ic("chevD")}</button>
        <button class="mini red" data-del aria-label="Delete ${esc(s.name)}">${ic("trash")}</button></div>`).join("") || `<div class="row flush muted">No stores yet.</div>`}</div>
      ${stores.length < 12 ? `<form class="group" id="sm-add-f" style="margin-top:12px"><div class="field"><input class="full" type="text" id="sm-new" maxlength="40" placeholder="Add a store, e.g. Trader Joe's"><button class="mini blue" type="submit" aria-label="Add store">${ic("plus")}</button></div></form>` : ""}
      <p class="hint">Stores show up as filters on the shopping list. When you move an item to a store, TablePlan remembers it, so that food goes to the same store next time. Up to 12 stores.</p>`;
    $("#sm-back").onclick = back;
    $$("#sm-list [data-i]").forEach((row) => {
      const i = +row.dataset.i, s = stores[i];
      const inp = $("[data-name]", row);
      inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); inp.blur(); } if (e.key === "Escape") { inp.value = s.name; inp.blur(); } };
      inp.onchange = () => {
        const v = inp.value.trim().slice(0, 40);
        if (!v || v === s.name) { inp.value = s.name; return; }
        commit(stores.map((x, k) => (k === i ? { ...x, name: v } : x)), `Renamed to ${v}`);
      };
      const swap = (j) => { const n = stores.slice(); [n[i], n[j]] = [n[j], n[i]]; commit(n); };
      $("[data-up]", row).onclick = () => swap(i - 1);
      $("[data-down]", row).onclick = () => swap(i + 1);
      $("[data-del]", row).onclick = () => { const before = stores.map((x) => ({ id: x.id, name: x.name })); commit(stores.filter((_, k) => k !== i), `Deleted ${s.name}`, before); };
    });
    $("#sm-add-f") && ($("#sm-add-f").onsubmit = (e) => {
      e.preventDefault();
      const v = $("#sm-new").value.trim().slice(0, 40);
      if (!v) return;
      if (stores.some((x) => x.name.toLowerCase() === v.toLowerCase())) return toast(`${v} is already a store`);
      commit([...stores, { name: v }], `Added ${v}`).then(() => $("#sm-new")?.focus());
    });
  };
  draw();
}

// ---------- Settings → Foods: canonical foods (rename, merge duplicates with Undo, default store/location/category)
function foodsManager(back) {
  const F = { q: "", list: [], total: 0, sel: new Set(), open: null, merging: false, stores: [] };
  const uses = (u) => [u.recipes ? plural(u.recipes, "recipe") : "", u.list ? "on list" : "", u.pantry ? "in pantry" : ""].filter(Boolean).join(" · ") || "Not used yet";
  const load = async () => {
    try {
      const [d, st] = await Promise.all([api("GET", `/api/foods?q=${enc(F.q)}`), F.stores.length ? F.stores : api("GET", "/api/stores").catch(() => [])]);
      F.list = d.foods || []; F.total = d.total || 0; F.stores = st || [];
    } catch (e) { fail(e); }
    drawRows();
  };
  const shell = () => {
    if (!sheetBody()) return;
    sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="fm-back">${ic("chevL")} Settings</button></div>
      <div class="search">${ic("search")}<input id="fm-q" type="search" placeholder="Search foods" autocomplete="off" value="${esc(F.q)}"></div>
      <div class="pk-tools"><span class="muted small" id="fm-n"></span><span class="grow"></span><button class="link-btn" id="fm-merge" aria-pressed="false">Merge duplicates</button></div>
      <div id="fm-list">${loading()}</div><div class="pk-bar" id="fm-bar" hidden></div>
      <p class="hint">Every ingredient, list item and inventory item points at one of these foods, so “Morton iodized salt” and “table salt” match while sea salt stays separate.</p>`;
    $("#fm-back").onclick = back;
    let t;
    $("#fm-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { F.q = e.target.value; load(); }, 200); };
    $("#fm-merge").onclick = () => { F.merging = !F.merging; F.sel.clear(); $("#fm-merge").textContent = F.merging ? "Cancel" : "Merge duplicates"; $("#fm-merge").setAttribute("aria-pressed", String(F.merging)); drawRows(); };
  };
  const drawRows = () => {
    const box = $("#fm-list"); if (!box) return;
    $("#fm-n").textContent = `${plural(F.total, "food")}`;
    box.innerHTML = F.list.length ? `<div class="group">${F.list.map((f) => {
      const on = F.sel.has(f.id), open = F.open === f.id;
      return `<div class="food-row ${open ? "open" : ""}"><button class="row" data-fid="${esc(f.id)}" ${F.merging ? `aria-pressed="${on}"` : `aria-expanded="${open}"`}>
        ${F.merging ? `<span class="selc ${on ? "on" : ""}" aria-hidden="true">${on ? ic("check") : ""}</span>` : ""}
        <div class="main"><div class="a">${esc(f.name)}</div><div class="b">${esc(uses(f.uses))}${f.aliases.length ? ` · ${esc(plural(f.aliases.length, "other name"))}` : ""}</div></div>${F.merging ? "" : `<span class="chev">${ic(open ? "chevD" : "chevR")}</span>`}</button>
        ${open ? foodDetail(f) : ""}</div>`;
    }).join("")}</div>` : `<div class="empty">No foods match.</div>`;
    $$("#fm-list [data-fid]").forEach((b) => (b.onclick = () => {
      const id = +b.dataset.fid;
      if (F.merging) { F.sel.has(id) ? F.sel.delete(id) : F.sel.add(id); }
      else F.open = F.open === id ? null : id;
      drawRows();
    }));
    const f = F.list.find((x) => x.id === F.open);
    if (f && !F.merging) bindDetail(f);
    drawBar();
  };
  const foodDetail = (f) => `<div class="food-detail">
      <div class="field"><label>Name</label><input id="fd-name" value="${esc(f.name)}" maxlength="60"></div>
      <div class="field"><label>Category</label><input id="fd-cat" value="${esc(f.category)}" maxlength="40" placeholder="Aisle"></div>
      <div class="field"><label>Stored in</label><select id="fd-loc">${[["", "Automatic"], ["fridge", "Fridge"], ["freezer", "Freezer"], ["pantry", "Pantry"]].map(([v, l]) => `<option value="${v}" ${f.location === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="field"><label>Buy at</label><select id="fd-store"><option value="">Any store</option>${F.stores.map((s) => `<option value="${esc(s.id)}" ${String(f.store_id) === String(s.id) ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></div>
      ${f.aliases.length ? `<div class="aliases"><small class="muted">Also matches</small>${f.aliases.map((a) => `<span class="cat-pill">${esc(a)}</span>`).join("")}</div>` : ""}
    </div>`;
  const bindDetail = (f) => {
    const save = async (body, msg) => { try { await api("PATCH", `/api/foods/${enc(f.id)}`, body); if (msg) toast(msg); await load(); } catch (e) { fail(e); } };
    $("#fd-name").onchange = (e) => { const v = e.target.value.trim(); if (v && v !== f.name) save({ name: v }, `Renamed to ${v}`); };
    $("#fd-cat").onchange = (e) => save({ category: e.target.value.trim() });
    $("#fd-loc").onchange = (e) => save({ location: e.target.value }, "Saved");
    $("#fd-store").onchange = (e) => save({ store_id: e.target.value || null }, "Saved");
  };
  const drawBar = () => {
    const bar = $("#fm-bar"); if (!bar) return;
    bar.hidden = !F.merging;
    if (!F.merging) return;
    const chosen = F.list.filter((f) => F.sel.has(f.id));
    bar.innerHTML = chosen.length < 2 ? `<span>Pick 2 or more foods that are the same thing</span>` :
      `<span>Keep:</span>${chosen.map((f) => `<button class="filter sm" data-into="${esc(f.id)}">${esc(f.name)}</button>`).join("")}`;
    $$("[data-into]", bar).forEach((b) => (b.onclick = async () => {
      const into = +b.dataset.into, ids = chosen.map((f) => f.id).filter((x) => x !== into);
      try {
        const r = await api("POST", "/api/foods/merge", { ids, into });
        toast(`Merged ${plural(r.merged, "food")} into ${b.textContent}`, "Undo", async () => { try { await api("POST", "/api/foods/unmerge", { undo_token: r.undo_token }); load(); } catch (x) { fail(x); } });
        F.merging = false; F.sel.clear(); const m = $("#fm-merge"); if (m) m.textContent = "Merge duplicates";
        load();
      } catch (e) { fail(e); }
    }));
  };
  shell(); load();
}

// ---------- Settings → Inventory → Always have (basics that never go on the list or count as missing)
function staplesManager(back) {
  const draw = () => {
    if (!sheetBody()) return;
    const list = state.cfg.settings.staples || [];
    sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="sp-back">${ic("chevL")} Settings</button></div>
      <div class="group-label" style="margin-top:4px">Always have</div>
      <div class="group" id="sp-list">${list.map((n, i) => `<div class="field store-row"><span class="full">${esc(n)}</span><button class="mini red" data-del="${i}" aria-label="Remove ${esc(n)}">${ic("trash")}</button></div>`).join("") || `<div class="row flush muted">Nothing yet.</div>`}</div>
      <form class="group" id="sp-add" style="margin-top:12px"><div class="field"><input class="full" id="sp-new" maxlength="40" placeholder="Add a food, e.g. Soy sauce"><button class="mini blue" type="submit" aria-label="Add">${ic("plus")}</button></div></form>
      <p class="hint">These never go on your shopping list, never count as missing, and aren't taken out of your inventory when you cook.</p>`;
    $("#sp-back").onclick = back;
    $$("#sp-list [data-del]").forEach((b) => (b.onclick = async () => {
      const name = list[+b.dataset.del];
      try { const r = await api("POST", "/api/staples/remove", { name }); state.cfg.settings.staples = r.staples; toast(`${name} removed`); draw(); } catch (e) { fail(e); }
    }));
    $("#sp-add").onsubmit = (e) => { e.preventDefault(); const v = $("#sp-new").value.trim(); if (v) alwaysHave(v, draw); };
  };
  draw();
}

// ---------- Settings → Danger zone: type the section's name to confirm; the server backs up first
const DANGER = [["inventory", "Inventory", "Every inventory item, its history and photos"],
  ["recipes", "Recipes", "All recipes, their photos and notes, and the meals planned with them"],
  ["plan", "Meal plan", "Every planned meal (the list drops what they needed)"],
  ["list", "Shopping list", "Everything on the shopping list (stores are kept)"],
  ["trips", "Grocery trips", "Logged trips, receipts and prices"],
  ["diary", "Cooking diary", "Every diary entry, rating and photo"],
  ["demo", "Demo data", "Only the sample recipes and items, if any"],
  ["everything", "Everything", "All of the above. Settings, stores and foods stay"]];
function bindDanger() {
  $$("#st-danger [data-reset]").forEach((b) => (b.onclick = () => {
    const k = b.dataset.reset, label = DANGER.find((x) => x[0] === k)[1];
    const box = $(`#st-danger [data-for="${k}"]`);
    if (!box.hidden) { box.hidden = true; return; }
    $$("#st-danger .danger-confirm").forEach((x) => { x.hidden = true; });
    box.hidden = false;
    box.innerHTML = `<form class="danger-f"><label>Type <b>${esc(label)}</b> to confirm</label><input autocomplete="off" aria-label="Type ${esc(label)} to confirm"><button class="btn red small" type="submit" disabled>${k === "everything" ? "Reset everything" : `Reset ${esc(label.toLowerCase())}`}</button></form>`;
    const inp = $("input", box), go = $("button", box);
    inp.focus();
    inp.oninput = () => { go.disabled = inp.value.trim().toLowerCase() !== label.toLowerCase(); };
    $("form", box).onsubmit = async (e) => {
      e.preventDefault(); if (go.disabled) return;
      go.disabled = true; go.textContent = "Backing up…";
      try {
        const r = await api("POST", `/api/reset/${enc(k)}`, { confirm: inp.value.trim() });
        box.innerHTML = `<div class="wstatus ok"><b>Done.</b><span>Backup saved as ${esc(r.backup)} (Settings → Backups).</span></div>`;
        toast(`${label} reset · backup saved`);
      } catch (x) { fail(x); go.disabled = false; go.textContent = "Try again"; }
    };
  }));
}

// ---------- Settings → Categories (add, rename everywhere, delete with Undo, reorder; every change saves right away)
function categoriesManager(back) {
  const cats = () => state.cfg.settings.categories || [];
  const setCats = (list) => { state.cfg.settings.categories = list; };
  const run = async (fn, msg, undo) => {
    try { const r = await fn(); if (r && r.categories) setCats(r.categories); if (msg) toast(msg, undo ? "Undo" : null, async () => { try { const u = await undo(r); if (u && u.categories) setCats(u.categories); draw(); } catch (x) { fail(x); } }); }
    catch (e) { fail(e); }
    draw();
  };
  const order = (list) => run(async () => ({ categories: (await api("PUT", "/api/settings", { categories: list })).categories }));
  const draw = () => {
    if (!sheetBody()) return;
    const list = cats();
    sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="cm-back">${ic("chevL")} Settings</button></div>
      <div class="group-label" style="margin-top:4px">Categories</div>
      <div class="group" id="cm-list">${list.map((c, i) => `<div class="field store-row" data-i="${i}">
        <input class="full" type="text" value="${esc(c)}" maxlength="30" aria-label="Category name" data-name>
        <button class="mini" data-up ${i ? "" : "disabled"} aria-label="Move ${esc(c)} up">${ic("chevU")}</button>
        <button class="mini" data-down ${i < list.length - 1 ? "" : "disabled"} aria-label="Move ${esc(c)} down">${ic("chevD")}</button>
        <button class="mini red" data-del aria-label="Delete ${esc(c)}">${ic("trash")}</button></div>`).join("") || `<div class="row flush muted">No categories yet.</div>`}</div>
      ${list.length < 30 ? `<form class="group" id="cm-add-f" style="margin-top:12px"><div class="field"><input class="full" type="text" id="cm-new" maxlength="30" placeholder="Add a category, e.g. Pasta"><button class="mini blue" type="submit" aria-label="Add category">${ic("plus")}</button></div></form>` : ""}
      <p class="hint">Categories become filters on the Recipes tab and in the plan picker. Renaming one updates every recipe that uses it. Up to 30.</p>`;
    $("#cm-back").onclick = back;
    $$("#cm-list [data-i]").forEach((row) => {
      const i = +row.dataset.i, name = list[i], inp = $("[data-name]", row);
      inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); inp.blur(); } if (e.key === "Escape") { inp.value = name; inp.blur(); } };
      inp.onchange = () => {
        const v = inp.value.trim().replace(/\s+/g, " ").slice(0, 30);
        if (!v || v === name) { inp.value = name; return; }
        run(() => api("POST", "/api/categories/rename", { from: name, to: v }), `Renamed to ${v}`);
      };
      const swap = (j) => { const n = list.slice(); [n[i], n[j]] = [n[j], n[i]]; order(n); };
      $("[data-up]", row).onclick = () => swap(i - 1);
      $("[data-down]", row).onclick = () => swap(i + 1);
      $("[data-del]", row).onclick = () => run(() => api("POST", "/api/categories/delete", { name }), `Deleted ${name}`, (r) => api("POST", "/api/categories/undo-delete", r.undo));
    });
    $("#cm-add-f") && ($("#cm-add-f").onsubmit = (e) => {
      e.preventDefault();
      const v = $("#cm-new").value.trim().replace(/\s+/g, " ").slice(0, 30);
      if (!v) return;
      if (list.some((x) => x.toLowerCase() === v.toLowerCase())) return toast(`${v} is already a category`);
      order([...list, v]).then(() => { toast(`Added ${v}`); $("#cm-new")?.focus(); });
    });
  };
  draw();
}

// ---------- Settings → Backups (status, back up now, downloads)
const fmtBytes = (n) => (n >= 1e9 ? (n / 1e9).toFixed(1) + " GB" : n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1e3)) + " KB");
function fmtWhen(isoTs) {
  if (!isoTs) return "";
  const d = new Date(isoTs);
  if (isNaN(d)) return String(isoTs);
  const days = Math.round((today() - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 864e5);
  const t = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return days === 0 ? `today ${t}` : days === 1 ? `yesterday ${t}` : fmt(d, { month: "short", day: "numeric" }) + ` ${t}`;
}
function backupSummary(st) {
  if (!st || st.backups == null && !st.last_backup) return "Daily backups of your recipes, plans and inventory";
  const parts = [st.last_backup ? `Last ${fmtWhen(st.last_backup)}` : "No backup yet", st.backups != null ? `${st.backups} kept` : ""];
  if (st.integrity && st.integrity !== "ok") parts.push("database check failed");
  if (st.persistent === false) parts.push("not on a persistent volume");
  return parts.filter(Boolean).join(" · ");
}
async function backupsView(back) {
  let list = [];
  const load = async () => {
    try { list = await api("GET", "/api/backups"); } catch (e) { list = []; fail(e); }
    try { state.cfg = await api("GET", "/api/config"); } catch (_) {}
  };
  const draw = () => {
    if (!sheetBody()) return;
    const st = state.cfg.storage || {}, ok = !st.integrity || st.integrity === "ok";
    sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="bk-back">${ic("chevL")} Settings</button></div>
      ${st.persistent === false ? `<div class="storage-bar inline" role="alert"><span class="sb-ic">⚠️</span><span>Your data isn't on a persistent volume and will be lost when this container is rebuilt. Download a backup and see <a ${extLink(DOCS_BACKUPS)}>docs/install.md#backups</a>.</span></div>` : ""}
      <div class="group">
        <div class="row flush"><div class="main"><div class="a">Last backup</div><div class="b">${esc(st.last_backup ? fmtWhen(st.last_backup) : "None yet")}${st.backups != null ? ` · ${esc(plural(st.backups, "backup"))} kept` : ""}</div></div></div>
        <div class="row flush"><div class="main"><div class="a">Database check</div><div class="b">${esc(ok ? "No problems found at startup" : st.integrity)}</div></div><span class="pill ${ok ? "ok" : "bad"}">${ok ? "OK" : "Problem"}</span></div>
        <div class="row flush"><div class="main"><div class="a">Storage</div><div class="b">${esc(st.data_dir || "")}${st.data_dir ? " · " : ""}${st.persistent === false ? "not persistent" : st.persistent ? "persistent volume" : "unknown"}</div></div><span class="pill ${st.persistent === false ? "bad" : st.persistent ? "ok" : "none"}">${st.persistent === false ? "At risk" : st.persistent ? "Safe" : "?"}</span></div>
      </div>
      <div style="height:12px"></div>
      <div class="btn-row"><button class="btn sec" id="bk-now">${ic("refresh")} Back up now</button><a class="btn" id="bk-zip" href="/export/backup.zip" download>${ic("down")} Download everything (.zip)</a></div>
      <p class="hint">TablePlan backs up at startup and every night around 3 AM, keeping the last 14 days plus a snapshot before each update. The .zip has your database and photos.</p>
      <div class="group-label">Backups on this server</div>
      <div class="group" id="bk-list">${list.length ? list.map((b) => `<a class="row flush bk-row" href="/backups/${enc(b.name)}" download><span class="emo">🗄️</span><div class="main"><div class="a">${esc(b.name)}</div><div class="b">${esc(fmtWhen(b.created))}${b.size != null ? ` · ${esc(fmtBytes(+b.size))}` : ""}</div></div><span class="chev">${ic("down")}</span></a>`).join("") : `<div class="row flush muted">No backups yet. Tap “Back up now”.</div>`}</div>
      <p class="hint">To restore, stop the container, replace <code>tableplan.db</code> in the data folder with a backup, and start it again. <a ${extLink(DOCS_BACKUPS)}>Step-by-step guide</a></p>`;
    $("#bk-back").onclick = back;
    $("#bk-now").onclick = async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = "Backing up…";
      try { await api("POST", "/api/backups"); await load(); toast("Backup saved"); } catch (x) { fail(x); }
      draw();
    };
  };
  sheetBody().innerHTML = loading();
  await load();
  draw();
}

function openShareSetup() {
  const base = location.origin;
  openSheet("Share to TablePlan", `
    <div class="group-label">iPhone & iPad (one-time, 1 minute)</div>
    <div class="whatsnew"><ul>
      <li><span class="ic bg-blue">1</span><span><b>Open the Shortcuts app → tap +</b><span>Name it “TablePlan”.</span></span></li>
      <li><span class="ic bg-blue">2</span><span><b>Tap the ⓘ info button → turn on “Show in Share Sheet”</b><span>Set it to receive <b>URLs</b> and <b>Text</b>.</span></span></li>
      <li><span class="ic bg-blue">3</span><span><b>Add the action “URL”</b><span>Set it to: <code id="sc-url">${esc(base)}/?url=</code> then tap after the = and insert the variable <b>Shortcut Input</b>.</span></span></li>
      <li><span class="ic bg-blue">4</span><span><b>Add the action “Open URLs”</b><span>Done. Now in Instagram tap Share → <b>TablePlan</b> (under “More” the first time).</span></span></li>
    </ul></div>
    <button class="btn sec" id="sc-copy">${ic("link")} Copy the address for step 3</button>
    <div class="group-label">Android</div>
    <p class="hint" style="margin:0 4px">Add TablePlan to your home screen from Chrome (⋮ → Install app). It then appears in every app's Share menu.</p>
    <p class="hint">Shared posts open TablePlan with the link filled in; tap Import to add it. Public posts work best; private accounts need screenshots.</p>`, {
    onMount() { $("#sc-copy").onclick = async () => { try { await navigator.clipboard.writeText(base + "/?url="); toast("Copied"); } catch (_) { toast(base + "/?url="); } }; },
  });
}

function openMealieImport() {
  openSheet("Import from Mealie", `<p class="hint" style="margin:0 4px 12px">Copies recipes, photos, favorites, meal plans and shopping lists. Safe to run again. Afterwards you can uninstall Mealie.</p>
    <div class="group"><div class="field"><input class="full" id="mi-url" placeholder="Mealie address, e.g. http://192.168.1.50:9925" autocomplete="off"></div>
    <div class="field"><input class="full" id="mi-tok" type="password" placeholder="API token (Mealie → Profile → API Tokens)" autocomplete="off"></div></div>
    <div style="height:12px"></div><button class="btn" id="mi-go">Import</button><div id="mi-res"></div>`, {
    onMount() {
      $("#mi-go").onclick = async (e) => {
        const b = e.currentTarget; b.disabled = true; b.textContent = "Importing…";
        try {
          const r = await api("POST", "/api/setup/import-mealie", { url: $("#mi-url").value.trim(), token: $("#mi-tok").value.trim() });
          $("#mi-res").innerHTML = `<div class="wstatus ok" style="margin-top:12px"><b>Done</b><span>${esc(r.recipes?.recipes ?? 0)} recipes (${esc(r.recipes?.images ?? 0)} photos) · ${esc(r.plans?.imported ?? 0)} planned meals · ${esc(r.lists?.items ?? 0)} list items</span></div>`;
          b.textContent = "Import again"; b.disabled = false;
        } catch (x) { fail(x); b.disabled = false; b.textContent = "Import"; }
      };
    },
  });
}

function rulesBrowser(back) {
  sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="rb-back">${ic("chevL")} Back</button><button class="btn small" id="rb-new">${ic("plus")} New rule</button></div>
    <div class="search">${ic("search")}<input id="rb-q" placeholder="Search (e.g. cream)"></div><div id="rb-res">${loading()}</div>`;
  $("#rb-back").onclick = back;
  $("#rb-new").onclick = () => editRule(null, () => rulesBrowser(back));
  let t;
  const run = async () => {
    const { rules } = await api("GET", `/api/rules?q=${encodeURIComponent($("#rb-q").value)}`);
    $("#rb-res").innerHTML = `<div class="group">${rules.map((r) => `<button class="row" data-r="${esc(r.id)}"><div class="main"><div class="a">${esc(r.name)} ${r.source === "custom" ? '<span class="badge">house</span>' : ""}</div><div class="b">${esc(ruleDesc(r))}</div></div><span class="chev">${ic("chevR")}</span></button>`).join("") || '<div class="row muted">No matches</div>'}</div>`;
    $$("#rb-res [data-r]").forEach((b) => (b.onclick = () => editRule(rules.find((r) => String(r.id) === b.dataset.r), () => rulesBrowser(back))));
  };
  $("#rb-q").oninput = () => { clearTimeout(t); t = setTimeout(run, 220); };
  run();
}

function editRule(r, back) {
  const v = r ? { ...r } : { name: "", keywords: "", default_location: "fridge" };
  const F = [["sealed_fridge", "Fridge, sealed"], ["opened_fridge", "Fridge, after opening"], ["sealed_pantry", "Pantry, sealed"], ["opened_pantry", "Pantry, after opening"], ["freezer", "Freezer"], ["thawed_fridge", "Fridge, after thawing"]];
  sheetBody().innerHTML = `
    <div class="group">
      <div class="field"><input class="full" id="er-name" placeholder="Name (e.g. Heavy cream)" value="${esc(v.name)}"></div>
      <div class="field"><input class="full" id="er-kw" placeholder="Also matches (comma separated)" value="${esc(v.keywords || "")}"></div>
      <div class="field"><label>Usually stored in</label><select id="er-loc">${["fridge", "freezer", "pantry"].map((l) => `<option ${v.default_location === l ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
    </div>
    <div class="group-label">Days it keeps</div>
    <div class="group">${F.map(([k, l]) => `<div class="field"><label>${l}</label><input type="number" min="0" data-k="${k}" value="${esc(v[k] ?? "")}" placeholder="—"></div>`).join("")}</div>
    <p class="hint">${r && r.source === "usda" ? "Saving turns this into a house rule, so USDA re-syncs won't overwrite your numbers." : "House rules win over USDA data when both match."}${r && r.tips ? `<br><br>USDA tip: ${esc(r.tips)}` : ""}</p>
    <div style="height:14px"></div><div class="btn-row"><button class="btn sec" id="er-back">Cancel</button><button class="btn" id="er-save">Save</button></div>`;
  $("#er-back").onclick = back;
  $("#er-save").onclick = async () => {
    const body = { name: $("#er-name").value.trim(), keywords: $("#er-kw").value.trim(), default_location: $("#er-loc").value };
    $$("[data-k]").forEach((i) => (body[i.dataset.k] = i.value === "" ? null : +i.value));
    if (!body.name) return toast("Name is required");
    try { await api(r ? "PUT" : "POST", r ? `/api/rules/${enc(r.id)}` : "/api/rules", body); toast("Saved"); back(); } catch (e) { fail(e); }
  };
}

// ------------------------------------------------------------------ boot
async function reloadCfg() { try { state.cfg = await api("GET", "/api/config"); } catch (_) {} refresh(); }
function openUpdateHelp() {
  const u = state.update || {};
  const zima = (u.install || "zimaos") === "zimaos";
  const steps = zima ? [
    ["Open ZimaOS", "On any computer, go to your ZimaOS dashboard."],
    ["Open the App Store", "TablePlan shows an <b>Update</b> button there once ZimaOS checks the store (refresh the page if you don't see it yet)."],
    ["Tap Update", "Your recipes, plans and inventory are kept. TablePlan restarts in about a minute."]]
    : [["Update TablePlan", esc(u.how || "Pull the new image and restart the container.")], ["That's it", "Your data lives in the data volume and is kept."]];
  openSheet("Update TablePlan", `<div class="whatsnew"><ul>${steps.map(([t, d], n) => `<li><span class="ic bg-blue">${n + 1}</span><span><b>${t}</b><span>${d}</span></span></li>`).join("")}</ul></div>
    ${u.notes ? `<p class="hint"><b>What's new:</b> ${esc(u.notes)}</p>` : ""}
    <p class="hint" style="text-align:center">Installed ${esc(u.version || state.cfg.version)}${u.latest ? ` · latest ${esc(u.latest)}` : ""}</p>`);
}

(async function boot() {
  let sess;
  try { sess = await _api("GET", "/api/session"); }
  catch (e) { app.innerHTML = `<h1 class="title">TablePlan</h1><div class="banner">${esc(e.message)}</div>`; return; }
  if ((sess.auth_required || sess.needs_setup_code) && !sess.authed) return renderLogin(() => location.reload(), sess);
  if (!sess.setup_complete) return runWizard(() => location.reload());
  try { state.cfg = await api("GET", "/api/config"); }
  catch (e) { app.innerHTML = `<h1 class="title">TablePlan</h1><div class="banner">${esc(e.message)}</div>`; return; }
  applyTheme();
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme());
  checkUpdate(); setInterval(checkUpdate, 3600e3);
  api("GET", "/api/setup/ai").then((a) => { state.setup = { ai: a }; }).catch(() => {});
  route();
  const qs = new URLSearchParams(location.search);
  const shared = [qs.get("share_url"), qs.get("url"), (qs.get("share_text") || "").match(/https?:\/\/\S+/)?.[0]]
    .map((u) => (u || "").trim().slice(0, 2048)).find((u) => /^https?:\/\//i.test(u) && safeUrl(u));
  if (qs.has("share_url") || qs.has("url") || qs.has("share_text") || qs.has("share_title")) history.replaceState(null, "", "/" + location.hash);
  if (shared) setTimeout(() => openAddRecipe(shared), 400);
  window.addEventListener("popstate", route);
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkUpdate(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#layer").firstChild && !$("#cook") && TABS.some((t) => t[0] === location.hash.slice(1))) refresh(); });
  if (sess.needs_account) setTimeout(() => maybeAccountPrompt(sess), 500);
  else setTimeout(async () => { if (!(await maybeTour())) maybeWhatsNew(); }, 600);
  setTimeout(() => resumeCook(), 300);   // timers survive a reload: reopen cook mode where it was
  if (c_native()) setTimeout(pollQueue, 900);   // scans still being read, and the Recipes badge
})();
