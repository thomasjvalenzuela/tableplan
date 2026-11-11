/* TablePlan — scan recipes with the camera, the background import queue, and the "quick look" review.
   The camera stays open between recipes: snap the pages, tap Done, and the next recipe can start right away. */
"use strict";

// ------------------------------------------------------------------ frame quality (downscaled canvas, no libraries)
const SQ = { W: 192, H: 256, SHARP: 2500, STEADY: 3.2, STEADY_MS: 600, DARK: 70, MOVED: 16 };   // SHARP: Laplacian variance at this size (sharp print ≫ 4000, a soft focus < 2000)
function frameStats(ctx, prev) {
  const { W, H } = SQ;
  const d = ctx.getImageData(0, 0, W, H).data, g = new Float32Array(W * H);
  let sum = 0, bright = 0, edgeBright = 0, edgeN = 0;
  for (let i = 0, p = 0; i < d.length; i += 4, p++) {
    const v = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    g[p] = v; sum += v;
  }
  const mean = sum / g.length, paper = Math.max(110, mean * 0.92);
  let lapSum = 0, lapSq = 0, n = 0, motion = 0;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const p = y * W + x, v = g[p];
      if (v > paper) bright++;
      const border = x < W / 16 || y < H / 16 || x >= W - W / 16 || y >= H - H / 16;
      if (border) { edgeN++; if (v > paper) edgeBright++; }
      if (prev) motion += Math.abs(v - prev[p]);
      if (x && y && x < W - 1 && y < H - 1) {
        const l = 4 * v - g[p - 1] - g[p + 1] - g[p - W] - g[p + W];   // Laplacian: sharp text has strong edges
        lapSum += l; lapSq += l * l; n++;
      }
    }
  }
  const lm = lapSum / n;
  return { gray: g, brightness: mean, sharp: lapSq / n - lm * lm, motion: prev ? motion / g.length : 99,
    cover: bright / g.length, edges: edgeBright / edgeN };
}
function frameHint(s, armed) {
  if (!armed) return "Turn to the next page, or tap the shutter";
  if (s.brightness < SQ.DARK) return "More light";
  if (s.cover < 0.3) return "Move closer";
  if (s.edges > 0.97 && s.cover > 0.95) return "Fit the whole page";
  if (s.motion > SQ.STEADY) return "Hold still";
  if (s.sharp < SQ.SHARP) return "Hold still";
  return "Looks good";
}

// ------------------------------------------------------------------ camera
const RC = { stream: null, track: null, pages: [], loop: null, prev: null, steadySince: 0, lastShot: 0, armed: true, shotGray: null,
  torch: false, retake: null, busy: false, poll: null, jobs: [] };
