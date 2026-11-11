/* TablePlan — your account, household members, the "create your account" prompt and the onboarding checklist.
   Loaded after setup.js and before app.js; everything here runs only after app.js has booted. */
"use strict";

const ACCT = { me: null };
const accountsOn = () => !!(state.cfg && state.cfg.me);
const isAdmin = () => !accountsOn() || !!state.cfg.me.admin;

// ------------------------------------------------------------------ deep links used by the checklist
const SETTINGS_LINKS = { account: "Your account", members: "Members", household: "Household", notify: "Notifications", ai: "AI recipe import" };
function openLink(link) {
  if (!link) return;
  if (link.startsWith("#")) { closeSheet(true); location.hash = link.slice(1); return; }
  if (link.startsWith("stock:")) return stockAt(link.slice(6));
  const k = link.startsWith("settings:") ? link.slice(9) : "";
  if (k === "account") return accountView();
  if (k === "members") return membersView();
  if (["household", "notify", "ai"].includes(k)) return openSetupSection(k, SETTINGS_LINKS[k], reloadCfg);
  openSettings();
}

// "Inventory your spice cabinet": open Stock up with that place picked (adding the place if it's new).
async function stockAt(key) {
  closeSheet(true);
  if (!invPlaces().some(([k]) => k === key)) {
    try { const r = await api("POST", "/api/places/ensure", { key }); state.cfg.settings.locations = r.locations; } catch (e) { return fail(e); }
  }
  SS.loc = key; try { localStorage.setItem("tp.scanLoc", key); } catch (_) {}
  if (location.hash !== "#pantry") go("pantry");
  setTimeout(() => startStockUp(renderPantry), 300);
}

// ------------------------------------------------------------------ Settings → Account
function sheetFor(title, back) {
  if (!back || !$("#layer .sheet")) openSheet(title, "");
  const body = sheetBody();
  const h = $("#layer .sheet-h h3"); if (h) h.textContent = title;
  return body;
}
const backRow = (back) => (back ? `<button class="link-btn" id="ac-back">${ic("chevL")} Settings</button>` : "");
const bindBack = (back) => { $("#ac-back") && ($("#ac-back").onclick = () => { const h = $("#layer .sheet-h h3"); if (h) h.textContent = "Settings"; back(); }); };

