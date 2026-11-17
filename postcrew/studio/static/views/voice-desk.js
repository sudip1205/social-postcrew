// Factory > Voice: the next days' scripts, your voice for each, and your two approvals before a video is made (owner, 2026-11-16).
// Backend: postcrew/voice_desk.py (/api/voice-desk/*). Built from the Factory page's own components (ui.js: chip, button, icon, tip).
let VD = null, vdTimer = null, VD_OPEN = new Set(), VD_EDIT = new Set();

const VD_VOICE = {
  none: ["pending", "No voice yet"], processing: ["running", "Processing your voice"], ready: ["awaiting_approval", "Voice ready: listen and approve"],
  approved: ["approved", "Voice approved"], failed: ["failed", "Voice failed"],
};
const VD_MODE = { own: "Your voice (matched to dip_puck)", dip_puck: "dip_puck (AI voice)", am_puck: "am_puck (Kokoro AI voice)" };

async function vdOpen() {
  clearInterval(vdTimer);
  await vdLoad();
  vdTimer = setInterval(() => { if (!document.getElementById("vd-root")) return clearInterval(vdTimer); vdLoad(); }, 5000);
}

async function vdLoad() {
  try { VD = await api("/api/voice-desk"); vdDraw(); } catch (e) { const r = document.getElementById("vd-root"); if (r) r.innerHTML = `<p class="p-5 text-sm text-rose-700">${esc(e.message)}</p>`; }
}

function vdEpisodeState(ep) {
  if (!ep) return ["pending", "No script yet"];
  if (ep.run?.state === "making" || ep.job?.what === "video" && !ep.job.done) return ["running", "Making the video"];
  if (ep.script !== "approved") return ["awaiting_approval", "Approve the script"];
  if (ep.voice?.state !== "approved") return ["awaiting_approval", "Add your voice"];
  return ["approved", "Ready to make"];
}

function vdDraw() {
  const root = document.getElementById("vd-root");
  if (!root || !VD) return;
  if (document.activeElement && root.contains(document.activeElement) && document.activeElement.tagName === "TEXTAREA") return;   // do not redraw over your typing
  const w = VD.writer || {};
  const missing = VD.days.filter(r => !r.episode && !r.made).length;
  root.innerHTML = `
    <div class="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-slate-200">
      <div class="flex items-center gap-3">
        <span class="w-9 h-9 rounded-lg bg-violet-50 text-violet-600 grid place-items-center">${icon("record_voice_over")}</span>
        <div>
          <h2 class="font-headline font-bold text-slate-900">Voice</h2>
          <p class="text-xs text-slate-500">The next ${VD.days_ahead} days' scripts. Record each one, upload it, and approve the ${tip("script", "The narration the video is built around. Edit any line before you approve it.")} and the ${tip("voice", "Your recording, cleaned (retakes and long gaps removed, your sentence pauses and pronunciation kept) and matched to dip_puck with Seed-VC. Or skip it and let dip_puck or am_puck read the script.")}: only then is the video made.</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        ${w.busy ? chip("running", `Writing the script for ${w.day}`) : ""}
        ${button("primary", "edit_note", missing ? `Write the next scripts (${missing})` : "All scripts written", `id="vd-ahead" ${w.busy || !missing ? "disabled" : ""}`)}
      </div>
    </div>
    ${w.error ? `<p class="px-5 py-2 text-sm text-rose-700 bg-rose-50 border-b border-rose-200">${icon("error", "text-sm align-middle")} ${esc(w.error)}</p>` : ""}
    ${!VD.whisper ? `<p class="px-5 py-2 text-sm text-amber-800 bg-amber-50 border-b border-amber-200">faster-whisper is not installed on this computer, so recordings cannot be processed here (pip install faster-whisper).</p>` : ""}
    ${!VD.converter ? `<p class="px-5 py-2 text-sm text-amber-800 bg-amber-50 border-b border-amber-200">Seed-VC is not found (~/voicelab/seed-vc): your recording cannot be matched to dip_puck on this computer. Skipping to dip_puck or am_puck still works.</p>` : ""}
    <div class="divide-y divide-slate-100">${VD.days.map(vdRow).join("") || `<p class="p-5 text-sm text-slate-500">Nothing is scheduled for YouTube in the next ${VD.days_ahead} days.</p>`}</div>
    ${VD.chat?.length ? `<p class="px-5 pt-4 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">From the Factory chat</p>
      <div class="divide-y divide-slate-100 border-t border-slate-100">${VD.chat.map(ep => vdRow({ day: "", weekday: "Chat", label: "Factory chat", episode: ep, made: false })).join("")}</div>` : ""}`;
  vdWire(root);
}

