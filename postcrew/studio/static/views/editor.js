// Factory > Plans > Edit video (owner, 2026-11-23): "I want to have option to edit video by hand or with AI command and I should be
// able to edit each frame or each section where I feel improvement required. And at the end if I approve then only it will be ready
// for upload." The episode's own animation plays live in a frame (it is a pure function of time, so any frame can be shown at once);
// texts are changed by hand (wording, hide, drag a floating label), or an AI command changes the picked frames / sections; then Render
// the video and Approve it (postcrew/factory_edit.py).
const ED = { slug: null, d: null, t: 0, playing: false, frames: [], sections: new Set(), edits: { texts: {}, hide: [], moves: {} },
             dirty: false, texts: [], sel: null, tab: "hand", poll: null, raf: 0, lastJob: null, drag: null };
const FPS = 30;

function edClose() {
  if (ED.dirty && !confirm("Leave without saving your hand edits?")) return;
  cancelAnimationFrame(ED.raf); clearTimeout(ED.poll);
  document.getElementById("ed-root")?.remove();
  ED.slug = null;
  if (typeof vdLoad === "function") vdLoad(true);
}

async function edOpen(slug) {
  ED.slug = slug; ED.frames = []; ED.sections = new Set(); ED.t = 0; ED.dirty = false; ED.sel = null; ED.lastJob = null;
  document.getElementById("ed-root")?.remove();
  const root = document.createElement("div");
  root.id = "ed-root";
  root.className = "fixed inset-0 z-50 bg-slate-900/60 flex items-stretch justify-center p-3 lg:p-6";
  root.innerHTML = `<div class="bg-slate-50 rounded-2xl shadow-xl w-full max-w-[1400px] flex flex-col overflow-hidden"><p class="p-6 text-sm text-slate-500">${icon("progress_activity", "text-sm animate-spin align-middle")} Opening the video editor…</p></div>`;
  document.body.appendChild(root);
  await edLoad(true);
}

async function edLoad(first) {
  if (!ED.slug) return;
  let d;
  try { d = await api(`/api/factory-edit?slug=${encodeURIComponent(ED.slug)}`); }
  catch (e) { document.querySelector("#ed-root > div").innerHTML = `<p class="p-6 text-sm text-rose-700">${esc(e.message)}</p>`; return; }
  const was = ED.d, jobDone = was?.job && !was.job.done ? !d.job || d.job.done : false;
  ED.d = d;
  if (first) ED.edits = { texts: { ...(d.edits.texts || {}) }, hide: [...(d.edits.hide || [])], moves: { ...(d.edits.moves || {}) } };
  if (first || jobDone || !document.getElementById("ed-frame")) edDraw();
  else edDrawSide();
  if (jobDone && d.job) toast(d.job.error ? `Not done: ${d.job.error}` : d.job.what === "ai" ? "The AI changed the video: have a look" : d.job.what === "render" ? "Video rendered: watch it, then approve" : "Editor ready");
  clearTimeout(ED.poll);
  if (d.job && !d.job.done) ED.poll = setTimeout(() => edLoad(false), 4000);
}

const edFmt = s => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const edBusy = () => ED.d?.job && !ED.d.job.done;
const edWin = () => document.getElementById("ed-frame")?.contentWindow;
const edSection = t => (ED.d?.sections || []).find(s => t >= s.t0 && t < s.t1);