async function accountView(back) {
  const body = sheetFor("Your account", back);
  body.innerHTML = loading();
  let sess = {};
  try { sess = await api("GET", "/api/session"); } catch (e) { return fail(e); }
  const me = sess.me;
  if (!me) {
    // No accounts yet: create the first (admin) account here.
    body.innerHTML = `${backRow(back)}<div class="wiz-in-sheet"><div id="ac-form"></div><div class="wiz-err" id="ac-err"></div><div style="height:12px"></div><button class="btn" id="ac-save">Create my account</button></div>`;
    bindBack(back);
    const st = { session: sess };
    Setup.account($("#ac-form"), st);
    $("#ac-save").onclick = async (ev) => {
      const b = ev.currentTarget; b.disabled = true;
      try { await $("#ac-form")._submit(); toast("Account created. You're the admin."); location.reload(); }
      catch (e) { $("#ac-err").textContent = e.message; b.disabled = false; }
    };
    return;
  }
  body.innerHTML = `${backRow(back)}
    <div class="acct-head"><span class="who-av" aria-hidden="true">${esc(me.name.charAt(0).toUpperCase())}</span><div><b>${esc(me.name)}</b><span>${me.admin ? "Household admin" : "Member"} · signs in with a ${me.kind === "pin" ? "PIN" : "password"}</span></div></div>
    <div class="group-label">Profile</div>
    <div class="group">
      <div class="field"><label for="me-name">Name</label><input id="me-name" maxlength="40" value="${esc(me.name)}" autocomplete="name"></div>
      <div class="field"><label for="me-email">Email</label><input id="me-email" type="email" maxlength="254" value="${esc(me.email)}" autocomplete="email" placeholder="Optional"></div>
      <div class="field"><label for="me-notify">Email me notifications<small class="lh">Plans, shopping lists and use-soon alerts, when email is set up.</small></label><label class="toggle"><input type="checkbox" id="me-notify" ${me.notify_email ? "checked" : ""}><span></span></label></div>
    </div>
    <div class="group-label">Change how you sign in</div>
    <div class="group" style="padding:10px 14px"><div class="wfield" style="padding:0 0 10px"><label for="me-cur">Current ${me.kind === "pin" ? "PIN" : "password"}</label><input id="me-cur" type="password" autocomplete="current-password" maxlength="256"></div>
      <div id="me-new"></div><div class="wiz-err" id="me-err"></div><div style="height:8px"></div><button class="btn sec" id="me-secret">Save new ${sess.pin_allowed ? "password or PIN" : "password"}</button></div>
    <p class="hint">Changing it signs you out on your other devices.</p>
    <div class="group"><button class="row" id="me-out"><div class="main"><div class="a" style="color:var(--red)">Sign out on this device</div></div></button></div>`;
  bindBack(back);
  const getNew = accountFields($("#me-new"), { pinAllowed: sess.pin_allowed, withName: false, withEmail: false, label: "New" });
  const savePatch = async (patch, msg) => {
    try { const r = await api("PATCH", "/api/me", patch); state.cfg.me = r.me; toast(msg || "Saved"); } catch (e) { fail(e); }
  };
  $("#me-name").onchange = (e) => savePatch({ name: e.target.value });
  $("#me-email").onchange = (e) => savePatch({ email: e.target.value });
  $("#me-notify").onchange = (e) => {
    if (e.target.checked && !$("#me-email").value.trim()) { e.target.checked = false; return toast("Add your email first"); }
    savePatch({ notify_email: e.target.checked, email: $("#me-email").value }, e.target.checked ? "You'll get notifications by email" : "Email notifications off");
  };
  $("#me-secret").onclick = async (ev) => {
    const b = ev.currentTarget; $("#me-err").textContent = "";
    try {
      const v = getNew();
      b.disabled = true;
      await api("POST", "/api/me/secret", { current: $("#me-cur").value, kind: v.kind, secret: v.secret });
      toast(`New ${v.kind === "pin" ? "PIN" : "password"} saved`); accountView(back);
    } catch (e) { $("#me-err").textContent = e.message; b.disabled = false; }
  };
  $("#me-out").onclick = async () => { await api("POST", "/api/logout").catch(() => {}); location.reload(); };
}

// ------------------------------------------------------------------ Settings → Members (admins manage, everyone can see)
async function membersView(back) {
  const body = sheetFor("Members", back);
  body.innerHTML = loading();
  let d;
  try { d = await api("GET", "/api/users"); } catch (e) { return fail(e); }
  const admin = d.me && d.me.admin;
  if (!d.me) {
    body.innerHTML = `${backRow(back)}<div class="empty"><b>Create your account first</b><span>Then add everyone in your household, each with their own sign-in.</span><button class="btn" id="mb-first">Create my account</button></div>`;
    bindBack(back);
    $("#mb-first").onclick = () => accountView(back);
    return;
  }
  body.innerHTML = `${backRow(back)}
    <p class="hint">Everyone shares the same recipes, plans, lists and inventory. Each person has their own sign-in, theme and checklist.</p>
    <div class="group">${d.users.map((u) => `<button class="row" data-uid="${esc(u.id)}" ${admin ? "" : "disabled"}>
      <span class="who-av sm" aria-hidden="true">${esc(u.name.charAt(0).toUpperCase())}</span>
      <div class="main"><div class="a">${esc(u.name)}${u.id === d.me.id ? " <span class=\"muted\">(you)</span>" : ""}</div><div class="b">${esc([u.admin ? "Admin" : "Member", u.kind === "pin" ? "PIN" : "Password", u.email].filter(Boolean).join(" · "))}</div></div>
      ${admin ? `<span class="chev">${ic("chevR")}</span>` : ""}</button>`).join("")}</div>
    ${admin ? `<button class="btn" id="mb-add">${ic("plus")} Add someone</button>` : `<p class="hint">Ask an admin to add people or reset a password.</p>`}`;
  bindBack(back);
  if (!admin) return;
  $("#mb-add").onclick = () => memberEditor(null, d, back);
  $$("[data-uid]", body).forEach((b) => (b.onclick = () => memberEditor(d.users.find((u) => String(u.id) === b.dataset.uid), d, back)));
}

