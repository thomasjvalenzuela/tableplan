/* Look before anything renders: this device's last theme + mode (the server usually set them already from a cookie). */
(function () {
  const r = document.documentElement;
  let m = "", t = "";
  try { m = localStorage.getItem("tp.theme") || ""; t = localStorage.getItem("tp.palette") || ""; } catch (_) {}
  if (!r.dataset.mode && (m === "light" || m === "dark")) r.dataset.mode = m;
  if (!r.dataset.theme && /^(midnight|blossom|forest)$/.test(t)) r.dataset.theme = t;
})();
/* TablePlan — sign-in, first-run setup wizard, and the setup sections reused by Settings. Loaded before app.js. */
"use strict";

// Small helpers (app.js defines the full set; these are safe duplicates for the wizard, which can run first).
const _esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// URLs for href/src: only http(s) and same-origin paths. data: is allowed for raster images only (and SVG when img=true,
// since an <img> never runs scripts). Anything else (javascript:, vbscript:, data:text/html, blob: …) becomes "".
// Still pass the result through _esc/esc when putting it into HTML.
function _safeUrl(u, img = false) {
  // Browsers drop tabs/newlines anywhere and control chars/spaces at the ends ("java\tscript:" still runs), so do the same first.
  const s = String(u ?? "").replace(/[\t\n\r]/g, "").replace(/^[\u0000- ]+|[\u0000- ]+$/g, "");
  if (!s || /[\u0000-\u001f\u007f]/.test(s)) return "";
  if (/^data:/i.test(s)) return (img ? /^data:image\/(png|jpe?g|gif|webp|avif|bmp|svg\+xml)[;,]/i : /^data:image\/(png|jpe?g|gif|webp|avif|bmp)[;,]/i).test(s) ? s : "";
  let p;
  try { p = new URL(s, location.origin); } catch (_) { return ""; }
  return p.protocol === "https:" || p.protocol === "http:" ? s : "";
}
async function _api(method, path, body) {
  const headers = { "X-TablePlan": "1" };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined, credentials: "same-origin" });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const e = new Error((data && data.error) || `Request failed (${res.status})`); e.status = res.status; throw e; }
  return data;
}

