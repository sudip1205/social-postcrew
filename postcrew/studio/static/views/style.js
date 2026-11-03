/* Style: teach the crew your style from reference videos (Motion Studio). No Stitch screen: built from the shell, design.md and the same
   components; the add card copies the zones of design/stitch/upload-your-own-youtube.html. See design/DEVIATIONS.md.
   API: GET /api/motion, POST /api/motion/references/upload (raw file), /api/motion/references/url, /api/motion/references/<id>/<action>,
   /api/motion/style, /api/motion/feedback. */
"use strict";

const ST_RIGHTS = { own: "I made it (my own video)", licensed: "I licensed it", permission: "I have the creator's permission", "public-domain": "It is in the public domain" };
const ST_MODES = {
  screen: { ic: "movie", tint: "bg-sky-100 text-sky-600", title: "Screens", sub: "Layout, type size, colour, motion, how each scene is built. Needs the video." },
  script: { ic: "edit_note", tint: "bg-orange-100 text-orange-600", title: "Script", sub: "Hook, structure, pacing, sentences, devices. Needs the words: pasted, subtitles or transcription." },
};
const ST_STATE = { new: ["idle", "Not analysed"], queued: ["scheduled", "Waiting"], downloading: ["running", "Downloading"], analyzing: ["running", "Analyzing"],
  profile_review: ["waiting", "Needs your review"], ready: ["passed", "Approved"], rejected: ["idle", "Rejected"], failed: ["failed", "Failed"] };
const ST_KIND = { hook_weak: "Hook too weak", narration_fast: "Narration too fast", too_much_text: "Too much text", too_few_changes: "Too few visual changes",
  animation_slow: "Animation too slow", animation_busy: "Animation too busy", wrong_palette: "Wrong colours", poor_metaphor: "Poor visual idea",
  wrong_fact: "Wrong fact", captions_hard: "Captions hard to read", audio_mismatch: "Picture does not follow the voice", transition_awkward: "Awkward transition",
  text_too_small: "Text too small", empty_screen: "Empty screen", other: "Other" };
const ST_SMALL = "inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const ST_BTN = { ok: `${ST_SMALL} bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-200`, no: `${ST_SMALL} bg-white hover:bg-slate-50 text-slate-700 border-slate-300`,
  bad: `${ST_SMALL} bg-rose-50 hover:bg-rose-100 text-rose-700 border-rose-200`, go: `${ST_SMALL} bg-violet-50 hover:bg-violet-100 text-violet-700 border-violet-200` };