function memberEditor(u, d, back) {
  const body = sheetBody(), self = u && u.id === d.me.id;
  const again = () => membersView(back);
  body.innerHTML = `<button class="link-btn" id="me-back">${ic("chevL")} Members</button>
    <h3 class="sub-h">${u ? esc(u.name) : "Add someone"}</h3>
    ${u ? `<div class="group">
        <div class="field"><label for="mu-name">Name</label><input id="mu-name" maxlength="40" value="${esc(u.name)}"></div>
        <div class="field"><label for="mu-email">Email</label><input id="mu-email" type="email" maxlength="254" value="${esc(u.email)}" placeholder="Optional"></div>
        <div class="field"><label for="mu-admin">Admin<small class="lh">Admins add and remove people, reset sign-ins and use the Danger zone.</small></label><label class="toggle"><input type="checkbox" id="mu-admin" ${u.admin ? "checked" : ""} ${self ? "disabled" : ""}><span></span></label></div>
      </div>
      <div class="group-label">${self ? "Your sign-in" : `Reset ${esc(u.name)}'s sign-in`}</div>
      <div class="group" style="padding:10px 14px">${self ? `<p class="hint" style="margin:0">Change yours in Settings → Your account.</p>` : `<div id="mu-secret"></div><div class="wiz-err" id="mu-err"></div><div style="height:8px"></div><button class="btn sec" id="mu-reset">Set new ${d.pin_allowed ? "password or PIN" : "password"}</button>`}</div>
      ${self ? "" : `<div style="height:12px"></div><button class="btn red" id="mu-rm">Remove ${esc(u.name)}</button><p class="hint">Their recipes, plans and diary entries stay. They're signed out everywhere.</p>`}`
    : `<div id="mu-form"></div><div class="field" style="margin-top:10px"><label for="mu-admin">Make them an admin</label><label class="toggle"><input type="checkbox" id="mu-admin"><span></span></label></div>
       <div class="wiz-err" id="mu-err"></div><div style="height:10px"></div><button class="btn" id="mu-create">Add to household</button>`}`;
  $("#me-back").onclick = again;
  if (!u) {
    const get = accountFields($("#mu-form"), { pinAllowed: d.pin_allowed });
    $("#mu-create").onclick = async (ev) => {
      const b = ev.currentTarget; $("#mu-err").textContent = "";
      try { const v = get(); b.disabled = true; await api("POST", "/api/users", { ...v, admin: $("#mu-admin").checked }); toast(`${v.name} can sign in now`); again(); }
      catch (e) { $("#mu-err").textContent = e.message; b.disabled = false; }
    };
    return;
  }
  const patch = async (p) => { try { await api("PATCH", `/api/users/${enc(u.id)}`, p); toast("Saved"); } catch (e) { fail(e); memberEditor(u, d, back); } };
  $("#mu-name").onchange = (e) => patch({ name: e.target.value });
  $("#mu-email").onchange = (e) => patch({ email: e.target.value });
  $("#mu-admin").onchange = (e) => patch({ admin: e.target.checked });
  if (self) return;
  const get = accountFields($("#mu-secret"), { pinAllowed: d.pin_allowed, withName: false, withEmail: false, label: "New" });
  $("#mu-reset").onclick = async (ev) => {
    const b = ev.currentTarget; $("#mu-err").textContent = "";
    try { const v = get(); b.disabled = true; await api("POST", `/api/users/${enc(u.id)}/secret`, { kind: v.kind, secret: v.secret }); toast(`${u.name}'s ${v.kind === "pin" ? "PIN" : "password"} was reset`); again(); }
    catch (e) { $("#mu-err").textContent = e.message; b.disabled = false; }
  };
  $("#mu-rm").onclick = async (ev) => {
    const b = ev.currentTarget;
    if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = `Tap again to remove ${u.name}`; return; }
    try { await api("DELETE", `/api/users/${enc(u.id)}`); toast(`${u.name} was removed`); again(); } catch (e) { fail(e); }
  };
}