function edDraw() {
  const d = ED.d, box = document.querySelector("#ed-root > div");
  if (!d.ready) {
    box.innerHTML = `${edHead()}<div class="p-8 flex flex-col items-start gap-3">
      <p class="text-sm text-slate-700">${edBusy() ? `${icon("progress_activity", "text-sm animate-spin align-middle")} Preparing the editor: drawing every section once (a minute or two)…` : "This video was made before the editor existed. Prepare it once: the editor draws every section and times it to your approved voice."}</p>
      ${edBusy() ? "" : button("primary", "build", "Prepare the editor", 'id="ed-prepare"')}</div>`;
    edWireHead();
    box.querySelector("#ed-prepare")?.addEventListener("click", () => edDo("/api/factory-edit/prepare", {}, "Preparing the editor"));
    return;
  }
  const wide = d.width > d.height;
  box.innerHTML = `${edHead()}
    <div class="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[auto_minmax(0,1fr)_minmax(0,1.1fr)] gap-4 p-4 overflow-auto">
      <section class="flex flex-col gap-2 items-center">
        <div id="ed-stage" class="relative rounded-xl overflow-hidden shadow bg-black ${wide ? "w-[560px]" : "w-[340px]"} max-w-full" style="aspect-ratio:${d.width}/${d.height}">
          <iframe id="ed-frame" src="${esc(d.page)}" class="absolute inset-0 w-full h-full border-0 pointer-events-none" title="The video, live"></iframe>
          <div id="ed-hit" class="absolute inset-0 cursor-crosshair"></div>
          <div id="ed-boxes" class="absolute inset-0 pointer-events-none"></div>
        </div>
        ${d.video ? `<audio id="ed-audio" preload="auto" src="${esc(d.video)}" class="hidden"></audio>` : ""}
        <div class="w-full ${wide ? "max-w-[560px]" : "max-w-[340px]"} flex flex-col gap-2">
          <div id="ed-line" class="relative h-9 rounded-lg bg-white border border-slate-200 overflow-hidden cursor-pointer select-none"></div>
          <div class="flex items-center gap-1 flex-wrap">
            <button id="ed-play" class="${BTN.secondary} !px-3" title="Play or pause (space)">${icon(ED.playing ? "pause" : "play_arrow")}</button>
            <button data-ed-step="-1" class="${BTN.secondary} !px-2" title="One frame back (left arrow)">${icon("chevron_left")}</button>
            <button data-ed-step="1" class="${BTN.secondary} !px-2" title="One frame on (right arrow)">${icon("chevron_right")}</button>
            <button data-ed-jump="-1" class="${BTN.secondary} !px-2" title="Previous section">${icon("skip_previous")}</button>
            <button data-ed-jump="1" class="${BTN.secondary} !px-2" title="Next section">${icon("skip_next")}</button>
            <span id="ed-time" class="text-xs font-mono text-slate-600 ml-1"></span>
          </div>
          <div class="flex items-center gap-2 flex-wrap">
            ${button("secondary", "add_photo_alternate", "Pick this frame", 'id="ed-pick" title="Pick the frame on screen for an AI change (up to 6)"')}
            <div id="ed-frames" class="flex flex-wrap gap-1"></div>
          </div>
        </div>
      </section>
      <section class="bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col min-h-0">
        <div class="px-4 py-3 border-b border-slate-100"><h3 class="text-sm font-bold text-slate-900">${tip("Sections", "One section per line of your script, as long as its voice. Click one to go to it; tick it to give it to the AI.")}</h3></div>
        <ol id="ed-sections" class="divide-y divide-slate-100 overflow-auto"></ol>
      </section>
      <section class="bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col min-h-0">
        <div class="flex border-b border-slate-100">
          ${[["hand", "pan_tool", "Edit by hand"], ["ai", "auto_awesome", "Edit with AI"]].map(([k, ic, w]) => { const cls = edTabCls(ED.tab === k); return `<button data-ed-tab="${k}" class="${cls}">${icon(ic, "text-base")}<span>${w}</span></button>`; }).join("")}
        </div>
        <div id="ed-side" class="p-4 overflow-auto flex-1 min-h-0"></div>
      </section>
    </div>
    <div id="ed-foot" class="border-t border-slate-200 bg-white px-4 py-3"></div>`;
  edWireHead();
  edWire();
  edDrawSide();
}

function edHead() {
  return `<div class="flex items-center gap-3 px-4 py-3 border-b border-slate-200 bg-white">
    ${icon("movie_edit", "text-violet-600 text-2xl")}
    <div class="min-w-0 flex-1"><h2 class="text-base font-bold text-slate-900 truncate">Edit video</h2><p class="text-xs text-slate-500 truncate">${esc(ED.d?.title || ED.slug)}</p></div>
    <button id="ed-close" class="${BTN.secondary} !px-3" title="Close the editor">${icon("close")}<span>Close</span></button></div>`;
}
function edWireHead() { document.getElementById("ed-close")?.addEventListener("click", edClose); }