async function openRecipeCamera(opts = {}) {
  closeSheet(true);
  if (!state.cfg?.ai_key) return toast("Scanning recipes needs AI. Add your OpenAI key in Settings → AI recipe import.", "Set up", () => openSetupSection("ai", "AI recipe import", reloadCfg));
  RC.retake = opts.retake || null; RC.pages = []; RC.armed = true; RC.prev = null; RC.steadySince = 0; RC.shotGray = null;
  const el = document.createElement("div"); el.className = "rcam"; el.id = "rcam"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Scan a recipe");
  el.innerHTML = `<div class="rcam-top"><button class="round-btn" id="rc-x" aria-label="Close camera">${ic("x")}</button>
      <span class="grow"></span><button class="rc-q" id="rc-q" hidden></button><button class="round-btn" id="rc-torch" hidden aria-label="Flashlight" aria-pressed="false">${ic("bolt")}</button></div>
    <div class="rcam-view"><video id="rc-video" playsinline muted autoplay></video><div class="rc-frame" aria-hidden="true"></div>
      <div class="rc-hint" id="rc-hint" aria-live="polite">Starting the camera…</div><div class="rc-flash" id="rc-flash"></div></div>
    <div class="rcam-strip" id="rc-strip"></div>
    <div class="rcam-bar"><label class="rc-side" aria-label="Choose photos instead">${ic("camera")}<input type="file" id="rc-file" accept="image/*" multiple hidden></label>
      <button class="rc-shutter" id="rc-shot" aria-label="Take photo"></button>
      <button class="rc-side rc-done" id="rc-done" disabled>${RC.retake ? "Use" : "Done"}</button></div>`;
  document.body.appendChild(el);
  document.body.style.overflow = "hidden";
  $("#rc-x").onclick = closeRecipeCamera;
  $("#rc-shot").onclick = () => capture(true);
  $("#rc-done").onclick = () => sendPages();
  $("#rc-file").onchange = async (e) => { for (const f of [...e.target.files].slice(0, 8 - RC.pages.length)) RC.pages.push(await shrink(f)); drawStrip(); };
  $("#rc-q").onclick = () => openImportQueue();
  drawStrip(); pollQueue();
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera");
    RC.stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 3840 }, height: { ideal: 2160 } } });
    const v = $("#rc-video"); v.srcObject = RC.stream; await v.play().catch(() => {});
    RC.track = RC.stream.getVideoTracks()[0];
    const caps = RC.track?.getCapabilities?.() || {};
    if (caps.torch) { const t = $("#rc-torch"); t.hidden = false; t.onclick = toggleTorch; }
    const cv = document.createElement("canvas"); cv.width = SQ.W; cv.height = SQ.H; RC.ctx = cv.getContext("2d", { willReadFrequently: true });
    RC.loop = setInterval(analyse, 150);
  } catch (_) {
    $("#rc-hint").textContent = "Camera not available. Tap the photo button to choose pictures instead.";
    $("#rc-shot").disabled = true;
  }
}
function closeRecipeCamera() {
  clearInterval(RC.loop); RC.loop = null;
  RC.stream?.getTracks().forEach((t) => t.stop()); RC.stream = null; RC.track = null;
  $("#rcam")?.remove(); document.body.style.overflow = "";
  if (state.tab === "recipes" && typeof renderRecipes === "function") { rstate.list = null; renderRecipes(); }
}
async function toggleTorch() {
  RC.torch = !RC.torch;
  try { await RC.track.applyConstraints({ advanced: [{ torch: RC.torch }] }); } catch (_) { RC.torch = false; }
  $("#rc-torch")?.setAttribute("aria-pressed", String(RC.torch)); $("#rc-torch")?.classList.toggle("on", RC.torch);
}
function analyse() {
  const v = $("#rc-video"); if (!v || !v.videoWidth || RC.busy) return;
  // centre-crop to the portrait analysis frame
  const ar = SQ.W / SQ.H, vw = v.videoWidth, vh = v.videoHeight;
  const sw = Math.min(vw, vh * ar), sh = sw / ar;
  RC.ctx.drawImage(v, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, SQ.W, SQ.H);
  const s = frameStats(RC.ctx, RC.prev); RC.prev = s.gray; RC.last = s;
  const now = Date.now();
  if (s.motion <= SQ.STEADY) { if (!RC.steadySince) RC.steadySince = now; } else RC.steadySince = 0;
  if (!RC.armed && RC.shotGray) {   // re-arm once the view has changed (a new page)
    let diff = 0; for (let i = 0; i < s.gray.length; i++) diff += Math.abs(s.gray[i] - RC.shotGray[i]);
    if (diff / s.gray.length > SQ.MOVED) RC.armed = true;
  }
  const hint = frameHint(s, RC.armed);
  const h = $("#rc-hint"); if (h && h.textContent !== hint) { h.textContent = hint; h.classList.toggle("good", hint === "Looks good"); }
  const ready = RC.armed && hint === "Looks good" && RC.steadySince && now - RC.steadySince >= SQ.STEADY_MS && now - RC.lastShot > 1500
    && (!RC.retake || !RC.pages.length) && RC.pages.length < 8;
  if (ready) capture(false);
}
async function capture(manual) {
  const v = $("#rc-video"); if (!v || !v.videoWidth || RC.busy) return;
  if (RC.pages.length >= 8) return toast("8 pages is the most for one recipe. Tap Done.");
  RC.busy = true;
  const k = Math.min(1, 2000 / Math.max(v.videoWidth, v.videoHeight));
  const cv = document.createElement("canvas"); cv.width = Math.round(v.videoWidth * k); cv.height = Math.round(v.videoHeight * k);
  cv.getContext("2d").drawImage(v, 0, 0, cv.width, cv.height);
  // check the frame we actually took, not just the preview
  const small = document.createElement("canvas"); small.width = SQ.W; small.height = SQ.H;
  const sctx = small.getContext("2d", { willReadFrequently: true });
  const ar = SQ.W / SQ.H, sw = Math.min(cv.width, cv.height * ar), sh = sw / ar;
  sctx.drawImage(cv, (cv.width - sw) / 2, (cv.height - sh) / 2, sw, sh, 0, 0, SQ.W, SQ.H);
  const st = frameStats(sctx, null);
  RC.busy = false;
  RC.lastShot = Date.now();
  if (st.sharp < SQ.SHARP * 0.8) {
    const h = $("#rc-hint"); if (h) { h.textContent = "That one was blurry. Hold still and try again"; h.classList.remove("good"); }
    RC.steadySince = 0;
    return;
  }
  RC.pages.push(cv.toDataURL("image/jpeg", 0.85));
  RC.armed = false; RC.shotGray = st.gray;
  const f = $("#rc-flash"); if (f) { f.classList.remove("on"); void f.offsetWidth; f.classList.add("on"); }
  try { navigator.vibrate?.(30); } catch (_) {}
  drawStrip();
  if (RC.retake) return sendPages();
  void manual;
}
function drawStrip() {
  const strip = $("#rc-strip"); if (!strip) return;
  strip.innerHTML = RC.pages.length ? RC.pages.map((p, i) => `<div class="rc-page"><img src="${esc(safeUrl(p, true))}" alt="Page ${i + 1}"><b>${i + 1}</b>
      <span class="rc-acts"><button data-pl="${i}" aria-label="Move page ${i + 1} earlier" ${i ? "" : "disabled"}>‹</button><button data-pr="${i}" aria-label="Retake page ${i + 1}">↻</button><button data-pd="${i}" aria-label="Delete page ${i + 1}">${ic("x")}</button><button data-pn="${i}" aria-label="Move page ${i + 1} later" ${i < RC.pages.length - 1 ? "" : "disabled"}>›</button></span></div>`).join("")
    + `<div class="rc-add">${RC.pages.length < 8 ? "Add page: turn the page" : "8 pages max"}</div>`
    : `<div class="rc-add">${RC.retake ? `Retake page ${esc(RC.retake.page)}` : "Point at the recipe. It snaps on its own when it's sharp and steady."}</div>`;
  const swap = (a, b) => { [RC.pages[a], RC.pages[b]] = [RC.pages[b], RC.pages[a]]; drawStrip(); };
  $$("[data-pl]", strip).forEach((b) => (b.onclick = () => swap(+b.dataset.pl, +b.dataset.pl - 1)));
  $$("[data-pn]", strip).forEach((b) => (b.onclick = () => swap(+b.dataset.pn, +b.dataset.pn + 1)));
  $$("[data-pd]", strip).forEach((b) => (b.onclick = () => { RC.pages.splice(+b.dataset.pd, 1); RC.armed = true; drawStrip(); }));
  $$("[data-pr]", strip).forEach((b) => (b.onclick = () => { RC.pages.splice(+b.dataset.pr, 1); RC.armed = true; RC.lastShot = 0; drawStrip(); toast(`Retake page ${+b.dataset.pr + 1}`); }));
  const done = $("#rc-done"); if (done) { done.disabled = !RC.pages.length; done.textContent = RC.retake ? "Use" : RC.pages.length ? `Done (${RC.pages.length})` : "Done"; }
}
async function sendPages() {
  if (!RC.pages.length) return;
  const pages = RC.pages.slice(); RC.pages = []; RC.armed = true; drawStrip();
  try {
    if (RC.retake) {
      await api("POST", `/api/import/queue/${enc(RC.retake.job)}/page/${enc(RC.retake.page)}`, { data: pages[0] });
      toast(`Page ${RC.retake.page} replaced. Reading it again…`);
      closeRecipeCamera(); pollQueue(); return;
    }
    await api("POST", "/api/import/queue", { pages });
    toast("Queued. Scan the next recipe whenever you're ready");
  } catch (e) { RC.pages = pages; drawStrip(); fail(e); }
  pollQueue();
}