// ------------------------------------------------------------------ sign-in screen
function renderLogin(onDone, sess) {
  document.querySelector(".tabbar").style.display = "none";
  const root = document.getElementById("app");
  const profiles = (sess && sess.profiles) || [];
  const shell = (inner) => `<div class="wiz"><div class="wiz-card fade-in" style="max-width:400px">
    <div class="wiz-logo"><img class="brand-logo logo-l" src="/static/logo.png" alt="TablePlan · Plan meals. Shop smarter."><img class="brand-logo logo-d" src="/static/logo-white.png" alt="TablePlan · Plan meals. Shop smarter."></div>${inner}</div></div>`;
  const finish = () => { document.querySelector(".tabbar").style.display = ""; onDone(); };
  if (profiles.length) {
    let last = "";
    try { last = localStorage.getItem("tp.lastUser") || ""; } catch (_) {}
    const chooser = () => {
      root.innerHTML = shell(`<h2 class="wiz-title">Who's cooking?</h2><p class="wiz-sub">Choose your name to sign in.</p>
        <div class="who" role="list">${profiles.map((p) => `<button class="who-btn" role="listitem" data-uid="${_esc(p.id)}"><span class="who-av" aria-hidden="true">${_esc((p.name || "?").trim().charAt(0).toUpperCase())}</span><span class="who-n">${_esc(p.name)}</span></button>`).join("")}</div>
        <p class="whint" style="text-align:center">New here? Ask whoever set up TablePlan to add you in Settings → Members.</p>`);
      root.querySelectorAll("[data-uid]").forEach((b) => (b.onclick = () => secretStep(profiles.find((p) => String(p.id) === b.dataset.uid))));
    };
    const secretStep = (p) => {
      const pin = p.kind === "pin";
      root.innerHTML = shell(`<h2 class="wiz-title">Hi, ${_esc(p.name)}</h2><p class="wiz-sub">Enter your ${pin ? "PIN" : "password"}.</p>
        <form id="lg"><input type="text" name="username" value="${_esc(p.name)}" autocomplete="username" hidden>
        <div class="wgroup"><div class="wfield"><label for="lg-pw">${pin ? "PIN" : "Password"}</label><input type="password" id="lg-pw" ${pin ? 'inputmode="numeric" autocomplete="one-time-code"' : 'autocomplete="current-password"'} maxlength="256" autofocus></div></div>
        <div class="wiz-err" id="lg-err"></div>
        <div class="wiz-actions">${profiles.length > 1 ? `<button class="btn sec" type="button" id="lg-back">Not ${_esc(p.name)}?</button>` : ""}<button class="btn" type="submit">Sign in</button></div></form>`);
      root.querySelector("#lg-back") && (root.querySelector("#lg-back").onclick = chooser);
      root.querySelector("#lg-pw").focus();
      root.querySelector("#lg").onsubmit = async (e) => {
        e.preventDefault();
        const btn = e.target.querySelector("button[type=submit]"); btn.disabled = true;
        try {
          await _api("POST", "/api/login", { user_id: p.id, secret: root.querySelector("#lg-pw").value });
          try { localStorage.setItem("tp.lastUser", String(p.id)); } catch (_) {}
          finish();
        } catch (err) { root.querySelector("#lg-err").textContent = err.message; btn.disabled = false; root.querySelector("#lg-pw").select(); }
      };
    };
    const remembered = profiles.find((p) => String(p.id) === last);
    return remembered ? secretStep(remembered) : chooser();
  }
  const code = sess && sess.needs_setup_code;
  root.innerHTML = shell(`<h2 class="wiz-title">TablePlan</h2><p class="wiz-sub">${code ? "This server is on the internet, so setup is locked. Enter the one-time setup code printed in the TablePlan log (ZimaOS → TablePlan → Logs)." : "Enter the household password."}</p>
    <form id="lg"><div class="wfield"><input type="${code ? "text" : "password"}" id="lg-pw" placeholder="${code ? "Setup code" : "Password"}" autocomplete="${code ? "one-time-code" : "current-password"}" autofocus></div>
    <div class="wiz-err" id="lg-err"></div>
    <button class="btn" type="submit">Sign in</button></form>`);
  document.getElementById("lg").onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button"); btn.disabled = true;
    try { await _api("POST", "/api/login", { password: document.getElementById("lg-pw").value }); finish(); }
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
        <div class="wfield"><label>Household name</label><input id="hh-name" placeholder="The Smiths" value="${_esc(h.name || "")}"></div>
        <div class="wfield"><label>How many people do you cook for?</label>
          <div class="stepper"><button type="button" data-d="-1">−</button><b id="hh-n">${_esc(h.people || 2)}</b><button type="button" data-d="1">+</button></div></div>
        <div class="wfield"><label>Scale recipes to fit</label><label class="toggle"><input type="checkbox" id="hh-scale" ${h.scale !== false ? "checked" : ""}><span></span></label></div>
      </div>
      <p class="whint">When you plan a meal, TablePlan sets the serving scale so a recipe written for 4 automatically shopping-lists for <span id="hh-n2">${_esc(h.people || 2)}</span>. You can still change servings on any recipe.</p>
      ${st.mealie?.native ? `<div class="wgroup"><div class="wfield col"><label>Where do you shop?</label><div class="chips wiz-stores" id="hh-stores"></div>
        <form class="wiz-add" id="hh-add" autocomplete="off"><input id="hh-store" maxlength="40" placeholder="Add a store" aria-label="Add a store"><button class="btn sec small" type="submit">Add</button></form></div></div>` : ""}`;
    let n = Math.max(1, Math.min(30, Math.round(+h.people) || 2));
    el.querySelectorAll("[data-d]").forEach((b) => (b.onclick = () => { n = Math.max(1, Math.min(30, n + +b.dataset.d)); el.querySelector("#hh-n").textContent = n; el.querySelector("#hh-n2").textContent = n; }));
    let stores = null;
    const box = el.querySelector("#hh-stores");
    if (box) {
      const draw = () => {
        box.innerHTML = stores.map((x, k) => `<button type="button" class="chip-s on store-chip-x" data-rm="${k}" aria-label="Remove ${_esc(x.name)}">${_esc(x.name)} <span aria-hidden="true">×</span></button>`).join("") || `<span class="whint">No stores yet (optional)</span>`;
        box.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { stores.splice(+b.dataset.rm, 1); draw(); }));
      };
      _api("GET", "/api/stores").then((list) => { stores = list && list.length ? list.map((x) => ({ id: x.id, name: x.name })) : [{ name: "Aldi" }, { name: "Costco" }]; draw(); }).catch(() => { stores = [{ name: "Aldi" }, { name: "Costco" }]; draw(); });
      el.querySelector("#hh-add").onsubmit = (e) => { e.preventDefault(); const v = el.querySelector("#hh-store").value.trim(); if (v && stores && stores.length < 12 && !stores.some((x) => x.name.toLowerCase() === v.toLowerCase())) { stores.push({ name: v }); draw(); } el.querySelector("#hh-store").value = ""; };
    }
    return async () => {
      const r = await _api("POST", "/api/setup/household", { name: el.querySelector("#hh-name").value, people: n, scale: el.querySelector("#hh-scale").checked });
      if (stores) await _api("PUT", "/api/stores", { stores });
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
        <div class="wgroup" style="margin-top:12px"><div class="wfield"><label>Mealie address for "Open recipe" links</label>
          <input id="ml-public" placeholder="${_esc(m.public_url || "")}" value="${m.public_url_set ? _esc(m.public_url) : ""}" autocomplete="off"></div></div>
        <p class="whint">Leave blank to use this server's address with port 9925. If you use HTTPS or a domain (for example https://recipes.example.com), enter it here.</p>
        <div style="height:10px"></div>
        <button class="btn sec" id="ml-switch">Use a different account</button>`;
      el.querySelector("#ml-switch").onclick = () => { st.mealie = { ...m, connected: false }; Setup.mealie(el, st, done); };
      return async () => {
        const v = el.querySelector("#ml-public").value.trim();
        if (v !== (m.public_url_set ? m.public_url : "")) await _api("POST", "/api/setup/mealie/public", { url: v });
        return true;
      };
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
      gmail: "Use an <b>App Password</b>. Turn on 2-Step Verification first, then go to myaccount.google.com/apppasswords. New accounts sometimes can't create one yet; use Telegram or ntfy instead.",
      outlook: "Use your Microsoft password, or an app password if 2-step sign-in is on. SMTP has to be allowed for your mailbox.",
      icloud: "Create an app-specific password at appleid.apple.com → Sign-In and Security.",
      yahoo: "Generate an app password in Yahoo Account Security.",
      custom: "Enter your mail provider's SMTP details. Free sending services such as Brevo or SMTP2GO work too; they give you an SMTP login.",
    };
    const draw = (p) => {
      el.innerHTML = `
        ${e.configured ? `<div class="wstatus ok"><b>Email is set up</b><span>${_esc(e.from || e.user || "")} → ${_esc((e.to || []).join(", "))}</span></div>` : ""}
        <p class="wlead">Send shopping lists, meal plans and inventory reports to your inbox.</p>
        <div class="wgroup">
          <div class="wfield"><label>Provider</label><select id="em-p">${presets.map(([k, l]) => `<option value="${k}" ${k === p ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          ${p === "custom" ? `<div class="wfield"><label>SMTP server</label><input id="em-host" value="${_esc(e.host || "")}" placeholder="smtp.example.com"></div>
            <div class="wfield"><label>Port</label><input id="em-port" type="number" value="${_esc(e.port || 587)}"></div>
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
      if (!user && !e.configured) return true;
      if (!user && e.configured) return true;
      const body = { preset: p === "custom" ? "" : p, smtp_user: user, smtp_from: user, smtp_password: pw, mail_to: el.querySelector("#em-to").value || user, test: true };
      if (p === "custom") Object.assign(body, { smtp_host: el.querySelector("#em-host").value, smtp_port: +el.querySelector("#em-port").value, smtp_security: el.querySelector("#em-sec").value });
      const r = await _api("POST", "/api/setup/email", body);
      st.email = r; done && done(r); return true;
    };
  },

  notify(el, st, done) {
    const n = st.notify || {};
    const ch = n.channels || {};
    const tabs = [["telegram", "Telegram"], ["ntfy", "ntfy"], ["email", "Email"]];
    const first = ch.telegram ? "telegram" : ch.ntfy ? "ntfy" : ch.email ? "email" : "telegram";
    el.innerHTML = `<p class="wlead">Send shopping lists, meal plans and use-soon alerts to your phone. Set up one or more. You can change this later in Settings.</p>
      <div class="seg wseg" id="nt-tabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${k === first ? "on" : ""}">${l}${ch[k] ? " ✓" : ""}</button>`).join("")}</div>
      <div id="nt-body"></div>`;
    let sub = null;
    const show = (k) => {
      el.querySelectorAll("#nt-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === k));
      const body = el.querySelector("#nt-body");
      Setup[k](body, st, () => {});
      sub = () => (body._submit ? body._submit() : true);
    };
    el.querySelectorAll("#nt-tabs button").forEach((b) => (b.onclick = () => show(b.dataset.t)));
    show(first);
    return async () => (sub ? sub() : true);
  },

  telegram(el, st, done) {
    const t = (st.notify || {}).telegram || {};
    const remove = async () => { st.notify = await _api("DELETE", "/api/setup/telegram"); Setup.telegram(el, st, done); };
    if (t.configured) {
      el.innerHTML = `<div class="wstatus ok"><b>Telegram is connected</b><span>Messages go to ${_esc(t.chat || "your chat")} via @${_esc(t.bot || "bot")}</span></div>
        <div class="btn-row"><button class="btn sec" type="button" id="tg-test">Send test</button><button class="btn red" type="button" id="tg-rm">Disconnect</button></div>`;
      el.querySelector("#tg-test").onclick = async (e) => { e.target.disabled = true; try { await _api("POST", "/api/send", { kind: "test", channel: "telegram" }); e.target.textContent = "Sent ✓"; } catch (x) { e.target.textContent = x.message; } };
      el.querySelector("#tg-rm").onclick = remove;
      return async () => true;
    }
    if (t.code) {
      el.innerHTML = `<div class="wstatus"><b>Last step: link your chat</b><span>Bot @${_esc(t.bot)} is ready</span></div>
        ${_safeUrl(t.link) ? `<a class="btn" href="${_esc(_safeUrl(t.link))}" target="_blank" rel="noopener noreferrer" style="text-decoration:none">Open @${_esc(t.bot)} in Telegram → Start</a>` : ""}
        <p class="whint">Telegram opens a chat with your bot. Tap <b>Start</b>. Want lists in a family group instead? Add the bot to the group and send this code there:</p>
        <div class="wgroup"><div class="wfield"><label>Link code (valid 15 minutes)</label><input readonly value="${_esc(t.code)}" style="font-family:ui-monospace,Menlo,monospace;letter-spacing:.15em;font-size:20px"></div></div>
        <div class="wiz-err" id="tg-err"></div>
        <div class="btn-row" style="margin-top:12px"><button class="btn sec" type="button" id="tg-restart">Start over</button><button class="btn" type="button" id="tg-check">I tapped Start, check</button></div>`;
      const check = async () => {
        const b = el.querySelector("#tg-check"); b.disabled = true; b.textContent = "Checking…";
        try { const r = await _api("POST", "/api/setup/telegram/verify"); st.notify = { ...(st.notify || {}), telegram: r, channels: { ...((st.notify || {}).channels || {}), telegram: true } }; Setup.telegram(el, st, done); done && done(r); }
        catch (e) { el.querySelector("#tg-err").textContent = e.message; b.disabled = false; b.textContent = "I tapped Start, check"; }
      };
      el.querySelector("#tg-check").onclick = check;
      el.querySelector("#tg-restart").onclick = remove;
      return async () => { await check(); if (!(st.notify?.telegram?.configured)) throw new Error("Tap Start in Telegram first, or choose Skip."); return true; };
    }
    el.innerHTML = `<p class="wlead">Telegram is free and works when email won't. You create a private bot just for your household, and only chats you link can receive messages.</p>
      <ol class="whint" style="margin:0 0 12px 18px;padding:0;line-height:1.6">
        <li>In Telegram, open <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer"><b>@BotFather</b></a> and send <code>/newbot</code>.</li>
        <li>Pick any name, then a username ending in <code>bot</code> (e.g. <code>smith_kitchen_bot</code>).</li>
        <li>Copy the <b>token</b> BotFather replies with and paste it here.</li></ol>
      <div class="wgroup"><div class="wfield"><label>Bot token</label><input id="tg-token" type="password" placeholder="123456789:AAH…" autocomplete="off"></div></div>
      <p class="whint">The token stays on your server. TablePlan only sends messages out, and nothing is opened to the internet.</p>`;
    return async () => {
      const tok = el.querySelector("#tg-token").value.trim();
      if (!tok) return true;
      const r = await _api("POST", "/api/setup/telegram", { token: tok });
      st.notify = { ...(st.notify || {}), telegram: r };
      Setup.telegram(el, st, done);
      throw Object.assign(new Error(""), { silent: true });   // stay on this screen for the linking step
    };
  },

  ntfy(el, st, done) {
    const n = (st.notify || {}).ntfy || {};
    if (n.configured) {
      el.innerHTML = `<div class="wstatus ok"><b>ntfy is connected</b><span>${_esc(n.server)} · topic ${_esc(n.topic)}${n.has_token ? " · access token ✓" : ""}</span></div>
        <div class="btn-row"><button class="btn sec" type="button" id="nf-test">Send test</button><button class="btn red" type="button" id="nf-rm">Disconnect</button></div>`;
      el.querySelector("#nf-test").onclick = async (e) => { e.target.disabled = true; try { await _api("POST", "/api/send", { kind: "test", channel: "ntfy" }); e.target.textContent = "Sent ✓"; } catch (x) { e.target.textContent = x.message; } };
      el.querySelector("#nf-rm").onclick = async () => { st.notify = await _api("DELETE", "/api/setup/ntfy"); Setup.ntfy(el, st, done); };
      return async () => true;
    }
    el.innerHTML = `<p class="wlead">ntfy sends push notifications to the free ntfy app (iPhone and Android). No account needed. It's also easy to self-host.</p>
      <div class="wgroup">
        <div class="wfield"><label>Server</label><input id="nf-server" value="${_esc(n.server || "https://ntfy.sh")}"></div>
        <div class="wfield"><label>Topic (keep it secret, like a password)</label><input id="nf-topic" value="${_esc(n.suggested_topic || "")}" style="font-family:ui-monospace,Menlo,monospace"></div>
        <div class="wfield"><label>Access token (optional)</label><input id="nf-token" type="password" placeholder="tk_… (for protected topics)" autocomplete="off"></div>
      </div>
      <p class="whint">In the ntfy app, tap <b>+</b> and subscribe to the topic above, then tap Connect and a test arrives. On the public ntfy.sh server, anyone who knows the topic can read it, so keep the long random name or use your own server with an access token.</p>
      <div class="wiz-err" id="nf-err"></div>
      <button class="btn" type="button" id="nf-go" style="margin-top:12px">Connect ntfy</button>`;
    el.querySelector("#nf-go").onclick = async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = "Connecting…"; el.querySelector("#nf-err").textContent = "";
      try {
        const r = await _api("POST", "/api/setup/ntfy", { server: el.querySelector("#nf-server").value, topic: el.querySelector("#nf-topic").value.trim(), token: el.querySelector("#nf-token").value });
        st.notify = { ...(st.notify || {}), ntfy: r, channels: { ...((st.notify || {}).channels || {}), ntfy: true } }; Setup.ntfy(el, st, done); done && done(r);
      } catch (x) { el.querySelector("#nf-err").textContent = x.message; b.disabled = false; b.textContent = "Connect ntfy"; }
    };
    return async () => true;
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

  // Your own sign-in. The first account is the household admin; it replaces the shared household password.
  account(el, st, done) {
    const sess = st.session || {};
    if (sess.accounts) {
      el.innerHTML = `<div class="wstatus ok"><b>Accounts are set up</b><span>Manage people in Settings → Members.</span></div>`;
      return async () => true;
    }
    const get = accountFields(el, { pinAllowed: sess.pin_allowed !== false, lead: sess.household_password
      ? "Everyone now signs in as themselves. Create yours first: you'll be the admin, and the shared household password stops working."
      : "You'll be the household admin. Add everyone else in Settings → Members, each with their own password or PIN." });
    return async () => {
      const v = get();
      const r = await _api("POST", "/api/account/first", { name: v.name, email: v.email, kind: v.kind, secret: v.secret });
      try { localStorage.setItem("tp.lastUser", String(r.me.id)); } catch (_) {}
      st.session = { ...sess, accounts: true, me: r.me }; done && done(r); return true;
    };
  },
};

// Name, email and a password or PIN, used for your own account and when an admin adds someone.
// Returns a getter that validates and throws a friendly Error.
function accountFields(el, { pinAllowed = true, lead = "", name = "", email = "", withName = true, withEmail = true, label = "" } = {}) {
  el.innerHTML = `${lead ? `<p class="wlead">${_esc(lead)}</p>` : ""}
    ${withName || withEmail ? `<div class="wgroup">
      ${withName ? `<div class="wfield"><label for="ac-name">Name</label><input id="ac-name" autocomplete="name" maxlength="40" value="${_esc(name)}" placeholder="Thomas"></div>` : ""}
      ${withEmail ? `<div class="wfield"><label for="ac-email">Email (optional)</label><input id="ac-email" type="email" autocomplete="email" maxlength="254" value="${_esc(email)}" placeholder="For notifications you opt in to"></div>` : ""}
    </div><div style="height:12px"></div>` : ""}
    ${pinAllowed ? `<div class="seg wseg" role="tablist" aria-label="Sign in with"><button type="button" data-k="password" class="on" role="tab" aria-selected="true">Password</button><button type="button" data-k="pin" role="tab" aria-selected="false">PIN</button></div>` : ""}
    <div class="wgroup">
      <div class="wfield"><label for="ac-secret" id="ac-l">${_esc(label || "Password")}</label><input id="ac-secret" type="password" autocomplete="new-password" maxlength="256"></div>
      <div class="wfield"><label for="ac-secret2">Type it again</label><input id="ac-secret2" type="password" autocomplete="new-password" maxlength="256"></div>
    </div>
    <p class="whint" id="ac-hint"></p>`;
  let kind = "password";
  const min = pinAllowed ? 8 : 10;
  const sec = el.querySelector("#ac-secret"), sec2 = el.querySelector("#ac-secret2");
  const setKind = (k) => {
    kind = k;
    el.querySelectorAll("[data-k]").forEach((b) => { b.classList.toggle("on", b.dataset.k === k); b.setAttribute("aria-selected", String(b.dataset.k === k)); });
    el.querySelector("#ac-l").textContent = label ? `${label} ${k === "pin" ? "PIN" : "password"}` : (k === "pin" ? "PIN" : "Password");
    for (const i of [sec, sec2]) { i.value = ""; i.inputMode = k === "pin" ? "numeric" : "text"; i.placeholder = k === "pin" ? "6 or more digits" : `At least ${min} characters`; }
    el.querySelector("#ac-hint").textContent = k === "pin"
      ? "A PIN is quick on a shared kitchen tablet. It only works on your home network."
      : pinAllowed ? "Use a password if you'll sign in away from home." : "This TablePlan is on the internet, so everyone uses a password of 10 or more characters.";
  };
  el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => setKind(b.dataset.k)));
  setKind("password");
  return () => {
    const v = { name: el.querySelector("#ac-name")?.value.trim() ?? "", email: el.querySelector("#ac-email")?.value.trim() ?? "", kind, secret: sec.value };
    if (withName && !v.name) throw new Error("Enter a name.");
    if (kind === "pin" && !/^\d{6,12}$/.test(v.secret)) throw new Error("A PIN is 6 to 12 digits.");
    if (kind === "password" && v.secret.length < min) throw new Error(`Use a password of at least ${min} characters.`);
    if (v.secret !== sec2.value) throw new Error(kind === "pin" ? "The PINs don't match." : "The passwords don't match.");
    return v;
  };
}