// ------------------------------------------------------------------ "Create your account" on existing installs
async function maybeAccountPrompt(sess) {
  if (!sess || !sess.needs_account) return;
  let st = {};
  try { st = (await api("GET", "/api/me")).state || {}; } catch (_) {}
  if (!sess.public && +st.account_prompt > Date.now()) return;   // "Not now" for a few days
  openSheet("Create your account", `<div class="wiz-in-sheet"><div id="ap-form"></div><div class="wiz-err" id="ap-err"></div>
    <div class="wiz-actions">${sess.public ? "" : `<button class="btn sec" id="ap-later">Not now</button>`}<button class="btn" id="ap-save">Create my account</button></div></div>`);
  Setup.account($("#ap-form"), { session: sess });
  $("#ap-later") && ($("#ap-later").onclick = async () => { await api("PUT", "/api/me/state", { account_prompt: Date.now() + 3 * 864e5 }).catch(() => {}); closeSheet(); });
  $("#ap-save").onclick = async (ev) => {
    const b = ev.currentTarget; b.disabled = true;
    try { await $("#ap-form")._submit(); toast("Account created. You're the admin."); setTimeout(() => location.reload(), 600); }
    catch (e) { $("#ap-err").textContent = e.message; b.disabled = false; }
  };
}

// ------------------------------------------------------------------ onboarding checklist (per person, server-side)
const CL_PAGES = [["", "No link"], ["#recipes", "Recipes"], ["#meals", "Plan"], ["#list", "Shopping"], ["#pantry", "Inventory"], ["#diary", "Cooking diary"], ["settings:notify", "Notifications"], ["settings:members", "Members"]];

async function homeChecklist(box) {
  let cl;
  try { cl = await api("GET", "/api/checklist"); } catch (_) { return; }
  if (!box.isConnected || cl.dismissed || !cl.total) return;
  const shown = cl.items.filter((i) => !i.hidden), next = shown.filter((i) => !i.done);
  box.hidden = false;
  if (cl.complete) {
    box.innerHTML = `<div class="hc-h"><h2>Getting started</h2></div><div class="cl-done"><b>All done ✓</b><span>You've set up everything on your checklist.</span>
      <button class="btn sec small" id="cl-dismiss">Hide this card</button></div>`;
    $("#cl-dismiss").onclick = async () => { try { await api("POST", "/api/checklist", { action: "dismiss" }); box.hidden = true; } catch (e) { fail(e); } };
    return;
  }
  const pct = Math.round((cl.done / cl.total) * 100);
  box.innerHTML = `<div class="hc-h"><h2>Getting started <span>· ${esc(cl.done)} of ${esc(cl.total)}</span></h2><button class="link-btn" id="cl-all">See all ›</button></div>
    <div class="cl-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${esc(cl.total)}" aria-valuenow="${esc(cl.done)}" aria-label="${esc(cl.done)} of ${esc(cl.total)} done"><i style="width:${pct}%"></i></div>
    <div class="cl-rows">${next.slice(0, 3).map((i) => clRow(i)).join("")}</div>
    ${next[0] && next[0].link ? `<button class="btn small" id="cl-resume">Resume: ${esc(next[0].title)}</button>` : ""}`;
  bindClRows(box, () => homeChecklist(box));
  $("#cl-all").onclick = () => checklistSheet(() => homeChecklist(box));
  $("#cl-resume") && ($("#cl-resume").onclick = () => openLink(next[0].link));
}

const clRow = (i, menu = false) => `<div class="cl-row ${i.done ? "done" : ""}" data-cl="${esc(i.id)}">
  <button class="check sq ${i.done ? "on" : ""}" data-tick="${esc(i.id)}" ${i.auto ? `disabled aria-label="${esc(i.title)}: done automatically"` : `aria-label="${i.done ? "Mark not done" : "Mark done"}: ${esc(i.title)}"`}>${ic("check")}</button>
  ${i.link ? `<button class="cl-t" data-link="${esc(i.link)}">${esc(i.title)}<span class="chev">${ic("chevR")}</span></button>` : `<span class="cl-t">${esc(i.title)}</span>`}
  ${menu ? `<button class="mini" data-clm="${esc(i.id)}" aria-label="More for ${esc(i.title)}">${ic("more")}</button>` : ""}</div>`;