// ------------------------------------------------------------------ the queue (server-side: survives a reload)
async function pollQueue() {
  clearTimeout(RC.poll);
  let d; try { d = await api("GET", "/api/import/queue"); } catch (_) { return; }
  const before = RC.jobs; RC.jobs = d.jobs || [];
  for (const j of RC.jobs) {   // tell the cook when a recipe saved silently
    const old = before.find((x) => x.id === j.id);
    if (old && old.status !== "done" && j.status === "done") toast(`Saved “${j.name || "your recipe"}”`, "Open", () => { closeRecipeCamera(); openRecipe(j.slug); });
  }
  const active = d.counts.waiting + d.counts.reading, review = d.counts.review;
  const q = $("#rc-q");
  if (q) { const n = active + review; q.hidden = !n; q.textContent = review ? `${n} in queue · ${review} to check` : `${n} in queue`; }
  setReviewBadge(review);
  if (active || $("#rcam")) RC.poll = setTimeout(pollQueue, active ? 3000 : 8000);
}
function setReviewBadge(n) {
  const t = $('#tabs .tab[data-tab="recipes"]'); if (!t) return;
  t.classList.toggle("dot", n > 0);
  t.setAttribute("aria-label", n > 0 ? `Recipes, ${n} need a quick look` : "Recipes");
}
const jobThumb = (j) => (j.page_urls && j.page_urls[0] ? `<img class="jq-img" src="${esc(j.page_urls[0])}" alt="">` : `<span class="jq-img ph">${ic("book")}</span>`);
async function openImportQueue() {
  openSheet("Import queue", loading());
  const draw = async () => {
    let d; try { d = await api("GET", "/api/import/queue"); } catch (e) { return fail(e); }
    RC.jobs = d.jobs; setReviewBadge(d.counts.review);
    const body = sheetBody(); if (!body) return;
    if (!d.jobs.length) { body.innerHTML = `<div class="empty"><b>Nothing in the queue</b><span>Scanned recipes appear here while they're read.</span></div>`; return; }
    body.innerHTML = `<div class="group">${d.jobs.map((j, i) => `<div class="row jq-row">${jobThumb(j)}
        <div class="main"><div class="a">${esc(j.name || `Recipe ${d.jobs.length - i}`)}${j.suggested ? ` <span class="muted small">(suggested)</span>` : ""}</div>
          <div class="b"><span class="jq-st st-${esc(j.status)}">${esc(j.label)}</span>${j.pages ? ` · ${esc(plural(j.pages, "page"))}` : ""}${j.error ? ` · ${esc(j.error)}` : ""}</div></div>
        ${j.status === "review" ? `<button class="pill-btn ink" data-look="${esc(j.id)}">Quick look</button>` : j.status === "failed" && j.kind === "scan" ? `<button class="pill-btn" data-retry="${esc(j.id)}">Retry</button>` : j.status === "done" && j.slug ? `<button class="pill-btn" data-open="${esc(j.slug)}">Open</button>` : ""}
        ${j.status === "reading" || j.status === "waiting" ? `<span class="spinner sm" aria-label="${esc(j.label)}"></span>` : `<button class="mini" data-dismiss="${esc(j.id)}" aria-label="Remove from the queue">${ic("x")}</button>`}</div>`).join("")}</div>
      <p class="hint">Recipes that need nothing save by themselves. Anything unclear waits here for a quick look.</p>`;
    $$("[data-look]", body).forEach((b) => (b.onclick = () => openReview(+b.dataset.look)));
    $$("[data-retry]", body).forEach((b) => (b.onclick = async () => { try { await api("POST", `/api/import/queue/${enc(b.dataset.retry)}/retry`); pollQueue(); draw(); } catch (e) { fail(e); } }));
    $$("[data-open]", body).forEach((b) => (b.onclick = () => { closeRecipeCamera(); closeSheet(true); openRecipe(b.dataset.open); }));
    $$("[data-dismiss]", body).forEach((b) => (b.onclick = async () => { try { await api("DELETE", `/api/import/queue/${enc(b.dataset.dismiss)}`); draw(); } catch (e) { fail(e); } }));
    if (d.counts.waiting + d.counts.reading && $("#layer .sheet")) setTimeout(() => { if (sheetBody() === body) draw(); }, 3000);
  };
  draw();
}

