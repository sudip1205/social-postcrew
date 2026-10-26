/* Upload dialog: copied from design/stitch/upload-your-own-youtube.html. Manages the files the user supplies for one video
   (GET/POST /api/assets/youtube/<date>); the next crew run for that date uses them. */
"use strict";

const UP_ZONES = {
  script: { tint: "bg-orange-100 text-orange-600", ic: "edit_note", title: "Custom Script (.txt, .md)", sub: "Structured text parsed into scenes", hint: "Drop your script here or click to choose", accept: ".txt,.md", limit: "200 KB" },
  voice: { tint: "bg-violet-100 text-violet-600", ic: "mic", title: "Voiceover Audio (.mp3, .wav, .m4a)", sub: "Your own voice track, used instead of the AI voice", hint: "Drop your voiceover here or click to choose", accept: ".mp3,.wav,.m4a", limit: "100 MB" },
  video: { tint: "bg-sky-100 text-sky-600", ic: "videocam", title: "Finished Video / B-Roll (.mp4, .mov)", sub: "Spec validation and aspect conformance", hint: "Drop your video here or click to choose", accept: ".mp4,.mov", limit: "1 GB" },
};
const upSecs = s => { s = Math.round(+s || 0); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const upSize = b => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((b || 0) / 1024))} KB`;

function openUploadForDate(date, kind) {
  return openUploadDialog({ platform: "youtube", date, topic: "" }, kind);
}

function openUploadDialog(post, focus) {
  const date = post?.date || String(post?.id || "").slice(0, 10), platform = post?.platform || "youtube";
  const base = `/api/assets/${encodeURIComponent(platform)}/${encodeURIComponent(date)}`;
  let assets = {}; const busy = {};

  const checkRow = c => `<div class="p-2 rounded-lg ${c.ok ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"} flex items-center gap-2">
    ${icon(c.ok ? "check_circle" : "cancel", `text-[18px] ${c.ok ? "text-emerald-600" : "text-rose-600"}`)}<span class="font-medium">${esc(c.label)}</span>${c.detail ? `<span class="ml-auto font-mono text-[11px]">${esc(c.detail)}</span>` : ""}</div>`;

  const detail = (key, a) => {
    const checks = (a.checks || []).length ? `<div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">${a.checks.map(checkRow).join("")}</div>` : "";
    if (key === "script") return `<div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">${(a.scenes || []).map((s, i) => `<div class="p-3 rounded-xl bg-slate-50 flex flex-col gap-1.5">
      <div class="flex justify-between text-xs font-semibold text-slate-800"><span>Scene ${i + 1}</span><span class="font-mono text-[11px] text-slate-400">${upSecs(s.seconds)}s</span></div>
      <p class="text-xs italic text-slate-600 line-clamp-3">&ldquo;${esc(s.narration)}&rdquo;</p>
      <span class="text-[11px] text-slate-500">${String(s.narration || "").trim().split(/\s+/).filter(Boolean).length} words</span></div>`).join("")}</div>${checks}`;
    if (key === "voice") return `<div class="flex items-center gap-3"><span class="font-mono text-sm font-bold text-slate-900">${upSecs(a.seconds)}</span>
      ${a.url ? `<audio controls preload="none" class="h-8 flex-1" src="${esc(a.url)}"></audio>` : ""}</div>${checks}`;
    return `<div class="flex gap-4 items-start">${a.thumbnail ? `<img class="w-24 rounded-lg border border-slate-200 object-cover" src="${esc(a.thumbnail)}" alt="Video thumbnail">` : ""}
      <div class="flex-1 flex flex-col gap-2"><span class="text-[11px] font-bold uppercase tracking-wider text-slate-500">Specification compliance audit</span>
      <span class="font-mono text-[11px] text-slate-500">${a.width && a.height ? `${a.width}x${a.height} · ` : ""}${upSecs(a.seconds)}</span>${checks}</div></div>`;
  };
  const badge = (key, a) => {
    const checks = a?.checks || [], bad = checks.filter(c => !c.ok).length;
    if (!a) return `<div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-200/70 text-slate-700 font-label text-xs font-medium">${icon("verified", "text-[16px] text-slate-500")}<span>No file yet</span></div>`;
    const text = key === "script" ? `${a.words || 0} words · ${upSecs(a.seconds)} estimated` : key === "voice" ? `${upSecs(a.seconds)} long` : bad ? `${bad} check(s) failed` : `${checks.length} verification tests passed`;
    return bad ? `<div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-50 text-rose-700 font-label text-xs font-medium">${icon("cancel", "text-[16px] text-rose-600")}<span>${esc(text)}</span></div>`
      : `<div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 font-label text-xs font-medium">${icon("check_circle", "text-[16px] text-emerald-600")}<span>${esc(text)}</span></div>`;
  };
  const zone = key => {
    const z = UP_ZONES[key], a = assets[key];
    const drop = `<button class="w-full flex flex-col items-center gap-1 py-5 rounded-lg border border-dashed border-slate-300 text-slate-500 hover:border-violet-400 hover:text-violet-600 hover:bg-violet-50/40 transition-colors" type="button" data-pick="${key}">
      ${icon(busy[key] ? "progress_activity" : "file_upload", `text-[24px]${busy[key] ? " animate-spin" : ""}`)}<span class="text-xs font-medium">${busy[key] ? "Uploading and checking…" : z.hint}</span><span class="text-[11px] text-slate-400">Up to ${z.limit}</span></button>`;
    const filled = a ? `<div class="flex items-center justify-between gap-2 text-xs"><span class="flex items-center gap-1.5 text-slate-700 min-w-0">${icon("description", "text-[16px] text-slate-400")}<span class="font-medium truncate">${esc(a.name)}</span><span class="text-slate-400">(${upSize(a.bytes)})</span></span>
      <span class="flex items-center gap-3 shrink-0"><button class="text-violet-600 font-medium inline-flex items-center gap-1 hover:underline disabled:opacity-50" type="button" data-pick="${key}" ${busy[key] ? "disabled" : ""}>${icon(busy[key] ? "progress_activity" : "sync", `text-[14px]${busy[key] ? " animate-spin" : ""}`)}<span>${busy[key] ? "Uploading…" : "Replace file"}</span></button>
      <button class="text-rose-600 font-medium inline-flex items-center gap-1 hover:underline" type="button" data-remove="${key}">${icon("delete", "text-[14px]")}<span>Remove</span></button></span></div>${detail(key, a)}` : drop;
    return `<div class="bg-slate-50/80 rounded-xl p-4 sm:p-5 flex flex-col gap-3.5 hover:bg-slate-50 transition-colors" data-zone="${key}">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2.5"><div class="w-8 h-8 rounded-lg ${z.tint} flex items-center justify-center">${icon(z.ic, "text-[20px]")}</div>
          <div><h3 class="font-headline font-semibold text-sm sm:text-base text-slate-900 flex items-center gap-1.5">${z.title}</h3><span class="font-body text-xs text-slate-500">${z.sub}</span></div></div>${badge(key, a)}</div>
      <div class="bg-white rounded-lg p-3.5 shadow-sm flex flex-col gap-2.5" data-drop="${key}">${filled}</div>
      <input type="file" class="hidden" accept="${z.accept}" data-file="${key}"></div>`;
  };

  const dlg = document.createElement("div");
  dlg.className = "fixed inset-0 z-50 flex items-start justify-center pt-2 sm:pt-4 pb-12 px-3 sm:px-4 bg-slate-900/40 backdrop-blur-md transition-all overflow-y-auto";
  dlg.id = "uploadModal";
  const fmt = post?.youtube?.format === "long" ? "YouTube Video" : "YouTube Short";
  dlg.innerHTML = `<div class="w-full max-w-4xl bg-white rounded-xl shadow-2xl flex flex-col overflow-hidden">
    <div class="px-6 sm:px-8 pt-6 pb-5 bg-gradient-to-b from-slate-50/70 to-white flex flex-col gap-3">
      <div class="flex items-center justify-between">
        <div class="inline-flex items-center gap-2 px-2.5 py-1 bg-rose-50 text-rose-600 rounded-lg"><span class="w-2 h-2 rounded-full bg-rose-600 animate-pulse"></span>${icon("smart_display", "text-[18px]")}<span class="font-label font-bold text-xs tracking-wide">${fmt} · ${esc(date)}${post?.topic ? " · " + esc(post.topic) : ""}</span></div>
        <button aria-label="Close dialog" class="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors active:scale-95" type="button" data-close>${icon("close", "text-[22px]")}</button></div>
      <div class="flex flex-col gap-1">
        <h2 class="font-headline font-bold text-2xl sm:text-[26px] text-slate-900 tracking-tight flex items-center gap-2.5">${icon("drive_folder_upload", "text-slate-700 text-2xl")}Use your own content for this video</h2>
        <p class="font-body text-slate-500 text-sm leading-relaxed max-w-2xl">Override automated generation by bringing your custom script, voiceover, or edited video clip. The crew will seamlessly stitch remaining components and harmonize metadata.</p></div></div>
    <div id="up-zones" class="px-6 sm:px-8 py-5 flex flex-col gap-5 overflow-y-auto max-h-[calc(85vh-180px)] custom-scrollbar"></div>
    <div class="px-6 sm:px-8 py-4 bg-slate-50 flex flex-col gap-3">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div class="flex items-start sm:items-center gap-2.5">
          <div class="w-6 h-6 rounded-full bg-gradient-to-tr from-indigo-600 to-violet-500 text-white flex items-center justify-center text-[11px] font-bold shrink-0 mt-0.5 sm:mt-0">QE</div>
          <div class="text-xs text-slate-600 leading-normal"><span>The crew will still check your script with </span>${tip("Quinn the Editor", "Reviews tone consistency, script pacing, policy compliance, and channel guidelines before rendering.")}<span> before final YouTube render.</span></div></div>
        <label class="inline-flex items-center gap-2.5 cursor-not-allowed shrink-0 select-none opacity-60" title="Coming soon">
          <div class="relative inline-flex items-center"><input class="sr-only peer" id="skipEditorToggle" type="checkbox" disabled/>
            <div class="w-9 h-5 bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-orange-600"></div></div>
          <div class="flex flex-col"><span class="text-xs font-semibold text-slate-800 font-label">Skip the Editor for this video</span><span class="text-[10px] text-slate-400">Disables tone, pacing, and policy guardrails</span></div></label></div>
      <div class="flex items-center gap-2 text-xs text-slate-500 bg-white/70 px-3 py-2 rounded-lg">${icon("arrow_forward", "text-[16px] text-slate-400")}<span>Handoff: <strong class="font-semibold text-slate-700">Echo the Publisher</strong> will automatically queue this for YouTube upload once confirmed.</span></div></div>
    <div class="px-6 sm:px-8 py-4 bg-white flex flex-col sm:flex-row items-center justify-between gap-3">
      <button class="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors active:scale-95" type="button" data-close>${icon("auto_fix_high", "text-[18px] text-slate-400")}<span>Let the crew make it</span></button>
      <div class="w-full sm:w-auto flex items-center justify-end gap-2.5">
        <button class="flex-1 sm:flex-none inline-flex items-center justify-center px-4 py-2 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-colors active:scale-95" type="button" data-close><span>Cancel</span></button>
        <button class="flex-1 sm:flex-none inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white font-label font-semibold text-xs shadow-md shadow-violet-200 disabled:opacity-50 disabled:cursor-not-allowed" type="button" id="up-use">${icon("publish", "text-[18px]")}<span>Use these files</span></button></div></div></div>`;

  const close = () => { dlg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  const draw = () => {
    $("#up-zones", dlg).innerHTML = Object.keys(UP_ZONES).map(zone).join("");
    dlg.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => dlg.querySelector(`[data-file="${b.dataset.pick}"]`).click());
    dlg.querySelectorAll("[data-file]").forEach(i => i.onchange = () => { if (i.files[0]) upload(i.dataset.file, i.files[0]); });
    dlg.querySelectorAll("[data-drop]").forEach(d => {
      d.addEventListener("dragover", e => { e.preventDefault(); d.classList.add("ring-2", "ring-violet-300"); });
      d.addEventListener("dragleave", () => d.classList.remove("ring-2", "ring-violet-300"));
      d.addEventListener("drop", e => { e.preventDefault(); d.classList.remove("ring-2", "ring-violet-300"); const f = e.dataTransfer.files[0]; if (f) upload(d.dataset.drop, f); });
    });
    dlg.querySelectorAll("[data-remove]").forEach(b => b.onclick = async () => {
      try { assets = (await post(`${base}/remove`, { kind: b.dataset.remove })).assets || {}; } catch (e) { toast(e.message, true); }
      draw();
    });
  };
  async function upload(kind, file) {
    busy[kind] = true; draw();
    try {
      const r = await fetch(`${base}?kind=${kind}&name=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "X-Postcrew": "1", "Content-Type": "application/octet-stream" }, body: file });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || `Upload failed (${r.status})`);
      assets = j.assets || {};
    } catch (e) { toast(e.message, true); }
    busy[kind] = false; draw();
  }
  dlg.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  dlg.onclick = e => { if (e.target === dlg) close(); };
  $("#up-use", dlg).onclick = () => {
    close();
    toast(`Your files are used the next time the crew runs for ${date}`);
    const bar = document.createElement("div");   // toast() has no action slot: a small secondary action beside it
    bar.className = "fixed bottom-16 left-1/2 -translate-x-1/2 z-50";
    bar.innerHTML = button("secondary", "play_arrow", "Run the crew now for this date", `type="button"`);
    document.body.appendChild(bar);
    const gone = setTimeout(() => bar.remove(), 12000);
    bar.querySelector("button").onclick = async () => {
      clearTimeout(gone); bar.remove();
      try { await post("/api/runs", { date, platform: "youtube", dry_run: false }); location.hash = "workflow"; } catch (e) { toast(e.message, true); }
    };
  };
  document.addEventListener("keydown", onKey);
  document.body.appendChild(dlg);
  draw();
  api(base).then(r => { assets = r.assets || {}; draw(); dlg.querySelector(`[data-zone="${focus}"]`)?.scrollIntoView({ block: "nearest" }); }).catch(e => toast(e.message, true));
}