function bindClRows(root, after) {
  $$("[data-tick]", root).forEach((b) => (b.onclick = async () => {
    const on = b.classList.contains("on");
    try { await api("POST", "/api/checklist", { action: on ? "untick" : "tick", id: b.dataset.tick }); after(); } catch (e) { fail(e); }
  }));
  $$("[data-link]", root).forEach((b) => (b.onclick = () => openLink(b.dataset.link)));
}

async function checklistSheet(after) {
  if (!$("#layer .sheet")) openSheet("Getting started", loading());
  const draw = async () => {
    let cl;
    try { cl = await api("GET", "/api/checklist"); } catch (e) { return fail(e); }
    const shown = cl.items.filter((i) => !i.hidden), hidden = cl.items.filter((i) => i.hidden);
    const body = sheetBody(); if (!body) return;
    body.innerHTML = `<p class="hint">${esc(cl.done)} of ${esc(cl.total)} done. Items tick themselves as you go, or tick them yourself.</p>
      <div class="group cl-list">${shown.map((i) => clRow(i, true)).join("")}</div>
      ${hidden.length ? `<div class="group-label">Hidden</div><div class="group">${hidden.map((i) => `<div class="cl-row"><span class="cl-t muted">${esc(i.title)}</span><button class="link-btn" data-unhide="${esc(i.id)}">Show</button></div>`).join("")}</div>` : ""}
      <div class="group-label">Add your own</div>
      <form class="group cl-add" id="cl-add"><div class="field"><label for="cl-new">Item</label><input id="cl-new" maxlength="80" placeholder="e.g. Try the barcode scanner"></div>
        <div class="field"><label for="cl-link">Opens</label><select id="cl-link">${CL_PAGES.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select></div>
        <div style="padding:8px 14px 12px"><button class="btn sec small" type="submit">Add</button></div></form>
      ${cl.complete && !cl.dismissed ? `<button class="btn" id="cl-dis">All done: hide the Home card</button>` : ""}
      ${cl.dismissed ? `<button class="btn sec" id="cl-restore">Show the card on Home again</button>` : ""}`;
    bindClRows(body, () => { draw(); after && after(); });
    $$("[data-unhide]", body).forEach((b) => (b.onclick = () => act({ action: "unhide", id: b.dataset.unhide })));
    $$("[data-clm]", body).forEach((b) => (b.onclick = () => {
      const it = cl.items.find((x) => x.id === b.dataset.clm);
      popover(b, `<button data-a="rename">${ic("edit")} Rename</button><button data-a="hide">${ic("x")} Hide</button>${it.custom ? `<button data-a="remove" class="red">${ic("trash")} Remove</button>` : ""}`, (el) => {
        $$("[data-a]", el).forEach((x) => (x.onclick = () => {
          closePop();
          if (x.dataset.a === "rename") return renameRow(it);
          act({ action: x.dataset.a, id: it.id });
        }));
      });
    }));
    $("#cl-add").onsubmit = (e) => { e.preventDefault(); const t = $("#cl-new").value.trim(); if (t) act({ action: "add", title: t, link: $("#cl-link").value }); };
    $("#cl-dis") && ($("#cl-dis").onclick = () => act({ action: "dismiss" }));
    $("#cl-restore") && ($("#cl-restore").onclick = () => act({ action: "restore" }));
  };
  const act = async (b) => { try { await api("POST", "/api/checklist", b); } catch (e) { fail(e); } draw(); after && after(); };
  const renameRow = (it) => {
    const row = $(`[data-cl="${CSS.escape(it.id)}"]`, sheetBody()); if (!row) return;
    row.innerHTML = `<form class="cl-ren"><input maxlength="80" value="${esc(it.title)}" aria-label="New name" placeholder="${esc(it.default_title || "")}"><button class="btn small" type="submit">Save</button></form>`;
    const f = $("form", row), inp = $("input", row); inp.focus(); inp.select();
    f.onsubmit = (e) => { e.preventDefault(); act({ action: "rename", id: it.id, title: inp.value.trim() }); };
  };
  const h = $("#layer .sheet-h h3"); if (h) h.textContent = "Getting started";
  draw();
}
