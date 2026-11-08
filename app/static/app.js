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
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  chevL: '<path d="m15 18-6-6 6-6"/>',
  chevR: '<path d="m9 18 6-6-6-6"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 19V7.5A1.5 1.5 0 0 1 5.5 6H10"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  leaf: '<path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14z"/><path d="M5 19 13 11"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4"/>',
  open: '<path d="M4 20h16M6 16l2-9h8l2 9M10 7V4h4v3"/>',
  dish: '<path d="M3 15h18M5 15a7 7 0 0 1 14 0M12 8V6M10 6h4M4 18h16"/>',
};
const ic = (n, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24">${P[n] || ""}</svg>`;

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = $("#app");
const state = { tab: "home", cfg: null, summary: null, weekOffset: 0, mealsMode: "week", monthOffset: 0, listId: localStorage.getItem("tp.list") || null, pantryFilter: "all", plan: null };

async function api(method, path, body) {
  const res = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (res.status === 401 && data && data.auth) { renderLogin(() => location.reload()); throw new Error("Sign in required"); }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
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
const imgUrl = (r, size = "min") => (r && r.id && r.has_image !== false ? `/img/${r.id}?size=${size}` : null);

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
  toastTimer = setTimeout(() => t.classList.remove("on"), actionLabel ? 6000 : 3200);
}
const fail = (e) => toast(e.message || String(e));

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
const TABS = [["home", "Home", "home"], ["meals", "Meals", "cal"], ["list", "List", "cart"], ["pantry", "Pantry", "box"]];
function renderTabs() {
  $("#tabs").innerHTML = TABS.map(([id, label, icon]) => `<button class="tab ${state.tab === id ? "on" : ""}" data-tab="${id}">${ic(icon)}<span>${label}</span></button>`).join("");
  $$("#tabs .tab").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
}
function go(tab) {
  state.tab = tab;
  if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  renderTabs();
  window.scrollTo(0, 0);
  ({ home: renderHome, meals: renderMeals, list: renderList, pantry: renderPantry }[tab] || renderHome)();
}
const topbar = (extra = "") => `<div class="topbar">${extra}<button class="round-btn" id="btn-settings" aria-label="Settings">${ic("gear")}</button></div>`;
function bindTopbar() { $("#btn-settings") && ($("#btn-settings").onclick = openSettings); }
const loading = () => `<div class="spinner"></div>`;

// ------------------------------------------------------------------ HOME
async function renderHome() {
  app.innerHTML = topbar(`<button class="round-btn" id="btn-add" aria-label="Add recipe">${ic("plus")}</button>`) +
    `<h1 class="title">TablePlan</h1><div class="subtitle">${fmt(new Date(), { weekday: "long", month: "long", day: "numeric" })}</div>${loading()}`;
  bindTopbar(); $("#btn-add").onclick = openAddRecipe;
  let s;
  try { s = state.summary = await api("GET", "/api/summary"); } catch (e) { app.querySelector(".spinner").outerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  if (state.tab !== "home") return;

  const todayISO = isoDate(today());
  const tonight = s.week.filter((e) => e.date === todayISO).sort((a, b) => (a.entry_type === "dinner" ? -1 : 1))[0];
  const exp = s.expiring || [];
  const expired = exp.filter((i) => i.days_left < 0).length;

  const chips = [
    tonight ? [cap(tonight.entry_type) + " tonight", entryName(tonight), "dish", "bg-orange", "meals"] : ["Tonight", "Nothing planned", "dish", "bg-gray", "meals"],
    [exp.length ? `${exp.length} expiring` : "Pantry", exp.length ? (expired ? `${expired} past date` : "Use soon") : `${s.pantry_count} items`, "clock", exp.length ? "bg-red" : "bg-green", "pantry"],
    ["Shopping", `${s.list_count} to buy`, "cart", "bg-blue", "list"],
    ["Recipes", `${s.recipe_count} saved`, "book", "bg-purple", "recipes"],
  ];

  let html = `<div class="chips fade-in">${chips.map(([a, b, i, c, t]) =>
    `<button class="chip" data-go="${t}"><span class="dot ${c}">${ic(i)}</span><span>${esc(a)}<small>${esc(b)}</small></span></button>`).join("")}</div>`;
  if (!s.mealie_ok) html += `<button class="banner" id="fix-mealie" style="width:100%;text-align:left">${esc(s.error)}</button>`;
  if (state.update?.update_available) html += `<button class="update-banner" id="home-up">${ic("refresh")}<span><b>TablePlan ${esc(state.update.latest)} is available</b><small>${esc(state.update.how)}</small></span></button>`;

  // Tonight hero
  html += `<div class="section-h"><h2>Tonight</h2></div>`;
  if (tonight && tonight.recipe) {
    const img = imgUrl(tonight.recipe, "full");
    html += `<button class="tile hero wide ${img ? "" : "noimg"}" id="hero" ${img ? `style="background-image:url('${img}')"` : ""}>
      <div class="shade"></div><div class="hero-txt"><div class="t-sub">${esc(cap(tonight.entry_type))}</div><div class="t-title">${esc(entryName(tonight))}</div></div></button>`;
  } else {
    html += `<div class="grid"><button class="tile wide dim" id="plan-now"><span class="ic bg-orange">${ic("sparkle")}</span>
      <span><div class="t-title">Plan this week</div><div class="t-sub">Pick meals from your recipes in one tap</div></span></button></div>`;
  }

  // This week strip
  html += `<div class="section-h"><h2>This Week</h2><button data-go="meals">See all</button></div><div class="strip">`;
  for (let i = 0; i < 7; i++) {
    const d = addDays(today(), i), iso = isoDate(d);
    const e = s.week.filter((x) => x.date === iso).sort((a, b) => (a.entry_type === "dinner" ? -1 : 1))[0];
    if (e) {
      const img = imgUrl(e.recipe);
      html += `<button class="day-card" data-entry="${e.id}"><div class="img ${img ? "" : "ph"}" ${img ? `style="background-image:url('${img}')"` : ""}>${img ? "" : ic("dish")}</div>
        <div class="body"><div class="d">${esc(dayName(iso))}</div><div class="n">${esc(entryName(e))}</div></div></button>`;
    } else {
      html += `<button class="day-card blank" data-plan-day="${iso}"><div class="img ph" style="background:rgba(255,255,255,.12)">${ic("plus")}</div>
        <div class="body"><div class="d">${esc(dayName(iso))}</div><div class="n">Not planned</div></div></button>`;
    }
  }
  html += `</div>`;

  // Use soon
  html += `<div class="section-h"><h2>Use Soon</h2><button data-go="pantry">Pantry</button></div>`;
  if (exp.length) {
    html += `<div class="grid">${exp.slice(0, 6).map((it) => {
      const [i, c] = locIcon[it.location] || locIcon.fridge;
      return `<button class="tile" data-item="${it.id}"><span class="ic ${it.days_left <= 0 ? "bg-red" : "bg-orange"}">${ic(i)}</span>
        <span style="min-width:0"><div class="t-title">${esc(it.name)}</div><div class="t-sub">${esc(relExpiry(it))}</div></span></button>`;
    }).join("")}</div>`;
  } else {
    html += `<div class="grid"><div class="tile dim wide"><span class="ic bg-green">${ic("leaf")}</span><span><div class="t-title">Nothing expiring soon</div><div class="t-sub">${s.pantry_count} items tracked</div></span></div></div>`;
  }

  // Quick actions
  html += `<div class="section-h"><h2>Quick Actions</h2></div><div class="grid">
    <button class="tile" id="qa-import"><span class="ic bg-purple">${ic("camera")}</span><span><div class="t-title">Add Recipe</div><div class="t-sub">Screenshot or link</div></span></button>
    <button class="tile" id="qa-plan"><span class="ic bg-orange">${ic("sparkle")}</span><span><div class="t-title">Auto-Plan</div><div class="t-sub">Week or month</div></span></button>
    <button class="tile" id="qa-list"><span class="ic bg-blue">${ic("mail")}</span><span><div class="t-title">Send List</div><div class="t-sub">Email or print</div></span></button>
    <button class="tile" id="qa-pantry"><span class="ic bg-green">${ic("plus")}</span><span><div class="t-title">Add to Pantry</div><div class="t-sub">Track a use-by date</div></span></button>
  </div>`;

  app.querySelector(".spinner").outerHTML = html;
  $$("[data-go]").forEach((b) => (b.onclick = () => (b.dataset.go === "recipes" ? window.open(state.cfg.mealie_url, "_blank") : go(b.dataset.go))));
  $("#hero") && ($("#hero").onclick = () => openEntry(tonight));
  $("#fix-mealie") && ($("#fix-mealie").onclick = () => openSetupSection("mealie", "Recipe library", reloadCfg));
  $("#home-up") && ($("#home-up").onclick = () => toast(state.update.how));
  $("#plan-now") && ($("#plan-now").onclick = () => openGenerate());
  $$("[data-entry]").forEach((b) => (b.onclick = () => openEntry(s.week.find((e) => String(e.id) === b.dataset.entry))));
  $$("[data-plan-day]").forEach((b) => (b.onclick = () => openGenerate({ start: b.dataset.planDay, days: 7 })));
  $$("[data-item]").forEach((b) => (b.onclick = () => openPantryItem(exp.find((i) => String(i.id) === b.dataset.item), renderHome)));
  $("#qa-import").onclick = openAddRecipe;
  $("#qa-plan").onclick = () => openGenerate();
  $("#qa-list").onclick = async () => { const l = s.lists[0]; if (!l) return toast("No shopping list in Mealie yet"); openShare("list", { id: l.id, name: l.name }); };
  $("#qa-pantry").onclick = () => openAddPantry(renderHome);
}
const entryName = (e) => (e.recipe && e.recipe.name) || e.title || "Note";
function relExpiry(it) {
  const d = it.days_left;
  if (d === null || d === undefined) return "No use-by date";
  if (d < 0) return `Expired ${-d} day${d === -1 ? "" : "s"} ago`;
  if (d === 0) return "Use today";
  if (d === 1) return "Use by tomorrow";
  return `Use within ${d} days`;
}

// ------------------------------------------------------------------ MEALS
async function renderMeals() {
  const mode = state.mealsMode;
  let start, end, label;
  if (mode === "week") {
    start = addDays(today(), state.weekOffset * 7); end = addDays(start, 6);
    label = state.weekOffset === 0 ? "Next 7 days" : `${fmt(start, { month: "short", day: "numeric" })} – ${fmt(end, { month: "short", day: "numeric" })}`;
  } else {
    const t = today(); start = new Date(t.getFullYear(), t.getMonth() + state.monthOffset, 1);
    end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
    label = fmt(start, { month: "long", year: "numeric" });
  }
  app.innerHTML = topbar(`<button class="round-btn" id="btn-share" aria-label="Share">${ic("share")}</button>`) +
    `<h1 class="title">Meals</h1>
    <div class="seg" id="mode"><button data-m="week" class="${mode === "week" ? "on" : ""}">Week</button><button data-m="month" class="${mode === "month" ? "on" : ""}">Month</button></div>
    <div class="week-nav"><button class="round-btn" id="prev">${ic("chevL")}</button><span class="lbl">${esc(label)}</span><button class="round-btn" id="next">${ic("chevR")}</button></div>
    <div class="toolbar"><button class="pill-btn" id="gen">${ic("sparkle")} Auto-plan ${mode === "week" ? "week" : "month"}</button>
    <button class="pill-btn" id="mealie-plan">${ic("cart")} Add to list</button></div>
    <div id="days">${loading()}</div>`;
  bindTopbar();
  $$("#mode button").forEach((b) => (b.onclick = () => { state.mealsMode = b.dataset.m; renderMeals(); }));
  $("#prev").onclick = () => { mode === "week" ? state.weekOffset-- : state.monthOffset--; renderMeals(); };
  $("#next").onclick = () => { mode === "week" ? state.weekOffset++ : state.monthOffset++; renderMeals(); };
  const genStart = start < today() ? today() : start;
  $("#gen").onclick = () => openGenerate({ start: isoDate(genStart), days: Math.round((end - genStart) / 864e5) + 1 });
  $("#btn-share").onclick = () => openShare("plan", { start: isoDate(start), end: isoDate(end), label });
  $("#mealie-plan").onclick = () => openPlanToList(isoDate(start < today() ? today() : start), isoDate(end), label);

  let data;
  try { data = state.plan = await api("GET", `/api/plan?start=${isoDate(start)}&end=${isoDate(end)}`); }
  catch (e) { $("#days").innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  const byDay = {};
  data.entries.forEach((e) => (byDay[e.date] = byDay[e.date] || []).push(e));
  let html = "";
  for (let d = new Date(start); d <= end; d = addDays(d, 1)) {
    const iso = isoDate(d), es = (byDay[iso] || []).sort((a, b) => order(a.entry_type) - order(b.entry_type));
    const isToday = iso === isoDate(today());
    html += `<div class="group-label">${isToday ? "Today · " : ""}${esc(fmt(d, { weekday: "long", month: "short", day: "numeric" }))}</div><div class="group">`;
    if (!es.length) html += `<button class="row" data-plan-day="${iso}"><div class="thumb ph" style="background:rgba(127,127,127,.15);color:var(--sub)">${ic("plus")}</div><div class="main"><div class="a muted">Not planned</div><div class="b">Tap to fill from your recipes</div></div></button>`;
    es.forEach((e) => {
      const img = imgUrl(e.recipe);
      html += `<button class="row" data-entry="${e.id}"><div class="thumb ${img ? "" : "ph"}" ${img ? `style="background-image:url('${img}')"` : ""}>${img ? "" : ic("dish")}</div>
        <div class="main"><div class="a">${esc(entryName(e))}</div><div class="b">${esc(cap(e.entry_type))}</div></div><span class="chev">${ic("chevR")}</span></button>`;
    });
    html += `</div>`;
  }
  $("#days").innerHTML = html;
  $$("#days [data-entry]").forEach((b) => (b.onclick = () => openEntry(data.entries.find((e) => String(e.id) === b.dataset.entry))));
  $$("#days [data-plan-day]").forEach((b) => (b.onclick = () => openGenerate({ start: b.dataset.planDay, days: 1 })));
}
const ORDER = { breakfast: 0, lunch: 1, dinner: 2, side: 3 };
const order = (t) => ORDER[t] ?? 9;

function openEntry(e) {
  if (!e) return;
  const r = e.recipe || {};
  const img = imgUrl(r, "full");
  openSheet(entryName(e), `
    ${img ? `<div style="height:190px;border-radius:14px;background:#ddd url('${img}') center/cover;margin-bottom:12px"></div>` : ""}
    <div class="muted" style="margin:-4px 2px 14px">${esc(cap(e.entry_type))} · ${esc(fmt(parseISO(e.date), { weekday: "long", month: "long", day: "numeric" }))}</div>
    ${r.link ? `<a class="btn" href="${esc(r.link)}" target="_blank" rel="noopener">${ic("book")} Open recipe</a>
      <p class="hint" style="margin:7px 4px 14px">Change servings on the recipe page and every ingredient scales exactly.</p>` : ""}
    <div class="btn-row"><button class="btn sec" id="swap">${ic("shuffle")} Swap</button><button class="btn red" id="rm">${ic("trash")} Remove</button></div>`, {
    onMount() {
      $("#rm").onclick = async () => { try { await api("DELETE", `/api/plan/${e.id}`); closeSheet(); toast("Removed from plan"); refresh(); } catch (x) { fail(x); } };
      $("#swap").onclick = async () => {
        try {
          const planned = (state.plan?.entries || state.summary?.week || []).map((p) => ({ date: p.date, recipe_id: p.recipe?.id, entry_type: p.entry_type }));
          const p = await api("POST", "/api/plan/reroll", { date: e.date, entry_type: e.entry_type, exclude_ids: [r.id], planned });
          await api("POST", "/api/plan/save", { entries: [{ date: p.date, entry_type: p.entry_type, recipe_id: p.recipe.id }] });
          await api("DELETE", `/api/plan/${e.id}`);
          closeSheet(); toast(`Swapped for ${p.recipe.name}`); refresh();
        } catch (x) { fail(x); }
      };
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
        <div class="field"><label>Start</label><input type="date" id="g-start" value="${g.start}"></div>
        <div class="field"><label>Length</label><div class="seg" style="margin:0;flex:1;max-width:230px">${presets.map(([n, l]) => `<button data-days="${n}" class="${g.days === n ? "on" : ""}">${l}</button>`).join("")}</div></div>
      </div>
      <div class="group-label">Meals</div>
      <div class="group"><div class="tag-cloud" id="g-types">${["breakfast", "lunch", "dinner", "side"].map((t) => `<button class="tag ${g.meal_types.includes(t) ? "on" : ""}" data-t="${t}">${cap(t)}</button>`).join("")}</div></div>
      <div class="group-label">Rules</div>
      <div class="group">
        <div class="field"><label>Don't repeat within</label><input type="number" id="g-nr" min="0" max="90" value="${g.no_repeat_days}"> <span class="muted">days</span></div>
        <div class="field"><label>Use up expiring food first</label><label class="toggle"><input type="checkbox" id="g-exp" ${g.prefer_expiring ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>Keep meals already planned</label><label class="toggle"><input type="checkbox" id="g-fill" ${g.fill_empty_only ? "checked" : ""}><span></span></label></div>
        <button class="row" id="g-tags"><div class="main"><div class="a">Tags & categories</div><div class="b">${tagSummary(g)}</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <div style="height:16px"></div>
      <button class="btn" id="g-go">${ic("sparkle")} Generate</button>`;
    $("#g-start").onchange = (e) => (g.start = e.target.value);
    $$("[data-days]").forEach((b) => (b.onclick = () => { g.days = +b.dataset.days; draw(); }));
    $$("#g-types .tag").forEach((b) => (b.onclick = () => { const t = b.dataset.t; g.meal_types = g.meal_types.includes(t) ? g.meal_types.filter((x) => x !== t) : [...g.meal_types, t]; draw(); }));
    $("#g-nr").onchange = (e) => (g.no_repeat_days = +e.target.value || 0);
    $("#g-exp").onchange = (e) => (g.prefer_expiring = e.target.checked);
    $("#g-fill").onchange = (e) => (g.fill_empty_only = e.target.checked);
    $("#g-tags").onclick = () => pickTags(g, draw);
    $("#g-go").onclick = () => runGenerate(g);
  };
  openSheet("Auto-Plan", "", { onMount: draw });
}
const tagSummary = (g) => {
  const a = g.include_tags.length ? `Only: ${g.include_tags.join(", ")}` : "All recipes";
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
        html += `<div class="row"><div class="thumb ${img ? "" : "ph"}" ${img ? `style="background-image:url('${img}')"` : ""}>${img ? "" : ic("dish")}</div>
          <div class="main"><div class="a">${esc(p.recipe.name)}${p.recipe.uses_expiring ? '<span class="badge">uses expiring</span>' : ""}</div><div class="b">${esc(cap(p.entry_type))}</div></div>
          <button class="round-btn" style="background:rgba(118,118,128,.14);color:var(--text)" data-rr="${i}" aria-label="Swap">${ic("shuffle")}</button>
          <button class="round-btn" style="background:rgba(118,118,128,.14);color:var(--sub)" data-del="${i}" aria-label="Remove">${ic("x")}</button></div>`;
      });
      html += `</div>`;
    });
    html += `<div style="height:16px"></div><div class="btn-row"><button class="btn sec" id="p-again">${ic("refresh")} Redo</button><button class="btn" id="p-save">${ic("check")} Save ${props.length}</button></div>
      <p class="hint" style="text-align:center">Saved meals appear in Mealie's planner too.</p>`;
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
        const r = await api("POST", "/api/plan/save", { entries: props.map((p) => ({ date: p.date, entry_type: p.entry_type, recipe_id: p.recipe.id })) });
        closeSheet(); toast(`Added ${r.created} meals to your plan`); refresh();
      } catch (e) { ev.target.disabled = false; fail(e); }
    };
  };
  draw();
}

// ------------------------------------------------------------------ SHOPPING LIST
async function renderList() {
  app.innerHTML = topbar(`<button class="round-btn" id="btn-share" aria-label="Share">${ic("share")}</button>`) + `<h1 class="title">Shopping</h1><div id="lists">${loading()}</div>`;
  bindTopbar();
  let lists;
  try { lists = (await api("GET", "/api/lists")).lists; } catch (e) { $("#lists").innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  if (!lists.length) {
    $("#lists").innerHTML = `<div class="empty"><div class="em">🛒</div>No shopping lists yet.<br>Create one in Mealie, or add a week of meals to a list from the planner.</div>
      <a class="btn" href="${esc(state.cfg.mealie_url)}/shopping-lists" target="_blank">${ic("ext")} Open Mealie</a>`;
    return;
  }
  if (!lists.find((l) => l.id === state.listId)) state.listId = lists[0].id;
  localStorage.setItem("tp.list", state.listId);
  const sl = await api("GET", `/api/lists/${state.listId}`).catch((e) => ({ error: e.message }));
  if (sl.error) { $("#lists").innerHTML = `<div class="banner">${esc(sl.error)}</div>`; return; }
  $("#btn-share").onclick = () => openShare("list", { id: sl.id, name: sl.name });
  const count = sl.groups.reduce((n, g) => n + g.items.length, 0);
  let html = lists.length > 1 ? `<div class="seg">${lists.map((l) => `<button data-l="${l.id}" class="${l.id === state.listId ? "on" : ""}">${esc(l.name)}</button>`).join("")}</div>` : "";
  html += `<div class="subtitle">${count ? `${count} item${count === 1 ? "" : "s"} · tap to check off — food goes into your pantry` : "All done 🎉"}</div>
    <div class="toolbar"><button class="pill-btn" id="l-email">${ic("mail")} Email</button><button class="pill-btn" id="l-print">${ic("print")} Print</button>
    <a class="pill-btn" href="${esc(sl.mealie_link)}" target="_blank" rel="noopener" style="text-decoration:none">${ic("plus")} Add items</a></div>`;
  sl.groups.forEach((g) => {
    html += `<div class="group-label">${esc(g.label)}</div><div class="group">${g.items.map((it) =>
      `<button class="row" data-id="${it.id}" data-name="${esc(it.name)}"><span class="check">${ic("check")}</span><div class="main"><div class="a">${esc(it.text)}</div></div></button>`).join("")}</div>`;
  });
  if (!count) html += `<div class="empty">Nothing left to buy.</div>`;
  $("#lists").innerHTML = html;
  $$("[data-l]").forEach((b) => (b.onclick = () => { state.listId = b.dataset.l; renderList(); }));
  $("#l-email").onclick = () => emailIt({ kind: "list", id: sl.id });
  $("#l-print").onclick = () => printIt(`/print/list/${sl.id}`);
  $$("#lists .row[data-id]").forEach((row) => (row.onclick = () => buyItem(sl.id, row)));
}

async function buyItem(listId, row) {
  if (row.classList.contains("done")) return;
  row.classList.add("done"); $(".check", row).classList.add("on");
  const id = row.dataset.id;
  try {
    const r = await api("POST", `/api/lists/${listId}/items/${id}/bought`, { to_pantry: "auto" });
    setTimeout(() => { row.style.transition = "opacity .3s"; row.style.opacity = "0"; setTimeout(() => row.remove(), 300); }, 500);
    const undo = async () => {
      try { await api("POST", `/api/lists/${listId}/items/${id}/undo`, { pantry_item_id: r.pantry_item && r.pantry_item.id }); renderList(); } catch (e) { fail(e); }
    };
    if (r.pantry_item) {
      const p = r.pantry_item;
      toast(`${p.name} → ${cap(p.location)}${p.expires_on ? ` · use by ${fmt(parseISO(p.expires_on), { month: "short", day: "numeric" })}` : ""}`, "Undo", undo);
    } else {
      toast(`Checked off · not tracked`, "Track it", async () => {
        try { const p = await api("POST", "/api/pantry", { name: row.dataset.name }); toast(`${p.name} added to ${cap(p.location)}`); } catch (e) { fail(e); }
      });
    }
  } catch (e) { row.classList.remove("done"); $(".check", row).classList.remove("on"); fail(e); }
}

// ------------------------------------------------------------------ PANTRY
async function renderPantry() {
  app.innerHTML = topbar(`<button class="round-btn" id="btn-share" aria-label="Share">${ic("share")}</button><button class="round-btn" id="btn-addp" aria-label="Add">${ic("plus")}</button>`) +
    `<h1 class="title">Pantry</h1><div id="pantry">${loading()}</div>`;
  bindTopbar();
  $("#btn-addp").onclick = () => openAddPantry(renderPantry);
  $("#btn-share").onclick = () => openShare("pantry", {});
  let items;
  try { items = (await api("GET", "/api/pantry")).items; } catch (e) { $("#pantry").innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  const f = state.pantryFilter;
  const counts = { all: items.length, fridge: 0, freezer: 0, pantry: 0 };
  items.forEach((i) => counts[i.location]++);
  const shown = f === "all" ? items : items.filter((i) => i.location === f);
  const soon = items.filter((i) => i.days_left !== null && i.days_left <= 3).length;
  let html = `<div class="subtitle">${items.length} items${soon ? ` · ${soon} to use soon` : ""}</div>
    <div class="seg">${[["all", "All"], ["fridge", "Fridge"], ["freezer", "Freezer"], ["pantry", "Pantry"]].map(([k, l]) =>
      `<button data-f="${k}" class="${f === k ? "on" : ""}">${l}${counts[k] ? ` ${counts[k]}` : ""}</button>`).join("")}</div>`;
  if (!shown.length) {
    html += `<div class="empty"><div class="em">🥬</div>${items.length ? "Nothing here." : "Your pantry is empty.<br>Check items off your shopping list and they'll show up here with use-by dates."}</div>`;
  } else {
    html += `<div class="group" style="margin-top:12px">${shown.map((it) => {
      const [i, c] = locIcon[it.location] || locIcon.fridge;
      const left = Math.round(it.amount_left * 100);
      return `<button class="row" data-id="${it.id}"><span class="ic ${c}" style="width:32px;height:32px;border-radius:50%;display:grid;place-items:center;color:#fff;flex:none">${ic(i)}</span>
        <div class="main"><div class="a">${esc(it.name)}</div><div class="b">${it.opened_on ? "Opened" : "Sealed"}${left < 100 ? ` · ${left}% left` : ""}${it.quantity_text && it.quantity_text !== it.name ? ` · ${esc(it.quantity_text)}` : ""}</div>
        ${left < 100 ? `<div class="meter"><i style="width:${left}%;background:${left <= 25 ? "var(--orange)" : "var(--green)"}"></i></div>` : ""}</div>${expiryPill(it)}</button>`;
    }).join("")}</div>`;
  }
  $("#pantry").innerHTML = html;
  $$("[data-f]").forEach((b) => (b.onclick = () => { state.pantryFilter = b.dataset.f; renderPantry(); }));
  $$("#pantry .row[data-id]").forEach((b) => (b.onclick = () => openPantryItem(items.find((i) => String(i.id) === b.dataset.id), renderPantry)));
}

function openPantryItem(it, after) {
  if (!it) return;
  const act = async (body, msg) => {
    try { const r = await api("PATCH", `/api/pantry/${it.id}`, body); if (msg) toast(msg); return r; } catch (e) { fail(e); return null; }
  };
  const draw = (it) => {
    const left = Math.round(it.amount_left * 100);
    const rule = it.rule;
    const ruleLine = rule ? `${rule.name}` : "No match — set one for accurate dates";
    const srcLabel = { package: "from package", manual: "set by you", estimate: rule ? (rule.source === "usda" ? "USDA FoodKeeper" : rule.source === "custom" ? "house rule" : "estimate") : "estimate", none: "" }[it.expiry_source] || "";
    sheetBody().innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin:-4px 2px 12px">${expiryPill(it)}<span class="muted">${esc(relExpiry(it))}${srcLabel ? ` · ${esc(srcLabel)}` : ""}</span></div>
      <div class="group"><div class="kv">
        <div><small>Bought</small><b>${esc(fmt(parseISO(it.purchased_on), { month: "short", day: "numeric" }))}</b></div>
        <div><small>Opened</small><b>${it.opened_on ? esc(fmt(parseISO(it.opened_on), { month: "short", day: "numeric" })) : "—"}</b></div>
        <div><small>Use by</small><b>${it.expires_on ? esc(fmt(parseISO(it.expires_on), { month: "short", day: "numeric" })) : "—"}</b></div>
      </div></div>
      <div class="group-label">How much did you use?</div>
      <div class="big-actions">
        <button data-use="0.25">${ic("open")}¼</button><button data-use="0.5">${ic("open")}½</button>
        <button data-use="0.75">${ic("open")}¾</button><button data-use="1">${ic("check")}All</button>
      </div>
      <div class="group"><div class="amount"><span class="muted">Left</span><input type="range" min="0" max="100" step="5" value="${left}" id="pi-left"><b id="pi-lv">${left}%</b></div></div>
      ${!it.opened_on && it.location !== "freezer" ? `<p class="hint">Using some marks it opened and switches to the after-opening shelf life${rule && (it.location === "fridge" ? rule.opened_fridge : rule.opened_pantry || rule.opened_fridge) ? ` (${it.location === "fridge" ? rule.opened_fridge : rule.opened_pantry || rule.opened_fridge} days)` : ""}.</p>` : ""}
      <div class="group-label">Stored in</div>
      <div class="seg" id="pi-loc">${["fridge", "freezer", "pantry"].map((l) => `<button data-loc="${l}" class="${it.location === l ? "on" : ""}">${cap(l)}</button>`).join("")}</div>
      <div class="group" style="margin-top:12px">
        <div class="field"><label>Use-by date</label><input type="date" id="pi-date" value="${it.expires_on || ""}"></div>
        <button class="row" id="pi-rule"><div class="main"><div class="a">Shelf life</div><div class="b">${esc(ruleLine)}</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <p class="hint">Have a printed date? Enter it above and it wins over the estimate.</p>
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
    const slider = $("#pi-left");
    slider.oninput = () => ($("#pi-lv").textContent = slider.value + "%");
    slider.onchange = async () => { const r = await act({ action: "use", left: slider.value / 100 }); if (r) { if (r.status !== "active") return done(); draw(r); after && after(); } };
    $$("#pi-loc [data-loc]").forEach((b) => (b.onclick = async () => { const r = await act({ action: "move", location: b.dataset.loc }, `Moved to ${b.dataset.loc}`); if (r) { draw(r); after && after(); } }));
    $("#pi-date").onchange = async (e) => { const r = await act({ action: "set_date", expires_on: e.target.value }, "Date saved"); if (r) { draw(r); after && after(); } };
    $("#pi-rule").onclick = () => pickRule(it, async (rule) => { const r = await act({ action: "rule", rule_id: rule ? rule.id : null }, rule ? "Shelf life updated" : null); draw(r || it); after && after(); });
    $("#pi-toss").onclick = async () => { const r = await act({ action: "toss" }); if (r) { toast(`${it.name} tossed`, "Undo", async () => { await act({ action: "restore" }); after && after(); }); done(); } };
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
      $("#rres").innerHTML = `<div class="group">${rules.map((r) => `<button class="row" data-r="${r.id}"><div class="main"><div class="a">${esc(r.name)} ${r.source === "custom" ? '<span class="badge">house</span>' : r.source === "usda" ? '<span class="badge" style="background:rgba(0,122,255,.14);color:var(--blue)">USDA</span>' : ""}</div><div class="b">${esc(ruleDesc(r))}</div></div></button>`).join("") || '<div class="row"><div class="main muted">No matches</div></div>'}</div>
        <p class="hint">Not listed? Add a house rule in Settings → Shelf life.</p>`;
      $$("#rres [data-r]").forEach((b) => (b.onclick = () => cb(rules.find((r) => String(r.id) === b.dataset.r))));
    } catch (e) { fail(e); }
  };
  q.oninput = () => { clearTimeout(t); t = setTimeout(run, 220); };
  run(); q.focus();
}

function openAddPantry(after) {
  const f = { name: "", location: "", package_date: "", quantity_text: "" };
  openSheet("Add to Pantry", `
    <div class="group"><div class="field"><input class="full" type="text" id="ap-name" placeholder="Item (e.g. Heavy cream)" autocomplete="off"></div>
      <div class="field"><input class="full" type="text" id="ap-qty" placeholder="Size (optional, e.g. 1 pint)"></div></div>
    <p class="hint" id="ap-match">Shelf life is looked up automatically.</p>
    <div class="group-label">Stored in</div>
    <div class="seg" id="ap-loc"><button data-loc="">Auto</button><button data-loc="fridge">Fridge</button><button data-loc="freezer">Freezer</button><button data-loc="pantry">Pantry</button></div>
    <div class="group" style="margin-top:12px"><div class="field"><label>Printed date</label><input type="date" id="ap-date"></div></div>
    <p class="hint">Optional — if the package has a use-by date, it's used instead of the estimate.</p>
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
function openAddRecipe() {
  const c = state.cfg;
  const imgs = [];
  openSheet("Add a Recipe", `
    <div class="seg" id="ar-mode"><button data-m="link" class="on">Link</button><button data-m="photo">Screenshot / Photo</button></div>
    <div id="ar-body"></div>
    <div id="ar-result"></div>`, {
    onMount() {
      const body = $("#ar-body");
      const drawLink = () => {
        body.innerHTML = `<div class="group" style="margin-top:12px"><div class="field"><input class="full" type="url" id="ar-url" placeholder="Paste a recipe, TikTok or YouTube link" autocomplete="off"></div></div>
          <div style="height:12px"></div><button class="btn" id="ar-go">${ic("link")} Import</button>
          <p class="hint">Most recipe sites import instantly. Video links need AI import turned on in Settings.</p>`;
        $("#ar-go").onclick = () => run(() => api("POST", "/api/import/url", { url: $("#ar-url").value.trim() }));
        if (navigator.clipboard && navigator.clipboard.readText) {
          $("#ar-url").addEventListener("focus", async () => { try { const t = await navigator.clipboard.readText(); if (/^https?:\/\//.test(t) && !$("#ar-url").value) $("#ar-url").value = t.trim(); } catch (_) {} }, { once: true });
        }
      };
      const drawPhoto = () => {
        body.innerHTML = `<label class="drop" style="margin-top:12px">${ic("camera")}<div style="margin-top:6px"><b>Choose screenshots or photos</b><br><span class="muted">Up to 8 images: a recipe card, cookbook page or a screenshot of a post</span></div>
          <input type="file" id="ar-files" accept="image/*" multiple hidden></label>
          <div class="thumbs" id="ar-thumbs"></div>
          <div style="height:12px"></div><button class="btn" id="ar-go" ${imgs.length ? "" : "disabled"}>${ic("sparkle")} Read recipe with AI</button>
          <p class="hint">${state.setup?.ai?.enabled === false ? "AI import isn't set up yet. Add your OpenAI key in Settings → AI recipe import." : "Takes 20–60 seconds. Check the ingredients afterwards."}</p>`;
        const thumbs = () => { $("#ar-thumbs").innerHTML = imgs.map((im) => `<img src="${im.data}" alt="">`).join(""); $("#ar-go").disabled = !imgs.length; };
        $("#ar-files").onchange = async (e) => {
          for (const f of [...e.target.files].slice(0, 8 - imgs.length)) imgs.push({ name: f.name, type: "image/jpeg", data: await shrink(f) });
          thumbs();
        };
        thumbs();
        $("#ar-go").onclick = () => run(() => api("POST", "/api/import/images", { images: imgs }));
      };
      const run = async (fn) => {
        const btn = $("#ar-go"); btn.disabled = true; const label = btn.innerHTML; btn.innerHTML = "Importing…";
        $("#ar-result").innerHTML = "";
        try {
          const r = await fn();
          $("#ar-body").innerHTML = "";
          $("#ar-mode").style.display = "none";
          $("#ar-result").innerHTML = `<div class="wstatus ok" style="margin-top:4px"><b>Added “${esc(r.name || r.slug)}”</b>
            <span>${r.ingredients ? `${r.ingredients} ingredients` : ""}${r.servings ? ` · serves ${r.servings}` : ""}</span></div>
            ${r.unparsed ? `<p class="hint">${r.unparsed} ingredient${r.unparsed > 1 ? "s aren't" : " isn't"} parsed yet. Open the recipe, tap Edit → Parse, so scaling and lists stay exact.</p>` : ""}
            <div class="btn-row" style="margin-top:12px"><a class="btn sec" href="${esc(r.link)}" target="_blank" rel="noopener">${ic("book")} Open recipe</a><button class="btn" id="ar-again">${ic("plus")} Add another</button></div>`;
          $("#ar-again").onclick = () => openAddRecipe();
        } catch (e) { btn.disabled = false; btn.innerHTML = label; $("#ar-result").innerHTML = `<div class="hint" style="color:var(--red)">${esc(e.message)}</div>`; }
      };
      $$("#ar-mode button").forEach((bt) => (bt.onclick = () => { $$("#ar-mode button").forEach((x) => x.classList.toggle("on", x === bt)); bt.dataset.m === "link" ? drawLink() : drawPhoto(); }));
      drawLink();
    },
  });
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

// ---------- meal plan → shopping list
async function openPlanToList(start, end, label) {
  let lists = [];
  try { lists = (await api("GET", "/api/lists")).lists; } catch (_) {}
  const people = state.cfg.household?.people || 2;
  openSheet("Add meals to shopping list", `
    <div class="group">
      <div class="field"><label>Meals</label><span class="muted">${esc(label)}</span></div>
      <div class="field"><label>List</label><select id="pl-list">${lists.length ? lists.map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join("") : '<option value="">New list "Groceries"</option>'}</select></div>
      <div class="field"><label>Skip what's in the pantry</label><label class="toggle"><input type="checkbox" id="pl-skip" checked><span></span></label></div>
    </div>
    <p class="hint">Ingredients are scaled for ${people} ${people === 1 ? "person" : "people"} and merged, so two recipes that need onions add up to one line.</p>
    <div style="height:14px"></div><button class="btn" id="pl-go">${ic("cart")} Add to list</button>`, {
    onMount() {
      $("#pl-go").onclick = async (ev) => {
        ev.currentTarget.disabled = true; ev.currentTarget.textContent = "Adding…";
        try {
          const r = await api("POST", "/api/plan/to-list", { start, end, list_id: $("#pl-list").value || null, skip_pantry: $("#pl-skip").checked });
          closeSheet();
          state.listId = r.list_id; localStorage.setItem("tp.list", r.list_id);
          toast(`Added ${r.recipes} recipe${r.recipes === 1 ? "" : "s"}${r.skipped.length ? ` · skipped ${r.skipped.length} you have` : ""}`, "View list", () => go("list"));
        } catch (e) { fail(e); ev.currentTarget.disabled = false; ev.currentTarget.textContent = "Add to list"; }
      };
    },
  });
}

// ------------------------------------------------------------------ share / export / print
function printIt(url) { window.open(url + (url.includes("?") ? "&" : "?") + "auto=1", "_blank"); }
async function emailIt(body) {
  if (!state.cfg.email_ready) return toast("Email isn't set up yet", "Set up", () => openSetupSection("email", "Email", reloadCfg));
  toast("Sending…");
  try { const r = await api("POST", "/api/email", body); toast(`Sent to ${r.to.join(", ")}`); } catch (e) { fail(e); }
}
async function shareText(url, title) {
  try { const txt = await (await fetch(url)).text(); await navigator.share({ title, text: txt }); }
  catch (e) { if (e.name !== "AbortError") fail(e); }
}
function openShare(kind, o) {
  let items = [], title = "Share";
  if (kind === "list") {
    title = o.name || "Shopping list";
    items = [["mail", "Email it", () => emailIt({ kind: "list", id: o.id })], ["print", "Print", () => printIt(`/print/list/${o.id}`)],
      ["file", "Text file", `/export/list/${o.id}.txt`], ["file", "Spreadsheet (CSV)", `/export/list/${o.id}.csv`]];
    if (navigator.share) items.unshift(["share", "Send via…", () => shareText(`/export/list/${o.id}.txt`, title)]);
  } else if (kind === "plan") {
    title = `Meal plan · ${o.label}`;
    const q = `start=${o.start}&end=${o.end}`;
    items = [["mail", "Email it", () => emailIt({ kind: "plan", start: o.start, end: o.end })], ["print", "Print", () => printIt(`/print/plan?${q}`)],
      ["cal", "Add to calendar (.ics)", `/export/plan.ics?${q}`], ["file", "Spreadsheet (CSV)", `/export/plan.csv?${q}`]];
    if (navigator.share) items.unshift(["share", "Send via…", () => shareText(`/export/plan.txt?${q}`, "Meal plan")]);
  } else if (kind === "pantry") {
    title = "Pantry";
    items = [["mail", "Email it", () => emailIt({ kind: "pantry" })], ["print", "Print", () => printIt("/print/pantry")], ["file", "Spreadsheet (CSV)", "/export/pantry.csv"]];
  }
  openSheet(title, `<div class="share-grid">${items.map(([i, l, a], n) =>
    typeof a === "string" ? `<a href="${a}" download>${ic(i)} ${esc(l)}</a>` : `<button data-n="${n}">${ic(i)} ${esc(l)}</button>`).join("")}</div>
    ${state.cfg.email_ready ? `<p class="hint">Email goes to ${esc(state.cfg.mail_to.join(", "))}.</p>` : ""}`, {
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
    const hh = c.household || {};
    sheetBody().innerHTML = `
      ${up.update_available ? `<button class="update-banner" id="st-up">${ic("refresh")}<span><b>Update available: ${esc(up.latest)}</b><small>${esc(up.how)}</small></span></button>` : ""}
      <div class="group-label">Setup</div>
      <div class="group">
        <button class="row" data-sec="household"><span class="ic bg-orange" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("home")}</span><div class="main"><div class="a">Household</div><div class="b">${esc(hh.name || "Household")} · cooking for ${hh.people || 2}${hh.scale === false ? " · scaling off" : ""}</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" data-sec="mealie"><span class="ic bg-purple" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("book")}</span><div class="main"><div class="a">Recipe library (Mealie)</div><div class="b">${c.connected ? "Connected" : "Not connected"}</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" data-sec="ai"><span class="ic bg-indigo" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("sparkle")}</span><div class="main"><div class="a">AI recipe import</div><div class="b">OpenAI key for screenshots, photos & videos</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" data-sec="email"><span class="ic bg-blue" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("mail")}</span><div class="main"><div class="a">Email</div><div class="b">${c.email_ready ? esc(c.mail_to.join(", ")) : "Not set up"}</div></div><span class="chev">${ic("chevR")}</span></button>
        <button class="row" data-sec="password"><span class="ic bg-gray" style="width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:#fff">${ic("open")}</span><div class="main"><div class="a">Password</div><div class="b">${c.auth_required ? "On" : "Off (anyone on your Wi-Fi)"}</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>
      <div class="group-label">Meal planning</div>
      <div class="group">
        <div class="tag-cloud" id="st-types">${["breakfast", "lunch", "dinner", "side"].map((t) => `<button class="tag ${s.meal_types.includes(t) ? "on" : ""}" data-t="${t}">${cap(t)}</button>`).join("")}</div>
        <div class="field"><label>Don't repeat within (days)</label><input type="number" id="st-nr" value="${s.no_repeat_days}" min="0" max="90"></div>
        <div class="field"><label>Use up expiring food first</label><label class="toggle"><input type="checkbox" id="st-exp" ${s.prefer_expiring ? "checked" : ""}><span></span></label></div>
        <div class="field"><label>"Use soon" window (days)</label><input type="number" id="st-win" value="${s.expiring_window_days}" min="1" max="14"></div>
        <div class="field"><label>Auto-plan next week every</label><select id="st-auto">${[["", "Off"], ["sun", "Sunday"], ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"]].map(([v, l]) => `<option value="${v}" ${s.auto_plan_day === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <div class="field"><label>Email the plan when it's made</label><label class="toggle"><input type="checkbox" id="st-aemail" ${s.auto_plan_email ? "checked" : ""}><span></span></label></div>
      </div>
      <p class="hint">Auto-plan runs at 8 AM on that day, fills empty days for the following week, and keeps anything you've already planned.</p>


      <div class="group-label">Shelf life data</div>
      <div class="group">
        <div class="row"><div class="main"><div class="a">USDA FoodKeeper</div><div class="b">${counts.usda ? `${counts.usda} foods · synced ${esc((c.usda_synced_at || "").replace("T", " "))}` : "Not synced yet — using starter table"}</div></div></div>
        <button class="row" id="st-sync"><div class="main"><div class="a" style="color:var(--blue)">${counts.usda ? "Re-sync now" : "Sync now"}</div></div></button>
        <button class="row" id="st-rules"><div class="main"><div class="a">House rules & edits</div><div class="b">${counts.custom || 0} custom · ${counts.starter || 0} starter</div></div><span class="chev">${ic("chevR")}</span></button>
      </div>

      <div class="group-label">Advanced</div>
      <div class="group">
        <a class="row" href="${esc(c.mealie_url)}" target="_blank" rel="noopener" style="text-decoration:none"><div class="main"><div class="a">Open Mealie</div><div class="b">Full recipe editor · ${esc(c.mealie_url)}</div></div><span class="chev">${ic("ext")}</span></a>
        <button class="row" id="st-wizard"><div class="main"><div class="a">Run setup wizard again</div></div><span class="chev">${ic("chevR")}</span></button>
        ${c.auth_required ? `<button class="row" id="st-logout"><div class="main"><div class="a" style="color:var(--red)">Sign out on this device</div></div></button>` : ""}
      </div>
      <p class="hint" style="text-align:center;margin-top:18px">TablePlan ${esc(up.version || c.version || "")}${up.latest && !up.update_available ? " · up to date" : ""} · your data stays on your server<br><a href="https://github.com/thomasjvalenzuela/tableplan" target="_blank" rel="noopener" style="color:var(--sub)">Source code (AGPL-3.0)</a></p>`;
    $$("#st-types .tag").forEach((b) => (b.onclick = async () => { const t = b.dataset.t; const mt = s.meal_types.includes(t) ? s.meal_types.filter((x) => x !== t) : [...s.meal_types, t]; if (!mt.length) return; await save({ meal_types: mt }); b.classList.toggle("on"); }));
    $("#st-nr").onchange = (e) => save({ no_repeat_days: +e.target.value || 0 });
    $("#st-exp").onchange = (e) => save({ prefer_expiring: e.target.checked });
    $("#st-win").onchange = (e) => save({ expiring_window_days: Math.max(1, +e.target.value || 3) });
    $("#st-auto").onchange = (e) => save({ auto_plan_day: e.target.value });
    $("#st-aemail").onchange = (e) => save({ auto_plan_email: e.target.checked });
    const titles = { household: "Household", mealie: "Recipe library", ai: "AI recipe import", email: "Email", password: "Password" };
    $$("[data-sec]").forEach((b) => (b.onclick = () => openSetupSection(b.dataset.sec, titles[b.dataset.sec], reloadCfg)));
    $("#st-wizard").onclick = () => { closeSheet(true); runWizard(() => location.reload()); };
    $("#st-logout") && ($("#st-logout").onclick = async () => { await api("POST", "/api/logout"); location.reload(); });
    $("#st-up") && ($("#st-up").onclick = () => toast(up.how));
    $("#st-sync").onclick = async (ev) => {
      ev.currentTarget.querySelector(".a").textContent = "Syncing…";
      try { const r = await api("POST", "/api/rules/sync-usda"); c.usda_synced_at = r.synced_at; toast(`Synced ${r.products} foods from USDA`); } catch (e) { fail(e); }
      draw();
    };
    $("#st-rules").onclick = () => rulesBrowser(draw);
  };
  openSheet("Settings", loading(), { onMount: draw });
}

function rulesBrowser(back) {
  sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="rb-back">${ic("chevL")} Back</button><button class="btn small" id="rb-new">${ic("plus")} New rule</button></div>
    <div class="search">${ic("search")}<input id="rb-q" placeholder="Search (e.g. cream)"></div><div id="rb-res">${loading()}</div>`;
  $("#rb-back").onclick = back;
  $("#rb-new").onclick = () => editRule(null, () => rulesBrowser(back));
  let t;
  const run = async () => {
    const { rules } = await api("GET", `/api/rules?q=${encodeURIComponent($("#rb-q").value)}`);
    $("#rb-res").innerHTML = `<div class="group">${rules.map((r) => `<button class="row" data-r="${r.id}"><div class="main"><div class="a">${esc(r.name)} ${r.source === "custom" ? '<span class="badge">house</span>' : ""}</div><div class="b">${esc(ruleDesc(r))}</div></div><span class="chev">${ic("chevR")}</span></button>`).join("") || '<div class="row muted">No matches</div>'}</div>`;
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
      <div class="field"><label>Usually stored in</label><select id="er-loc">${["fridge", "freezer", "pantry"].map((l) => `<option ${v.default_location === l ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    </div>
    <div class="group-label">Days it keeps</div>
    <div class="group">${F.map(([k, l]) => `<div class="field"><label>${l}</label><input type="number" min="0" data-k="${k}" value="${v[k] ?? ""}" placeholder="—"></div>`).join("")}</div>
    <p class="hint">${r && r.source === "usda" ? "Saving turns this into a house rule, so USDA re-syncs won't overwrite your numbers." : "House rules win over USDA data when both match."}${r && r.tips ? `<br><br>USDA tip: ${esc(r.tips)}` : ""}</p>
    <div style="height:14px"></div><div class="btn-row"><button class="btn sec" id="er-back">Cancel</button><button class="btn" id="er-save">Save</button></div>`;
  $("#er-back").onclick = back;
  $("#er-save").onclick = async () => {
    const body = { name: $("#er-name").value.trim(), keywords: $("#er-kw").value.trim(), default_location: $("#er-loc").value };
    $$("[data-k]").forEach((i) => (body[i.dataset.k] = i.value === "" ? null : +i.value));
    if (!body.name) return toast("Name is required");
    try { await api(r ? "PUT" : "POST", r ? `/api/rules/${r.id}` : "/api/rules", body); toast("Saved"); back(); } catch (e) { fail(e); }
  };
}

// ------------------------------------------------------------------ boot
async function reloadCfg() { try { state.cfg = await api("GET", "/api/config"); } catch (_) {} refresh(); }

(async function boot() {
  let sess;
  try { sess = await _api("GET", "/api/session"); }
  catch (e) { app.innerHTML = `<h1 class="title">TablePlan</h1><div class="banner">${esc(e.message)}</div>`; return; }
  if (sess.auth_required && !sess.authed) return renderLogin(() => location.reload());
  if (!sess.setup_complete) return runWizard(() => location.reload());
  try { state.cfg = await api("GET", "/api/config"); }
  catch (e) { app.innerHTML = `<h1 class="title">TablePlan</h1><div class="banner">${esc(e.message)}</div>`; return; }
  api("GET", "/api/version").then((u) => { state.update = u; if (u.update_available && state.tab === "home") renderHome(); }).catch(() => {});
  api("GET", "/api/setup/ai").then((a) => { state.setup = { ai: a }; }).catch(() => {});
  const h = location.hash.slice(1);
  go(TABS.some((t) => t[0] === h) ? h : "home");
  window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if (TABS.some((x) => x[0] === t) && t !== state.tab) go(t); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#layer").firstChild) refresh(); });
})();
