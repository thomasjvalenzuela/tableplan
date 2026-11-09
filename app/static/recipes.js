/* TablePlan: recipes, recipe page, cook mode, images, AI spending, barcode scanner, pantry check-in, what's new.
   Loaded after app.js and uses its helpers ($, api, esc, ic, openSheet, toast, state, …). */
"use strict";
// Broken images fall back to their emoji/text (no inline handlers, so the strict CSP stays on).
document.addEventListener("error", (e) => { const t = e.target; if (t && t.tagName === "IMG" && t.dataset.fb != null) t.replaceWith(document.createTextNode(t.dataset.fb)); }, true);

// ------------------------------------------------------------------ number formatting & scaling
const FRAC = [[1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"], [1 / 2, "½"], [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"]];
function fmtQty(q) {
  if (q == null || !isFinite(q) || q <= 0) return "";
  const whole = Math.floor(q + 1e-9), rem = q - whole;
  if (rem < 0.04) return String(whole || "");
  if (rem > 0.96) return String(whole + 1);
  if (q >= 10) return String(Math.round(q));
  let best = FRAC[0], bd = 9;
  for (const f of FRAC) { const d = Math.abs(f[0] - rem); if (d < bd) { bd = d; best = f; } }
  if (bd > 0.06) return (Math.round(q * 100) / 100).toString();
  return (whole ? whole : "") + best[1];
}
// One ingredient for display: name (sentence case) as the title, the amount as the subtitle, prep note muted.
// Number-less amounts ("pinch", "to taste") never scale.
const sentence = (t) => { t = String(t || "").trim(); return t ? t.charAt(0).toUpperCase() + t.slice(1) : ""; };
function ingLine(x, factor, portion = 1) {
  const name = sentence(x.name || x.food);
  if (!name) return { amt: "", name: x.display || x.raw || "", note: "", text: x.display || x.raw || "" };
  if (x.amount_text) return { amt: x.amount_text, name, note: x.note || "", text: `${name}${x.note ? `, ${x.note}` : ""}, ${x.amount_text}` };
  if (!x.parsed || x.quantity == null) return { amt: "", name: x.display || name, note: "", text: x.display || name };
  const q = x.quantity * factor * portion;
  let unit = q > 1 && x.unit_plural ? x.unit_plural : x.unit;
  if (x.size) unit = `(${x.size}) ${unit}`;
  const food = q > 1 && x.food_plural && !x.unit ? sentence(x.food_plural) : name;
  const amt = [fmtQty(q), unit].filter(Boolean).join(" ");
  return { amt, name: food, note: x.note || "", text: [amt, food.toLowerCase() === food ? food : food.charAt(0).toLowerCase() + food.slice(1)].filter(Boolean).join(" ") + (x.note ? `, ${x.note}` : "") };
}
const ingTitle = (l) => `${esc(l.name)}${l.note ? ` <span class="ing-note">${esc(l.note)}</span>` : ""}`;
const recipeImg = (r, size = "min") => (r && r.has_image ? `/img/${enc(r.id)}?size=${enc(size)}&v=${enc(r.image_v || "")}` : null);

// ------------------------------------------------------------------ RECIPES list
const rstate = { q: "", filter: "all", list: null, tags: [], sel: null, last: -1, shown: [] };
async function renderRecipes() {
  rstate.sel = null;
  app.innerHTML = topbar(`<button class="text-btn" id="btn-select">Select</button><button class="round-btn" id="btn-rmore" aria-label="More" aria-haspopup="menu">${ic("more")}</button><button class="round-btn" id="btn-add" aria-label="Add recipe">${ic("plus")}</button>`) +
    `<h1 class="title">All recipes</h1>
    <div class="search">${ic("search")}<input id="rq" placeholder="Search recipes" value="${esc(rstate.q)}" autocomplete="off"></div>
    <div class="chips" id="rchips"></div><div id="rlist">${loading()}</div><div class="sel-bar" id="sel-bar" hidden></div>`;
  bindTopbar();
  $("#btn-add").onclick = openAddRecipe;
  $("#btn-select").onclick = () => setSelect(!rstate.sel);
  $("#btn-rmore").onclick = () => popover($("#btn-rmore"), `<button data-a="diary">${ic("book")} Cooking diary</button>`, (el) => {
    $("[data-a=diary]", el).onclick = () => { closePop(); location.hash = "diary"; };
  });
  try { const d = await api("GET", "/api/recipes"); rstate.list = d.recipes; rstate.tags = d.tags; }
  catch (e) { $("#rlist").innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  drawRecipeChips();
  let t;
  $("#rq").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { rstate.q = e.target.value; drawRecipeList(); }, 120); };
  drawRecipeList();
}
function drawRecipeChips() {
  const cats = (state.cfg?.settings?.categories || []).filter((c) => rstate.list.some((r) => (r.categories || []).includes(c)));
  const uncat = rstate.list.some((r) => !(r.categories || []).length) && cats.length;
  const chips = [["all", "All"], ["fav", "♥ Favorites"], ...cats.map((c) => ["cat:" + c, c]), ...(uncat ? [["none", "Uncategorized"]] : [])];
  if (!chips.some(([k]) => k === rstate.filter)) rstate.filter = "all";
  $("#rchips").innerHTML = chips.map(([k, l]) => `<button class="filter ${rstate.filter === k ? "on" : ""}" data-f="${esc(k)}">${esc(l)}</button>`).join("");
  $$("#rchips [data-f]").forEach((b) => (b.onclick = () => { rstate.filter = b.dataset.f; $$("#rchips .filter").forEach((x) => x.classList.toggle("on", x === b)); drawRecipeList(); }));
}
function setSelect(on) {
  rstate.sel = on ? new Set() : null; rstate.last = -1;
  const b = $("#btn-select"); if (b) b.textContent = on ? "Cancel" : "Select";
  document.body.classList.toggle("selecting", !!on);
  drawRecipeList();
}
function drawRecipeList() {
  const box = $("#rlist");
  if (!box || !rstate.list) return;
  const q = rstate.q.trim().toLowerCase(), f = rstate.filter;
  const list = rstate.shown = rstate.list.filter((r) => (!q || r.name.toLowerCase().includes(q) || r.tags.some((x) => x.toLowerCase().includes(q))) &&
    (f === "all" || (f === "fav" ? r.favorite : f === "none" ? !(r.categories || []).length : f.startsWith("cat:") ? (r.categories || []).includes(f.slice(4)) : true)));
  drawSelBar();
  if (!rstate.list.length) {
    box.innerHTML = `<div class="empty"><div class="em">📖</div>No recipes yet.<br>Add one from a link or a screenshot.</div><button class="btn" id="r-first">${ic("plus")} Add your first recipe</button>`;
    $("#r-first").onclick = openAddRecipe; return;
  }
  if (!list.length) { box.innerHTML = `<div class="empty">No recipes match.</div>`; return; }
  const sel = rstate.sel;
  const mark = (r) => (sel ? `<span class="selc ${sel.has(r.slug) ? "on" : ""}" aria-hidden="true">${sel.has(r.slug) ? ic("check") : ""}</span>` : "");
  const pressed = (r) => (sel ? `aria-pressed="${sel.has(r.slug)}"` : "");
  const meta = (r) => `<div class="meta">${r.minutes ? `${ic("clock")}<span>${esc(r.minutes)} mins</span>` : ""}${r.minutes && r.rating ? '<i class="dotsep"></i>' : ""}${r.rating ? `<span class="star">★</span><span>${(+r.rating).toFixed(1)}</span>` : ""}${r.favorite ? ' <span class="heart-s">♥</span>' : ""}</div>`;
  box.innerHTML = `<div class="group recipe-list ${sel ? "selecting" : ""}">${list.map((r, i) => {
    const img = recipeImg(r);
    return `<button class="row ${sel && sel.has(r.slug) ? "sel" : ""}" data-slug="${esc(r.slug)}" data-i="${i}" ${pressed(r)}>${mark(r)}<div class="thumb" ${img ? bgStyle(img) : ""}>${img ? "" : "🍽️"}</div>
      <div class="main"><div class="a">${esc(r.name)}</div>${meta(r)}</div>${sel ? "" : `<span class="chev">${ic("chevR")}</span>`}</button>`;
  }).join("")}</div>
  <div class="recipe-grid ${sel ? "selecting" : ""}">${list.map((r, i) => {
    const img = recipeImg(r);
    return `<button class="rcard ${sel && sel.has(r.slug) ? "sel" : ""}" data-slug="${esc(r.slug)}" data-i="${i}" ${pressed(r)}><div class="img" ${img ? bgStyle(img) : ""}>${img ? "" : "🍽️"}${mark(r)}${r.favorite ? '<span class="heart">♥</span>' : ""}</div>
      <div class="body"><div class="n">${esc(r.name)}</div>${meta(r)}</div></button>`;
  }).join("")}</div>`;
  box.onclick = (e) => {
    const b = e.target.closest("[data-slug]"); if (!b) return;
    if (!rstate.sel) return openRecipe(b.dataset.slug);
    const i = +b.dataset.i, slug = b.dataset.slug;
    if (e.shiftKey && rstate.last >= 0) {
      const [lo, hi] = [Math.min(rstate.last, i), Math.max(rstate.last, i)];
      rstate.shown.slice(lo, hi + 1).forEach((r) => rstate.sel.add(r.slug));
    } else if (rstate.sel.has(slug)) rstate.sel.delete(slug); else rstate.sel.add(slug);
    rstate.last = i;
    drawRecipeList();
  };
}
const SEL = { arm: null, timer: 0, picking: false, cats: new Set(), busy: false };
function drawSelBar() {
  const bar = $("#sel-bar");
  if (!bar) return;
  if (!rstate.sel) { bar.hidden = true; bar.innerHTML = ""; SEL.picking = false; return; }
  bar.hidden = false;
  const n = rstate.sel.size, cats = state.cfg?.settings?.categories || [];
  if (SEL.picking) {
    bar.innerHTML = `<div class="sel-cats" role="group" aria-label="Categories">${cats.map((c) => `<button class="filter sm ${SEL.cats.has(c) ? "on" : ""}" data-sc="${esc(c)}" aria-pressed="${SEL.cats.has(c)}">${esc(c)}</button>`).join("")}</div>
      <div class="sel-row"><span class="muted">Set for ${esc(plural(n, "recipe"))}</span><span class="grow"></span><button class="text-btn" id="sc-cancel">Cancel</button><button class="pill-btn ink" id="sc-apply" ${n ? "" : "disabled"}>Apply</button></div>`;
    $$("[data-sc]", bar).forEach((b) => (b.onclick = () => { const c = b.dataset.sc; SEL.cats.has(c) ? SEL.cats.delete(c) : SEL.cats.add(c); drawSelBar(); }));
    $("#sc-cancel").onclick = () => { SEL.picking = false; drawSelBar(); };
    $("#sc-apply").onclick = async () => {
      const slugs = [...rstate.sel], names = cats.filter((c) => SEL.cats.has(c));
      try {
        await api("POST", "/api/recipes/bulk", { slugs, categories: names });
        toast(names.length ? `${plural(slugs.length, "recipe")} · ${names.join(", ")}` : `Cleared categories on ${plural(slugs.length, "recipe")}`);
        SEL.picking = false; renderRecipes();
      } catch (e) { fail(e); }
    };
    return;
  }
  bar.innerHTML = `<div class="sel-row"><b>${esc(n)} selected</b><button class="text-btn" id="sel-all">Select all</button><span class="grow"></span>
    <button class="text-btn" id="sel-cat" ${n ? "" : "disabled"}>Set category</button>
    <button class="pill-btn ${SEL.arm ? "danger" : ""}" id="sel-del" ${n ? "" : "disabled"}>${SEL.arm ? `Tap again to delete ${esc(n)}` : "Delete"}</button>
    <button class="text-btn strong" id="sel-done">Done</button></div>`;
  $("#sel-all").onclick = () => { rstate.shown.forEach((r) => rstate.sel.add(r.slug)); drawRecipeList(); };
  $("#sel-done").onclick = () => setSelect(false);
  $("#sel-cat").onclick = () => {
    const chosen = rstate.list.filter((r) => rstate.sel.has(r.slug));
    SEL.cats = new Set(cats.filter((c) => chosen.length && chosen.every((r) => (r.categories || []).includes(c))));
    SEL.picking = true; drawSelBar();
  };
  $("#sel-del").onclick = async () => {
    if (SEL.busy || !n) return;
    if (!SEL.arm) {
      SEL.arm = true; drawSelBar();
      clearTimeout(SEL.timer); SEL.timer = setTimeout(() => { SEL.arm = null; drawSelBar(); }, 4000);
      return;
    }
    clearTimeout(SEL.timer); SEL.arm = null; SEL.busy = true;
    const slugs = [...rstate.sel], btn = $("#sel-del");
    let done = 0;
    try {
      for (const slug of slugs) {
        if (btn) btn.textContent = `Deleting ${done + 1} of ${slugs.length}…`;
        await api("DELETE", `/api/recipe/${encodeURIComponent(slug)}`);
        done++;
      }
    } catch (e) { fail(e); }
    SEL.busy = false;
    if (done) toast(`Deleted ${plural(done, "recipe")}`);
    document.body.classList.remove("selecting");
    renderRecipes();
  };
}