function vdRow(r) {
  const ep = r.episode, [st, word] = r.made ? [r.post_status || "queued", "Video made"] : vdEpisodeState(ep);
  const open = ep && VD_OPEN.has(ep.slug);
  const head = `
    <div class="flex flex-wrap items-center gap-3 px-5 py-3 ${ep ? "cursor-pointer hover:bg-slate-50" : ""}" ${ep ? `data-vd-toggle="${ep.slug}"` : ""}>
      <div class="w-40 shrink-0"><p class="text-sm font-semibold text-slate-900">${esc(r.weekday.slice(0, 3))} ${esc((r.day || "").slice(5))}</p><p class="text-[11px] text-slate-500 truncate" title="${esc(r.label)}">${esc(r.label)}</p></div>
      <div class="flex-1 min-w-[12rem]">
        <p class="text-sm text-slate-900 font-medium">${esc(ep?.title || r.planned || "Topic picked when the script is written")}</p>
        ${ep ? `<p class="text-xs text-slate-500">${ep.words} words · ${ep.lines.length} lines · ${esc(ep.style || "look")}${ep.voice?.mode && ep.voice.state === "approved" ? ` · ${esc(VD_MODE[ep.voice.mode])}` : ""}</p>` : ""}
      </div>
      ${chip(st, word, "sm")}
      ${!ep && !r.made ? button("secondary", "edit_note", "Write script", `data-vd-write="${r.day}" ${VD.writer?.busy ? "disabled" : ""}`) : ""}
      ${ep ? icon(open ? "expand_less" : "expand_more", "text-slate-400") : ""}
    </div>`;
  return head + (open ? vdDetail(r, ep) : "");
}