// ---------- the live picture ----------
async function edFrameReady() {
  const w = edWin();
  if (!w || !w.shellReady) return false;
  await w.shellReady;
  w.EDITOR?.set(ED.edits);
  try { w.prepareLabels?.(); } catch (e) { /* drawn anyway */ }
  return true;
}
function edShow(t) {
  const d = ED.d, w = edWin();
  ED.t = Math.max(0, Math.min(t, (d.duration || 0) - 0.001));
  try { w?.seek?.(ED.t); } catch (e) { /* a drawing error shows as a blank frame */ }
  const tm = document.getElementById("ed-time"), sec = edSection(ED.t);
  if (tm) tm.textContent = `${edFmt(ED.t)} / ${edFmt(d.duration || 0)}${sec ? ` · section ${sec.i + 1}` : ED.t >= (d.end || 1e9) ? " · outro" : ""}`;
  const ph = document.getElementById("ed-head-mark");
  if (ph) ph.style.left = `${100 * ED.t / (d.duration || 1)}%`;
  document.querySelectorAll("[data-ed-sec]").forEach(li => li.classList.toggle("bg-violet-50", sec && +li.dataset.edSec === sec.i));
  if (!ED.playing) edTexts();
}
function edPlay(on) {
  ED.playing = on;
  const a = document.getElementById("ed-audio"), b = document.getElementById("ed-play");
  if (b) b.innerHTML = icon(on ? "pause" : "play_arrow");
  cancelAnimationFrame(ED.raf);
  if (!on) { a?.pause(); edShow(ED.t); return; }
  const t0 = performance.now(), s0 = ED.t >= (ED.d.duration - 0.05) ? 0 : ED.t;
  if (a) { a.currentTime = s0; a.play().catch(() => {}); }
  const tick = () => {
    if (!ED.playing) return;
    const t = a && !a.paused ? a.currentTime : s0 + (performance.now() - t0) / 1000;
    if (t >= ED.d.duration) { ED.t = ED.d.duration - 0.001; edPlay(false); return; }
    edShow(t);
    ED.raf = requestAnimationFrame(tick);
  };
  ED.raf = requestAnimationFrame(tick);
}

// the texts this frame draws, as boxes over the picture: click one to edit it, drag a floating label to move it
function edTexts() {
  const w = edWin(), boxes = document.getElementById("ed-boxes");
  if (!w?.EDITOR || !boxes) return;
  try { ED.texts = w.EDITOR.texts(ED.t); } catch (e) { ED.texts = []; }
  const k = boxes.clientWidth / ED.d.width;
  boxes.innerHTML = ED.texts.map((r, i) => { const cls = ED.sel === r.s ? "border-violet-500 bg-violet-500/10" : "border-transparent"; return `<div class="absolute rounded border ${cls}" style="left:${(r.x - 3) * k}px;top:${(r.y - 3) * k}px;width:${(r.w + 6) * k}px;height:${(r.h + 6) * k}px" data-i="${i}"></div>`; }).join("");
  if (ED.tab === "hand") edDrawSide();
}
function edHit(ev) {
  const r = document.getElementById("ed-hit").getBoundingClientRect(), k = ED.d.width / r.width;
  const x = (ev.clientX - r.left) * k, y = (ev.clientY - r.top) * k;
  let best = null;
  for (const b of ED.texts) if (x >= b.x - 8 && x <= b.x + b.w + 8 && y >= b.y - 8 && y <= b.y + b.h + 8 && (!best || b.w * b.h < best.w * best.h)) best = b;
  return { best, x, y, k };
}
function edApply(relayout) {
  const w = edWin();
  w?.EDITOR?.set(ED.edits);
  if (relayout) try { w?.prepareLabels?.(); } catch (e) { /* drawn anyway */ }
  edShow(ED.t);
}
let edRelayout = 0;
function edChanged(relayout) {
  ED.dirty = true;
  if (relayout) { clearTimeout(edRelayout); edRelayout = setTimeout(() => edApply(true), 500); edApply(false); }
  else edApply(false);
  edDrawFoot();
}