// ------------------------------------------------------------------ cooking diary
const stars = (n) => (n ? "★".repeat(n) + "☆".repeat(5 - n) : "");
const dayHead = (iso) => { const d = Math.round((today() - parseISO(iso)) / 864e5); return d === 0 ? "Today" : d === 1 ? "Yesterday" : d < 7 ? fmt(parseISO(iso), { weekday: "long" }) : fmt(parseISO(iso), { month: "short", day: "numeric", year: parseISO(iso).getFullYear() === today().getFullYear() ? undefined : "numeric" }); };
function diaryTimeline(entries, { showRecipe = true } = {}) {
  let html = "", last = "";
  for (const e of entries) {
    const h = dayHead(e.date);
    if (h !== last) { html += `<div class="dy-h">${esc(h)}</div>`; last = h; }
    const img = e.photo || (showRecipe ? e.recipe_image : null);
    const time = (e.cooked_at || "").slice(11, 16);
    html += `<button class="dy-row" data-dslug="${esc(e.slug || "")}" data-did="${esc(e.id)}">${img ? `<img class="dy-img" src="${esc(img)}" alt="">` : `<span class="dy-img emo">${e.kind === "adjusted" ? "✏️" : e.kind === "note" ? "📝" : "🍽️"}</span>`}
      <span class="main">${showRecipe ? `<span class="a">${esc(e.recipe_name || "Recipe")}</span>` : ""}<span class="b">${esc(e.kind === "cooked" ? `Cooked${time ? ` at ${time}` : ""}` : e.kind === "adjusted" ? "Adjusted" : "Note")}${e.rating ? ` · <span class="stars" aria-label="${esc(e.rating)} stars">${stars(e.rating)}</span>` : ""}</span>
      ${e.note ? `<span class="dy-note">${esc(e.note.split("\n")[0])}</span>` : ""}</span></button>`;
  }
  return `<div class="dy">${html}</div>`;
}
function bindDiaryTimeline(box) {
  $$(".dy-row[data-dslug]", box).forEach((b) => (b.onclick = () => { if (b.dataset.dslug) { state.diaryFocus = true; openRecipe(b.dataset.dslug); } }));
}
async function renderDiary() {
  state.tab = "recipes"; renderTabs();
  const f = state.diaryFilter || "all";
  app.innerHTML = `${topbar(`<button class="round-btn left" id="dy-back" aria-label="Back">${ic("chevL")}</button><span class="grow"></span>`)}
    <h1 class="title">Cooking diary</h1>
    <div class="chips" id="dy-f">${[["all", "All"], ["top", "★ 4+"], ["notes", "Has notes"]].map(([k, l]) => `<button class="filter ${f === k ? "on" : ""}" data-f="${k}">${esc(l)}</button>`).join("")}</div>
    <div id="dy-list">${loading()}</div>`;
  bindTopbar();
  $("#dy-back").onclick = () => (history.length > 1 ? history.back() : go("home"));
  $$("#dy-f [data-f]").forEach((b) => (b.onclick = () => { state.diaryFilter = b.dataset.f; renderDiary(); }));
  try {
    const d = await api("GET", `/api/diary?filter=${enc(f)}&limit=200`);
    const box = $("#dy-list"); if (!box) return;
    box.innerHTML = (d.entries || []).length ? `<div class="home-card">${diaryTimeline(d.entries)}</div>` : `<div class="empty"><div class="em">📔</div>Nothing here yet. Mark a meal as cooked and it shows up here.</div>`;
    bindDiaryTimeline(box);
  } catch (e) { fail(e); }
}
// "How was it?": stars, a note and a photo, right after cooking (inline, never a modal)
function howWasItHtml() {
  return `<div class="how" id="how"><div class="how-h"><b>How was it?</b><button class="link-btn" id="how-skip">Skip</button></div>
    <div class="how-stars" role="radiogroup" aria-label="Rating">${[1, 2, 3, 4, 5].map((n) => `<button data-star="${n}" role="radio" aria-checked="false" aria-label="${n} star${n > 1 ? "s" : ""}">☆</button>`).join("")}</div>
    <textarea id="how-note" rows="2" maxlength="2000" placeholder="What would you change next time?"></textarea>
    <div class="how-acts"><label class="pill-btn how-photo" id="how-drop">${ic("camera")} <span>Add photo</span><input type="file" accept="image/*" id="how-file" hidden></label><span class="grow"></span><button class="btn small" id="how-save">Save</button></div></div>`;
}
function bindHowWasIt(diaryId, done) {
  let rating = 0, photo = null;
  $$("#how [data-star]").forEach((b) => (b.onclick = () => {
    rating = +b.dataset.star;
    $$("#how [data-star]").forEach((x) => { const on = +x.dataset.star <= rating; x.textContent = on ? "★" : "☆"; x.classList.toggle("on", on); x.setAttribute("aria-checked", String(+x.dataset.star === rating)); });
  }));
  const take = async (files) => { const f = files[0]; if (!f) return; photo = await shrink(f); $("#how-drop span").textContent = "Photo added ✓"; };
  $("#how-file").onchange = (e) => take([...e.target.files]);
  dropZone($("#how-drop"), take);
  $("#how-skip").onclick = () => { state.justCooked = null; done(false); };
  $("#how-save").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      const note = $("#how-note").value.trim();
      if (rating || note) await api("PATCH", `/api/diary/${enc(diaryId)}`, { ...(rating ? { rating } : {}), note });
      if (photo) await api("POST", `/api/diary/${enc(diaryId)}/photo`, { data: photo });
      state.justCooked = null; toast("Saved to your cooking diary"); done(true);
    } catch (x) { fail(x); e.currentTarget.disabled = false; }
  };
}
function yourNotesHtml(rec) {
  const list = rec.diary || [];
  return `<div class="section-h" id="rd-diary"><h2>Your notes</h2><button class="link-btn" id="rd-note-add">Add a note</button></div>
    <div id="rd-note-form"></div>
    ${list.length ? `<div class="home-card">${diaryTimeline(list, { showRecipe: false })}</div>` : `<p class="hint">Nothing yet. Rate it after you cook, or add a note any time.</p>`}`;
}
function bindYourNotes(rec, slug) {
  $("#rd-note-add").onclick = () => {
    const box = $("#rd-note-form");
    box.innerHTML = `<form class="how" id="note-f"><textarea id="note-t" rows="2" maxlength="2000" placeholder="A note for next time" required></textarea><div class="how-acts"><span class="grow"></span><button type="button" class="link-btn" id="note-x">Cancel</button><button class="btn small" type="submit">Save note</button></div></form>`;
    $("#note-t").focus();
    $("#note-x").onclick = () => { box.innerHTML = ""; };
    $("#note-f").onsubmit = async (e) => {
      e.preventDefault();
      try { await api("POST", "/api/diary", { slug, note: $("#note-t").value }); toast("Note saved"); renderRecipe(slug); } catch (x) { fail(x); }
    };
  };
}
// ------------------------------------------------------------------ "Make it my way": AI adjustments shown as a diff
const ADJ_CHIPS = ["Spicier", "Milder", "Less salt", "Healthier", "Dairy-free", "Gluten-free", "Vegetarian", "Kid-friendly", "Faster"];
function openAdjust(rec) {
  const box = $("#rd-adjust"); if (!box) return;
  if (!state.cfg.ai_key) {
    box.innerHTML = `<div class="adj"><b>Make it my way</b><p class="hint">Adjusting a recipe needs AI (Settings → AI recipe import). You can always edit it yourself.</p><button class="pill-btn" id="adj-edit">${ic("edit")} Edit recipe</button></div>`;
    $("#adj-edit").onclick = () => { location.hash = "edit/" + encodeURIComponent(rec.slug); };
    return;
  }
  const picked = new Set();
  box.innerHTML = `<div class="adj"><div class="how-h"><b>Make it my way</b><button class="link-btn" id="adj-x">Close</button></div>
    <div class="chips wrap" id="adj-chips">${ADJ_CHIPS.map((c) => `<button class="filter sm" data-c="${esc(c)}" aria-pressed="false">${esc(c)}</button>`).join("")}</div>
    <input id="adj-text" maxlength="200" placeholder="e.g. spicier, and use chicken thighs">
    <div class="how-acts"><span class="grow"></span><button class="btn small" id="adj-go">${ic("sparkle")} Adjust</button></div><div id="adj-out"></div></div>`;
  $("#adj-x").onclick = () => { box.innerHTML = ""; };
  $$("#adj-chips [data-c]").forEach((b) => (b.onclick = () => { picked.has(b.dataset.c) ? picked.delete(b.dataset.c) : picked.add(b.dataset.c); b.classList.toggle("on"); b.setAttribute("aria-pressed", String(picked.has(b.dataset.c))); }));
  $("#adj-go").onclick = async (e) => {
    const request = [...picked, $("#adj-text").value.trim()].filter(Boolean).join(", ").toLowerCase();
    if (!request) return toast("Pick a change or type one");
    const btn = e.currentTarget; btn.disabled = true; btn.textContent = "Adjusting…";
    try {
      const p = await api("POST", `/api/recipe/${encodeURIComponent(rec.slug)}/adjust`, { request });
      const line = (x, key) => `<li class="df-${esc(x.status)}">${x.status === "added" ? "<b>+</b> " : ""}${x.status === "removed" ? `<s>${esc(x.was)}</s>` : esc(x[key])}${x.status === "changed" ? ` <span class="df-was">was: ${esc(x.was)}</span>` : ""}${x.reason ? ` <span class="df-why">${esc(x.reason)}</span>` : ""}</li>`;
      $("#adj-out").innerHTML = `<div class="diff"><p><b>${esc(p.summary)}</b></p><div class="group-label">Ingredients</div><ul>${p.ingredients.map((x) => line(x, "line")).join("")}</ul>
        <div class="group-label">Steps</div><ol>${p.steps.map((x) => line(x, "text")).join("")}</ol></div>
        <div class="how-acts"><button class="link-btn" id="adj-discard">Discard</button><span class="grow"></span><button class="btn small" id="adj-save">Save as my version</button></div>`;
      $("#adj-discard").onclick = () => { box.innerHTML = ""; };
      $("#adj-save").onclick = async (ev) => {
        ev.currentTarget.disabled = true;
        try { const d = await api("POST", `/api/recipe/${encodeURIComponent(rec.slug)}/adjust/save`, { ...p }); toast("Saved as your version · earlier text kept in Versions"); location.replace("#recipe/" + encodeURIComponent(d.slug)); renderRecipe(d.slug); }
        catch (x) { fail(x); ev.currentTarget.disabled = false; }
      };
    } catch (x) { fail(x); } finally { btn.disabled = false; btn.innerHTML = `${ic("sparkle")} Adjust`; }
  };
}
async function openVersions(rec) {
  let v;
  try { v = await api("GET", `/api/recipe/${encodeURIComponent(rec.slug)}/versions`); } catch (e) { return fail(e); }
  openSheet("Versions", `${(v.versions || []).length ? `<div class="group">${v.versions.map((x) => `<div class="row flush"><div class="main"><div class="a">${esc(x.label)}</div><div class="b">${esc(fmt(new Date(x.at), { month: "short", day: "numeric" }))} · ${esc(plural(x.ingredients, "ingredient"))} · ${esc(plural(x.steps, "step"))}</div></div><button class="pill-btn" data-n="${esc(x.n)}">Go back</button></div>`).join("")}</div>
    <p class="hint">Going back keeps the current text as a version too, so nothing is lost.</p>` : `<p class="hint">No earlier versions yet. They're kept when you use “Make it my way”.</p>`}`, {
    onMount() {
      $$("[data-n]").forEach((b) => (b.onclick = async () => {
        try { const d = await api("POST", `/api/recipe/${encodeURIComponent(rec.slug)}/versions/${enc(b.dataset.n)}/restore`); closeSheet(); toast("Restored"); renderRecipe(d.slug); } catch (e) { fail(e); }
      }));
    },
  });
}