function vdDetail(r, ep) {
  const editing = VD_EDIT.has(ep.slug), n = ep.lines.length - (ep.outro ? 1 : 0);
  const v = ep.voice || {}, rep = ep.report, job = ep.job;
  const [vs, vw] = VD_VOICE[v.state] || VD_VOICE.none;
  const lines = ep.lines.map((t, i) => {
    const outro = ep.outro && i === n;
    return `<li class="flex gap-3"><span class="w-6 text-right text-xs text-slate-400 pt-1">${i + 1}</span>${editing && !outro
      ? `<textarea data-vd-line="${i}" rows="2" class="flex-1 text-sm rounded-lg border-slate-300 focus:border-violet-500 focus:ring-violet-500">${esc(t)}</textarea>`
      : `<p class="flex-1 text-sm ${outro ? "text-slate-500 italic" : "text-slate-800"}">${esc(t)}${outro ? " (outro, the same in every video)" : ""}</p>`}</li>`;
  }).join("");
  const scriptOk = ep.script === "approved";
  const upOff = !VD.whisper || v.state === "processing" ? "opacity-50 pointer-events-none" : "";
  const listen = (k, label) => ep.audio?.[k] ? `<div class="flex items-center gap-2"><span class="text-xs text-slate-500 w-40">${label}</span><audio controls preload="none" class="h-8" src="/voice-desk/${ep.audio[k]}"></audio></div>` : "";
  return `
  <div class="px-5 pb-5 grid grid-cols-1 lg:grid-cols-2 gap-5 bg-slate-50/50">
    <div class="rounded-lg border border-slate-200 bg-white p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-slate-900 flex items-center gap-2">${icon("description", "text-slate-500")} 1. Script ${chip(scriptOk ? "approved" : "awaiting_approval", scriptOk ? "Approved" : "Draft", "sm")}</h3>
        <span class="text-[11px] text-slate-500">${esc(ep.slug)}</span>
      </div>
      <p class="text-xs text-slate-500 mb-2">Read it aloud in one take, line by line. Retakes are fine: say the line again and the last take is kept.</p>
      <ol class="space-y-2 max-h-80 overflow-y-auto pr-1">${lines}</ol>
      ${!editing && r.day ? `<input data-vd-notes type="text" placeholder="Notes for Write again (optional): what to change" class="mt-3 w-full text-sm rounded-lg border-slate-300 focus:border-violet-500 focus:ring-violet-500">` : ""}
      <div class="flex flex-wrap gap-2 mt-3">
        ${editing ? button("primary", "save", "Save lines", `data-vd-save="${ep.slug}"`) + button("secondary", "close", "Cancel", `data-vd-cancel="${ep.slug}"`)
          : button("secondary", "edit", "Edit lines", `data-vd-edit="${ep.slug}"`)}
        ${!editing ? (scriptOk ? button("secondary", "undo", "Take approval back", `data-vd-unapprove="${ep.slug}"`) : button("approve", "check", "Approve script", `data-vd-approve="${ep.slug}"`)) : ""}
        ${!editing && r.day ? button("secondary", "refresh", "Write again", `data-vd-rewrite="${r.day}" ${VD.writer?.busy ? "disabled" : ""}`) : ""}
      </div>
    </div>
    <div class="rounded-lg border border-slate-200 bg-white p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-slate-900 flex items-center gap-2">${icon("mic", "text-slate-500")} 2. Voice ${chip(vs, vw, "sm")}</h3>
        ${v.state === "approved" ? `<span class="text-[11px] text-slate-500">${esc(VD_MODE[v.mode] || v.mode)}</span>` : ""}
      </div>
      ${v.state === "failed" || job?.error ? `<p class="text-sm text-rose-700 mb-2">${esc(v.error || job.error)}</p>` : ""}
      ${v.state === "processing" ? `<p class="text-sm text-slate-600 mb-2">${icon("progress_activity", "text-sm animate-spin align-middle")} Finding your words, cleaning the take and matching it to dip_puck. A few minutes.</p>` : ""}
      ${rep && v.mode === "own" && v.state !== "processing" ? `
        <div class="text-xs text-slate-600 space-y-1 mb-3">
          <p>${rep.kept_lines} of ${rep.lines} lines found · ${rep.seconds} s · ${rep.huge_gaps_shortened} long gaps shortened</p>
          ${rep.removed?.length ? `<p>Cut (not in the script, or an earlier take): <span class="text-slate-500">${rep.removed.slice(0, 8).map(x => `"${esc(x.slice(0, 60))}"`).join(", ")}${rep.removed.length > 8 ? " …" : ""}</span></p>` : ""}
          ${rep.missing?.length ? `<p class="text-amber-800">Not found in the recording (dip_puck reads these): ${rep.missing.map(m => `line ${m.line}`).join(", ")}</p>` : ""}
          ${ep.outro && !rep.outro_recorded ? `<p class="text-slate-500">The outro was not recorded: dip_puck reads it.</p>` : ""}
        </div>
        <div class="space-y-1 mb-3">${listen("converted", "Matched to dip_puck")}${listen("cleaned", "Cleaned, your own voice")}</div>` : ""}
      <div class="flex flex-wrap gap-2">
        <label class="${BTN.secondary} cursor-pointer ${upOff}">${icon("upload")}<span>${v.mode === "own" && v.state !== "none" ? "Upload again" : "Upload your recording"}</span>
          <input type="file" accept="audio/*,video/*,.wav,.mp3,.m4a,.aac,.ogg,.opus,.webm,.flac,.mp4,.mov,.caf,.aiff" class="hidden" data-vd-upload="${ep.slug}"></label>
        ${v.state === "ready" && v.mode === "own" ? button("approve", "check", "Approve my voice", `data-vd-voice="own" data-slug="${ep.slug}"`) : ""}
        ${v.state === "approved" ? button("secondary", "undo", "Change voice", `data-vd-reopen="${ep.slug}"`) : ""}
      </div>
      ${v.state !== "approved" ? `
      <div class="mt-3 pt-3 border-t border-slate-100">
        <p class="text-xs text-slate-500 mb-2">No time to record? Skip your voice for this video:</p>
        <div class="flex flex-wrap gap-2">
          ${button("secondary", "smart_toy", "Use dip_puck", `data-vd-voice="dip_puck" data-slug="${ep.slug}"`)}
          ${button("secondary", "smart_toy", "Use am_puck", `data-vd-voice="am_puck" data-slug="${ep.slug}"`)}
        </div>
      </div>` : ""}
    </div>
    <div class="lg:col-span-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <p class="text-sm text-slate-700">${icon("movie", "text-slate-500 align-middle")} ${scriptOk && v.state === "approved"
        ? (ep.run?.state === "making" || (job?.what === "video" && !job.done) ? "Making the video now. It appears in the Queue when it is done."
          : r.day && ep.run?.state !== "waiting" ? `Both approved. The video is made on its scheduled run for ${esc(r.day)}, or now.` : "Both approved: make the video.")
        : "The video is made once the script and the voice are both approved."}</p>
      ${button("primary", "play_arrow", "Make the video now", `data-vd-make="${ep.slug}" ${scriptOk && v.state === "approved" && !(job?.what === "video" && !job.done) ? "" : "disabled"}`)}
    </div>
  </div>`;
}