function edWire() {
  const fr = document.getElementById("ed-frame");
  fr.addEventListener("load", async () => { if (await edFrameReady()) { edShow(ED.t); edDrawLine(); } });
  document.getElementById("ed-play").addEventListener("click", () => edPlay(!ED.playing));
  document.querySelectorAll("[data-ed-step]").forEach(b => b.addEventListener("click", () => { edPlay(false); edShow(ED.t + (+b.dataset.edStep) / FPS); }));
  document.querySelectorAll("[data-ed-jump]").forEach(b => b.addEventListener("click", () => {
    edPlay(false);
    const s = ED.d.sections, cur = edSection(ED.t), i = cur ? cur.i + (+b.dataset.edJump) : (+b.dataset.edJump > 0 ? 0 : s.length - 1);
    if (s[i]) edShow(s[i].t0 + 0.8 * (s[i].t1 - s[i].t0));
  }));
  document.getElementById("ed-pick").addEventListener("click", () => {
    const t = Math.round(ED.t * 100) / 100;
    if (ED.frames.includes(t)) return;
    if (ED.frames.length >= 6) return toast("Up to 6 frames: remove one first", true);
    ED.frames.push(t); ED.frames.sort((a, b) => a - b);
    ED.tab = "ai"; edDrawTabs(); edDrawLine(); edDrawFrames(); edDrawSide();
  });
  const line = document.getElementById("ed-line");
  const seekAt = ev => { const r = line.getBoundingClientRect(); edShow((ev.clientX - r.left) / r.width * ED.d.duration); };
  line.addEventListener("mousedown", ev => {
    edPlay(false); seekAt(ev);
    const mv = e => seekAt(e), up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); };
    addEventListener("mousemove", mv); addEventListener("mouseup", up);
  });
  const hit = document.getElementById("ed-hit");
  hit.addEventListener("mousedown", ev => {
    edPlay(false);
    const { best } = edHit(ev);
    ED.sel = best ? best.s : null;
    ED.tab = "hand"; edDrawTabs(); edTexts();
    if (!best || best.kind !== "label") return;
    const m0 = ED.edits.moves[best.s] || [0, 0], x0 = ev.clientX, y0 = ev.clientY;
    const r = hit.getBoundingClientRect(), V = ED.d.height > ED.d.width, S = V ? ED.d.width / 1080 : ED.d.height / 1080, k = ED.d.width / r.width / S;
    const mv = e => { ED.edits.moves[best.s] = [Math.round(m0[0] + (e.clientX - x0) * k), Math.round(m0[1] + (e.clientY - y0) * k)]; edChanged(false); };
    const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); edTexts(); };
    addEventListener("mousemove", mv); addEventListener("mouseup", up);
  });
  document.querySelectorAll("[data-ed-tab]").forEach(b => b.addEventListener("click", () => { ED.tab = b.dataset.edTab; edDrawTabs(); edDrawSide(); }));
  document.getElementById("ed-root").onkeydown = ev => {
    if (ev.target.closest("input,textarea")) return;
    if (ev.key === " ") { ev.preventDefault(); edPlay(!ED.playing); }
    if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") { ev.preventDefault(); edPlay(false); edShow(ED.t + (ev.key === "ArrowRight" ? 1 : -1) / FPS); }
  };
  document.getElementById("ed-root").tabIndex = -1;
  document.getElementById("ed-root").focus();
}
const edTabCls = on => "flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm font-semibold " + (on ? "text-violet-700 border-b-2 border-violet-600" : "text-slate-500 hover:text-slate-800");
function edDrawTabs() {
  document.querySelectorAll("[data-ed-tab]").forEach(b => {
    const on = b.dataset.edTab === ED.tab;
    b.className = edTabCls(on);
  });
}