// ------------------------------------------------------------------ quick look: one compact card per recipe
async function openReview(jobId) {
  if (!$("#layer .sheet")) openSheet("Quick look", loading());
  const h = $("#layer .sheet-h h3"); if (h) h.textContent = "Quick look";
  let d; try { d = await api("GET", "/api/import/queue"); } catch (e) { return fail(e); }
  const todo = d.jobs.filter((j) => j.status === "review");
  setReviewBadge(todo.length);
  const j = todo.find((x) => x.id === jobId) || todo[0];
  const body = sheetBody(); if (!body) return;
  if (!j) { body.innerHTML = `<div class="empty"><b>All caught up ✓</b><span>No recipes need a quick look.</span></div>`; return; }
  const others = todo.filter((x) => x.id !== j.id);
  body.innerHTML = reviewCard(j) + (others.length ? `<button class="btn sec" id="rv-next" style="margin-top:12px">Next › <span class="muted">(${esc(others.length)} more)</span></button>` : "");
  bindReview(body, j, others);
}
function reviewCard(j) {
  const nameBlock = j.suggested && !j.name_ok
    ? `<div class="rv-sec"><div class="rv-l">Suggested name <span class="muted small">(the page has no title)</span></div>
        <form class="rv-name" id="rv-name"><input value="${esc(j.suggested_title)}" maxlength="120" aria-label="Recipe name"><button class="btn small" type="submit" id="rv-name-go">Approve</button></form></div>`
    : `<h3 class="rv-title">${esc(j.name)}</h3>`;
  const qs = j.questions.filter((q) => !q.answered).map((q) => `<div class="rv-sec rv-q" data-q="${esc(q.id)}"><div class="rv-l">${esc(q.text)}</div>
      <div class="rv-chips">${q.choices.map((c) => `<button class="chip-s" data-a="${esc(c)}">${esc(c)}</button>`).join("")}</div>
      <form class="rv-own"><input maxlength="200" placeholder="${q.kind === "cutoff" ? "Type the missing part" : "Or type it"}" aria-label="Your answer"><button class="btn small sec" type="submit">Use</button></form>
      <div class="rv-row">${q.page && j.kind === "scan" ? `<button class="link-btn" data-retake="${esc(q.page)}">${ic("camera")} Retake page ${esc(q.page)}</button>` : ""}<button class="link-btn" data-a="skip">Skip</button></div></div>`).join("");
  const dup = j.dups.length && !j.dup_choice ? (() => {
    const m = j.dups[0];
    return `<div class="rv-sec rv-dup"><div class="rv-l">Looks like you already have “${esc(m.name)}”</div>
      <div class="rv-cmp"><div><b>New</b><span>${esc(j.name || j.suggested_title)}</span><small>${esc(plural(j.ingredients.length, "ingredient"))}${j.url ? ` · ${esc(hostOf(j.url))}` : ""}</small></div>
        <div><b>You have</b><span>${esc(m.name)}</span><small>${esc((m.reasons || []).join(", "))}${m.url ? ` · ${esc(hostOf(m.url))}` : ""}</small></div></div>
      <div class="rv-row"><button class="btn small sec" data-dup="keep">Keep both</button><button class="btn small sec" data-dup="replace">Replace</button><button class="btn small sec" data-dup="cancel">Cancel</button></div></div>`;
  })() : "";
  return `<div class="rv-card" data-job="${esc(j.id)}">
    ${j.page_urls.length ? `<div class="rv-pages">${j.page_urls.map((u, i) => `<img src="${esc(u)}" alt="Page ${i + 1}">`).join("")}</div>` : ""}
    ${nameBlock}${qs}${dup}
    ${j.ingredients.length ? `<details class="rv-more"><summary>${esc(plural(j.ingredients.length, "ingredient"))} · ${esc(plural(j.steps.length, "step"))}</summary><ul>${j.ingredients.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}
    <div class="rv-foot muted small">${esc(plural(j.todo.length, "thing"))} left · saves by itself when done</div></div>`;
}
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (_) { return ""; } };
function bindReview(body, j, others) {
  const send = async (patch) => {
    try {
      const r = await api("POST", `/api/import/queue/${enc(j.id)}/answer`, patch);
      if (r.status === "done") {
        toast(`Saved “${r.name}”`, "Open", () => { closeSheet(true); openRecipe(r.slug); });
        if (typeof rstate !== "undefined") rstate.list = null;
        return others.length ? openReview(others[0].id) : openReview();
      }
      if (r.status === "cancelled") { toast("Not saved"); return openReview(others[0]?.id); }
      openReview(j.id);
    } catch (e) { fail(e); }
  };
  const nf = $("#rv-name", body);
  if (nf) {
    const inp = $("input", nf), go = $("#rv-name-go", nf);
    inp.oninput = () => { go.textContent = inp.value.trim() === j.suggested_title ? "Approve" : "Save name"; };
    nf.onsubmit = (e) => { e.preventDefault(); const v = inp.value.trim(); if (!v) return; send(v === j.suggested_title ? { approve_name: true } : { name: v }); };
  }
  $$(".rv-q", body).forEach((box) => {
    const qid = box.dataset.q;
    $$("[data-a]", box).forEach((b) => (b.onclick = () => send({ answers: { [qid]: b.dataset.a } })));
    $(".rv-own", box).onsubmit = (e) => { e.preventDefault(); const v = $("input", e.target).value.trim(); if (v) send({ answers: { [qid]: v } }); };
    $$("[data-retake]", box).forEach((b) => (b.onclick = () => openRecipeCamera({ retake: { job: j.id, page: +b.dataset.retake } })));
  });
  $$("[data-dup]", body).forEach((b) => (b.onclick = () => send({ duplicate: b.dataset.dup })));
  $("#rv-next") && ($("#rv-next").onclick = () => openReview(others[0].id));
}

// A direct import (link, paste, screenshot…) that looks like a recipe we have: decide inline.
function duplicateCard(box, err, onSaved) {
  const m = err.data.matches[0], n = err.data.new;
  box.innerHTML = `<div class="rv-card rv-dup" style="margin-top:12px"><div class="rv-l">Looks like you already have “${esc(m.name)}”</div>
    <div class="rv-cmp"><div><b>New</b><span>${esc(n.name)}</span><small>${esc(plural(n.ingredients, "ingredient"))}${n.url ? ` · ${esc(hostOf(n.url))}` : ""}</small></div>
      <div><b>You have</b><span>${esc(m.name)}</span><small>${esc((m.reasons || []).join(", "))}${m.url ? ` · ${esc(hostOf(m.url))}` : ""}</small></div></div>
    <div class="rv-row"><button class="btn small sec" data-dup="keep">Keep both</button><button class="btn small sec" data-dup="replace">Replace</button><button class="btn small sec" data-dup="cancel">Cancel</button><button class="link-btn" data-dup="see">See yours</button></div></div>`;
  $$("[data-dup]", box).forEach((b) => (b.onclick = async () => {
    if (b.dataset.dup === "see") { closeSheet(true); return openRecipe(m.slug); }
    try {
      const r = await api("POST", `/api/import/queue/${enc(err.data.job)}/answer`, { duplicate: b.dataset.dup });
      if (r.status === "cancelled") { box.innerHTML = `<div class="hint">Not saved.</div>`; return; }
      onSaved({ slug: r.slug, name: r.name });
    } catch (e) { fail(e); }
  }));
}