// ------------------------------------------------------------------ RECIPE page
const R = { rec: null, servings: 0, style: "classic", guide: null };
function openRecipe(slug) { location.hash = "recipe/" + encodeURIComponent(slug); }
// "Source: Serious Eats" (a link) or "Added by you"
function sourceLine(rec) {
  const u = safeUrl(rec.source_url);
  if (u) {
    let host = "";
    try { host = new URL(u).hostname.replace(/^www\./, ""); } catch (_) {}
    return `Source: <a ${extLink(u)}>${esc(host || "original recipe")}</a>`;
  }
  return "Added by you";
}
async function renderRecipe(slug) {
  state.tab = "recipes"; renderTabs();
  app.innerHTML = loading();
  let rec;
  try { rec = await api("GET", `/api/recipe/${encodeURIComponent(slug)}`); }
  catch (e) { app.innerHTML = `${topbar(`<button class="round-btn left" id="rd-err-back">${ic("chevL")}</button>`)}<div class="banner">${esc(e.message)}</div>`; bindTopbar(); $("#rd-err-back").onclick = () => go("recipes"); return; }
  R.rec = rec; R.servings = rec.servings || state.cfg.household?.people || 4; R.guide = null; R.showOrig = false;
  R.style = state.cfg.settings.recipe_style === "steps" ? "steps" : "classic";
  const img = recipeImg(rec, "full");
  const src = sourceLine(rec);
  app.innerHTML = `${storageBar()}<div class="rd rd2 fade-in">
    <div class="rd-band"><button class="round-btn back" id="rd-back" aria-label="Back">${ic("chevL")}</button><span class="grow"></span><button class="round-btn" id="rd-menu" aria-label="More" aria-haspopup="menu">${ic("more")}</button></div>
    <div class="rd-plate-row">
      <button class="round-btn side" id="rd-share2" aria-label="Share">${ic("share")}</button>
      <button class="rd-plate ${img ? "" : "ph"}" id="rd-img" ${img ? bgStyle(img) : ""} aria-label="Change photo">${img ? "" : `<span>${esc(rec.ingredients?.[0]?.emoji || "🍽️")}</span>`}</button>
      <button class="round-btn side fav ${rec.favorite ? "on" : ""}" id="rd-fav" aria-label="Favorite" aria-pressed="${!!rec.favorite}">${rec.favorite ? "♥" : "♡"}</button>
    </div>
    <div class="rd-head">
      <h1>${esc(rec.name)}</h1>
      ${src ? `<div class="rd-src">${src}</div>` : ""}
      <div class="rd-meta">
        ${rec.minutes ? `<span class="mp">${ic("clock")} ${esc(rec.minutes)} mins</span>` : ""}
        <span class="mp">${ic("chef")} ${esc(rec.difficulty)}</span>
        <span class="mp stepper">${ic("users")}<button data-s="-1" aria-label="Fewer servings">−</button><b id="rd-serv">${fmtQty(R.servings)}</b><button data-s="1" aria-label="More servings">+</button></span>
      </div>
      ${(rec.categories || []).length ? `<div class="cat-pills">${rec.categories.map((c) => `<span class="cat-pill">${esc(c)}</span>`).join("")}</div>` : ""}
      ${rec.cook_entry ? `<div class="cook-due"><span>On the plan ${esc(rec.cook_entry.today ? "today" : dayName(rec.cook_entry.date).toLowerCase())}</span><button class="cook-pill" id="rd-cooked">✓ Mark as cooked</button></div>` : ""}
    </div>
    <div class="rd-sheet"><div class="grabber" aria-hidden="true"></div>
      ${state.justCooked && state.justCooked.slug === rec.slug ? howWasItHtml() : ""}
      ${rec.description ? `<p class="desc">${esc(rec.description)}</p>` : ""}
      <div class="seg" id="rd-style"><button data-v="classic">Classic</button><button data-v="steps">Step-by-step</button></div>
      <div id="rd-content"></div>
      <div class="toolbar" style="margin-top:18px">
        <button class="pill-btn" id="rd-plan">${ic("cal")} Plan it</button>
        ${rec.cook_entry ? "" : `<button class="pill-btn" id="rd-cooked">${ic("check")} Mark as cooked</button>`}
        <button class="pill-btn" id="rd-adj">${ic("sparkle")} Make it my way</button>
      </div>
      <div id="rd-adjust"></div>
      ${yourNotesHtml(rec)}
      <div id="rd-miss"></div>
      <div class="cta-bar"><button class="btn" id="rd-cook">${ic("play")} Start cooking</button></div>
    </div></div>`;
  $("#rd-share2").onclick = () => openRecipeExport();
  $("#rd-menu").onclick = () => popover($("#rd-menu"), `<button data-a="edit">${ic("edit")} Edit</button><button data-a="missing">${ic("cart")} Add missing to list</button><button data-a="share">${ic("share")} Share & export</button>${rec.versions ? `<button data-a="versions">${ic("refresh")} Versions</button>` : ""}`, (el) => {
    $$("[data-a]", el).forEach((b) => (b.onclick = () => { closePop(); ({ edit: () => { location.hash = "edit/" + encodeURIComponent(slug); }, missing: addMissing, share: openRecipeExport, versions: () => openVersions(rec) })[b.dataset.a](); }));
  });
  $("#rd-adj").onclick = () => openAdjust(rec);
  bindYourNotes(rec, slug);
  if ($("#how")) bindHowWasIt(state.justCooked.diary_id, () => renderRecipe(slug));
  if (state.diaryFocus) { state.diaryFocus = false; setTimeout(() => $("#rd-diary")?.scrollIntoView({ block: "start" }), 50); }
  $("#rd-back").onclick = () => (history.length > 1 ? history.back() : go("recipes"));
  $("#rd-fav").onclick = async (e) => {
    const on = !R.rec.favorite, btn = e.currentTarget;
    try { await api("POST", `/api/recipe/${encodeURIComponent(slug)}/favorite`, { favorite: on }); R.rec.favorite = on; btn.classList.toggle("on", on); btn.textContent = on ? "♥" : "♡"; } catch (x) { fail(x); }
  };
  $("#rd-img").onclick = () => openImagePicker({ kind: "recipe", slug, name: rec.name, after: () => renderRecipe(slug) });
  $$(".stepper [data-s]").forEach((b) => (b.onclick = () => { R.servings = Math.max(0.5, R.servings + +b.dataset.s * (R.servings < 2 ? 0.5 : 1)); $("#rd-serv").textContent = fmtQty(R.servings); drawContent(); }));
  $$("#rd-style button").forEach((b) => (b.onclick = () => { R.style = b.dataset.v; drawContent(); }));
  $("#rd-cook").onclick = () => ((R.rec.missing || []).length ? showMissing() : startCook());
  $("#rd-plan").onclick = () => planRecipe(rec);

  $("#rd-cooked").onclick = async (e) => {
    const btn = e.currentTarget; btn.disabled = true;
    const body = rec.cook_entry ? { plan_id: rec.cook_entry.id } : { servings: R.servings };
    try { await markCooked(rec.slug, body, () => { if (location.hash === "#recipe/" + encodeURIComponent(slug)) renderRecipe(slug); }); }
    catch (x) { fail(x); btn.disabled = false; }
  };
  drawContent();
  drawCookReady();
}
const factor = () => (R.rec.servings ? R.servings / R.rec.servings : 1);
function pantryTag(x) {
  if (!x.pantry) return "";
  const d = x.pantry.days_left;
  return d != null && d <= 3 ? `<span class="pill soon">Use soon</span>` : `<span class="pill ok">In ${esc(x.pantry.location)}</span>`;
}
function ingPic(x) {
  const src = safeUrl(x.img, true);
  return `<div class="pic" data-ing="${esc(x.food || "")}">${src ? `<img src="${esc(src)}" alt="" loading="lazy" data-fb="${esc(x.emoji)}">` : esc(x.emoji)}</div>`;
}
async function drawContent() {
  $$("#rd-style button").forEach((b) => b.classList.toggle("on", b.dataset.v === R.style));
  const box = $("#rd-content"), rec = R.rec, f = factor();
  if (R.style === "classic") {
    let sec = null, html = `<div class="section-h" style="margin-top:20px"><h2>Ingredients (${rec.ingredients.length})</h2></div><div class="group ing">`;
    rec.ingredients.forEach((x) => {
      if (x.section && x.section !== sec) { sec = x.section; html += `</div><div class="group-label">${esc(sec)}</div><div class="group ing">`; }
      const l = ingLine(x, f);
      html += `<div class="row ing-row">${ingPic(x)}<div class="main"><div class="a">${esc(l.name)}</div>${l.note ? `<div class="note">${esc(l.note)}</div>` : ""}</div><div class="amt-col">${l.amt ? `<span class="amt">${esc(l.amt)}</span>` : ""}${pantryTag(x)}</div></div>`;
    });
    html += `</div><div class="section-h"><h2>Instructions</h2><span class="sh-actions">${rec.original ? `<button class="link-btn" id="rd-orig" aria-pressed="${!!R.showOrig}">${R.showOrig ? "Show reworded" : "Show original"}</button>` : ""}<button class="pill-btn sm" id="rd-reword">${ic("sparkle")} Reword with AI</button></span></div>`;
    if (R.showOrig && rec.original) {
      html += `<div class="orig-box"><div class="group-label">Original ingredients</div><ul class="orig-list">${rec.original.ingredients.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
        <div class="group-label">Original steps</div>${rec.original.steps.map((t, n) => `<div class="step-card"><div class="num">Step ${n + 1}</div><div class="txt">${esc(t)}</div></div>`).join("")}</div>`;
    } else rec.steps.forEach((s, n) => { html += `<div class="step-card">${s.title ? `<div class="num">${esc(s.title)}</div>` : `<div class="num">Step ${n + 1}</div>`}<div class="txt">${esc(s.text)}</div></div>`; });
    box.innerHTML = html;
    $("#rd-orig") && ($("#rd-orig").onclick = () => { R.showOrig = !R.showOrig; drawContent(); });
    $("#rd-reword").onclick = async (e) => {
      if (!state.cfg.ai_key) return openSetupSection("ai", "AI recipe import", reloadCfg);
      const btn = e.currentTarget; btn.disabled = true; btn.textContent = "Rewording…";
      const slug = rec.slug;
      try {
        const r = await api("POST", `/api/recipe/${encodeURIComponent(slug)}/polish`);
        R.rec = { ...R.rec, ...r }; R.guide = null; R.showOrig = false; drawContent();
        toast("Reworded · Show original", "Undo", async () => {
          try { const u = await api("POST", `/api/recipe/${encodeURIComponent(slug)}/restore-original`); R.rec = { ...R.rec, ...u }; R.guide = null; drawContent(); toast("Original text restored"); } catch (x) { fail(x); }
        });
      } catch (x) { fail(x); btn.disabled = false; btn.innerHTML = `${ic("sparkle")} Reword with AI`; }
    };
  } else {
    if (!R.guide) {
      box.innerHTML = state.cfg.ai_key ? `<div class="importing"><div class="pot">✨</div><div class="stage">Arranging the steps for your kitchen…</div><div class="muted small">First time only, about 10–20 seconds. After that it's instant.</div></div>` : loading();
      try { R.guide = await api("GET", `/api/recipe/${encodeURIComponent(rec.slug)}/guided${R.guideAi ? "?ai=1" : ""}`); }
      catch (e) { box.innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
    }
    const g = R.guide;
    let html = `<div class="section-h" style="margin-top:20px"><h2>Step by step</h2><span class="muted" style="font-size:13px">${g.source === "ai" ? "✨ AI-arranged" : "Auto-arranged"} · ${esc(state.cfg.settings.stove)} stove</span></div>`;
    g.steps.forEach((s, n) => {
      const uses = s.ingredients.map((u) => { const x = rec.ingredients[u.i]; if (!x) return ""; const l = ingLine(x, f, u.portion); return `<span class="use">${esc(x.emoji)} <b>${esc(l.amt)}</b> ${esc(l.name)}</span>`; }).join("");
      html += `<div class="step-card"><div class="num">${n + 1}. ${esc(s.title || "")}</div><div class="txt">${esc(s.text)}</div>
        ${uses ? `<div class="uses">${uses}</div>` : ""}
        <div class="badges">${s.temperature ? `<span class="badge2">🌡️ ${esc(s.temperature)}</span>` : ""}${s.heat ? `<span class="badge2">🔥 ${esc(s.heat)}</span>` : ""}${s.timer_sec ? `<span class="badge2 blue">⏱ ${esc(s.timer_label || fmtDur(s.timer_sec))}</span>` : ""}</div>
        ${s.tip ? `<p class="hint" style="margin:8px 0 0">${esc(s.tip)}</p>` : ""}</div>`;
    });
    if (g.tips?.length) html += `<div class="group" style="padding:14px 16px"><b>Tips</b><ul style="margin:6px 0 0;padding-left:18px;color:var(--sub)">${g.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>`;
    if (g.source !== "ai") html += `<div class="nudge" id="rd-ai" style="margin-top:14px"><span class="ic bg-indigo">${ic("sparkle")}</span><span><b>Make it smarter with AI</b><small>${state.cfg.ai_key ? `Reorders everything for your ${esc(state.cfg.settings.stove)} stove, with exact timing. Usually under 1¢.` : "Add your OpenAI key in Settings → AI recipe import."}</small></span></div>`;
    else html += `<button class="pill-btn" id="rd-ai-redo" style="margin-top:8px">${ic("refresh")} Re-do with AI</button>`;
    box.innerHTML = html;
    $("#rd-ai") && ($("#rd-ai").onclick = async () => {
      if (!state.cfg.ai_key) return openSetupSection("ai", "AI recipe import", reloadCfg);
      box.insertAdjacentHTML("beforeend", loading());
      try { R.guide = await api("GET", `/api/recipe/${encodeURIComponent(rec.slug)}/guided?ai=1`); R.guideAi = true; drawContent(); } catch (e) { fail(e); drawContent(); }
    });
    $("#rd-ai-redo") && ($("#rd-ai-redo").onclick = async () => { try { R.guide = await api("GET", `/api/recipe/${encodeURIComponent(rec.slug)}/guided?ai=1&refresh=1`); drawContent(); } catch (e) { fail(e); } });
  }
  $$("#rd-content [data-ing]").forEach((p) => p.dataset.ing && (p.onclick = () => openImagePicker({ kind: "ingredient", name: p.dataset.ing, after: () => drawContent() })));
}
function fmtDur(sec) { const m = Math.round(sec / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60 ? (m % 60) + " min" : ""}` : `${m} min`; }
async function addMissing() {
  const f = factor();
  const missing = R.rec.ingredients.filter((x) => !x.pantry && (x.food || x.display));
  if (!missing.length) return toast("You have everything in your inventory 🎉");
  openSheet("Add to shopping list", `<p class="hint" style="margin:0 4px 10px">Untick anything you already have.</p>
    <div class="group">${missing.map((x) => { const l = ingLine(x, f); return `<label class="row"><span class="emo">${esc(x.emoji)}</span><div class="main"><div class="a">${ingTitle(l)}</div>${l.amt ? `<div class="b">${esc(l.amt)}</div>` : ""}</div><input type="checkbox" checked data-t="${esc(l.text)}" style="width:22px;height:22px;accent-color:var(--tint)"></label>`; }).join("")}</div>
    <div style="height:14px"></div><button class="btn" id="am-go">${ic("cart")} Add to list</button>`, {
    onMount() { $("#am-go").onclick = async () => {
      const items = $$("[data-t]").filter((c) => c.checked).map((c) => c.dataset.t);
      try { const r = await api("POST", `/api/recipe/${encodeURIComponent(R.rec.slug)}/to-list`, { items, list_id: state.listId }); closeSheet(); toast(`Added ${r.added} to your list`, "View", () => go("list")); } catch (e) { fail(e); }
    }; },
  });
}
async function planRecipe(rec) {
  // one tap per day: shows the coming days with what's planned, assigning replaces that day's dinner
  const H = horizon(), days = Array.from({ length: H }, (_, i) => isoDate(addDays(today(), i)));
  openSheet("Plan this recipe", `<div id="pr-days">${loading()}</div>
    <p class="hint">Scaled to ${esc(state.cfg.household?.people || 2)} people. Missing ingredients go straight onto your shopping list.</p>`);
  let plan = [];
  try { plan = (await api("GET", `/api/plan?start=${enc(days[0])}&end=${enc(days[days.length - 1])}`)).entries || []; } catch (_) {}
  const box = $("#pr-days"); if (!box) return;
  const type = PLAN_TYPES[0];
  box.innerHTML = `<div class="group">${days.map((d) => {
    const e = plan.find((x) => x.date === d && x.entry_type === type);
    return `<button class="row flush" data-d="${esc(d)}"><div class="main"><div class="a">${esc(dayName(d))} <span class="muted">${esc(shortDate(d))}</span></div><div class="b">${e ? `Replaces ${esc(entryName(e))}` : "Free"}</div></div>${e ? "" : `<span class="pill ok">Free</span>`}</button>`;
  }).join("")}</div>`;
  $$("#pr-days [data-d]").forEach((b) => (b.onclick = async () => {
    $$("#pr-days [data-d]").forEach((x) => (x.disabled = true));
    try { await assignRecipe(b.dataset.d, rec.id, type); closeSheet(); } catch (e) { fail(e); $$("#pr-days [data-d]").forEach((x) => (x.disabled = false)); }
  }));
}

// ---------- cook readiness: Start cooking waits until the list items for this recipe are bought or marked "have"
function drawCookReady() {
  const btn = $("#rd-cook"), box = $("#rd-miss");
  if (!btn || !box) return;
  const miss = R.rec.missing || [];
  if (!miss.length) {
    btn.className = "btn"; btn.innerHTML = `${ic("play")} Start cooking`;
    box.innerHTML = "";
    return;
  }
  btn.className = "btn sec miss-btn"; btn.innerHTML = `${ic("cart")} Missing ${miss.length} ingredient${miss.length === 1 ? "" : "s"}`;
  box.innerHTML = `<div class="miss-card" id="miss-card">
    <div class="miss-h"><b>Still on your shopping list</b><span>Tick anything you already have.</span></div>
    <div class="group">${miss.map((m) => `<div class="row flush miss-row"><button class="miss-main" data-mid="${esc(m.id)}"><span class="check sq">${ic("check")}</span><span class="main"><span class="a">${esc(m.text)}</span></span></button>${m.food ? `<button class="link-btn sm" data-always="${esc(m.food)}">Always have</button>` : ""}</div>`).join("")}</div>
    <div class="miss-acts"><button class="btn small" id="miss-all">${ic("check")} I have them all</button><button class="link-btn" id="miss-anyway">Cook anyway</button></div></div>`;
  $$("#rd-miss [data-always]").forEach((b) => (b.onclick = () => alwaysHave(b.dataset.always, async () => {
    try { const r = await api("GET", `/api/recipe/${encodeURIComponent(R.rec.slug)}`); R.rec.missing = r.missing; drawCookReady(); } catch (_) {}
  })));
  $$("#rd-miss [data-mid]").forEach((btn2) => (btn2.onclick = async () => {
    const b = btn2.closest(".miss-row");
    if (b.classList.contains("done")) return;
    const id = btn2.dataset.mid, m = miss.find((x) => String(x.id) === id);
    b.classList.add("done"); $(".check", b).classList.add("on");
    try {
      await api("POST", `/api/list/items/${enc(id)}/have`);
      R.rec.missing = (R.rec.missing || []).filter((x) => String(x.id) !== id);
      const left = R.rec.missing.length;
      btn.innerHTML = left ? `${ic("cart")} Missing ${left} ingredient${left === 1 ? "" : "s"}` : btn.innerHTML;
      setTimeout(() => { drawCookReady(); if (!left) toast("Everything's here. Ready to cook!"); }, left ? 250 : 350);
      if (left) toast(`${m ? m.text : "Item"} · you have it`, "Undo", () => undoHave([m]));
    } catch (e) { b.classList.remove("done"); $(".check", b).classList.remove("on"); fail(e); }
  }));
  $("#miss-all").onclick = async (e) => {
    const all = (R.rec.missing || []).slice();
    e.currentTarget.disabled = true;
    try {
      const r = await api("POST", `/api/recipe/${encodeURIComponent(R.rec.slug)}/have-all`);
      R.rec.missing = [];
      drawCookReady();
      toast(`Marked ${plural((r && r.count) || all.length, "item")} as have`, "Undo", () => undoHave(all));
    } catch (x) { fail(x); e.currentTarget.disabled = false; }
  };
  $("#miss-anyway").onclick = () => startCook();
}
async function undoHave(items) {
  try {
    for (const m of items.filter(Boolean)) await api("PATCH", `/api/list/items/${enc(m.id)}`, { checked: false });
    if (!R.rec) return;
    const ids = new Set((R.rec.missing || []).map((x) => String(x.id)));
    R.rec.missing = [...(R.rec.missing || []), ...items.filter((m) => m && !ids.has(String(m.id)))];
    drawCookReady();
  } catch (e) { fail(e); }
}
function showMissing() {
  const card = $("#miss-card");
  if (!card) return startCook();
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
}

// ---------- Share & export: print/PDF in several sizes, send, copy, download
const PRINT_SIZES = [["card35", "Index card 3×5"], ["card46", "Index card 4×6"], ["card57", "Card 5×7"], ["half", "Half page"], ["letter", "Full page"], ["a4", "A4"]];
function recipeExportUrls(slug, o) {
  const s = enc(o.servings || "");
  return {
    print: `/print/recipe/${enc(slug)}?size=${enc(o.size)}&servings=${s}&style=${o.steps ? "steps" : "classic"}&photo=${o.photo ? 1 : 0}&auto=1`,
    txt: `/export/recipe/${enc(slug)}.txt?servings=${s}`,
    md: `/export/recipe/${enc(slug)}.md?servings=${s}`,
    json: `/export/recipe/${enc(slug)}.json?servings=${s}`,
  };
}
const cutHint = (size) => (size === "a4" ? "Prints on A4 paper." : size === "letter" ? "Prints on Letter paper." : "Prints on Letter paper with dashed lines to cut out.");
function openRecipeExport() {
  const rec = R.rec, slug = rec.slug;
  const saved = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (_) { return d; } };
  const o = { size: saved("tp.printSize", "card46"), photo: !!rec.has_image && saved("tp.printPhoto", "1") === "1", steps: R.style === "steps", servings: R.servings || rec.servings || "" };
  if (!PRINT_SIZES.some(([k]) => k === o.size)) o.size = "card46";
  const body = { kind: "recipe", slug, servings: o.servings };
  const sends = sendItems(body);
  const share = [...sends];
  if (navigator.share) share.unshift(["share", "Send via…", () => shareText(recipeExportUrls(slug, o).txt, rec.name)]);
  share.push(["copy", "Copy as text", async () => {
    try { const t = await (await fetch(recipeExportUrls(slug, o).txt)).text(); await navigator.clipboard.writeText(t); toast("Recipe copied"); }
    catch (e) { fail(e); }
  }]);
  const u = recipeExportUrls(slug, o);
  openSheet("Share & export", `
    <div class="group-label" style="margin-top:4px">Print / PDF</div>
    <div class="chips wrap" id="ex-size">${PRINT_SIZES.map(([k, l]) => `<button class="filter ${o.size === k ? "on" : ""}" data-size="${k}">${esc(l)}</button>`).join("")}</div>
    <div class="group" style="margin-top:10px">
      <div class="field"><label>Photo${rec.has_image ? "" : '<small class="lh">This recipe has no photo yet.</small>'}</label><label class="toggle"><input type="checkbox" id="ex-photo" ${o.photo ? "checked" : ""} ${rec.has_image ? "" : "disabled"}><span></span></label></div>
      <div class="field"><label>Step-by-step<small class="lh">Ingredients inside each step instead of one list.</small></label><label class="toggle"><input type="checkbox" id="ex-steps" ${o.steps ? "checked" : ""}><span></span></label></div>
      <div class="field"><label>Servings<small class="lh">Change servings on the recipe page.</small></label><span class="muted">${esc(fmtQty(+o.servings) || o.servings || "—")}</span></div>
    </div>
    <div style="height:12px"></div>
    <button class="btn" id="ex-print" data-url="${esc(u.print)}">${ic("print")} Open print view</button>
    <p class="hint" id="ex-cut">${esc(cutHint(o.size))}</p>
    <p class="hint">Choose “Save as PDF” in the print dialog to keep a PDF copy.</p>
    <div class="group-label">Share</div>
    <div class="share-grid" id="ex-share">${share.map(([i, l], n) => `<button data-n="${n}">${ic(i)} ${esc(l)}</button>`).join("")}</div>
    <div class="group-label">Download</div>
    <div class="share-grid" id="ex-dl">
      <a href="${esc(safeUrl(u.txt))}" download data-k="txt">${ic("file")} Text</a>
      <a href="${esc(safeUrl(u.md))}" download data-k="md">${ic("file")} Markdown</a>
      <a href="${esc(safeUrl(u.json))}" download data-k="json">${ic("down")} Recipe file (JSON)</a>
    </div>`, {
    onMount() {
      const sync = () => { $("#ex-print").dataset.url = recipeExportUrls(slug, o).print; $("#ex-cut").textContent = cutHint(o.size); };
      $$("#ex-size [data-size]").forEach((b) => (b.onclick = () => {
        o.size = b.dataset.size; try { localStorage.setItem("tp.printSize", o.size); } catch (_) {}
        $$("#ex-size .filter").forEach((x) => x.classList.toggle("on", x === b)); sync();
      }));
      $("#ex-photo").onchange = (e) => { o.photo = e.target.checked; try { localStorage.setItem("tp.printPhoto", o.photo ? "1" : "0"); } catch (_) {} sync(); };
      $("#ex-steps").onchange = (e) => { o.steps = e.target.checked; sync(); };
      $("#ex-print").onclick = () => window.open(recipeExportUrls(slug, o).print, "_blank");
      $$("#ex-share [data-n]").forEach((b) => (b.onclick = () => share[+b.dataset.n][2]()));
    },
  });
}

// ------------------------------------------------------------------ COOK MODE (walkthrough with timers)
const C = { i: 0, steps: [], timers: [], tick: null, wake: null, audio: null };
async function startCook() {
  const btn = $("#rd-cook");
  if (btn?.disabled) return;
  if (!R.guide) {
    const label = btn?.innerHTML;
    if (btn) { btn.disabled = true; btn.innerHTML = state.cfg.ai_key ? "✨ Arranging steps… (first time ~15 s)" : "Preparing…"; }
    try { R.guide = await api("GET", `/api/recipe/${encodeURIComponent(R.rec.slug)}/guided`); }
    catch (e) { R.guide = null; }
    finally { if (btn) { btn.disabled = false; btn.innerHTML = label; } }
  }
  let steps = R.guide?.steps || [];
  if (!steps.length) {   // fall back to the recipe's own steps so cooking always works
    steps = (R.rec.steps || []).filter((s) => s.text).map((s) => ({ title: s.title || "", text: s.text, ingredients: (s.refs || []).map((i) => ({ i, portion: 1 })),
      timer_sec: s.duration_sec || null, timer_label: null, heat: null, temperature: null, tip: null }));
  }
  if (!steps.length) return toast("This recipe has no instructions yet. Tap Edit to add them.", "Edit", () => { location.hash = "edit/" + encodeURIComponent(R.rec.slug); });
  C.steps = steps.map((s) => ({ ...s, ingredients: s.ingredients || [], text: s.text || "" })); C.i = 0;
  const el = document.createElement("div"); el.className = "cook"; el.id = "cook"; document.body.appendChild(el);
  document.body.style.overflow = "hidden";
  try { C.wake = await navigator.wakeLock?.request("screen"); } catch (_) {}
  if ("Notification" in window && Notification.permission === "default" && window.isSecureContext) { try { Notification.requestPermission(); } catch (_) {} }
  C.tick = setInterval(tickTimers, 1000);
  document.addEventListener("keydown", cookKeys);
  try { drawCook(); } catch (e) { endCook(); fail(e); }
}
function endCook() {
  clearInterval(C.tick); C.timers = []; document.removeEventListener("keydown", cookKeys);
  try { C.wake?.release(); } catch (_) {}
  $("#cook")?.remove(); document.body.style.overflow = "";
}
function cookKeys(e) { if (e.key === "ArrowRight") cookMove(1); if (e.key === "ArrowLeft") cookMove(-1); if (e.key === "Escape") endCook(); }
function cookMove(d) { C.i = Math.max(0, Math.min(C.steps.length - 1, C.i + d)); drawCook(); }
function drawCook() {
  const s = C.steps[C.i], rec = R.rec, f = factor(), n = C.steps.length;
  const uses = s.ingredients.map((u) => { const x = rec.ingredients[u.i]; if (!x) return ""; const l = ingLine(x, f, u.portion); return `<span class="use" style="font-size:16px;padding:7px 13px 7px 9px">${esc(x.emoji)} <b>${esc(l.amt)}</b> ${esc(l.name)}</span>`; }).join("");
  const running = C.timers.find((t) => t.step === C.i);
  $("#cook").innerHTML = `
    <div class="cook-top"><button class="round-btn" id="ck-x" aria-label="Close">${ic("x")}</button><div class="prog"><i style="width:${((C.i + 1) / n) * 100}%"></i></div><span class="count">${C.i + 1}/${n}</span></div>
    <div class="cook-body">
      <div class="ttl">${esc(s.title || `Step ${C.i + 1}`)}</div>
      <div class="big">${esc(s.text)}</div>
      ${uses ? `<div class="uses" style="display:flex;flex-wrap:wrap;gap:8px">${uses}</div>` : ""}
      <div class="badges">${s.temperature ? `<span class="badge2">🌡️ ${esc(s.temperature)}</span>` : ""}${s.heat ? `<span class="badge2">🔥 ${esc(s.heat)}</span>` : ""}</div>
      ${s.tip ? `<p class="hint" style="margin:12px 0 0">${esc(s.tip)}</p>` : ""}
      ${s.timer_sec ? `<div class="timer-ring"><div><div class="t" id="ck-t">${running ? fmtClock(running.left) : fmtClock(s.timer_sec)}</div><div class="l">${esc(s.timer_label || "Timer")}</div></div>
        <div class="acts">${running ? `<button class="btn sec small" id="ck-add">+1 min</button><button class="btn sec small" id="ck-stop">Stop</button>` : `<button class="btn tint small" id="ck-start">${ic("play")} Start timer</button>`}</div></div>` : ""}
      ${C.i < n - 1 ? `<p class="hint" style="margin:18px 0 0">Next: ${esc(C.steps[C.i + 1].text.slice(0, 120))}${C.steps[C.i + 1].text.length > 120 ? "…" : ""}</p>` : ""}
    </div>
    <div class="timers-tray" id="ck-tray"></div>
    <div class="cook-foot"><button class="btn sec" id="ck-prev" ${C.i ? "" : "disabled"}>${ic("chevL")} Back</button>
      ${C.i < n - 1 ? `<button class="btn" id="ck-next">Next ${ic("chevR")}</button>` : `<button class="btn tint" id="ck-done">Done 🎉</button>`}</div>`;
  $("#ck-x").onclick = endCook;
  $("#ck-prev").onclick = () => cookMove(-1);
  $("#ck-next") && ($("#ck-next").onclick = () => cookMove(1));
  $("#ck-done") && ($("#ck-done").onclick = async (e) => {
    e.currentTarget.disabled = true;
    const rec = R.rec, ce = rec && rec.cook_entry;
    if (!rec) { endCook(); return toast("Enjoy your meal! 🍽️"); }
    const body = { servings: R.servings };
    if (ce && ce.today) body.plan_id = ce.id;
    let r;
    try { r = await markCooked(rec.slug, body); } catch (x) { endCook(); return fail(x); }
    const back = () => { endCook(); if (location.hash === "#recipe/" + encodeURIComponent(rec.slug)) renderRecipe(rec.slug); };
    if (!r.diary_id || !$("#cook")) return back();
    $("#cook").innerHTML = `<div class="ck-finish"><div class="ck-cheers">🎉</div><h2>${esc(rec.name)}</h2><p class="muted">${esc(cookedMessage(r))}</p>${howWasItHtml()}<button class="btn sec" id="ck-close">Close</button></div>`;
    bindHowWasIt(r.diary_id, back);
    $("#ck-close").onclick = () => { state.justCooked = null; back(); };
  });
  $("#ck-start") && ($("#ck-start").onclick = () => { unlockAudio(); C.timers.push({ step: C.i, label: s.timer_label || `Step ${C.i + 1}`, left: s.timer_sec, done: false }); drawCook(); });
  $("#ck-stop") && ($("#ck-stop").onclick = () => { C.timers = C.timers.filter((t) => t.step !== C.i); drawCook(); });
  $("#ck-add") && ($("#ck-add").onclick = () => { const t = C.timers.find((x) => x.step === C.i); if (t) { t.left += 60; t.done = false; } drawCook(); });
  drawTray();
}
const fmtClock = (sec) => { sec = Math.max(0, Math.round(sec)); const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0"); };
function drawTray() {
  const tray = $("#ck-tray"); if (!tray) return;
  tray.innerHTML = C.timers.map((t, k) => `<button class="tchip ${t.done ? "done" : ""}" data-k="${k}">⏱ ${esc(t.label)} · ${t.done ? "Done!" : fmtClock(t.left)}</button>`).join("");
  $$("#ck-tray [data-k]").forEach((b) => (b.onclick = () => { const t = C.timers[+b.dataset.k]; if (t.done) C.timers.splice(+b.dataset.k, 1); C.i = t.step; drawCook(); }));
}
function tickTimers() {
  let changed = false;
  C.timers.forEach((t) => {
    if (t.done) return;
    t.left -= 1; changed = true;
    if (t.left <= 0) { t.done = true; alertTimer(t); }
  });
  if (changed) { const cur = C.timers.find((t) => t.step === C.i); if (cur && $("#ck-t")) $("#ck-t").textContent = cur.done ? "0:00" : fmtClock(cur.left); drawTray(); }
}
function unlockAudio() { try { C.audio = C.audio || new (window.AudioContext || window.webkitAudioContext)(); C.audio.resume(); } catch (_) {} }
function alertTimer(t) {
  const next = C.steps[t.step + 1];
  const msg = `⏰ ${t.label} is done${next ? ` · Next: ${next.title || next.text.slice(0, 60)}` : ""}`;
  toast(msg, next ? "Go" : null, () => { C.i = t.step + 1; drawCook(); });
  try { navigator.vibrate?.([300, 150, 300, 150, 300]); } catch (_) {}
  try {
    const a = C.audio; if (a) [0, 0.35, 0.7].forEach((d) => { const o = a.createOscillator(), g = a.createGain(); o.frequency.value = 880; o.connect(g); g.connect(a.destination); g.gain.setValueAtTime(0.25, a.currentTime + d); g.gain.exponentialRampToValueAtTime(0.001, a.currentTime + d + 0.3); o.start(a.currentTime + d); o.stop(a.currentTime + d + 0.32); });
  } catch (_) {}
  try { if (document.hidden && window.Notification?.permission === "granted") new Notification("TablePlan timer", { body: msg }); } catch (_) {}
}

// ------------------------------------------------------------------ image picker (recipes & ingredients)
function openImagePicker({ kind, slug, name, after }) {
  const isRec = kind === "recipe";
  openSheet(isRec ? "Recipe photo" : `Photo: ${name}`, `
    <div style="border-radius:16px;overflow:hidden;background:var(--card2);aspect-ratio:${isRec ? "4/3" : "1"};max-height:300px;margin:0 auto 14px;display:grid;place-items:center" id="ip-prev">
      ${isRec ? (R.rec?.has_image ? `<img src="${esc(recipeImg(R.rec, "full"))}" style="width:100%;height:100%;object-fit:cover">` : "🍽️") : `<img src="/img/ing?name=${encodeURIComponent(name)}&t=${Date.now()}" style="width:70%;height:70%;object-fit:contain" data-fb="No photo yet">`}
    </div>
    <div class="btn-row"><button class="btn sec" id="ip-next">${ic("refresh")} Try another</button><label class="btn" style="cursor:pointer">${ic("camera")} Upload<input type="file" accept="image/*" id="ip-file" hidden></label></div>
    <p class="hint" id="ip-credit">${isRec ? "“Try another” finds openly licensed food photos (Openverse)." : "Ingredient photos come from TheMealDB, then openly licensed photos (Openverse)."} Your own photo always wins.<span class="desktop-only"> Drag & drop or paste an image onto the photo to use it.</span></p>`, {
    onMount() {
      const done = (credit) => { if (credit) $("#ip-credit").textContent = `Photo: ${credit}`; toast("Photo updated"); closeSheet(); after && after(); };
      $("#ip-next").onclick = async (e) => {
        const btn = e.currentTarget; btn.disabled = true; btn.textContent = "Searching…";
        try { const r = await api("POST", isRec ? `/api/recipe/${encodeURIComponent(slug)}/image/next` : "/api/ingredient-image/next", isRec ? {} : { name }); done(r.credit); }
        catch (x) { fail(x); btn.disabled = false; btn.innerHTML = `${ic("refresh")} Try another`; }
      };
      const upload = async (f) => {
        if (!f) return;
        $("#ip-prev").innerHTML = loading();
        const data = await shrink(f);
        try { await api("POST", isRec ? `/api/recipe/${encodeURIComponent(slug)}/image/upload` : "/api/ingredient-image/upload", isRec ? { data } : { name, data }); done("Your photo"); } catch (x) { fail(x); }
      };
      $("#ip-file").onchange = (e) => upload(e.target.files[0]);
      dropZone($("#ip-prev"), (files) => upload(files[0]));
    },
  });
}

// ------------------------------------------------------------------ AI spending
async function openAiSpending() {
  openSheet("AI spending", loading(), { wide: true });
  let d; try { d = await api("GET", "/api/ai/spending"); } catch (e) { sheetBody().innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  const draw = () => {
    const exact = d.exact, total = exact ? exact.total : d.estimate_usd;
    const days = exact ? exact.days : d.daily;
    const max = Math.max(0.0001, ...days.map((x) => x.usd));
    const pct = d.budget ? Math.min(100, (total / d.budget) * 100) : 0;
    sheetBody().innerHTML = `
      <div class="group"><div class="bigstat"><b>$${total.toFixed(total < 1 ? 3 : 2)}</b><small>${exact ? "Exact OpenAI spend this month (all apps on your account, including Mealie imports)" : "Estimated spend this month from TablePlan's own AI features"}</small>
        ${d.budget ? `<div class="meter" style="max-width:none;margin-top:10px"><i style="width:${pct}%;background:${pct >= 100 ? "var(--red)" : pct >= 80 ? "var(--orange)" : "var(--green)"}"></i></div><small>${pct.toFixed(0)}% of your $${d.budget.toFixed(2)} monthly budget</small>` : ""}</div>
        ${days.length ? `<div class="bars">${days.map((x) => `<i title="${esc(x.date)}: $${(+x.usd).toFixed(4)}" style="height:${((+x.usd / max) * 100) || 0}%"></i>`).join("")}</div>` : ""}</div>
      <div class="group-label">This month by feature</div>
      <div class="group">${d.by_feature.length ? d.by_feature.map((r) => `<div class="row flush"><div class="main"><div class="a">${esc(cap(r.feature))}</div><div class="b">${esc(r.n)} call${r.n === 1 ? "" : "s"}${r.tin ? ` · ${(r.tin / 1000).toFixed(1)}k in / ${(r.tout / 1000).toFixed(1)}k out tokens` : ""}</div></div><b>${r.usd ? "$" + r.usd.toFixed(4) : "—"}</b></div>`).join("") : `<div class="row flush muted">No AI use yet this month.</div>`}</div>
      <p class="hint">Video imports aren't tracked here; OpenAI's own numbers (below) include everything. Estimates use list prices (${esc(d.model || "gpt-5-mini")}: $${esc(((d.prices || {})[d.model] || (d.prices || {})["gpt-5-mini"] || {}).input)}/1M in, $${esc(((d.prices || {})[d.model] || (d.prices || {})["gpt-5-mini"] || {}).output)}/1M out).</p>
      <div class="group-label">Monthly budget</div>
      <div class="group"><div class="field"><label>Alert me at (USD / month)</label><input type="number" id="ai-b" min="0" step="1" value="${esc(d.budget || "")}" placeholder="Off"></div></div>
      <p class="hint">You get a notification at 80% and 100%. To hard-cap spending, also set a limit in OpenAI → Settings → Limits.</p>
      <div class="group-label">Exact costs from OpenAI</div>
      <div class="group"><div class="field"><input class="full" type="password" id="ai-ak" placeholder="${d.has_admin_key ? "Admin key saved ✓ (enter to replace)" : "sk-admin-… (optional)"}" autocomplete="off"></div></div>
      <p class="hint">An <b>Admin key</b> (OpenAI → Settings → Organization → Admin keys) lets TablePlan read your real bill. It can only read costs here, and it stays on your server.${d.exact_error ? `<br><span style="color:var(--red)">${esc(d.exact_error)}</span>` : ""}</p>
      <div style="height:12px"></div><div class="btn-row"><button class="btn" id="ai-save">Save</button>${d.has_admin_key ? `<button class="btn red" id="ai-rm">Remove admin key</button>` : ""}</div>
      ${d.recent.length ? `<div class="group-label">Recent</div><div class="group">${d.recent.slice(0, 10).map((r) => `<div class="row flush"><div class="main"><div class="a" style="font-size:15px">${esc(r.detail || r.feature)}</div><div class="b">${esc(r.at.replace("T", " ").slice(0, 16))} · ${esc(r.model || "")}</div></div><span class="muted">${r.cost_usd != null ? "$" + r.cost_usd.toFixed(4) : "—"}</span></div>`).join("")}</div>` : ""}`;
    $("#ai-save").onclick = async () => {
      try {
        const b = +$("#ai-b").value || 0;
        await api("PUT", "/api/settings", { ai_budget: b }); state.cfg.settings.ai_budget = b;
        const k = $("#ai-ak").value.trim();
        d = k ? await api("POST", "/api/setup/openai-admin", { key: k }) : await api("GET", "/api/ai/spending");
        toast("Saved"); draw();
      } catch (e) { fail(e); }
    };
    $("#ai-rm") && ($("#ai-rm").onclick = async () => { d = await api("POST", "/api/setup/openai-admin", { key: "" }); draw(); });
  };
  draw();
}

// ------------------------------------------------------------------ barcode scanner → pantry
let ZX = null;
function loadZXing() {
  if (ZX) return ZX;
  ZX = new Promise((res, rej) => {
    const s = document.createElement("script"); s.src = "/static/vendor/zxing/zxing-reader.js";
    s.onload = () => { try { window.ZXingWASM.prepareZXingModule({ overrides: { locateFile: (p, pre) => (p.endsWith(".wasm") ? "/static/vendor/zxing/zxing_reader.wasm" : pre + p) }, fireImmediately: true }); res(window.ZXingWASM); } catch (e) { rej(e); } };
    s.onerror = () => rej(new Error("Couldn't load the barcode reader"));
    document.head.appendChild(s);
  });
  return ZX;
}
const BC_OPTS = { formats: ["EAN13", "EAN8", "UPCA", "UPCE"], tryHarder: true, maxNumberOfSymbols: 1 };
// ------------------------------------------------------------------ barcode scan sessions (camera, USB or Bluetooth scanner)
// A keyboard-wedge scanner "types" the digits fast and ends with Enter. Every scan adds to the pantry at once (with
// Undo), ticks it off the shopping list if it's there, and scanning the same code again adds one more.
const SCAN_LOCS = [["pantry", "Pantry"], ["fridge", "Fridge"], ["freezer", "Freezer"]];
const SS = { active: false, loc: (() => { try { return localStorage.getItem("tp.scanLoc") || ""; } catch (_) { return ""; } })(), rows: [], naming: null, queue: [], busy: false, foods: null, after: null };
const scanCount = () => SS.rows.reduce((n, r) => n + r.count, 0);
const STOCK_METHODS = [["scanner", "Scanner"], ["camera", "Camera"], ["type", "Type it"], ["receipt", "Receipt"]];
const stockMethod = () => { try { return localStorage.getItem("tp.stockMethod") || "scanner"; } catch (_) { return "scanner"; } };
function setStockMethod(m) { try { localStorage.setItem("tp.stockMethod", m); } catch (_) {} }
// "How do you want to stock up?": scanner, camera, type it (receipt comes later); the choice is remembered
function startStockUp(after) {
  startScanSession(after);
  if (stockMethod() === "camera") openScanner(after);
}
function startScanSession(after) {
  if (after) SS.after = after;
  if (SS.active) { drawSession(); $("#sb-code")?.focus(); return; }
  SS.active = true; SS.rows = []; SS.naming = null; SS.queue = [];
  document.body.classList.add("scanning");
  document.body.insertAdjacentHTML("beforeend", `<div class="scan-bar" id="scan-bar" role="region" aria-label="Stock up">
    <div class="sb-head"><b>How do you want to stock up?</b><span class="grow"></span><button class="text-btn strong" id="sb-done">Done</button></div>
    <div class="seg sb-method" id="sb-method" role="radiogroup" aria-label="Method"></div>
    <div class="chips sb-locs" id="sb-locs" role="radiogroup" aria-label="Put items in"></div>
    <div id="sb-input"></div>
    <div class="sb-opts"><label class="sb-toggle"><input type="checkbox" id="sb-counting" ${counting() ? "checked" : ""}> Counting what I already have</label>
      <label class="sb-all">Set date for all <input type="date" id="sb-all-date" aria-label="Use-by date for every item this session"></label></div>
    <div class="muted small" id="sb-n" aria-live="polite"></div>
    <div id="sb-name"></div><div class="sb-rows" id="sb-rows"></div></div>`);
  $("#sb-done").onclick = endScanSession;
  $("#sb-counting").onchange = (e) => { try { localStorage.setItem("tp.counting", e.target.checked ? "1" : "0"); } catch (_) {} drawSession(); };
  $("#sb-all-date").onchange = async (e) => {
    const d = e.target.value; if (!d) return;
    for (const row of SS.rows.filter((r) => r.item)) {
      try { const r = await api("PATCH", `/api/pantry/${enc(row.item.id)}`, { action: "set_date", expires_on: d, source: "package" }); row.item = { ...row.item, ...r }; } catch (x) { fail(x); }
    }
    drawSession(); toast(`Use-by date set for ${plural(SS.rows.length, "item")}`);
  };
  drawSession();
}
function drawStockInput() {
  const box = $("#sb-input"); if (!box) return;
  const m = stockMethod();
  $("#sb-method").innerHTML = STOCK_METHODS.map(([k, l]) => `<button data-m="${k}" class="${m === k ? "on" : ""}" role="radio" aria-checked="${m === k}" >${esc(l)}</button>`).join("");
  $$("#sb-method [data-m]").forEach((b) => (b.onclick = () => {
    if (b.dataset.m === "receipt") { endScanSession(); return openTrip(SS.after || (state.tab === "pantry" ? renderPantry : null)); }
    setStockMethod(b.dataset.m); drawSession();
    if (b.dataset.m === "camera") openScanner(SS.after);
  }));
  if (box.dataset.m === m) return;
  box.dataset.m = m;
  if (m === "type") {
    box.innerHTML = `<form class="sb-form" id="sb-type" autocomplete="off"><input id="sb-food" list="sb-foods-t" placeholder="Type a food, e.g. Greek yogurt" aria-label="Food name" maxlength="80"><input id="sb-size" placeholder="Size" aria-label="Size" maxlength="40" class="sz"><button class="pill-btn ink" type="submit">Add</button></form><datalist id="sb-foods-t"></datalist>`;
    const fill = () => { const dl = $("#sb-foods-t"); if (dl && SS.foods) dl.innerHTML = SS.foods.map((n) => `<option value="${esc(n)}"></option>`).join(""); };
    if (SS.foods) fill(); else api("GET", "/api/foods").then((d) => { SS.foods = (d.foods || []).map((x) => x.name); fill(); }).catch(() => {});
    $("#sb-type").onsubmit = async (e) => {
      e.preventDefault();
      const name = $("#sb-food").value.trim(); if (!name) return;
      try {
        const it = await api("POST", "/api/pantry", { name, location: SS.loc || "pantry", quantity_text: $("#sb-size").value.trim() });
        const row = { code: "", item: it, count: 1, list: false };
        SS.rows.push(row); $("#sb-food").value = ""; $("#sb-size").value = ""; drawSession(); $("#sb-food").focus();
        toast(`${it.name} added`, "Undo", async () => { try { await api("POST", "/api/scan/undo", { pantry_item_id: it.id }); SS.rows = SS.rows.filter((x) => x !== row); drawSession(); } catch (x) { fail(x); } });
      } catch (x) { fail(x); }
    };
  } else {
    box.innerHTML = `<form class="sb-form" id="sb-form" autocomplete="off"><input id="sb-code" inputmode="numeric" placeholder="${m === "camera" ? "Or type a barcode or produce code" : "Ready, scan away (or paste a code)"}" aria-label="Barcode or produce code" maxlength="20"><button class="pill-btn ink" type="submit">Add</button>${m === "camera" ? `<button class="pill-btn" type="button" id="sb-cam">${ic("camera")}</button>` : ""}</form>`;
    $("#sb-form").onsubmit = (e) => { e.preventDefault(); const v = $("#sb-code").value.replace(/\D/g, ""); $("#sb-code").value = ""; if (v.length >= 4) sessionScan(v); else toast("Enter the numbers under the barcode, or a 4–5 digit produce code"); };
    $("#sb-cam") && ($("#sb-cam").onclick = () => openScanner(SS.after));
  }
}
function endScanSession() {
  if (!SS.active) return;
  SS.active = false;
  $("#scan-bar")?.remove(); document.body.classList.remove("scanning");
  const n = scanCount();
  const trip = SS.trip; SS.trip = null;
  const ids = SS.rows.map((r) => r.item?.id).filter((x) => x != null);
  if (trip && ids.length) api("POST", "/api/trip/scans", { ...trip, pantry_item_ids: ids }).then((r) => toast(r.summary)).catch(() => {});
  else if (n) toast(`Added ${plural(n, "item")} to your inventory`);
  if (SS.after) SS.after(); else if (state.tab === "pantry") renderPantry();
  SS.after = null;
}
const FILLS = [[1, "Full"], [0.75, "¾"], [0.5, "½"], [0.25, "¼"], [0.1, "Almost empty"]];
const counting = () => { try { return localStorage.getItem("tp.counting") === "1"; } catch (_) { return false; } };
const fillLabel = (v) => (FILLS.find(([f]) => Math.abs(f - v) < 0.02) || [0, `${Math.round(v * 100)}%`])[1];
const plusDays = (n) => isoDate(addDays(today(), n));
function scanRowHtml(r, i) {
  if (r.naming) return "";
  const it = r.item, sub = [it.product, it.quantity_text].filter(Boolean).join(" · ");
  const left = it.amount_left ?? 1, open = r.fillOpen ?? counting();
  const exp = it.expires_on ? (it.expiry_label || fmt(parseISO(it.expires_on), { month: "short", day: "numeric" })) : "No date";
  return `<div class="sb-row" data-i="${i}"><div class="sb-line">${it.image ? `<img class="sb-img" src="${esc(it.image)}" alt="">` : `<span class="sb-img emo">${esc(it.emoji || "🥫")}</span>`}
    <div class="main"><div class="a">${esc(it.name)}</div><div class="b">${esc(sub || cap(it.location))}${r.list ? ` · <span class="ok-note">✓ Checked off your list</span>` : ""}</div></div>
    <div class="sb-count"><button class="mini" data-less aria-label="One fewer ${esc(it.name)}">−</button><b>${esc(r.count)}</b><button class="mini" data-more aria-label="One more ${esc(it.name)}">+</button></div></div>
    <div class="sb-ctl">${open
      ? `<span class="fill-chips" role="radiogroup" aria-label="How full">${FILLS.map(([f, l]) => `<button class="chip-s ${Math.abs(f - left) < 0.02 ? "on" : ""}" data-fill="${f}" role="radio" aria-checked="${Math.abs(f - left) < 0.02}">${esc(l)}</button>`).join("")}</span>`
      : `<button class="chip-s" data-fill-open aria-expanded="false">${esc(fillLabel(left))} ▾</button>`}
      <button class="chip-s exp ${it.expires_on ? "set" : ""}" data-exp aria-expanded="${!!r.expOpen}">Exp: ${esc(exp)}</button></div>
    ${r.expOpen ? `<div class="sb-exp"><input type="date" data-exp-date value="${esc(it.expires_on || "")}" aria-label="Printed use-by date">
      <button class="chip-s" data-exp-add="3">+3d</button><button class="chip-s" data-exp-add="7">+1w</button><button class="chip-s" data-exp-add="30">+1mo</button>
      ${it.expires_on ? `<button class="chip-s" data-exp-clear>No date</button>` : ""}<span class="muted small">The date picker is for the printed date.</span></div>` : ""}</div>`;
}
async function patchScanned(row, body) {
  try { const r = await api("PATCH", `/api/pantry/${enc(row.item.id)}`, body); if (r && r.id) row.item = { ...row.item, ...r }; drawSession(); }
  catch (e) { fail(e); }
}
function bindScanRow(box, row) {
  const el = $(`[data-i="${SS.rows.indexOf(row)}"]`, box); if (!el) return;
  $$("[data-fill]", el).forEach((b) => (b.onclick = () => patchScanned(row, { action: "fill", left: +b.dataset.fill })));
  $("[data-fill-open]", el) && ($("[data-fill-open]", el).onclick = () => { row.fillOpen = true; drawSession(); });
  $("[data-exp]", el).onclick = () => { row.expOpen = !row.expOpen; drawSession(); };
  $("[data-exp-date]", el) && ($("[data-exp-date]", el).onchange = (e) => { if (e.target.value) { row.expOpen = false; patchScanned(row, { action: "set_date", expires_on: e.target.value, source: "package" }); } });
  $$("[data-exp-add]", el).forEach((b) => (b.onclick = () => { row.expOpen = false; patchScanned(row, { action: "set_date", expires_on: plusDays(+b.dataset.expAdd), source: "manual" }); }));
  $("[data-exp-clear]", el) && ($("[data-exp-clear]", el).onclick = () => { row.expOpen = false; patchScanned(row, { action: "set_date", expires_on: "" }); });
}
function drawSession() {
  const bar = $("#scan-bar");
  const loc = SS.loc || "pantry";
  if (bar) {
    drawStockInput();
    $("#sb-locs").innerHTML = SCAN_LOCS.map(([k, l]) => `<button class="filter sm ${loc === k ? "on" : ""}" data-sl="${k}" role="radio" aria-checked="${loc === k}">${esc(l)}</button>`).join("");
    $$("#sb-locs [data-sl]").forEach((b) => (b.onclick = () => { SS.loc = b.dataset.sl; try { localStorage.setItem("tp.scanLoc", SS.loc); } catch (_) {} drawSession(); }));
    const n = scanCount();
    $("#sb-n").textContent = n ? `${plural(n, "item")} added` : stockMethod() === "scanner" ? "Ready, scan away" : "";
  }
  const rowsHtml = SS.rows.map(scanRowHtml).reverse().join("");
  [$("#sb-rows"), $("#sc-rows")].forEach((box) => {
    if (!box) return;
    box.innerHTML = rowsHtml;
    $$("[data-more],[data-less]", box).forEach((b) => (b.onclick = () => bumpScan(SS.rows[+b.closest("[data-i]").dataset.i], b.hasAttribute("data-more") ? 1 : -1)));
    SS.rows.forEach((r) => !r.naming && bindScanRow(box, r));
  });
  [$("#sb-name"), $("#sc-name")].forEach((box) => { if (box) drawNaming(box); });
}
function drawNaming(box) {
  if (!SS.naming) { box.innerHTML = ""; return; }
  const code = SS.naming;
  box.innerHTML = `<form class="sb-naming" autocomplete="off"><div class="muted small">Barcode ${esc(code)} isn't known yet. Name this item:</div>
    <div class="sb-name-row"><input class="nm" list="sb-foods" placeholder="e.g. Greek yogurt" maxlength="80" aria-label="Item name" required>
    <input class="sz" placeholder="Size (e.g. 32 oz)" maxlength="40" aria-label="Size"><button class="pill-btn ink" type="submit">Save</button></div>
    <datalist id="sb-foods">${(SS.foods || []).map((f) => `<option value="${esc(f)}"></option>`).join("")}</datalist>
    ${SS.queue.length ? `<div class="muted small">${esc(plural(SS.queue.length, "more scan"))} waiting</div>` : ""}
    <div class="sb-name-row">${state.cfg?.ai_key ? `<label class="pill-btn sb-snap">${ic("camera")} Snap the product<input type="file" accept="image/*" capture="environment" hidden></label>` : ""}<button type="button" class="link-btn sb-skip">Skip this one</button></div></form>`;
  const f = $("form", box);
  if (!SS.foods) api("GET", "/api/foods").then((d) => { SS.foods = (d.foods || []).map((x) => x.name); const dl = $("#sb-foods", box); if (dl) dl.innerHTML = SS.foods.map((n) => `<option value="${esc(n)}"></option>`).join(""); }).catch(() => {});
  setTimeout(() => $(".nm", f)?.focus(), 30);
  f.onsubmit = async (e) => {
    e.preventDefault();
    const name = $(".nm", f).value.trim(); if (!name) return;
    SS.naming = null;
    await sessionScan(code, { name, quantity: $(".sz", f).value.trim() });
    nextQueued();
  };
  $(".sb-skip", f).onclick = () => { SS.naming = null; drawSession(); nextQueued(); };
  const snap = $(".sb-snap input", f);
  if (snap) snap.onchange = async (e) => {
    const file = e.target.files[0]; if (!file) return;
    const lbl = $(".sb-snap", f); lbl.classList.add("busy"); lbl.firstChild && (lbl.lastChild.previousSibling.textContent = " Reading…");
    try {
      const r = await api("POST", "/api/scan/photo", { code, image: await shrink(file), location: SS.loc || "pantry" });
      SS.naming = null;
      if (r.ok) {
        const row = { code, item: r.item, count: 1, list: !!r.list_checked };
        SS.rows.push(row);
        toast(`${r.item.name} · remembered for next time`, "Undo", async () => { try { await api("POST", "/api/scan/undo", { pantry_item_id: row.item.id }); SS.rows = SS.rows.filter((x) => x !== row); drawSession(); } catch (x) { fail(x); } });
      }
      drawSession(); nextQueued();
    } catch (x) { fail(x); lbl.classList.remove("busy"); }
  };
}
function nextQueued() { const c = SS.queue.shift(); if (c) sessionScan(c); }
async function sessionScan(code, named) {
  if (!SS.active && !$("#sc-rows")) startScanSession();
  if (SS.naming && !named) { if (code !== SS.naming) SS.queue.push(code); drawSession(); return; }
  const prev = SS.rows.find((r) => r.code === code && !named);
  if (prev) return bumpScan(prev, 1);
  try { navigator.vibrate?.(40); } catch (_) {}
  try {
    const r = await api("POST", "/api/scan", { code, location: SS.loc || "pantry", ...(named || {}) });
    if (!r.ok && r.needs_name) { SS.naming = code; drawSession(); return; }
    const row = { code, item: r.item, count: 1, list: !!r.list_checked };
    SS.rows.push(row);
    drawSession();
    toast(`${r.item.name}${r.list_checked ? " · checked off your list" : ""}`, "Undo", async () => {
      try { await api("POST", "/api/scan/undo", { pantry_item_id: row.item.id }); SS.rows = SS.rows.filter((x) => x !== row); drawSession(); } catch (e) { fail(e); }
    });
  } catch (e) { fail(e); }
}
async function bumpScan(row, d) {
  if (!row) return;
  if (d < 0 && row.count <= 1) {
    try { await api("POST", "/api/scan/undo", { pantry_item_id: row.item.id }); SS.rows = SS.rows.filter((x) => x !== row); drawSession(); toast(`Removed ${row.item.name}`); } catch (e) { fail(e); }
    return;
  }
  try {
    const r = await api("POST", `/api/scan/${enc(row.item.id)}/${d > 0 ? "more" : "less"}`, {});
    row.item = { ...row.item, ...r.item }; row.count += d; drawSession();
  } catch (e) { fail(e); }
}
// keyboard-wedge burst: >= 6 digits, < 50 ms apart, then Enter, while no text field is focused
const WEDGE = { buf: "", last: 0 };
document.addEventListener("keydown", (e) => {
  const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  if (typing) { WEDGE.buf = ""; return; }
  const now = performance.now();
  if (/^\d$/.test(e.key)) {
    if (now - WEDGE.last > 50) WEDGE.buf = "";
    WEDGE.buf += e.key; WEDGE.last = now;
    return;
  }
  if (e.key === "Enter" && WEDGE.buf.length >= 6 && now - WEDGE.last <= 50) {
    const code = WEDGE.buf; WEDGE.buf = "";
    if (state.tab === "pantry" || SS.active || $("#sc-rows")) {
      e.preventDefault();
      if (stockMethod() !== "scanner" && !$("#sc-rows")) setStockMethod("scanner");   // a scanner just spoke: switch to it
      sessionScan(code);
    }
    return;
  }
  WEDGE.buf = "";
});

async function openScanner(after) {
  const live = window.isSecureContext && navigator.mediaDevices?.getUserMedia;
  openSheet("Stock up", `
    ${live ? `<div class="scan-view"><video id="sc-v" playsinline muted></video><div class="aim"></div></div><p class="hint" style="text-align:center">Point at a barcode. It scans automatically.</p>` :
      `<label class="drop" style="padding:28px">${ic("camera")}<div style="margin-top:8px"><b>Take a photo of the barcode</b><br><span class="muted">Fill most of the photo with the barcode</span></div><input type="file" accept="image/*" capture="environment" id="sc-file" hidden></label>
       <p class="hint">Live scanning needs HTTPS. Set it up with Tailscale (see the README) to scan without taking photos.</p>`}
    <div id="sc-res"></div><div id="sc-name"></div><div class="sb-rows" id="sc-rows"></div>
    <form class="group sb-form" id="sc-form" style="margin-top:12px"><div class="field"><input class="full" id="sc-code" inputmode="numeric" placeholder="Or type the barcode number" maxlength="20"></div></form>
    <div style="height:10px"></div><div class="btn-row"><button class="btn sec" id="sc-look">Look up</button><button class="btn sec" id="sc-wedge">${ic("scan")} USB / Bluetooth scanner</button></div>
    <p class="hint">Product names come from Open Food Facts (free, open database). A USB or Bluetooth scanner works anywhere on the Inventory tab too.</p>`, {
    async onMount(sheet) {
      let stream = null, stop = false, busy = false;
      SS.rows = SS.active ? SS.rows : [];
      const found = async (code) => {
        if (busy) return; busy = true;
        $("#sc-res").innerHTML = "";
        await sessionScan(code);
        busy = false;
        after && after();
      };
      drawSession();
      const look = () => { const c = $("#sc-code").value.replace(/\D/g, ""); $("#sc-code").value = ""; if (c.length >= 4) found(c); else toast("Enter the numbers under the barcode"); };
      $("#sc-look").onclick = look;
      $("#sc-form").onsubmit = (e) => { e.preventDefault(); look(); };
      $("#sc-wedge").onclick = () => { closeSheet(); setStockMethod("scanner"); startScanSession(after); };
      let zx;
      try { zx = await loadZXing(); } catch (e) { $("#sc-res").innerHTML = `<div class="banner">${esc(e.message)}. Type the number instead.</div>`; return; }
      if ($("#sc-file")) $("#sc-file").onchange = async (e) => {
        const f = e.target.files[0]; if (!f) return;
        const r = await zx.readBarcodes(f, BC_OPTS).catch(() => []);
        if (r[0]?.text) found(r[0].text); else $("#sc-res").innerHTML = `<div class="banner">Couldn't read a barcode in that photo. Try closer and steadier, or type the number.</div>`;
      };
      if (live) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false });
          const v = $("#sc-v"); v.srcObject = stream; await v.play();
          const cv = document.createElement("canvas"), ctx = cv.getContext("2d", { willReadFrequently: true });
          let lastCode = "", lastAt = 0;
          const loop = async () => {
            if (stop || !document.body.contains(v)) { stream.getTracks().forEach((t) => t.stop()); return; }
            if (!busy && v.videoWidth) {
              cv.width = v.videoWidth; cv.height = v.videoHeight; ctx.drawImage(v, 0, 0);
              const r = await zx.readBarcodes(ctx.getImageData(0, 0, cv.width, cv.height), BC_OPTS).catch(() => []);
              const code = r[0]?.text;
              if (code && (code !== lastCode || Date.now() - lastAt > 2500)) { lastCode = code; lastAt = Date.now(); await found(code); }
            }
            setTimeout(loop, 250);
          };
          loop();
        } catch (e) { $("#sc-res").innerHTML = `<div class="banner">Camera unavailable (${esc(e.message)}). Type the number instead.</div>`; }
      }
      const obs = new MutationObserver(() => { if (!document.body.contains(sheet)) { stop = true; stream?.getTracks().forEach((t) => t.stop()); obs.disconnect(); } });
      obs.observe(document.body, { childList: true, subtree: true });
    },
  });
}