// ---------- timeline, sections, picked frames ----------
function edDrawLine() {
  const d = ED.d, line = document.getElementById("ed-line");
  if (!line) return;
  const pc = t => `${100 * t / (d.duration || 1)}%`;
  line.innerHTML = d.sections.map(s => { const cls = ED.sections.has(s.i) ? "bg-violet-300" : s.i % 2 ? "bg-slate-200" : "bg-slate-100"; return `<div class="absolute top-0 bottom-0 border-r border-white ${cls}" style="left:${pc(s.t0)};width:${pc(s.t1 - s.t0)}" title="Section ${s.i + 1}: ${esc(s.say)}"><span class="absolute left-1 top-0.5 text-[10px] font-semibold text-slate-600">${s.i + 1}</span></div>`; }).join("")
    + `<div class="absolute top-0 bottom-0 bg-amber-100" style="left:${pc(d.end)};right:0" title="The outro"></div>`
    + ED.frames.map(t => `<div class="absolute bottom-0 w-1 h-3 bg-violet-700 rounded-t" style="left:${pc(t)}" title="Picked frame ${t.toFixed(2)} s"></div>`).join("")
    + `<div id="ed-head-mark" class="absolute top-0 bottom-0 w-0.5 bg-rose-600" style="left:${pc(ED.t)}"></div>`;
  edDrawFrames();
  const ol = document.getElementById("ed-sections");
  if (ol) {
    const cur = edSection(ED.t);
    ol.innerHTML = d.sections.map(s => { const on = cur && cur.i === s.i ? "bg-violet-50" : ""; return `<li data-ed-sec="${s.i}" class="flex items-start gap-2 px-4 py-2.5 cursor-pointer hover:bg-slate-50 ${on}">
      <input type="checkbox" class="mt-0.5 rounded border-slate-300 text-violet-600" data-ed-tick="${s.i}" ${ED.sections.has(s.i) ? "checked" : ""} title="Give this section to the AI">
      <div class="min-w-0"><p class="text-xs font-semibold text-slate-500">${s.i + 1} · ${edFmt(s.t0)} to ${edFmt(s.t1)}</p><p class="text-sm text-slate-800">${esc(s.say)}</p></div></li>`; }).join("");
    ol.querySelectorAll("[data-ed-sec]").forEach(li => li.addEventListener("click", ev => {
      if (ev.target.matches("input")) return;
      const s = d.sections[+li.dataset.edSec]; edPlay(false); edShow(s.t0 + 0.8 * (s.t1 - s.t0));
    }));
    ol.querySelectorAll("[data-ed-tick]").forEach(cb => cb.addEventListener("change", () => {
      const i = +cb.dataset.edTick; cb.checked ? ED.sections.add(i) : ED.sections.delete(i); edDrawLine(); if (ED.tab === "ai") edDrawSide();
    }));
  }
}
function edDrawFrames() {
  const el = document.getElementById("ed-frames");
  if (!el) return;
  el.innerHTML = ED.frames.map(t => `<span class="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-full bg-violet-50 border border-violet-200 text-xs text-violet-800">
    <button data-ed-go="${t}" class="font-mono" title="Go to this frame">${t.toFixed(2)} s</button>
    <button data-ed-unpick="${t}" class="text-violet-500 hover:text-rose-600" title="Remove">${icon("close", "text-xs")}</button></span>`).join("");
  el.querySelectorAll("[data-ed-go]").forEach(b => b.addEventListener("click", () => { edPlay(false); edShow(+b.dataset.edGo); }));
  el.querySelectorAll("[data-ed-unpick]").forEach(b => b.addEventListener("click", () => { ED.frames = ED.frames.filter(x => x !== +b.dataset.edUnpick); edDrawLine(); if (ED.tab === "ai") edDrawSide(); }));
}

