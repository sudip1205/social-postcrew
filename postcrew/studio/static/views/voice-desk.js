// Factory > Plans (owner, 2026-11-17): YouTube is made by hand. Type a topic and Plan (research + plans, like the monthly ones); pick a plan
// and Write the script with your instructions; record your voice for it (or skip to dip_puck / am_puck); approve both; Make the video.
// Backend: postcrew/factory_plans.py and postcrew/voice_desk.py. Built from the Factory page's components (ui.js: chip, button, icon, tip).
let VD = null, vdTimer = null;
const VD_OPEN = new Set(), VD_EDIT = new Set();
const VD_VOICE = {
  none: ["pending", "No voice yet"], processing: ["running", "Processing your voice"], ready: ["awaiting_approval", "Listen and approve"],
  approved: ["approved", "Voice approved"], failed: ["failed", "Voice failed"],
};
const VD_MODE = { own: "Your voice (matched to dip_puck)", dip_puck: "dip_puck (AI voice)", am_puck: "am_puck (Kokoro AI voice)" };
const VD_LOOK = { iso: "Isometric", signal: "Signal (blue)", story: "Story", code: "VS Code", "3d": "3D" };

async function vdOpen() {
  clearInterval(vdTimer);
  await vdLoad();
  vdTimer = setInterval(() => { if (!document.getElementById("vd-root")) return clearInterval(vdTimer); vdLoad(); }, 5000);
}

let vdLast = "";
async function vdLoad(force) {
  try {
    const d = await api("/api/voice-desk"), key = JSON.stringify(d);
    if (!force && key === vdLast && document.getElementById("vd-root")?.childElementCount) return;   // nothing changed: no redraw, no flicker
    vdLast = key; VD = d; vdDraw();
  }
  catch (e) { const r = document.getElementById("vd-root"); if (r) r.innerHTML = `<p class="p-5 text-sm text-rose-700">${esc(e.message)}</p>`; }
}

const vdBusy = j => j && !j.done;

// where a plan is: [chip state, word]
function vdState(p) {
  const ep = p.episode, v = ep?.voice || {};
  if (p.state === "writing") return ["running", "Writing the script"];
  if (p.state === "making") return ["running", "Making the video"];
  if (!ep) return ["idle", "Planned"];
  if (ep.script !== "approved") return ["awaiting_approval", "Approve the script"];
  if (v.state === "processing") return ["running", "Processing your voice"];
  if (v.state !== "approved") return ["awaiting_approval", "Add your voice"];
  return ["approved", "Ready to make"];
}