// ------------------------------------------------------------------ grocery trip: a receipt or scanning, then one review
const readFile = (f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
const TRIP_UNITS = [["", "count"], ["lb", "lb"], ["oz", "oz"], ["kg", "kg"], ["g", "g"], ["fl oz", "fl oz"], ["cup", "cup"], ["pint", "pint"], ["quart", "quart"], ["gallon", "gallon"], ["l", "l"], ["ml", "ml"]];
async function openTrip(after) {
  const T = { store_id: null, store_name: "", stores: [], files: [], read: null, step: 1 };
  try { T.stores = await api("GET", "/api/stores"); } catch (_) {}
  openSheet("Log a grocery trip", `<div id="trip"></div>`, { onMount: () => draw() });
  function draw() {
    const box = $("#trip"); if (!box) return;
    if (T.step === 1) {
      box.innerHTML = `<div class="group-label" style="margin-top:2px">Where did you shop?</div>
        <div class="chips wrap" id="tr-stores">${T.stores.map((st) => `<button class="filter ${String(T.store_id) === String(st.id) ? "on" : ""}" data-sid="${esc(st.id)}">${esc(st.name)}</button>`).join("")}<button class="filter ${T.store_id === "other" ? "on" : ""}" data-sid="other">Other</button></div>
        ${T.store_id === "other" ? `<div class="group" style="margin-top:8px"><div class="field"><input class="full" id="tr-other" maxlength="60" placeholder="Store name" value="${esc(T.store_name)}"></div></div>` : ""}
        <div class="group-label">How do you want to add it?</div>
        <div class="trip-methods">
          <button class="trip-m" id="tr-receipt" ${state.cfg.ai_key ? "" : "disabled"}>${ic("file")}<b>Receipt</b><span>${state.cfg.ai_key ? "Photo, PDF or drop a file" : "Needs an OpenAI key (Settings)"}</span></button>
          <button class="trip-m" id="tr-scan">${ic("scan")}<b>Scan the items</b><span>Scanner or camera</span></button>
        </div>`;
      $$("#tr-stores [data-sid]").forEach((b) => (b.onclick = () => { T.store_id = b.dataset.sid; T.store_name = b.dataset.sid === "other" ? T.store_name : b.textContent; draw(); if (T.store_id === "other") $("#tr-other")?.focus(); }));
      $("#tr-other") && ($("#tr-other").oninput = (e) => { T.store_name = e.target.value; });
      $("#tr-receipt").onclick = () => { T.step = 2; draw(); };
      $("#tr-scan").onclick = () => {
        closeSheet();
        SS.trip = { store_id: T.store_id && T.store_id !== "other" ? T.store_id : null, store_name: T.store_name };
        startStockUp(after);
      };
      return;
    }
    if (T.step === 2) {
      box.innerHTML = `<button class="link-btn" id="tr-back">${ic("chevL")} Back</button>
        <label class="drop" id="tr-drop" style="padding:26px;margin-top:6px">${ic("camera")}<div style="margin-top:8px"><b>Take a photo of the receipt</b><br><span class="muted">or choose photos or a PDF, or drop them here</span></div>
          <input type="file" accept="image/*,application/pdf" multiple id="tr-file" hidden></label>
        <div id="tr-status"></div>`;
      $("#tr-back").onclick = () => { T.step = 1; draw(); };
      const go = async (files) => {
        $("#tr-status").innerHTML = `<div class="importing"><div class="pot">🧾</div><div class="stage">Reading your receipt…</div><div class="muted small">Usually 10–20 seconds.</div></div>`;
        try {
          T.files = [];
          for (const f of files.slice(0, 6)) T.files.push({ data: f.type === "application/pdf" ? await readFile(f) : await shrink(f) });
          T.read = await api("POST", "/api/receipt", { images: T.files });
          if (!T.store_name && T.read.store_name) T.store_name = T.read.store_name;
          T.step = 3; draw();
        } catch (e) { $("#tr-status").innerHTML = `<div class="banner">${esc(e.message)}</div>`; }
      };
      $("#tr-file").onchange = (e) => go([...e.target.files]);
      dropZone($("#tr-drop"), go, /^(image\/|application\/pdf)/);
      return;
    }
    const rows = T.read.rows;
    const acts = (r) => [r.list_item ? ["check_off", "Check off + add"] : null, ["add", "Add to inventory"], r.pantry_item ? ["increase", `Add to ${r.pantry_item.name}`] : null, ["ignore", "Ignore"]].filter(Boolean);
    box.innerHTML = `<div class="trip-head"><b>${esc(T.store_name || "Grocery trip")}</b><span class="muted">${esc(fmt(parseISO(T.read.date), { month: "short", day: "numeric" }))} · ${esc(plural(rows.length, "line"))}${T.read.total != null ? ` · $${esc((+T.read.total).toFixed(2))}` : ""}</span></div>
      <div class="trip-rows">${rows.map((r, i) => `<div class="trip-row ${r.action === "ignore" ? "ignored" : ""}" data-i="${i}">
        <div class="tr-top"><input class="tr-name" value="${esc(r.name)}" aria-label="Item name" maxlength="80"><select class="tr-act" aria-label="What to do">${acts(r).map(([k, l]) => `<option value="${k}" ${r.action === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
        <div class="muted small">${esc(r.raw_text)}${r.list_item ? ` · on your list: ${esc(r.list_item.text)}` : ""}</div>
        <div class="tr-bottom"><input class="tr-qty" type="number" inputmode="decimal" min="0" step="any" value="${r.quantity != null ? esc(r.quantity) : ""}" placeholder="Qty" aria-label="Quantity">
          <select class="tr-unit" aria-label="Unit">${TRIP_UNITS.map(([v, l]) => `<option value="${esc(v)}" ${v === (r.unit || "") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
          <select class="tr-loc" aria-label="Store in">${["fridge", "freezer", "pantry"].map((l) => `<option value="${l}" ${r.location === l ? "selected" : ""}>${cap(l)}</option>`).join("")}</select>
          <span class="tr-price">$<input type="number" inputmode="decimal" min="0" step="0.01" value="${r.price != null ? esc((+r.price).toFixed(2)) : ""}" aria-label="Price"></span></div>
        <div class="tr-bottom"><select class="tr-fill" aria-label="How full">${FILLS.map(([f, l]) => `<option value="${f}" ${(r.left ?? 1) === f ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
          <label class="tr-exp muted small">Exp <input type="date" class="tr-date" value="${esc(r.expires_on || "")}" aria-label="Printed use-by date"></label></div></div>`).join("")}</div>
      <div style="height:12px"></div><button class="btn" id="tr-apply">Apply all</button>`;
    $$("#trip .trip-row").forEach((el) => {
      const r = rows[+el.dataset.i];
      $(".tr-name", el).onchange = (e) => { r.name = e.target.value; };
      $(".tr-act", el).onchange = (e) => { r.action = e.target.value; el.classList.toggle("ignored", r.action === "ignore"); };
      $(".tr-qty", el).onchange = (e) => { r.quantity = e.target.value === "" ? null : +e.target.value; };
      $(".tr-unit", el).onchange = (e) => { r.unit = e.target.value; };
      $(".tr-loc", el).onchange = (e) => { r.location = e.target.value; };
      $(".tr-price input", el).onchange = (e) => { r.price = e.target.value === "" ? null : +e.target.value; };
      $(".tr-fill", el).onchange = (e) => { r.left = +e.target.value; };
      $(".tr-date", el).onchange = (e) => { r.expires_on = e.target.value || null; };
    });
    $("#tr-apply").onclick = async (e) => {
      e.currentTarget.disabled = true;
      try {
        const res = await api("POST", "/api/trip/apply", { store_id: T.store_id && T.store_id !== "other" ? T.store_id : null, store_name: T.store_name,
          date: T.read.date, method: "receipt", files: T.files,
          rows: rows.map((r) => ({ ...r, list_item_id: r.list_item?.id || null, pantry_item_id: r.pantry_item?.id ?? null })) });
        closeSheet();
        toast(res.summary, "Undo", async () => { try { await api("POST", `/api/trip/${enc(res.trip_id)}/undo`); toast("Trip undone"); after && after(); } catch (x) { fail(x); } });
        after && after();
      } catch (x) { fail(x); e.currentTarget && (e.currentTarget.disabled = false); }
    };
  }
}

// ------------------------------------------------------------------ pantry check-in (quick review)
async function openCheckin(after) {
  let items = [];
  try { items = (await api("GET", "/api/pantry")).items; } catch (e) { return fail(e); }
  const acted = new Set();
  openSheet("Inventory check-in", `<p class="hint" style="margin:0 4px 12px">Confirm what's still here. It takes a minute and keeps use-by dates and shopping lists accurate.</p>
    <div class="group">${items.map((it) => `<div class="row flush" data-id="${esc(it.id)}"><span class="emo">${esc(it.emoji || "🥫")}</span><div class="main"><div class="a">${esc(it.name)}</div><div class="b">${esc(cap(it.location))} · ${Math.round(it.amount_left * 100)}% left${it.expires_on ? ` · ${esc(relExpiry(it))}` : ""}</div></div>
      <div style="display:flex;gap:6px"><button class="pill-btn" data-a="keep" style="box-shadow:none;background:var(--fill)">✓</button><button class="pill-btn" data-a="half" style="box-shadow:none;background:var(--fill)">½</button><button class="pill-btn" data-a="gone" style="box-shadow:none;background:var(--fill);color:var(--red)">✕</button></div></div>`).join("") || `<div class="row flush muted">Your inventory is empty. Scan or add items first.</div>`}</div>
    <div style="height:14px"></div><button class="btn" id="ci-done">${ic("check")} Done</button>`, {
    onMount() {
      $$("[data-a]").forEach((b) => (b.onclick = async () => {
        const row = b.closest("[data-id]"), id = row.dataset.id, a = b.dataset.a, it = items.find((x) => String(x.id) === id);
        try {
          if (a === "gone") await api("PATCH", `/api/pantry/${enc(id)}`, { action: "use", left: 0 });
          if (a === "half") await api("PATCH", `/api/pantry/${enc(id)}`, { action: "use", left: Math.min(0.5, it.amount_left) });
          acted.add(id); row.style.opacity = a === "gone" ? ".35" : ".6";
          $$("[data-a]", row).forEach((x) => (x.style.background = x === b ? "var(--ink)" : "var(--fill)", x.style.color = x === b ? "var(--on-ink)" : ""));
        } catch (e) { fail(e); }
      }));
      $("#ci-done").onclick = async () => { await api("POST", "/api/pantry/checked").catch(() => {}); closeSheet(); toast("Inventory checked ✓"); after && after(); };
    },
  });
}

// ------------------------------------------------------------------ what's new (shown once per new version)
// ------------------------------------------------------------------ what's new: a feature feed (static/whatsnew.json);
// what's been seen is kept server-side so it shows once across devices.
async function loadWhatsNew() {
  try { const r = await fetch("/static/whatsnew.json", { cache: "no-cache" }); const d = await r.json(); return Array.isArray(d) ? d : []; } catch (_) { return []; }
}
const wnItem = (e) => `<li><span class="ic bg-${esc(e.color || "orange")}">${ic(e.icon || "sparkle")}</span><span><b>${esc(e.title)}</b><span>${esc(e.text)}</span></span></li>`;
async function maybeWhatsNew(tries = 0) {
  if (!state.cfg?.setup_complete) return;
  const busy = !!$("#layer")?.firstChild || !!$("#cook") || !!$(".wiz") || document.hidden;
  if (busy) { if (tries < 60) setTimeout(() => maybeWhatsNew(tries + 1), 5000); return; }
  const feed = await loadWhatsNew();
  const seen = new Set(state.cfg.settings?.whatsnew_seen || []);
  const unseen = feed.filter((e) => !seen.has(e.id));
  if (!unseen.length || $("#layer")?.firstChild || $("#cook")) return;
  const first = unseen.slice(0, 6), rest = unseen.slice(6);
  openSheet("What's new", `<div class="whatsnew"><ul>${first.map(wnItem).join("")}</ul>
      ${rest.length ? `<button class="link-btn" id="wn-more" aria-expanded="false">and ${esc(rest.length)} more</button><ul id="wn-rest" hidden>${rest.map(wnItem).join("")}</ul>` : ""}</div>
    <div style="height:14px"></div><button class="btn" id="wn-ok">Got it</button>`, {
    onMount() {
      $("#wn-more") && ($("#wn-more").onclick = (e) => { $("#wn-rest").hidden = false; e.currentTarget.remove(); });
      $("#wn-ok").onclick = async () => {
        closeSheet();
        const ids = [...new Set([...(state.cfg.settings?.whatsnew_seen || []), ...feed.map((e) => e.id)])].slice(-500);
        try { state.cfg.settings = await api("PUT", "/api/settings", { whatsnew_seen: ids }); } catch (_) {}
      };
    },
  });
}
async function openWhatsNewAll(back) {
  const feed = await loadWhatsNew();
  sheetBody().innerHTML = `<div class="btn-row" style="margin-bottom:12px"><button class="btn sec small" id="wn-back">${ic("chevL")} Settings</button></div>
    <div class="whatsnew"><ul>${feed.map(wnItem).join("")}</ul></div>`;
  $("#wn-back").onclick = back;
}

// ------------------------------------------------------------------ zoom / Home Screen tip (iOS keeps Safari's per-site page zoom)
function zoomedOut() { return window.innerWidth > (screen.width || window.innerWidth) * 1.12 && screen.width < 900; }
function zoomNudge() {
  if (!zoomedOut()) return "";
  const standalone = navigator.standalone || window.matchMedia("(display-mode: standalone)").matches;
  return `<div class="nudge" style="border:1px solid rgba(255,149,0,.4)"><span class="ic bg-orange">${ic("search")}</span><span><b>Everything looks tiny?</b><small>${standalone
    ? "This Home Screen app kept Safari's zoom. Open this page in Safari, tap <b>aA</b> → set zoom to <b>100%</b>, then remove this icon and tap Share → <b>Add to Home Screen</b> again."
    : "Safari's page zoom is below 100%. Tap <b>aA</b> in the address bar and choose <b>100%</b>. If you added TablePlan to your Home Screen, re-add it afterwards."}</small></span></div>`;
}

// ------------------------------------------------------------------ recipe editor (everything stays in TablePlan; Mealie stores it)
async function renderRecipeEditor(slug) {
  state.tab = "recipes"; renderTabs();
  app.innerHTML = loading();
  let rec;
  try { rec = await api("GET", `/api/recipe/${encodeURIComponent(slug)}`); } catch (e) { app.innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }
  let sec = null;
  const ingText = rec.ingredients.map((x) => { let t = ""; if (x.section && x.section !== sec) { sec = x.section; t = `# ${x.section}\n`; } return t + (x.raw || x.display || x.food); }).join("\n");
  const stepText = rec.steps.map((s) => s.text).join("\n\n");
  app.innerHTML = `${storageBar()}<div class="topbar"><button class="round-btn left" id="ed-x" aria-label="Cancel">${ic("x")}</button><button class="pill-btn dark" id="ed-save">${ic("check")} Save</button></div>
    <h1 class="title">Edit recipe</h1>
    <div class="group"><div class="field"><input class="full" id="ed-name" value="${esc(rec.name)}" placeholder="Recipe name"></div>
      <div class="field"><textarea class="full-area" id="ed-desc" rows="2" placeholder="Short description (optional)">${esc(rec.description)}</textarea></div></div>
    ${(state.cfg.settings.categories || []).length ? `<div class="group-label">Categories</div>
    <div class="ed-cats" id="ed-cats" role="group" aria-label="Categories">${state.cfg.settings.categories.map((c) => `<button type="button" class="filter sm ${(rec.categories || []).includes(c) ? "on" : ""}" data-cat="${esc(c)}" aria-pressed="${(rec.categories || []).includes(c)}">${esc(c)}</button>`).join("")}</div>` : ""}
    <div class="group-label">Details</div>
    <div class="group">
      <div class="field"><label>Servings</label><input type="number" id="ed-serv" min="0" step="0.5" value="${esc(rec.servings || "")}"></div>
      <div class="field"><label>Prep (min)</label><input type="number" id="ed-prep" min="0" value="${esc(rec.prep_minutes || "")}"></div>
      <div class="field"><label>Cook (min)</label><input type="number" id="ed-cook" min="0" value="${esc(rec.cook_minutes || "")}"></div>
      <div class="field"><label>Total (min)</label><input type="number" id="ed-total" min="0" value="${esc(rec.total_minutes || "")}"></div>
    </div>
    <div class="group-label">Ingredients</div>
    <div class="group"><textarea class="full-area mono" id="ed-ing" rows="${Math.min(18, (+rec.ingredients.length || 0) + 3)}" placeholder="One per line, e.g. 1 ½ cups heavy cream">${esc(ingText)}</textarea></div>
    <p class="hint">One ingredient per line, amount first (“2 cups flour”), so it scales. Start a line with # for a heading, like “# Sauce”.</p>
    <div class="group-label">Instructions</div>
    <div class="group"><textarea class="full-area" id="ed-steps" rows="${Math.min(20, (+rec.steps.length || 0) * 3 + 3)}" placeholder="Leave a blank line between steps">${esc(stepText)}</textarea></div>
    <p class="hint">Leave a blank line between steps.${rec.original ? ` <button type="button" class="link-btn inline" id="ed-orig">Restore original text</button>` : ""}</p>
    <div style="height:18px"></div><button class="btn red" id="ed-del">${ic("trash")} Delete recipe</button><div style="height:30px"></div>`;
  const back = () => (history.length > 1 ? history.back() : openRecipe(slug));
  $("#ed-x").onclick = back;
  $$("#ed-cats [data-cat]").forEach((b) => (b.onclick = () => { const on = !b.classList.contains("on"); b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }));
  $("#ed-orig") && ($("#ed-orig").onclick = () => {
    const o = rec.original;
    $("#ed-ing").value = (o.ingredients || []).join("\n");
    $("#ed-steps").value = (o.steps || []).join("\n\n");
    if (o.description) $("#ed-desc").value = o.description;
    toast("Original text restored. Save to keep it.");
  });
  $("#ed-save").onclick = async (e) => {
    const btn = e.currentTarget; btn.disabled = true;
    const body = { name: $("#ed-name").value, description: $("#ed-desc").value, servings: $("#ed-serv").value,
      prep_minutes: $("#ed-prep").value, cook_minutes: $("#ed-cook").value, total_minutes: $("#ed-total").value,
      ingredients: $("#ed-ing").value.split("\n"), steps: $("#ed-steps").value.split(/\n\s*\n/) };
    if ($("#ed-cats")) body.categories = $$("#ed-cats [data-cat].on").map((b) => b.dataset.cat);
    try { const r = await api("PUT", `/api/recipe/${encodeURIComponent(slug)}`, body); toast("Saved"); rstate.list = null; location.replace("#recipe/" + encodeURIComponent(r.slug)); }
    catch (x) { fail(x); btn.disabled = false; }
  };
  $("#ed-del").onclick = () => openSheet("Delete recipe?", `<p class="hint" style="margin:0 4px 14px">“${esc(rec.name)}” will be removed from your library and any meal plans that use it.</p><div class="btn-row"><button class="btn sec" id="dd-no">Cancel</button><button class="btn red" id="dd-yes">Delete</button></div>`, {
    onMount() {
      $("#dd-no").onclick = () => closeSheet();
      $("#dd-yes").onclick = async () => { try { await api("DELETE", `/api/recipe/${encodeURIComponent(slug)}`); closeSheet(true); toast("Recipe deleted"); go("recipes"); } catch (x) { fail(x); } };
    },
  });
}