// ---------- the side panel: by hand, with AI ----------
const ED_KIND = { name: ["Name", "Printed on its object"], label: ["Label", "Floats beside the picture with an arrow: drag it on the picture to move it"], text: ["Text", "Drawn by the animation"] };
function edDrawSide() {
  const side = document.getElementById("ed-side");
  if (!side) return;
  if (ED.tab === "hand") side.innerHTML = edHand();
  else side.innerHTML = edAi();
  edWireSide(side);
  edDrawFoot();
}
function edHand() {
  const hidden = ED.edits.hide || [];
  const rows = ED.texts.map(r => {
    const [kw, kt] = ED_KIND[r.kind] || ED_KIND.text, now = ED.edits.texts[r.s] ?? r.s, mv = ED.edits.moves[r.s];
    const on = ED.sel === r.s ? "bg-violet-50 -mx-2 px-2 rounded-lg" : "";
    return `<li class="py-2.5 ${on}">
      <div class="flex items-center gap-2 mb-1"><span class="text-[11px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600" title="${esc(kt)}">${kw}</span>
        ${now !== r.s ? `<span class="text-[11px] text-slate-400 truncate" title="As drawn">was "${esc(r.s)}"</span>` : ""}
        ${mv ? `<span class="text-[11px] text-violet-700">moved</span><button data-ed-unmove="${esc(r.s)}" class="text-[11px] text-slate-500 underline">put back</button>` : ""}</div>
      <div class="flex items-center gap-2"><input data-ed-word="${esc(r.s)}" value="${esc(now)}" maxlength="120" class="flex-1 min-w-0 rounded-lg border-slate-300 text-sm py-1.5">
        <button data-ed-hide="${esc(r.s)}" class="${BTN.secondary} !px-2.5 !py-1.5" title="Hide this text in the whole video">${icon("visibility_off", "text-base")}</button></div></li>`;
  }).join("");
  return `<p class="text-xs text-slate-500 mb-2">Click a text on the picture to pick it. Change its words, hide it, or drag a floating label to a new place. A change counts for the whole video, and you see it at once.</p>
    <ul class="divide-y divide-slate-100">${rows || `<li class="py-4 text-sm text-slate-500">No text in this frame.</li>`}</ul>
    ${hidden.length ? `<div class="mt-4"><p class="text-xs font-semibold text-slate-600 mb-1">Hidden</p><div class="flex flex-wrap gap-1">${hidden.map(s => `<button data-ed-unhide="${esc(s)}" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-xs text-slate-700 hover:bg-slate-200" title="Show it again">${icon("visibility", "text-xs")}<span>${esc(s)}</span></button>`).join("")}</div></div>` : ""}
    <div class="flex gap-2 mt-4">${button("primary", "save", "Save hand edits", `id="ed-save" ${ED.dirty ? "" : "disabled"}`)}${button("secondary", "undo", "Discard", `id="ed-discard" ${ED.dirty ? "" : "disabled"}`)}</div>`;
}
function edAi() {
  const d = ED.d, busy = edBusy() && d.job.what === "ai", secs = [...ED.sections].sort((a, b) => a - b);
  const scope = ED.frames.length || secs.length
    ? `${ED.frames.length ? `frame${ED.frames.length > 1 ? "s" : ""} ${ED.frames.map(t => `${t.toFixed(1)} s`).join(", ")}` : ""}${ED.frames.length && secs.length ? " and " : ""}${secs.length ? `section${secs.length > 1 ? "s" : ""} ${secs.map(i => i + 1).join(", ")}` : ""}`
    : "the whole video (pick frames or tick sections to aim it)";
  const live = (d.history || []).filter(h => !h.undone);
  return `<label class="text-xs font-semibold text-slate-600" for="ed-cmd">What should change?</label>
    <textarea id="ed-cmd" rows="4" maxlength="1500" class="mt-1 w-full rounded-lg border-slate-300 text-sm" placeholder="e.g. the two chips on the right cover each other: put the second one under the server; make the database bigger" ${busy ? "disabled" : ""}>${esc(ED.cmd || "")}</textarea>
    <p class="text-xs text-slate-500 mt-1">For ${esc(scope)}.</p>
    <div class="flex gap-2 mt-3 flex-wrap">${button("primary", "auto_awesome", busy ? "The AI is changing it…" : "Ask AI to change it", `id="ed-ask" ${edBusy() ? "disabled" : ""}`)}
      ${button("secondary", "undo", "Undo last AI change", `id="ed-undo" ${live.length && !edBusy() ? "" : "disabled"}`)}</div>
    ${busy ? `<p class="text-sm text-slate-600 mt-3">${icon("progress_activity", "text-sm animate-spin align-middle")} Changing the drawing and checking it (a few minutes). You can keep watching.</p>` : ""}
    <h4 class="text-xs font-semibold text-slate-600 mt-5 mb-1">Changes</h4>
    <ol class="space-y-2">${(d.history || []).map(h => `<li class="rounded-lg border border-slate-200 p-2.5 ${h.undone ? "opacity-60" : ""}">
      <p class="text-xs text-slate-500">${fmtTime(h.at)}${h.sections?.length ? ` · sections ${h.sections.join(", ")}` : ""}${h.frames?.length ? ` · frames ${h.frames.map(t => t.toFixed(1)).join(", ")} s` : ""}${h.undone ? " · undone" : ""}</p>
      <p class="text-sm text-slate-900 mt-0.5">${esc(h.command)}</p>
      ${h.result ? `<p class="text-sm text-slate-600 mt-1">${icon("auto_awesome", "text-xs text-violet-500 align-middle")} ${esc(h.result)}</p>` : ""}
      ${(h.problems || []).length ? `<p class="text-xs text-amber-700 mt-1">The check still sees: ${esc(h.problems.join("; "))}</p>` : ""}</li>`).join("") || `<li class="text-sm text-slate-500">No AI changes yet.</li>`}</ol>`;
}
function edWireSide(side) {
  side.querySelectorAll("[data-ed-word]").forEach(inp => {
    inp.addEventListener("focus", () => { ED.sel = inp.dataset.edWord; });
    inp.addEventListener("input", () => {
      const k = inp.dataset.edWord, v = inp.value.trim();
      if (!v || v === k) delete ED.edits.texts[k]; else ED.edits.texts[k] = v;
      edChanged(true);
    });
    inp.addEventListener("change", () => edTexts());
  });
  side.querySelectorAll("[data-ed-hide]").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.edHide; if (!ED.edits.hide.includes(k)) ED.edits.hide.push(k); edChanged(true); edTexts();
  }));
  side.querySelectorAll("[data-ed-unhide]").forEach(b => b.addEventListener("click", () => {
    ED.edits.hide = ED.edits.hide.filter(s => s !== b.dataset.edUnhide); edChanged(true); edTexts();
  }));
  side.querySelectorAll("[data-ed-unmove]").forEach(b => b.addEventListener("click", () => { delete ED.edits.moves[b.dataset.edUnmove]; edChanged(false); edTexts(); }));
  side.querySelector("#ed-save")?.addEventListener("click", edSave);
  side.querySelector("#ed-discard")?.addEventListener("click", () => {
    const e = ED.d.edits; ED.edits = { texts: { ...(e.texts || {}) }, hide: [...(e.hide || [])], moves: { ...(e.moves || {}) } };
    ED.dirty = false; edApply(true); edTexts(); edDrawFoot();
  });
  const cmd = side.querySelector("#ed-cmd");
  cmd?.addEventListener("input", () => { ED.cmd = cmd.value; });
  side.querySelector("#ed-ask")?.addEventListener("click", edAsk);
  side.querySelector("#ed-undo")?.addEventListener("click", () => edDo("/api/factory-edit/undo", {}, "Undone: the drawing from before that change is back"));
}