const stSecs = s => { s = Math.round(+s || 0); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const stList = (title, items) => items?.length ? `<div class="mt-3"><div class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">${esc(title)}</div>
  <ul class="list-disc pl-5 text-sm text-slate-700 mt-1 space-y-0.5">${items.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
const stLine = (label, text) => text ? `<p class="text-sm text-slate-700 mt-1"><span class="font-semibold text-slate-900">${esc(label)}:</span> ${esc(text)}</p>` : "";

async function renderStyle() {
  const view = $("#view");
  view.innerHTML = `<div class="max-w-7xl mx-auto">${emptyState("progress_activity", "Loading your reference videos...")}</div>`;
  let d;
  try { d = await api("/api/motion"); } catch (e) { view.innerHTML = errorBanner(e.message); return; }
  let file = null;

  const modeCard = (key, on) => { const m = ST_MODES[key];
    return `<label class="flex-1 flex items-start gap-3 p-4 rounded-xl border ${on ? "border-violet-300 bg-violet-50/50" : "border-slate-200 bg-white"} cursor-pointer hover:border-violet-300 transition-colors" data-modecard="${key}">
      <input type="checkbox" class="mt-1 accent-violet-600" data-mode="${key}" ${on ? "checked" : ""}>
      <div class="w-8 h-8 rounded-lg ${m.tint} flex items-center justify-center shrink-0">${icon(m.ic, "text-[20px]")}</div>
      <div><div class="font-headline font-semibold text-sm text-slate-900">${m.title}</div><div class="text-xs text-slate-500 mt-0.5">${m.sub}</div></div></label>`; };

  view.innerHTML = `
  ${card(`<div class="p-6 flex flex-col gap-4">
    <div class="flex items-start gap-3 flex-wrap">${sectionHead("school", "Teach your style", "Add Shorts you like. The crew learns how they look and how they are written, never their words, voice, music or branding.", "violet")}
      <span class="flex-1"></span><span id="st-house-chip"></span></div>
    <div class="flex items-start gap-2.5 text-xs text-slate-600 bg-slate-50 rounded-lg px-3 py-2.5">${icon("info", "text-[18px] text-blue-600 shrink-0")}
      <span>Only add videos you made, licensed or have permission to use. A public video is not yours to download: YouTube's terms forbid downloading other people's videos without permission. For those, paste the transcript and analyse the ${tip("script", "The words only: no video is downloaded when you analyse just the script and paste its transcript.")}.</span></div>
  </div>`)}

  ${card(`<div class="p-6 flex flex-col gap-5">
    ${sectionHead("add", "Add a reference", `A Short or one explainer, at most ${Math.round(d.max_seconds / 60)} minutes.`, "sky")}
    <div class="grid gap-4 md:grid-cols-2">
      <div class="bg-slate-50/80 rounded-xl p-4 sm:p-5 flex flex-col gap-3.5">
        <div class="flex items-center gap-2.5"><div class="w-8 h-8 rounded-lg bg-sky-100 text-sky-600 flex items-center justify-center">${icon("videocam", "text-[20px]")}</div>
          <div><h3 class="font-headline font-semibold text-sm sm:text-base text-slate-900">Upload a video (.mp4, .mov, .webm)</h3><span class="font-body text-xs text-slate-500">From your computer</span></div></div>
        <div class="bg-white rounded-lg p-3.5 shadow-sm flex flex-col gap-2.5" id="st-drop">
          <button class="w-full flex flex-col items-center gap-1 py-5 rounded-lg border border-dashed border-slate-300 text-slate-500 hover:border-violet-400 hover:text-violet-600 hover:bg-violet-50/40 transition-colors" type="button" id="st-pick">
            ${icon("file_upload", "text-[24px]")}<span class="text-xs font-medium" id="st-file-name">Drop a video or click to choose</span><span class="text-[11px] text-slate-400">Up to ${d.max_mb >= 1024 ? `${d.max_mb / 1024} GB` : `${d.max_mb} MB`}</span></button>
          <input type="file" class="hidden" accept=".mp4,.mov,.m4v,.webm,.mkv" id="st-file"></div></div>
      <div class="bg-slate-50/80 rounded-xl p-4 sm:p-5 flex flex-col gap-3.5">
        <div class="flex items-center gap-2.5"><div class="w-8 h-8 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center">${icon("link", "text-[20px]")}</div>
          <div><h3 class="font-headline font-semibold text-sm sm:text-base text-slate-900">Or a video URL</h3><span class="font-body text-xs text-slate-500">${d.tools.url ? "Fetched with yt-dlp on the computer running Postcrew" : "Needs yt-dlp: pip install yt-dlp on the computer running Postcrew"}</span></div></div>
        <div class="bg-white rounded-lg p-3.5 shadow-sm flex flex-col gap-2">
          <input id="st-url" type="url" placeholder="https://www.youtube.com/shorts/..." class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500" ${d.tools.url ? "" : "disabled"}>
          <span class="text-[11px] text-slate-400">Used instead of the upload when both are given.</span></div></div>
    </div>
    <div class="flex flex-col gap-2"><span class="text-xs font-semibold text-slate-700">What should the crew analyse?</span>
      <div class="flex flex-col sm:flex-row gap-3" id="st-modes">${modeCard("screen", true)}${modeCard("script", true)}</div></div>
    <div id="st-transcript-box" class="flex flex-col gap-1.5">
      <label class="text-xs font-semibold text-slate-700" for="st-transcript">Transcript (optional)</label>
      <textarea id="st-transcript" rows="3" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500" placeholder="Paste the narration. Left empty: the video's subtitles${d.tools.whisper ? ", else local transcription (faster-whisper)" : " (install faster-whisper to transcribe uploads)"}."></textarea></div>
    <div class="grid gap-4 md:grid-cols-3">
      <label class="flex flex-col gap-1.5"><span class="text-xs font-semibold text-slate-700">Your right to use it</span>
        <select id="st-rights" class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500">
          <option value="">Choose...</option>${d.rights.map(r => `<option value="${esc(r)}">${esc(ST_RIGHTS[r] || r)}</option>`).join("")}</select></label>
      <label class="flex flex-col gap-1.5"><span class="text-xs font-semibold text-slate-700">Title (optional)</span>
        <input id="st-title" class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500" placeholder="Its own title when empty"></label>
      <label class="flex flex-col gap-1.5"><span class="text-xs font-semibold text-slate-700">What you like about it (optional)</span>
        <input id="st-notes" class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500" placeholder="The pacing, the big numbers..."></label>
    </div>
    <div class="flex items-center justify-end gap-3">${button("primary", "auto_fix_high", "Add and analyse", `id="st-add"`)}</div>
  </div>`)}

  <div id="st-list"></div>
  <div class="grid gap-6 lg:grid-cols-2"><div id="st-house"></div><div id="st-prefs"></div></div>`;

  /* ---------- the add form ---------- */
  const modes = () => [...view.querySelectorAll("[data-mode]")].filter(i => i.checked).map(i => i.dataset.mode);
  const syncModes = () => {
    view.querySelectorAll("[data-modecard]").forEach(c => { const on = c.querySelector("input").checked;
      c.classList.toggle("border-violet-300", on); c.classList.toggle("bg-violet-50/50", on); c.classList.toggle("border-slate-200", !on); c.classList.toggle("bg-white", !on); });
    $("#st-transcript-box").hidden = !modes().includes("script");
  };
  view.querySelectorAll("[data-mode]").forEach(i => i.onchange = syncModes);
  const setFile = f => { file = f; $("#st-file-name").textContent = f ? `${f.name} (${(f.size / 1048576).toFixed(1)} MB)` : "Drop a video or click to choose"; };
  $("#st-pick").onclick = () => $("#st-file").click();
  $("#st-file").onchange = () => setFile($("#st-file").files[0] || null);
  const drop = $("#st-drop");
  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("ring-2", "ring-violet-300"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("ring-2", "ring-violet-300"));
  drop.addEventListener("drop", e => { e.preventDefault(); drop.classList.remove("ring-2", "ring-violet-300"); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });

  $("#st-add").onclick = async () => {
    const url = $("#st-url").value.trim(), rights = $("#st-rights").value, m = modes(), transcript = $("#st-transcript").value;
    const title = $("#st-title").value.trim(), notes = $("#st-notes").value.trim();
    if (!url && !file) return toast("Choose a video file or give its URL", true);
    if (!rights) return toast("Say what right you have to use this video", true);
    if (!m.length) return toast("Choose what to analyse: the screens, the script or both", true);
    if (!url && !m.includes("screen") && !transcript.trim() && !d.tools.whisper) toast("No transcript: paste it, or the script analysis will fail", true);
    const b = $("#st-add"); b.disabled = true; b.querySelector("span:last-child").textContent = url ? "Adding..." : "Uploading...";
    try {
      if (url) await post("/api/motion/references/url", { url, rights, title, notes, modes: m, transcript });
      else {
        const qs = new URLSearchParams({ name: file.name, rights, title, notes });
        const r = await fetch(`/api/motion/references/upload?${qs}`, { method: "POST", headers: { "X-Postcrew": "1", "Content-Type": "application/octet-stream" }, body: file });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error || `Upload failed (${r.status})`);
        await post(`/api/motion/references/${j.reference.id}/analyze`, { modes: m, transcript });
      }
      toast("Added: the analysis runs in the background");
      $("#st-url").value = ""; $("#st-title").value = ""; $("#st-notes").value = ""; $("#st-transcript").value = ""; $("#st-file").value = ""; setFile(null);
      await refresh();
    } catch (e) { toast(e.message, true); }
    b.disabled = false; b.querySelector("span:last-child").textContent = "Add and analyse";
  };

  /* ---------- the parts that change while analyses run ---------- */
  const refRow = r => {
    const [kind, word] = ST_STATE[r.status] || ["idle", r.status];
    const busy = ["queued", "downloading", "analyzing"].includes(r.status), meas = r.measured || {};
    const facts = [r.seconds ? stSecs(r.seconds) : "", r.width ? `${r.width}x${r.height}` : "", meas.cuts_per_minute ? `${meas.cuts_per_minute} cuts/min` : "",
      meas.shot_seconds ? `${meas.shot_seconds}s per shot` : "", meas.words_per_second ? `${meas.words_per_second} words/s` : "",
      r.transcript_source ? `transcript: ${r.transcript_source}` : ""].filter(Boolean);
    const sc = r.screen, sp = r.script;
    const details = (sc || sp) ? `<details class="mt-3 group"><summary class="cursor-pointer text-xs font-semibold text-violet-700 inline-flex items-center gap-1">${icon("expand_more", "text-[16px] group-open:rotate-180 transition-transform")}What the crew learned</summary>
      <div class="grid gap-4 ${sc && sp ? "lg:grid-cols-2" : ""} mt-3">
        ${sc ? `<div class="rounded-xl bg-slate-50 p-4"><h4 class="flex items-center gap-2 text-sm font-bold text-slate-900">${icon("movie", "text-sky-600")}Screens${sc.name ? `: ${esc(sc.name)}` : ""}</h4>
          <p class="text-sm text-slate-600 mt-1">${esc(sc.summary)}</p>${stLine("Composition", sc.composition)}${stLine("Motion", sc.motion)}${stLine("Rhythm", sc.rhythm)}
          ${stList("Patterns", sc.patterns)}${stList("Strengths", sc.strengths)}${stList("Weaknesses", sc.weaknesses)}
          ${r.sheets.length ? `<div class="flex gap-2 mt-3 overflow-x-auto">${r.sheets.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="Contact sheet of the reference's shots" class="h-40 rounded-lg border border-slate-200"></a>`).join("")}</div>` : ""}</div>` : ""}
        ${sp ? `<div class="rounded-xl bg-slate-50 p-4"><h4 class="flex items-center gap-2 text-sm font-bold text-slate-900">${icon("edit_note", "text-orange-600")}Script</h4>
          <p class="text-sm text-slate-600 mt-1">${esc(sp.summary)}</p>${stLine("Hook", sp.hook)}${stLine("Structure", sp.structure)}${stLine("Tone", sp.tone)}${stLine("Sentences", sp.sentences)}
          ${stList("Parts", sp.parts)}${stList("Rules a writer can follow", sp.rules)}${stList("Patterns", sp.patterns)}${stList("Strengths", sp.strengths)}${stList("Weaknesses", sp.weaknesses)}</div>` : ""}
      </div></details>` : "";
    const again = Object.keys(ST_MODES).map(k => `<button class="${ST_BTN.go}" data-again="${esc(r.id)}:${k}" ${busy ? "disabled" : ""}>${icon(ST_MODES[k].ic, "text-sm")}<span>Analyse ${k === "screen" ? "screens" : "script"}</span></button>`).join("");
    return `<div class="rounded-xl border border-slate-200 p-4 ${r.status === "rejected" ? "bg-slate-50" : "bg-white"}">
      <div class="flex items-start gap-3 flex-wrap">
        <div class="w-9 h-9 rounded-lg ${r.source_type === "url" ? "bg-rose-50 text-rose-600" : "bg-sky-50 text-sky-600"} flex items-center justify-center shrink-0">${icon(r.source_type === "url" ? "link" : "videocam", "text-[20px]")}</div>
        <div class="min-w-0 flex-1"><div class="font-bold text-slate-900 truncate">${esc(r.title === r.source_url ? "Video from a URL" : r.title)}</div>
          <div class="text-xs text-slate-500 mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">${r.source_url ? `<a class="text-violet-700 hover:underline truncate max-w-xs" href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.source_url)}</a>` : r.video_url ? `<a class="text-violet-700 hover:underline" href="${esc(r.video_url)}" target="_blank" rel="noopener">${esc(r.original_name || "video")}</a>` : ""}
            <span>${esc(ST_RIGHTS[r.rights] || r.rights)}</span>${r.creator ? `<span>${esc(r.creator)}</span>` : ""}<span>${esc(ago(r.created_at))}</span></div></div>
        <div class="flex items-center gap-1.5 flex-wrap">${chip(kind, word)}${(r.analyzed || []).map(k => chip("info", k === "screen" ? "Screens" : "Script", "sm")).join("")}</div></div>
      ${facts.length ? `<div class="flex flex-wrap gap-1.5 mt-3">${facts.map(f => `<span class="text-[11px] px-2 py-0.5 rounded-md border border-slate-200 bg-slate-50 text-slate-600 font-mono">${esc(f)}</span>`).join("")}</div>` : ""}
      ${busy && r.log?.length ? `<div class="flex items-center gap-2 mt-3 text-xs text-violet-700">${icon("progress_activity", "text-sm animate-spin")}<span>${esc(r.log.at(-1))}</span></div>` : ""}
      ${r.status === "failed" && r.status_reason ? `<div class="mt-3">${errorBanner(r.status_reason)}</div>` : ""}
      ${details}
      <div class="flex flex-wrap items-center gap-2 mt-4">
        ${r.status === "profile_review" || r.status === "rejected" ? `<button class="${ST_BTN.ok}" data-act="${esc(r.id)}:approve">${icon("check_circle", "text-sm")}<span>Approve: learn from it</span></button>` : ""}
        ${r.status === "profile_review" || r.status === "ready" ? `<button class="${ST_BTN.no}" data-act="${esc(r.id)}:reject">${icon("do_not_disturb_on", "text-sm")}<span>Reject</span></button>` : ""}
        ${again}<span class="flex-1"></span>
        <button class="${ST_BTN.bad}" data-act="${esc(r.id)}:delete" ${busy ? "disabled" : ""}>${icon("delete", "text-sm")}<span>Delete</span></button></div></div>`;
  };

  const draw = () => {
    const approved = d.references.filter(r => r.status === "ready").length;
    $("#st-house-chip").innerHTML = chip(d.house.version ? "passed" : "idle", `House style v${d.house.version}${d.house.version ? "" : " (built-in)"}`);
    $("#st-list").innerHTML = card(`<div class="p-6">${sectionHead("video_library", "Reference videos", `${d.references.length} added, ${approved} approved. Approve the ones worth learning from, then build the house style.`, "indigo")}
      <div class="flex flex-col gap-3 mt-5">${d.references.length ? d.references.map(refRow).join("") : emptyState("video_library", "No reference videos yet. Add a Short you like above.")}</div></div>`);
    const job = d.style_job || {};
    $("#st-house").innerHTML = card(`<div class="p-6 h-full">
      <div class="flex items-start gap-3 flex-wrap">${sectionHead("auto_awesome", "House style", `${d.house.name} v${d.house.version}${d.house.source === "built-in" ? ", built in" : ""}. Muse plans every video with it, Lens judges every video by it.`, "violet")}</div>
      ${job.state ? `<div class="mt-4 flex items-center gap-2 text-xs ${job.state === "failed" ? "text-rose-700" : "text-violet-700"}">${icon(job.state === "running" ? "progress_activity" : job.state === "failed" ? "error" : "check_circle", `text-sm ${job.state === "running" ? "animate-spin" : ""}`)}<span>${esc(job.message)}</span></div>` : ""}
      <pre class="mt-4 whitespace-pre-wrap text-xs text-slate-700 bg-slate-50 rounded-lg p-3 font-mono max-h-72 overflow-y-auto">${esc(d.house.brief)}</pre>
      ${d.house.script ? `<pre class="mt-3 whitespace-pre-wrap text-xs text-slate-700 bg-orange-50/60 rounded-lg p-3 font-mono max-h-60 overflow-y-auto">${esc(d.house.script)}</pre>` : `<p class="text-xs text-slate-500 mt-3">No script style yet: approve a reference with a script analysis and build again. Until then the Script Writer follows its own rules.</p>`}
      <div class="flex flex-wrap items-center gap-2 mt-4">
        ${button("primary", "auto_fix_high", "Build from approved videos", `id="st-build" ${approved && job.state !== "running" ? "" : "disabled"} title="${approved ? "Merge the approved references into a new version" : "Approve a reference first"}"`)}
        ${d.house.version ? button("secondary", "undo", "Back to built-in", `id="st-reset"`) : ""}</div>
      ${d.versions.length ? `<div class="mt-4 flex flex-wrap gap-1.5 items-center"><span class="text-xs text-slate-500 mr-1">Versions:</span>${d.versions.map(v => `<button class="${v.version === d.house.version ? ST_BTN.go : ST_BTN.no}" data-use="${v.version}" title="${esc(fmtTime(v.created_at))}, from ${v.from.length} reference(s)">${icon("history", "text-sm")}<span>v${v.version}</span></button>`).join("")}</div>` : ""}
    </div>`);
    $("#st-prefs").innerHTML = card(`<div class="p-6 h-full">${sectionHead("grade", "Your preferences", "Notes on finished videos. Only the ones you approve change how the crew works.", "amber")}
      ${d.preferences.length ? `<ul class="mt-4 divide-y divide-slate-100">${d.preferences.map((p, i) => `<li class="flex items-start gap-3 py-2"><span class="flex-1 text-sm text-slate-700">${esc(p.rule)}</span>
        <button class="${ST_BTN.no}" data-forget="${i + 1}">${icon("delete", "text-sm")}<span>Forget</span></button></li>`).join("")}</ul>` : `<p class="text-sm text-slate-500 mt-4">No approved preferences yet.</p>`}
      ${d.feedback.length ? `<h3 class="flex items-center gap-2 text-sm font-bold text-slate-900 mt-6">${icon("inbox", "text-violet-600")}Waiting for your approval</h3>
        <ul class="mt-2 divide-y divide-slate-100">${d.feedback.map(f => `<li class="flex items-start gap-3 py-2"><div class="flex-1 text-sm text-slate-700"><span class="font-semibold">${esc(ST_KIND[f.kind] || f.kind)}</span>${f.scene ? ` · scene ${f.scene}` : ""}${f.rating ? ` · ${f.rating}/5` : ""}
          ${f.comment ? `<div class="text-slate-500">${esc(f.comment)}</div>` : ""}<div class="text-[11px] text-slate-400 font-mono">${esc(f.video)}</div></div>
          <button class="${ST_BTN.ok}" data-approve-fb="${esc(f.id)}">${icon("check_circle", "text-sm")}<span>Approve</span></button></li>`).join("")}</ul>` : ""}
      <h3 class="flex items-center gap-2 text-sm font-bold text-slate-900 mt-6">${icon("edit_note", "text-violet-600")}Add a note</h3>
      <div class="grid gap-2 sm:grid-cols-2 mt-2">
        <input id="fb-video" class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500" placeholder="Run id, e.g. 2026-11-03-110927">
        <select id="fb-kind" class="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500">${d.kinds.map(k => `<option value="${esc(k)}">${esc(ST_KIND[k] || k)}</option>`).join("")}</select>
        <input id="fb-comment" class="sm:col-span-2 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-violet-500 focus:ring-violet-500" placeholder="What should change (optional)"></div>
      <div class="flex justify-end mt-2">${button("secondary", "add", "Add note", `id="fb-add"`)}</div>
    </div>`);
    wire();
  };

  const act = async (path, body, msg) => { try { d = await post(path, body); if (msg) toast(msg); } catch (e) { toast(e.message, true); } draw(); schedule(); };
  const wire = () => {
    view.querySelectorAll("[data-act]").forEach(b => b.onclick = () => {
      const [id, what] = b.dataset.act.split(":");
      if (what === "delete" && !confirm("Delete this reference and its files?")) return;
      b.disabled = true;
      act(`/api/motion/references/${id}/${what}`, {}, { approve: "Approved: build the house style to use it", reject: "Rejected", delete: "Deleted" }[what]);
    });
    view.querySelectorAll("[data-again]").forEach(b => b.onclick = async () => {
      const [id, mode] = b.dataset.again.split(":");
      let transcript = "";
      if (mode === "script" && !(d.references.find(r => r.id === id)?.transcript_source)) transcript = prompt("Paste the narration (leave empty to use the video's subtitles or local transcription):") || "";
      b.disabled = true;
      try { await post(`/api/motion/references/${id}/analyze`, { modes: [mode], transcript }); toast("Analysis started"); } catch (e) { toast(e.message, true); }
      refresh();
    });
    view.querySelectorAll("[data-use]").forEach(b => b.onclick = () => act("/api/motion/style", { action: "use", version: +b.dataset.use }, `House style v${b.dataset.use} is in use`));
    $("#st-build")?.addEventListener("click", () => act("/api/motion/style", { action: "build" }, "Building the house style"));
    $("#st-reset")?.addEventListener("click", () => { if (confirm("Go back to the built-in house style? Your versions are kept.")) act("/api/motion/style", { action: "reset" }, "Back to the built-in style"); });
    view.querySelectorAll("[data-forget]").forEach(b => b.onclick = () => act("/api/motion/feedback", { action: "forget", index: +b.dataset.forget }, "Forgotten"));
    view.querySelectorAll("[data-approve-fb]").forEach(b => b.onclick = () => act("/api/motion/feedback", { action: "approve", id: b.dataset.approveFb }, "Approved: the crew follows it from the next video"));
    $("#fb-add").onclick = () => {
      const video = $("#fb-video").value.trim(), kind = $("#fb-kind").value, comment = $("#fb-comment").value.trim();
      if (!video) return toast("Name the video: its run id", true);
      act("/api/motion/feedback", { action: "add", video, kind, comment }, "Noted: approve it to make it a rule");
    };
  };

  async function refresh() { try { d = await api("/api/motion"); } catch (e) { toast(e.message, true); } draw(); schedule(); }
  function schedule() {
    clearTimeout(S.stylePoll);
    if (d.busy || d.references.some(r => ["queued", "downloading", "analyzing"].includes(r.status)))
      S.stylePoll = setTimeout(() => { if (S.tab === "style") refresh(); }, 3000);
  }
  syncModes(); draw(); schedule();
}
VIEWS.style = renderStyle;