// Every section records its current submit handler on its container, so screens that redraw themselves
// (Telegram linking, Mealie retry) always submit the right form.
for (const k of Object.keys(Setup)) {
  const f = Setup[k];
  Setup[k] = (el, st, done) => { const r = f(el, st, done); el._submit = r; return r; };
}

// ------------------------------------------------------------------ first-run wizard
// First run: only what's needed to start. Everything else waits in the Getting started checklist.
const WIZ_STEPS = [
  { key: "account", title: "Welcome to TablePlan", sub: "Create your account first. You'll be the household admin; everyone else gets their own sign-in later.", section: "account" },
  { key: "household", title: "Your household", sub: "Who you cook for and where you shop. You can change this any time.", section: "household", skippable: true },
  { key: "mealie", title: "Recipe library", sub: "TablePlan keeps recipes in Mealie, which is included and runs on your server.", section: "mealie", skippable: true },
  { key: "ai", title: "AI recipe import (optional)", sub: "Let AI read recipe photos, screenshots and tricky web pages. Add a key now or later.", section: "ai", skippable: true },
  { key: "notify", title: "Notifications (optional)", sub: "Get lists, plans and heads-ups on your phone. Set it up now or later.", section: "notify", skippable: true },
];

async function runWizard(onFinish) {
  document.querySelector(".tabbar").style.display = "none";
  const root = document.getElementById("app");
  root.innerHTML = `<div class="wiz"><div class="spinner"></div></div>`;
  let st = await _api("GET", "/api/setup/status").catch(() => ({}));
  st.session = await _api("GET", "/api/session").catch(() => ({}));
  if (st.session.accounts) { const k = WIZ_STEPS.findIndex((s) => s.key === "account"); if (k >= 0) WIZ_STEPS.splice(k, 1); }
  if (st.mealie?.native) { const k = WIZ_STEPS.findIndex((s) => s.key === "mealie"); if (k >= 0) WIZ_STEPS.splice(k, 1); }
  let i = 0, submit = null;

  const draw = () => {
    const step = WIZ_STEPS[i];
    const dots = WIZ_STEPS.map((_, n) => `<i class="${n === i ? "on" : n < i ? "past" : ""}"></i>`).join("");
    root.innerHTML = `<div class="wiz"><div class="wiz-card fade-in">
      <div class="wiz-dots">${dots}</div>
      ${i === 0 ? `<div class="wiz-logo"><img class="brand-logo logo-l" src="/static/logo.png" alt="TablePlan · Plan meals. Shop smarter."><img class="brand-logo logo-d" src="/static/logo-white.png" alt="TablePlan · Plan meals. Shop smarter."></div>` : ""}
      <h2 class="wiz-title">${_esc(step.title)}</h2>${step.sub ? `<p class="wiz-sub">${_esc(step.sub)}</p>` : ""}
      <div id="wiz-body"></div><div class="wiz-err" id="wiz-err"></div>
      <div class="wiz-actions">
        ${i > 0 ? `<button class="btn sec" id="wz-back">Back</button>` : ""}
        ${step.skippable ? `<button class="btn sec" id="wz-skip">Skip</button>` : ""}
        <button class="btn" id="wz-next">${i === WIZ_STEPS.length - 1 ? "Finish" : "Continue"}</button>
      </div></div></div>`;
    const body = document.getElementById("wiz-body");
    submit = null;
    if (step.section) { Setup[step.section](body, st); submit = () => (body._submit ? body._submit() : true); }
    const err = document.getElementById("wiz-err");
    const go = async (skip) => {
      err.textContent = "";
      const btn = document.getElementById("wz-next");
      if (!skip && submit) {
        btn.disabled = true; const label = btn.textContent; btn.textContent = "Working…";
        try { await submit(); }
        catch (e) { if (!e.silent) err.textContent = e.message; btn.disabled = false; btn.textContent = label; return; }
      }
      if (i === WIZ_STEPS.length - 1) {
        await _api("POST", "/api/setup/complete").catch(() => {});
        document.querySelector(".tabbar").style.display = "";
        return onFinish();
      }
      if (step.key === "mealie" || step.key === "ai" || step.key === "notify") st = await _api("GET", "/api/setup/status").catch(() => st);
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
  const ssBody = document.getElementById("ss-body");
  Setup[section](ssBody, st);
  const submit = () => (ssBody._submit ? ssBody._submit() : true);
  document.getElementById("ss-save").onclick = async (ev) => {
    const b = ev.currentTarget; b.disabled = true; b.textContent = "Saving…";
    try { await submit(); toast("Saved"); closeSheet(); after && after(); }
    catch (e) { if (!e.silent) document.getElementById("ss-err").textContent = e.message; b.disabled = false; b.textContent = "Save"; }
  };
}