// ---------- actions ----------
async function edSave(quiet) {
  if (!ED.dirty) return true;
  try {
    ED.d = await post("/api/factory-edit/edits", { slug: ED.slug, edits: ED.edits });
    ED.dirty = false;
    if (quiet !== true) toast("Hand edits saved: Render the video to record them");
    edDrawSide();
    return true;
  } catch (e) { toast(e.message, true); return false; }
}
async function edDo(path, body, ok) {
  try { ED.d = await post(path, { slug: ED.slug, ...body }); toast(ok); }
  catch (e) { toast(e.message, true); return; }
  edLoad(false);
}
async function edAsk() {
  const command = (ED.cmd || "").trim();
  if (command.length < 3) return toast("Say what to change", true);
  if (!(await edSave(true))) return;
  const w = edWin(), cv = w?.document.getElementById("c"), frames = [];
  for (const t of ED.frames) { try { w.seek(t); frames.push({ t, image: cv.toDataURL("image/jpeg", 0.85) }); } catch (e) { frames.push({ t }); } }
  edShow(ED.t);
  try { ED.d = await post("/api/factory-edit/ask", { slug: ED.slug, command, frames, sections: [...ED.sections] }); }
  catch (e) { return toast(e.message, true); }
  ED.cmd = ""; toast("The AI is on it: the change shows here when it is done");
  edDrawSide(); edLoad(false);
}
function edDrawFoot() {
  const f = document.getElementById("ed-foot"), d = ED.d;
  if (!f) return;
  const busy = edBusy(), rendering = busy && d.job.what === "render", approved = d.plan_state === "made" || d.post?.status === "approved";
  const changed = d.changed || ED.dirty;
  const where = approved ? `${icon("check_circle", "text-emerald-600 align-middle")} Approved: it is in the Queue, ready for upload.`
    : rendering ? `${icon("progress_activity", "text-sm animate-spin align-middle")} Rendering the video with your changes (several minutes)…`
    : changed ? `${icon("edit", "text-amber-600 align-middle")} Changed since the video was last rendered: render it, watch it, then approve it.`
    : `${icon("movie", "text-slate-500 align-middle")} The video${d.rendered_at ? ` was rendered ${esc(ago(d.rendered_at))}` : " is rendered"}. Nothing is uploaded until you approve it.`;
  const theme = (d.themes || []).length && !approved ? `<label class="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600">${icon("palette", "text-sm text-slate-400")}<span>${tip("Theme", "The look of the whole video: colours, set and captions. The drawing stays; render the video to record it.")}</span>
      <select id="ed-theme" class="rounded-lg border-slate-300 text-sm py-1.5" ${busy ? "disabled" : ""}>${d.themes.map(t => `<option value="${t.id}" title="${esc(t.what)}" ${d.theme === t.id ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></label>` : "";
  const thumbBox = d.thumbnail || d.post ? `<div class="flex items-center gap-2">
      ${d.thumbnail ? `<a href="${esc(d.thumbnail)}" target="_blank" title="The thumbnail set on YouTube with this video"><img src="${esc(d.thumbnail)}" alt="Thumbnail" class="h-16 w-9 rounded object-cover border border-slate-200"></a>` : ""}
      ${tip(d.thumbnail ? "Thumbnail" : "No thumbnail yet", "Designed from the title and the narration; it is set on YouTube when the video uploads.")}
      ${approved ? "" : button("secondary", "image", d.thumbnail ? "Make it again" : "Make the thumbnail", `id="ed-thumb" ${busy ? "disabled" : ""}`)}</div>` : "";
  f.innerHTML = `<div class="flex items-center gap-3 flex-wrap">
    ${theme}
    ${thumbBox}
    <p class="text-sm text-slate-700 flex-1 min-w-[16rem]">${where}${d.job?.error && d.job.done ? ` <span class="text-rose-700">${esc(d.job.error)}</span>` : ""}</p>
    ${d.video ? `<a href="${esc(d.video)}" target="_blank" class="${BTN.secondary}">${icon("play_circle")}<span>Watch the rendered video</span></a>` : ""}
    ${approved ? button("secondary", "undo", "Take it back to edit", 'id="ed-reopen"')
      : `${button(changed ? "primary" : "secondary", "movie", rendering ? "Rendering…" : "Render the video", `id="ed-render" ${busy ? "disabled" : ""}`)}
         <button id="ed-approve" class="${BTN.approve} disabled:opacity-40 disabled:cursor-not-allowed" ${busy || changed ? "disabled" : ""} title="${changed ? "Render the video first, watch it, then approve" : "Approve: ready for upload"}">${icon("check")}<span>Approve video</span></button>`}</div>`;
  f.querySelector("#ed-thumb")?.addEventListener("click", () => edDo("/api/factory-edit/thumbnail", {}, "Designing the thumbnail (about a minute)"));
  f.querySelector("#ed-theme")?.addEventListener("change", async e => {
    if (!(await edSave(true))) return;
    edDo("/api/factory-edit/theme", { theme: e.target.value }, "Theme changed: drawing the video in it (a minute or two)");
  });
  f.querySelector("#ed-render")?.addEventListener("click", async () => { if (await edSave(true)) edDo("/api/factory-edit/render", {}, "Rendering the video with your changes"); });
  f.querySelector("#ed-approve")?.addEventListener("click", () => edDo("/api/factory-edit/approve", {}, "Approved: the video is ready for upload"));
  f.querySelector("#ed-reopen")?.addEventListener("click", () => edDo("/api/factory-edit/reopen", {}, "Back in the editor: approve it again when it is ready"));
}