function vdWire(root) {
  const go = async (fn, ok) => { try { await fn(); if (ok) toast(ok); } catch (e) { toast(e.message, true); } await vdLoad(); };
  root.querySelector("#vd-ahead")?.addEventListener("click", () => go(() => post("/api/voice-desk/write-ahead"), "Writing the next scripts. Each one appears here when it is written."));
  root.querySelectorAll("[data-vd-toggle]").forEach(el => el.addEventListener("click", e => {
    if (e.target.closest("button,label,input,textarea,audio")) return;
    const s = el.dataset.vdToggle; VD_OPEN.has(s) ? VD_OPEN.delete(s) : VD_OPEN.add(s); vdDraw();
  }));
  root.querySelectorAll("[data-vd-write]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/write", { day: b.dataset.vdWrite }), "Writing the script. It appears here when it is written.")));
  root.querySelectorAll("[data-vd-rewrite]").forEach(b => b.addEventListener("click", () => {
    const box = b.closest(".grid")?.querySelector("[data-vd-notes]");
    go(() => post("/api/voice-desk/write", { day: b.dataset.vdRewrite, notes: box?.value ? [box.value] : [] }), "Writing it again. Your approval and voice for the old script are cleared.");
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
  root.querySelectorAll("[data-vd-make]").forEach(b => b.addEventListener("click", () => go(() => post("/api/voice-desk/make", { slug: b.dataset.vdMake }), "Making the video. It appears in the Queue when it is done.")));
  root.querySelectorAll("[data-vd-upload]").forEach(inp => inp.addEventListener("change", async () => {
    const f = inp.files?.[0]; if (!f) return;
    const slug = inp.dataset.vdUpload;
    toast(`Uploading ${f.name} …`);
    await go(async () => {
      const res = await fetch(`/api/voice-desk/upload?slug=${encodeURIComponent(slug)}&name=${encodeURIComponent(f.name)}`,
        { method: "POST", headers: { "X-Postcrew": "1", "Content-Type": "application/octet-stream" }, body: f });
      const r = await res.json().catch(() => ({})); if (!res.ok) throw new Error(r.error || "upload failed");
    }, "Uploaded. Processing your voice: listen to it here when it is ready.");
  }));
}
