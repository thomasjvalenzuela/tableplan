/* TablePlan — sign-in, first-run setup wizard, and the setup sections reused by Settings. Loaded before app.js. */
"use strict";

// Small helpers (app.js defines the full set; these are safe duplicates for the wizard, which can run first).
const _esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
async function _api(method, path, body) {
  const res = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined, credentials: "same-origin" });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const e = new Error((data && data.error) || `Request failed (${res.status})`); e.status = res.status; throw e; }
  return data;
}

// ------------------------------------------------------------------ sign-in screen
function renderLogin(onDone) {
  document.querySelector(".tabbar").style.display = "none";
  const root = document.getElementById("app");
  root.innerHTML = `<div class="wiz"><div class="wiz-card fade-in" style="max-width:380px">
    <div class="wiz-logo"><img src="/static/icon.svg" alt=""></div>
    <h2 class="wiz-title">TablePlan</h2><p class="wiz-sub">Enter the household password.</p>
    <form id="lg"><div class="wfield"><input type="password" id="lg-pw" placeholder="Password" autocomplete="current-password" autofocus></div>
    <div class="wiz-err" id="lg-err"></div>
    <button class="btn" type="submit">Sign in</button></form></div></div>`;
  document.getElementById("lg").onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button"); btn.disabled = true;
    try { await _api("POST", "/api/login", { password: document.getElementById("lg-pw").value }); document.querySelector(".tabbar").style.display = ""; onDone(); }
    catch (err) { document.getElementById("lg-err").textContent = err.message; btn.disabled = false; }
  };
}

// ------------------------------------------------------------------ reusable setup sections
// Each section renders into `el`, reports progress through `done(result)`, and works in both the wizard and Settings.