function vdDraw() {
  const root = document.getElementById("vd-root");
  if (!root || !VD) return;
  const a = document.activeElement;
  if (a && root.contains(a) && (a.tagName === "TEXTAREA" || a.tagName === "INPUT" && a.type === "text")) return;   // never redraw over your typing
  if ([...root.querySelectorAll("audio")].some(x => !x.paused)) return;   // never cut off a recording you are listening to
  // keep where you were: the page scroll and every scrolled list (the script lines) survive the redraw
  const pageY = window.scrollY, lists = {};
  root.querySelectorAll("[data-vd-scroll]").forEach(el => { lists[el.dataset.vdScroll] = el.scrollTop; });
  const pl = VD.planning;
  root.style.minHeight = root.offsetHeight + "px";
  root.innerHTML = `
    <div class="px-5 py-4 border-b border-slate-200">
      <div class="flex items-center gap-3 mb-3">
        <span class="w-9 h-9 rounded-lg bg-violet-50 text-violet-600 grid place-items-center">${icon("record_voice_over")}</span>
        <div>
          <h2 class="font-headline font-bold text-slate-900">Plans</h2>
          <p class="text-xs text-slate-500">Nothing is made automatically. Plan a topic, write a plan's script with your instructions, record the ${tip("voice", "Your recording, cleaned (retakes and long gaps removed, your sentence pauses and pronunciation kept) and matched to dip_puck with Seed-VC. Or skip it and let dip_puck or am_puck read the script.")}, approve both, then make the video. A plan stays here until its video is made.</p>
        </div>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <label class="flex-1 min-w-[16rem]"><span class="block text-xs font-medium text-slate-600 mb-1">Topic</span>
          <input id="vd-topic" type="text" placeholder="e.g. how databases scale, consistent hashing, binary search" class="w-full text-sm rounded-lg border-slate-300 focus:border-violet-500 focus:ring-violet-500"></label>
        <label class="flex-1 min-w-[12rem]"><span class="block text-xs font-medium text-slate-600 mb-1">What you want (optional)</span>
          <input id="vd-hint" type="text" placeholder="angle, audience, what to avoid" class="w-full text-sm rounded-lg border-slate-300 focus:border-violet-500 focus:ring-violet-500"></label>
        <label><span class="block text-xs font-medium text-slate-600 mb-1">Plans</span>
          <select id="vd-count" class="text-sm rounded-lg border-slate-300">${[1, 2, 3, 4, 5].map(n => `<option ${n === 3 ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label><span class="block text-xs font-medium text-slate-600 mb-1">Format</span>
          <select id="vd-format" class="text-sm rounded-lg border-slate-300"><option value="short">Short</option><option value="long">Long</option></select></label>
        ${button("primary", "travel_explore", vdBusy(pl) ? "Planning…" : "Plan", `id="vd-plan" ${vdBusy(pl) ? "disabled" : ""}`)}
      </div>
      ${vdBusy(pl) ? `<p class="mt-2 text-sm text-slate-600">${icon("progress_activity", "text-sm animate-spin align-middle")} ${esc(pl.step || "Working")} (“${esc(pl.topic || "")}”). About a minute.</p>` : ""}
      ${pl?.error ? `<p class="mt-2 text-sm text-rose-700">${icon("error", "text-sm align-middle")} ${esc(pl.error)}</p>` : ""}
    </div>
    ${!VD.whisper ? `<p class="px-5 py-2 text-sm text-amber-800 bg-amber-50 border-b border-amber-200">faster-whisper is not installed on this computer, so recordings cannot be processed here (pip install faster-whisper). Use the Studio on the lab.</p>` : ""}
    ${!VD.converter ? `<p class="px-5 py-2 text-sm text-amber-800 bg-amber-50 border-b border-amber-200">Seed-VC is not found (~/voicelab/seed-vc): your recording cannot be matched to dip_puck on this computer. Skipping to dip_puck or am_puck still works.</p>` : ""}
    <div class="divide-y divide-slate-100">${VD.plans.map(vdRow).join("") || `<p class="p-5 text-sm text-slate-500">No plans yet. Type a topic above and press Plan.</p>`}</div>
    ${VD.made ? `<p class="px-5 py-3 text-xs text-slate-500 border-t border-slate-100">${VD.made} plan(s) made into videos: they are in the Queue.</p>` : ""}
    ${VD.others?.length ? `<p class="px-5 pt-4 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 border-t border-slate-200">Other scripts waiting for your voice (Factory chat, manual runs)</p>
      <div class="divide-y divide-slate-100 border-t border-slate-100">${VD.others.map(ep => vdRow({ id: "", title: ep.title, topic: "", state: "script", slug: ep.slug, episode: ep, other: true })).join("")}</div>` : ""}`;
  vdWire(root);
  root.querySelectorAll("[data-vd-scroll]").forEach(el => { if (lists[el.dataset.vdScroll] != null) el.scrollTop = lists[el.dataset.vdScroll]; });
  root.style.minHeight = "";
  if (Math.abs(window.scrollY - pageY) > 1) window.scrollTo(0, pageY);
}

function vdRow(p) {
  const key = p.id || p.slug, open = VD_OPEN.has(key), [st, word] = vdState(p), r = p.research || {};
  const meta = [p.format === "long" ? "Long" : "Short", p.topic && p.topic !== p.title ? `topic: ${p.topic}` : "",
    r.trend_score != null ? `trend ${r.trend_score}/100` : "", p.looks?.length ? p.looks.map(l => VD_LOOK[l] || l).join(" + ") : ""].filter(Boolean).join(" · ");
  return `
    <div class="flex flex-wrap items-center gap-3 px-5 py-3 cursor-pointer hover:bg-slate-50" data-vd-toggle="${esc(key)}">
      <div class="flex-1 min-w-[14rem]">
        <p class="text-sm text-slate-900 font-medium">${esc(p.title)}</p>
        <p class="text-xs text-slate-500">${esc(meta)}</p>
        ${p.error ? `<p class="text-xs text-rose-700 mt-0.5">${esc(p.error)}</p>` : ""}
      </div>
      ${chip(st, word, "sm")}
      ${button("secondary", "delete", "Delete", `${p.other ? `data-vd-remove-ep="${esc(p.slug)}"` : `data-vd-remove="${p.id}"`} title="Delete it from the Factory" ${p.state === "writing" || p.state === "making" || (vdBusy(p.episode?.job) && p.episode.job.what === "video") ? "disabled" : ""}`)}
      ${icon(open ? "expand_less" : "expand_more", "text-slate-400")}
    </div>` + (open ? vdDetail(p) : "");
}

function vdPlanCard(p) {
  const r = p.research || {};
  const field = (k, label) => p[k] ? `<p class="text-sm text-slate-700"><span class="text-xs font-semibold text-slate-500">${label}:</span> ${esc(p[k])}</p>` : "";
  const busy = p.state === "writing";
  return `
    <div class="rounded-lg border border-slate-200 bg-white p-4 ${p.episode ? "" : "lg:col-span-2"}">
      <h3 class="text-sm font-bold text-slate-900 flex items-center gap-2 mb-2">${icon("lightbulb", "text-slate-500")} Plan</h3>
      <div class="space-y-1">${field("angle", "Angle")}${field("context", "What it is about")}${field("example", "Example")}${field("takeaway", "Takeaway")}</div>
      ${r.trend_score != null || r.why ? `<div class="mt-2 text-xs text-slate-600 space-y-0.5">
        ${r.trend_score != null ? `<p>${tip("Research", "Read from YouTube when the plan was written: how this subject is doing right now.")}: trend ${r.trend_score}/100${r.label ? ` (${esc(r.label)})` : ""}${r.views_per_day != null ? ` · ${Number(r.views_per_day).toLocaleString()} views/day` : ""}${r.engagement_pct != null ? ` · ${r.engagement_pct}% like` : ""}</p>` : ""}
        ${r.why ? `<p>${esc(r.why)}</p>` : ""}${r.gap ? `<p>Gap to fill: ${esc(r.gap)}</p>` : ""}</div>` : ""}
      <label class="block mt-3"><span class="block text-xs font-medium text-slate-600 mb-1">Instructions for the script (optional)</span>
        <textarea data-vd-instr="${p.id}" rows="3" class="w-full text-sm rounded-lg border-slate-300 focus:border-violet-500 focus:ring-violet-500" placeholder="e.g. open with a bank queue analogy, keep it near 70 s, show the code for the loop">${esc(p.instructions || "")}</textarea></label>
      <p class="text-xs text-slate-500 mt-1">The script is written in the Looks ticked in the Factory chat below.</p>
      <div class="flex flex-wrap gap-2 mt-3">
        ${button("primary", "edit_note", busy ? "Writing…" : p.episode ? "Write the script again" : "Write the script", `data-vd-script="${p.id}" ${busy || p.state === "making" ? "disabled" : ""}`)}
      </div>
      ${busy ? `<p class="mt-2 text-sm text-slate-600">${icon("progress_activity", "text-sm animate-spin align-middle")} The Script Writer is writing it. A few minutes.</p>` : ""}
    </div>`;
}

function vdDetail(p) {
  const ep = p.episode;
  if (!ep) return `<div class="px-5 pb-5 grid grid-cols-1 lg:grid-cols-2 gap-5 bg-slate-50/50">${vdPlanCard(p)}</div>`;
  const editing = VD_EDIT.has(ep.slug), n = ep.lines.length - (ep.outro ? 1 : 0);
  const v = ep.voice || {}, rep = ep.report;
  const [vs, vw] = VD_VOICE[v.state] || VD_VOICE.none;
  const lines = ep.lines.map((t, i) => {
    const outro = ep.outro && i === n;
    return `<li class="flex gap-3"><span class="w-6 text-right text-xs text-slate-400 pt-1">${i + 1}</span>${editing && !outro
      ? `<textarea data-vd-line="${i}" rows="2" class="flex-1 text-sm rounded-lg border-slate-300 focus:border-violet-500 focus:ring-violet-500">${esc(t)}</textarea>`
      : `<p class="flex-1 text-sm ${outro ? "text-slate-500 italic" : "text-slate-800"}">${esc(t)}${outro ? " (outro, the same in every video)" : ""}</p>`}</li>`;
  }).join("");
  const scriptOk = ep.script === "approved", ready = scriptOk && v.state === "approved";
  const making = p.state === "making" || (vdBusy(ep.job) && ep.job.what === "video");
  const upOff = !VD.whisper || v.state === "processing" ? "opacity-50 pointer-events-none" : "";
  const listen = (k, label) => ep.audio?.[k] ? `<div class="flex items-center gap-2"><span class="text-xs text-slate-500 w-40">${label}</span><audio controls preload="none" class="h-8" src="/voice-desk/${ep.audio[k]}"></audio></div>` : "";
  const makeAttr = p.other ? `data-vd-make-ep="${ep.slug}"` : `data-vd-make="${p.id}"`;
  return `
  <div class="px-5 pb-5 grid grid-cols-1 lg:grid-cols-2 gap-5 bg-slate-50/50">
    ${p.other ? "" : vdPlanCard(p)}
    <div class="rounded-lg border border-slate-200 bg-white p-4 ${p.other ? "lg:col-span-2" : ""}">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-slate-900 flex items-center gap-2">${icon("description", "text-slate-500")} 1. Script ${chip(scriptOk ? "approved" : "awaiting_approval", scriptOk ? "Approved" : "Draft", "sm")}</h3>
        <span class="text-[11px] text-slate-500">${ep.words} words${ep.style ? ` · ${esc(ep.style)}` : ""}</span>
      </div>
      <p class="text-xs text-slate-500 mb-2">Read it aloud in one take, line by line. Retakes are fine: say the line again and the last take is kept.</p>
      <ol data-vd-scroll="${esc(ep.slug)}" class="space-y-2 max-h-80 overflow-y-auto pr-1">${lines}</ol>
      ${!editing && ep.hook_options?.length > 1 ? `<div class="mt-3 rounded-lg bg-violet-50/60 border border-violet-100 p-3">
        <p class="text-xs font-semibold text-violet-800 mb-1">${tip("Catch lines", "The opening line decides if a viewer keeps watching. The Script Writer wrote these options; the first line of the script is the one it picked.")}</p>
        <ul class="space-y-1">${ep.hook_options.map((h, k) => { const cls = h === ep.lines[0] ? "text-slate-900 font-medium" : "text-slate-700"; return `<li class="flex items-start gap-2 text-sm ${cls}">
          <span class="flex-1">${esc(h)}</span>${h === ep.lines[0] ? chip("approved", "In use", "sm") : button("secondary", "swap_horiz", "Use this", `data-vd-hook="${ep.slug}" data-k="${k}"`)}</li>`; }).join("")}</ul>
      </div>` : ""}
      <div class="flex flex-wrap gap-2 mt-3">
        ${editing ? button("primary", "save", "Save lines", `data-vd-save="${ep.slug}"`) + button("secondary", "close", "Cancel", `data-vd-cancel="${ep.slug}"`)
          : button("secondary", "edit", "Edit lines", `data-vd-edit="${ep.slug}"`)
            + (scriptOk ? button("secondary", "undo", "Take approval back", `data-vd-unapprove="${ep.slug}"`) : button("approve", "check", "Approve script", `data-vd-approve="${ep.slug}"`))}
      </div>
    </div>
    <div class="rounded-lg border border-slate-200 bg-white p-4 lg:col-span-2">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-slate-900 flex items-center gap-2">${icon("mic", "text-slate-500")} 2. Voice ${chip(vs, vw, "sm")}</h3>
        ${v.state === "approved" ? `<span class="text-[11px] text-slate-500">${esc(VD_MODE[v.mode] || v.mode)}</span>` : ""}
      </div>
      ${v.state === "failed" || ep.job?.error ? `<p class="text-sm text-rose-700 mb-2">${esc(v.error || ep.job.error)}</p>` : ""}
      ${v.state === "processing" ? `<p class="text-sm text-slate-600 mb-2">${icon("progress_activity", "text-sm animate-spin align-middle")} Finding your words, cleaning the take and matching it to dip_puck. Under a minute.</p>` : ""}
      ${rep && v.mode === "own" && v.state !== "processing" ? `
        <div class="text-xs text-slate-600 space-y-1 mb-3">
          <p>${rep.kept_lines} of ${rep.lines} lines found · ${rep.seconds} s · ${rep.huge_gaps_shortened} long gap(s) shortened</p>
          ${rep.removed?.length ? `<p>Cut (not in the script, or an earlier take): <span class="text-slate-500">${rep.removed.slice(0, 8).map(x => `“${esc(x.slice(0, 60))}”`).join(", ")}${rep.removed.length > 8 ? " …" : ""}</span></p>` : ""}
          ${rep.missing?.length ? `<p class="text-amber-800">Not found in the recording (dip_puck reads these): ${rep.missing.map(m => `line ${m.line}`).join(", ")}</p>` : ""}
          ${ep.outro && !rep.outro_recorded ? `<p class="text-slate-500">The outro was not recorded: dip_puck reads it.</p>` : ""}
        </div>
        <div class="space-y-1 mb-3">${listen("converted", "Matched to dip_puck")}${listen("cleaned", "Cleaned, your own voice")}</div>` : ""}
      <div class="flex flex-wrap items-center gap-2">
        <label class="${BTN.secondary} cursor-pointer ${upOff}">${icon("upload")}<span>${v.mode === "own" && v.state !== "none" ? "Upload again" : "Upload your recording"}</span>
          <input type="file" accept="audio/*,video/*,.wav,.mp3,.m4a,.aac,.ogg,.opus,.webm,.flac,.mp4,.mov,.caf,.aiff" class="hidden" data-vd-upload="${ep.slug}"></label>
        ${v.state === "ready" && v.mode === "own" ? button("approve", "check", "Approve my voice", `data-vd-voice="own" data-slug="${ep.slug}"`) : ""}
        ${v.state === "approved" ? button("secondary", "undo", "Change voice", `data-vd-reopen="${ep.slug}"`) : ""}
        ${v.state !== "approved" ? `<span class="text-xs text-slate-500 ml-2">or skip your voice:</span>`
          + button("secondary", "smart_toy", "Use dip_puck", `data-vd-voice="dip_puck" data-slug="${ep.slug}"`)
          + button("secondary", "smart_toy", "Use am_puck", `data-vd-voice="am_puck" data-slug="${ep.slug}"`) : ""}
      </div>
    </div>
    <div class="lg:col-span-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <p class="text-sm text-slate-700">${icon("movie", "text-slate-500 align-middle")} ${making ? "Making the video now. It appears in the Queue when it is done."
        : ready ? `Script and voice approved. It is made in the style its script was written in${ep.style ? ` (${esc(ep.style)})` : ""}.` : "Approve the script and the voice, then make the video."}</p>
      ${button("primary", "play_arrow", making ? "Making…" : "Make the video", `${makeAttr} ${ready && !making ? "" : "disabled"}`)}
    </div>
  </div>`;
}

function vdWire(root) {
  const go = async (fn, ok) => { try { await fn(); if (ok) toast(ok); } catch (e) { toast(e.message, true); } await vdLoad(true); };
  const val = id => root.querySelector(id)?.value || "";
  root.querySelector("#vd-plan")?.addEventListener("click", () => {
    const topic = val("#vd-topic").trim();
    if (!topic) return toast("Type a topic first", true);
    const body = { topic, hint: val("#vd-hint"), count: +val("#vd-count"), format: val("#vd-format") };
    root.querySelector("#vd-topic").value = "";
    root.querySelector("#vd-topic").blur();
    go(() => post("/api/factory-plans/plan", body), "Researching the topic on YouTube and writing the plans.");
  });
  root.querySelector("#vd-topic")?.addEventListener("keydown", e => { if (e.key === "Enter") root.querySelector("#vd-plan")?.click(); });
  root.querySelectorAll("[data-vd-toggle]").forEach(el => el.addEventListener("click", e => {
    if (e.target.closest("button,label,input,textarea,audio,select")) return;
    const k = el.dataset.vdToggle; VD_OPEN.has(k) ? VD_OPEN.delete(k) : VD_OPEN.add(k); vdDraw();
  }));
  root.querySelectorAll("[data-vd-script]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.vdScript, instr = root.querySelector(`[data-vd-instr="${id}"]`)?.value || "";
    go(() => post("/api/factory-plans/script", { id, instructions: instr }), "Writing the script. It appears here when it is written.");
  }));
  root.querySelectorAll("[data-vd-remove],[data-vd-remove-ep]").forEach(b => b.addEventListener("click", () => {
    if (b.dataset.armed !== "1") {   // no browser dialogs: a second click confirms
      b.dataset.armed = "1"; b.querySelector("span:last-child").textContent = "Click again to delete";
      setTimeout(() => { if (b.isConnected) { b.dataset.armed = ""; b.querySelector("span:last-child").textContent = "Delete"; } }, 4000);
      return;
    }
    const ep = b.dataset.vdRemoveEp;
    VD_OPEN.delete(ep || b.dataset.vdRemove);
    go(() => ep ? post("/api/voice-desk/delete", { slug: ep }) : post("/api/factory-plans/remove", { id: b.dataset.vdRemove }), ep ? "Script deleted." : "Plan deleted.");
  }));
  root.querySelectorAll("[data-vd-hook]").forEach(b => b.addEventListener("click", () => {
    const all = [...(VD.plans || []), ...(VD.others || []).map(e => ({ episode: e }))];
    const ep = all.map(p => p.episode).find(e => e && e.slug === b.dataset.vdHook); if (!ep) return;
    const n = ep.lines.length - (ep.outro ? 1 : 0), lines = ep.lines.slice(0, n); lines[0] = ep.hook_options[+b.dataset.k];
    go(() => post("/api/voice-desk/lines", { slug: ep.slug, lines }), "Catch line changed. Approve the script again when it reads right.");
  }));
    root.querySelectorAll("[data-vd-edit]").forEach(b => b.addEventListener("click", () => { VD_EDIT.add(b.dataset.vdEdit); vdDraw(); }));
  root.querySelectorAll("[data-vd-cancel]").forEach(b => b.addEventListener("click", () => { VD_EDIT.delete(b.dataset.vdCancel); vdDraw(); }));
  root.querySelectorAll("[data-vd-save]").forEach(b => b.addEventListener("click", () => {
    const slug = b.dataset.vdSave, lines = [...b.closest(".rounded-lg").querySelectorAll("[data-vd-line]")].map(t => t.value);
    VD_EDIT.delete(slug);
    go(() => post("/api/voice-desk/lines", { slug, lines }), "Lines saved. Approve the script when it reads right.");
  }));
  root.querySelectorAll("[data-vd-approve]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/approve-script", { slug: b.dataset.vdApprove }), "Script approved.")));
  root.querySelectorAll("[data-vd-unapprove]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/approve-script", { slug: b.dataset.vdUnapprove, approved: false }))));
  root.querySelectorAll("[data-vd-voice]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/voice", { slug: b.dataset.slug, mode: b.dataset.vdVoice }), `Voice approved: ${VD_MODE[b.dataset.vdVoice]}.`)));
  root.querySelectorAll("[data-vd-reopen]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/reopen", { slug: b.dataset.vdReopen }))));
  root.querySelectorAll("[data-vd-make]").forEach(b => b.addEventListener("click", () => go(() => post("/api/factory-plans/make", { id: b.dataset.vdMake }), "Making the video. It appears in the Queue when it is done.")));
  root.querySelectorAll("[data-vd-make-ep]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/make", { slug: b.dataset.vdMakeEp }), "Making the video.")));
  root.querySelectorAll("[data-vd-upload]").forEach(inp => inp.addEventListener("change", async () => {
    const f = inp.files?.[0]; if (!f) return;
    toast(`Uploading ${f.name} …`);
    await go(async () => {
      const res = await fetch(`/api/voice-desk/upload?slug=${encodeURIComponent(inp.dataset.vdUpload)}&name=${encodeURIComponent(f.name)}`,
        { method: "POST", headers: { "X-Postcrew": "1", "Content-Type": "application/octet-stream" }, body: f });
      const r = await res.json().catch(() => ({})); if (!res.ok) throw new Error(r.error || "upload failed");
    }, "Uploaded. Processing your voice: listen to it here when it is ready.");
  }));
}