const Setup = {
  household(el, st, done) {
    const h = st.household || {};
    el.innerHTML = `
      <div class="wgroup">
        <div class="wfield"><label>Household name</label><input id="hh-name" placeholder="The Valenzuelas" value="${_esc(h.name || "")}"></div>
        <div class="wfield"><label>How many people do you cook for?</label>
          <div class="stepper"><button type="button" data-d="-1">−</button><b id="hh-n">${h.people || 2}</b><button type="button" data-d="1">+</button></div></div>
        <div class="wfield"><label>Scale recipes to fit</label><label class="toggle"><input type="checkbox" id="hh-scale" ${h.scale !== false ? "checked" : ""}><span></span></label></div>
      </div>
      <p class="whint">When you plan a meal, TablePlan sets the serving scale so a recipe written for 4 automatically shopping-lists for ${h.people || 2}. You can still change servings on any recipe.</p>`;
    let n = h.people || 2;
    el.querySelectorAll("[data-d]").forEach((b) => (b.onclick = () => { n = Math.max(1, Math.min(30, n + +b.dataset.d)); el.querySelector("#hh-n").textContent = n; el.querySelector(".whint").innerHTML = el.querySelector(".whint").innerHTML.replace(/for \d+\./, `for ${n}.`); }));
    return async () => {
      const r = await _api("POST", "/api/setup/household", { name: el.querySelector("#hh-name").value, people: n, scale: el.querySelector("#hh-scale").checked });
      done && done(r); return true;
    };
  },

  mealie(el, st, done) {
    const m = st.mealie || {};
    if (!m.reachable) {
      el.innerHTML = `<div class="wstatus bad"><b>Can't reach Mealie yet</b><span>${_esc(m.error || "")}</span></div>
        <p class="whint">Mealie takes about a minute to start the first time. If you installed TablePlan from the ZimaOS App Store or the installer, Mealie is already included. Just wait and retry.</p>
        <button class="btn sec" id="ml-retry">Check again</button>`;
      el.querySelector("#ml-retry").onclick = async () => { el.innerHTML = '<div class="spinner"></div>'; st.mealie = await _api("GET", "/api/setup/mealie").catch((e) => ({ error: e.message })); Setup.mealie(el, st, done); };
      return async () => { throw new Error("Mealie needs to be running before you continue. You can also skip this for now."); };
    }
    if (m.connected) {
      el.innerHTML = `<div class="wstatus ok"><b>Connected to Mealie ${_esc(m.version || "")}</b><span>Signed in as ${_esc(m.user?.name || "")} · ${_esc(m.user?.email || "")}</span></div>
        <p class="whint">TablePlan stores your recipes, plans and lists in Mealie. You can still open Mealie directly for advanced recipe editing.</p>
        <button class="btn sec" id="ml-switch">Use a different account</button>`;
      el.querySelector("#ml-switch").onclick = () => { st.mealie = { ...m, connected: false }; Setup.mealie(el, st, done); };
      return async () => true;
    }
    const first = m.first_login;
    const draw = (mode) => {
      el.innerHTML = `
        ${first ? `<p class="wlead">Mealie is installed and waiting. Create the login your household will use. TablePlan sets everything else up.</p>` :
                  `<p class="wlead">Sign in with your Mealie account. TablePlan creates its own secure access key, and your password isn't stored.</p>`}
        <div class="seg wseg"><button data-m="form" class="${mode === "form" ? "on" : ""}">${first ? "Create account" : "Sign in"}</button><button data-m="token" class="${mode === "token" ? "on" : ""}">Use API token</button></div>
        ${mode === "form" ? `<div class="wgroup">
          ${first ? `<div class="wfield"><label>Your name</label><input id="ml-name" autocomplete="name" placeholder="Thomas"></div>` : ""}
          <div class="wfield"><label>Email</label><input id="ml-email" type="email" autocomplete="username" placeholder="you@example.com"></div>
          <div class="wfield"><label>Password</label><input id="ml-pw" type="password" autocomplete="${first ? "new-password" : "current-password"}" placeholder="${first ? "At least 8 characters" : ""}"></div>
        </div>${first ? `<p class="whint">This replaces Mealie's default login (changeme@example.com), so no one else can use it.</p>` : ""}` :
        `<div class="wgroup"><div class="wfield"><label>Mealie API token</label><input id="ml-token" placeholder="eyJhbGciOi…"></div></div>
         <p class="whint">To get one, open Mealie and go to Profile → API Tokens → Create.</p>`}`;
      el.querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => draw(b.dataset.m)));
      el.dataset.mode = mode;
    };
    draw("form");
    return async () => {
      let r;
      if (el.dataset.mode === "token") r = await _api("POST", "/api/setup/mealie/token", { token: el.querySelector("#ml-token").value });
      else if (first) r = await _api("POST", "/api/setup/mealie/create-account", { name: el.querySelector("#ml-name").value, email: el.querySelector("#ml-email").value, password: el.querySelector("#ml-pw").value });
      else r = await _api("POST", "/api/setup/mealie/sign-in", { email: el.querySelector("#ml-email").value, password: el.querySelector("#ml-pw").value });
      st.mealie = r; done && done(r); return true;
    };
  },

  ai(el, st, done) {
    const a = st.ai || {};
    if (!st.mealie?.connected) {
      el.innerHTML = `<div class="wstatus"><b>Connect Mealie first</b><span>AI import is configured inside Mealie.</span></div>`;
      return async () => true;
    }
    el.innerHTML = `
      ${a.enabled ? `<div class="wstatus ok"><b>AI import is on</b><span>${a.images ? "Screenshots & photos ✓" : "Text only"}${a.audio ? " · Video links ✓" : ""}</span></div>` : ""}
      <p class="wlead">Turn a screenshot, a photo of a cookbook page, or a TikTok/YouTube link into a full recipe. It uses your own OpenAI key and costs a few cents per recipe.</p>
      <div class="wgroup">
        <div class="wfield"><label>OpenAI API key</label><input id="ai-key" type="password" placeholder="${a.enabled ? "•••••• saved (enter to replace)" : "sk-…"}" autocomplete="off"></div>
        <div class="wfield"><label>Model</label><input id="ai-model" value="gpt-5-mini"></div>
        <div class="wfield"><label>Also read video links</label><label class="toggle"><input type="checkbox" id="ai-audio" checked><span></span></label></div>
      </div>
      <p class="whint">Create a key at platform.openai.com → API keys. TablePlan tests the key before saving it. The model has to read images; gpt-5-mini works and is inexpensive.</p>`;
    return async () => {
      const key = el.querySelector("#ai-key").value.trim();
      if (!key) { if (a.enabled) return true; throw new Error("Paste an OpenAI key, or tap Skip to set this up later."); }
      const r = await _api("POST", "/api/setup/ai", { api_key: key, model: el.querySelector("#ai-model").value, audio: el.querySelector("#ai-audio").checked });
      st.ai = r; done && done(r); return true;
    };
  },

  email(el, st, done) {
    const e = st.email || {};
    const presets = [["gmail", "Gmail / Google Workspace"], ["outlook", "Outlook / Microsoft 365"], ["icloud", "iCloud Mail"], ["yahoo", "Yahoo"], ["custom", "Other (SMTP)"]];
    const guess = e.host ? (presets.find(([k]) => ({ gmail: "smtp.gmail.com", outlook: "smtp.office365.com", icloud: "smtp.mail.me.com", yahoo: "smtp.mail.yahoo.com" })[k] === e.host) || ["custom"])[0] : "gmail";
    const help = {
      gmail: "Use an <b>App Password</b>: Google Account → Security → 2-Step Verification → App passwords. Your normal password won't work.",
      outlook: "Use your Microsoft password, or an app password if 2-step sign-in is on. SMTP has to be allowed for your mailbox.",
      icloud: "Create an app-specific password at appleid.apple.com → Sign-In and Security.",
      yahoo: "Generate an app password in Yahoo Account Security.",
      custom: "Enter your mail provider's SMTP server details.",
    };
    const draw = (p) => {
      el.innerHTML = `
        ${e.configured ? `<div class="wstatus ok"><b>Email is set up</b><span>${_esc(e.from || e.user || "")} → ${_esc((e.to || []).join(", "))}</span></div>` : ""}
        <p class="wlead">Send shopping lists, meal plans and pantry reports to your inbox.</p>
        <div class="wgroup">
          <div class="wfield"><label>Provider</label><select id="em-p">${presets.map(([k, l]) => `<option value="${k}" ${k === p ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          ${p === "custom" ? `<div class="wfield"><label>SMTP server</label><input id="em-host" value="${_esc(e.host || "")}" placeholder="smtp.example.com"></div>
            <div class="wfield"><label>Port</label><input id="em-port" type="number" value="${e.port || 587}"></div>
            <div class="wfield"><label>Security</label><select id="em-sec">${["starttls", "ssl", "none"].map((x) => `<option ${x === (e.security || "starttls") ? "selected" : ""}>${x}</option>`).join("")}</select></div>` : ""}
          <div class="wfield"><label>Your email</label><input id="em-user" type="email" value="${_esc(e.user || "")}" placeholder="you@gmail.com" autocomplete="off"></div>
          <div class="wfield"><label>${p === "gmail" ? "App password" : "Password"}</label><input id="em-pw" type="password" placeholder="${e.has_password ? "•••••• saved" : ""}" autocomplete="off"></div>
          <div class="wfield"><label>Send lists to</label><input id="em-to" value="${_esc((e.to || []).join(", "))}" placeholder="Same as above, or add more, comma-separated"></div>
        </div>
        <p class="whint">${help[p]} When you continue, TablePlan sends a test email.</p>`;
      el.querySelector("#em-p").onchange = (ev) => draw(ev.target.value);
      el.dataset.p = p;
    };
    draw(guess);
    return async () => {
      const p = el.dataset.p, user = el.querySelector("#em-user").value.trim(), pw = el.querySelector("#em-pw").value;
      if (!user && !e.configured) throw new Error("Enter your email address, or tap Skip to set this up later.");
      if (!user && e.configured) return true;
      const body = { preset: p === "custom" ? "" : p, smtp_user: user, smtp_from: user, smtp_password: pw, mail_to: el.querySelector("#em-to").value || user, test: true };
      if (p === "custom") Object.assign(body, { smtp_host: el.querySelector("#em-host").value, smtp_port: +el.querySelector("#em-port").value, smtp_security: el.querySelector("#em-sec").value });
      const r = await _api("POST", "/api/setup/email", body);
      st.email = r; done && done(r); return true;
    };
  },

  password(el, st, done) {
    const set = st.password?.set;
    el.innerHTML = `
      <p class="wlead">${set ? "A password is set. Anyone opening TablePlan has to enter it once on each device." : "Optional. Anyone on your home Wi-Fi can open TablePlan. Add a password if you want it locked."}</p>
      <div class="wgroup"><div class="wfield"><label>${set ? "New password" : "Password"}</label><input id="pw-1" type="password" autocomplete="new-password" placeholder="Leave blank for no password"></div></div>
      ${set ? `<button class="btn red" id="pw-rm" type="button">Remove password</button>` : ""}`;
    if (set) el.querySelector("#pw-rm").onclick = async () => { await _api("POST", "/api/setup/password", { password: "" }); st.password = { set: false }; Setup.password(el, st, done); };
    return async () => {
      const pw = el.querySelector("#pw-1").value;
      if (!pw) return true;
      await _api("POST", "/api/setup/password", { password: pw });
      st.password = { set: true }; done && done(); return true;
    };
  },
};

// ------------------------------------------------------------------ first-run wizard
const WIZ_STEPS = [
  { key: "welcome", title: "Welcome to TablePlan", sub: "Recipes, meal plans, a smart pantry and grocery lists for your household. This takes about 3 minutes, and you can skip anything and finish it later in Settings." },
  { key: "household", title: "Your household", sub: "This sets how much every recipe makes." , section: "household" },
  { key: "mealie", title: "Recipe library", sub: "TablePlan keeps recipes in Mealie, which is included and runs on your server.", section: "mealie", skippable: true },
  { key: "ai", title: "Import from screenshots", sub: "Let AI read recipe photos, screenshots and videos.", section: "ai", skippable: true },
  { key: "email", title: "Email", sub: "Get grocery lists and meal plans in your inbox.", section: "email", skippable: true },
  { key: "password", title: "Lock it (optional)", sub: "Protect TablePlan with a household password.", section: "password", skippable: true },
  { key: "done", title: "You're all set", sub: "" },
];

async function runWizard(onFinish) {
  document.querySelector(".tabbar").style.display = "none";
  const root = document.getElementById("app");
  root.innerHTML = `<div class="wiz"><div class="spinner"></div></div>`;
  let st = await _api("GET", "/api/setup/status").catch(() => ({}));
  let i = 0, submit = null;

  const draw = () => {
    const step = WIZ_STEPS[i];
    const dots = WIZ_STEPS.map((_, n) => `<i class="${n === i ? "on" : n < i ? "past" : ""}"></i>`).join("");
    root.innerHTML = `<div class="wiz"><div class="wiz-card fade-in">
      <div class="wiz-dots">${dots}</div>
      ${step.key === "welcome" || step.key === "done" ? `<div class="wiz-logo"><img src="/static/icon.svg" alt=""></div>` : ""}
      <h2 class="wiz-title">${_esc(step.title)}</h2>${step.sub ? `<p class="wiz-sub">${_esc(step.sub)}</p>` : ""}
      <div id="wiz-body"></div><div class="wiz-err" id="wiz-err"></div>
      <div class="wiz-actions">
        ${i > 0 && step.key !== "done" ? `<button class="btn sec" id="wz-back">Back</button>` : ""}
        ${step.skippable ? `<button class="btn sec" id="wz-skip">Skip</button>` : ""}
        <button class="btn" id="wz-next">${step.key === "welcome" ? "Get started" : step.key === "done" ? "Open TablePlan" : "Continue"}</button>
      </div></div></div>`;
    const body = document.getElementById("wiz-body");
    submit = null;
    if (step.section) submit = Setup[step.section](body, st);
    if (step.key === "welcome") body.innerHTML = `<ul class="wiz-feats">
        <li><b>🍳 Recipes from anywhere</b><span>Links, screenshots and cookbook photos</span></li>
        <li><b>🗓️ Auto meal plans</b><span>A week or a month in one tap</span></li>
        <li><b>🥛 Smart pantry</b><span>Real use-by dates that update as you cook</span></li>
        <li><b>🛒 Shopping lists</b><span>Scaled to your household, emailed or printed</span></li></ul>`;
    if (step.key === "done") {
      const row = (ok, label, todo) => `<li class="${ok ? "ok" : ""}"><b>${ok ? "✓" : "○"} ${label}</b><span>${ok ? "" : _esc(todo)}</span></li>`;
      body.innerHTML = `<ul class="wiz-feats">
        ${row(st.mealie?.connected, "Recipe library connected", "Settings → Mealie")}
        ${row(st.ai?.enabled, "Screenshot import", "Settings → AI recipe import")}
        ${row(st.email?.configured, "Email", "Settings → Email")}
        ${row(true, `Cooking for ${st.household?.people || 2}`, "")}</ul>
        <p class="whint" style="text-align:center">Tip: in Safari, tap Share → <b>Add to Home Screen</b> to open TablePlan like an app.</p>`;
    }
    const err = document.getElementById("wiz-err");
    const go = async (skip) => {
      err.textContent = "";
      const btn = document.getElementById("wz-next");
      if (!skip && submit) {
        btn.disabled = true; const label = btn.textContent; btn.textContent = "Working…";
        try { await submit(); }
        catch (e) { err.textContent = e.message; btn.disabled = false; btn.textContent = label; return; }
      }
      if (step.key === "done") {
        await _api("POST", "/api/setup/complete").catch(() => {});
        document.querySelector(".tabbar").style.display = "";
        return onFinish();
      }
      if (step.key === "mealie" || step.key === "ai") st = await _api("GET", "/api/setup/status").catch(() => st);
      i++; draw();
    };
    document.getElementById("wz-next").onclick = () => go(false);
    document.getElementById("wz-skip") && (document.getElementById("wz-skip").onclick = () => go(true));
    document.getElementById("wz-back") && (document.getElementById("wz-back").onclick = () => { i--; draw(); });
  };
  draw();
}

// ------------------------------------------------------------------ settings entry points (used by app.js)
async function openSetupSection(section, title, after) {
  openSheet(title, '<div class="spinner"></div>');
  const st = await _api("GET", "/api/setup/status").catch((e) => { toast(e.message); return null; });
  if (!st) return;
  const body = sheetBody();
  body.innerHTML = `<div class="wiz-in-sheet"><div id="ss-body"></div><div class="wiz-err" id="ss-err"></div>
    <div style="height:12px"></div><button class="btn" id="ss-save">Save</button></div>`;
  const submit = Setup[section](document.getElementById("ss-body"), st);
  document.getElementById("ss-save").onclick = async (ev) => {
    const b = ev.currentTarget; b.disabled = true; b.textContent = "Saving…";
    try { await submit(); toast("Saved"); closeSheet(); after && after(); }
    catch (e) { document.getElementById("ss-err").textContent = e.message; b.disabled = false; b.textContent = "Save"; }
  };
}
