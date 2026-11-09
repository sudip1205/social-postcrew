/* Factory: a chat with Claude Code inside the Shorts factory (~/Youtube on the computer running the Studio), like the Claude Code app.
   A topic -> it writes and renders the Short. An instruction for every video -> it changes the skill. No Stitch screen: built from the
   Queue page's layout, the shared cards, chips and buttons (design/DEVIATIONS.md). */
"use strict";

const FC_EXAMPLES = [
  ["Make a Short", "Make a Short about why Python's default arguments are shared between calls."],
  ["Change the style", "From now on, put the captions a little higher and make the voice slightly slower. Update the skill."],
  ["What changed", "Which rules did we add to the skill this week? List them."],
];
let fcTimer = null, fcSeen = -1;
const FC_OPEN = new Set();   // videos whose details are open (kept open across refreshes)

function fcBubble(m) {
  const t = esc(m.text);
  if (m.role === "user") return `<div class="flex justify-end"><div class="max-w-[85%] bg-violet-600 text-white rounded-2xl rounded-br-md px-4 py-2.5 text-sm whitespace-pre-wrap">${t}</div></div>`;
  if (m.role === "assistant") return `<div class="flex"><div class="max-w-[85%] bg-white border border-slate-200 rounded-2xl rounded-bl-md px-4 py-2.5 text-sm text-slate-800 whitespace-pre-wrap shadow-sm">${t}</div></div>`;
  if (m.role === "tool") return `<div class="flex items-center gap-1.5 pl-2 text-[11px] font-mono text-slate-500 truncate" title="${t}">${icon("build", "text-xs text-slate-400")}<span class="truncate">${t}</span></div>`;
  if (m.role === "error") return `<div class="flex items-start gap-1.5 bg-rose-50 border border-rose-200 text-rose-700 rounded-lg px-3 py-2 text-xs">${icon("error", "text-sm")}<span class="whitespace-pre-wrap">${t}</span></div>`;
  return `<div class="text-center text-[11px] text-slate-400">${t}</div>`;
}

function fcVideo(v) {
  const today = OV_ISO(new Date());
  return `<li class="py-3 flex gap-3">
    <button class="relative shrink-0 w-16 h-28 rounded-lg overflow-hidden bg-slate-900 group" data-fc-play="${esc(v.file)}" title="Watch">
      ${v.thumb ? `<img class="w-full h-full object-cover" src="/factory-out/${encodeURIComponent(v.thumb)}" alt="">` : ""}
      <span class="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/10 text-white">${icon("play_arrow", "text-2xl")}</span>
    </button>
    <div class="min-w-0 flex-1 flex flex-col gap-1.5">
      <div class="text-sm font-semibold text-slate-900 line-clamp-2" title="${esc(v.title)}">${esc(v.title)}</div>
      <div class="text-[11px] text-slate-500">${esc(ago(v.made))} · ${v.mb} MB</div>
      <div class="flex flex-wrap items-center gap-1.5 mt-auto">
        ${v.has_meta ? `<input type="date" class="text-xs border border-slate-300 rounded-md px-2 py-1" value="${today}" min="${today}" data-fc-date="${esc(v.slug)}">
          <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold" data-fc-queue="${esc(v.slug)}">${icon("playlist_add", "text-sm")}<span>Move to Queue</span></button>`
          : `<span class="text-[11px] text-amber-700">${tip("No youtube.json", "Ask Claude to write the title, description and tags for this episode; then it can be queued.")}</span>`}
        <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-xs font-semibold" data-fc-delete="${esc(v.slug)}" data-fc-title="${esc(v.title)}">${icon("delete", "text-sm")}<span>Delete</span></button>
      </div>
      ${v.has_meta ? `<details class="group" data-fc-meta="${esc(v.slug)}" ${FC_OPEN.has(v.slug) ? "open" : ""}>
        <summary class="cursor-pointer text-[11px] font-semibold text-violet-700 flex items-center gap-1 select-none">${icon("edit_note", "text-sm")}<span>YouTube details: title, description, tags</span></summary>
        <div class="mt-2 space-y-2">
          <label class="block"><span class="text-[11px] font-semibold text-slate-600">Title <span class="font-normal text-slate-400" data-fc-count="title">${v.yt_title.length}/100</span></span>
            <input class="mt-0.5 w-full text-xs border border-slate-300 rounded-md px-2 py-1" maxlength="100" data-fc-field="title" value="${esc(v.yt_title)}"></label>
          <label class="block"><span class="text-[11px] font-semibold text-slate-600">Description</span>
            <textarea rows="5" class="mt-0.5 w-full text-xs border border-slate-300 rounded-md px-2 py-1 resize-y" maxlength="5000" data-fc-field="description">${esc(v.description)}</textarea></label>
          <label class="block"><span class="text-[11px] font-semibold text-slate-600">Tags <span class="font-normal text-slate-400">(comma separated)</span></span>
            <input class="mt-0.5 w-full text-xs border border-slate-300 rounded-md px-2 py-1" data-fc-field="tags" value="${esc(v.tags.join(", "))}"></label>
          <p class="text-[11px] text-slate-400">Saved to the episode's youtube.json when you move it to the Queue; you can still change them in the Queue before it is published.</p>
        </div></details>` : ""}
    </div></li>`;
}

function fcRef(r) {
  return `<li class="py-3 flex gap-3" data-fc-ref="${esc(r.id)}">
    <button class="relative shrink-0 w-20 h-14 rounded-lg overflow-hidden bg-slate-900 group" data-fc-refplay="${esc(r.video || "")}" title="Watch">
      ${r.thumb ? `<img class="w-full h-full object-cover" src="/factory-ref/${r.thumb.split("/").map(encodeURIComponent).join("/")}" alt="">` : ""}
      <span class="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/10 text-white">${icon("play_arrow", "text-xl")}</span>
    </button>
    <div class="min-w-0 flex-1 flex flex-col gap-1.5">
      <div class="text-sm font-semibold text-slate-900 truncate" title="${esc(r.name)}">${esc(r.name || "Reference video")}</div>
      <div class="text-[11px] text-slate-500 flex flex-wrap items-center gap-x-2">${r.seconds ? `<span>${Math.round(r.seconds)} s · ${r.frames} frames</span>` : ""}
        ${r.learned ? `<span class="inline-flex items-center gap-0.5 text-emerald-700">${icon("check_circle", "text-xs")}<span>Taught ${esc(ago(r.learned))}</span></span>`
          : `<span class="inline-flex items-center gap-0.5 text-amber-700">${icon("schedule", "text-xs")}<span>Not taught yet</span></span>`}</div>
      <textarea rows="2" class="w-full text-xs border border-slate-300 rounded-md px-2 py-1 resize-y" maxlength="4000" data-fc-refnote
        placeholder="What should the skill learn from this video? e.g. the way the title pops in, the caption size">${esc(r.comment || "")}</textarea>
      <div class="flex flex-wrap items-center gap-1.5">
        <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold disabled:opacity-50" data-fc-teach>${icon("school", "text-sm")}<span>Teach the skill</span></button>
        <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold" data-fc-refsave>${icon("save", "text-sm")}<span>Save comment</span></button>
        <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-xs font-semibold" data-fc-refdel>${icon("delete", "text-sm")}<span>Delete</span></button>
      </div>
    </div></li>`;
}

function fcPlay(src) {
  const dlg = $("#fc-player"); dlg.querySelector("video").src = src; dlg.showModal(); dlg.querySelector("video").play();
}

function fcDrawRefs(refs) {
  if (document.activeElement?.closest?.("#fc-refs")) return;   // never redraw while you are writing a comment
  $("#fc-refs").innerHTML = (refs || []).length ? refs.map(fcRef).join("")
    : `<li class="py-2 text-xs text-slate-500">No reference videos yet. Add a video you like and say what to learn from it.</li>`;
  document.querySelectorAll("[data-fc-ref]").forEach(li => {
    const id = li.dataset.fcRef, note = () => li.querySelector("[data-fc-refnote]").value;
    li.querySelector("[data-fc-refplay]").onclick = e => { const v = e.currentTarget.dataset.fcRefplay; if (v) fcPlay(`/factory-ref/${v.split("/").map(encodeURIComponent).join("/")}`); };
    li.querySelector("[data-fc-refsave]").onclick = async () => {
      try { const r = await post("/api/factory/references/comment", { id, comment: note() }); document.activeElement?.blur?.(); fcDrawRefs(r.references); toast("Comment saved"); }
      catch (e) { toast(e.message, true); }
    };
    li.querySelector("[data-fc-teach]").onclick = async e => {
      const b = e.currentTarget; b.disabled = true;
      try {
        await post("/api/factory/references/comment", { id, comment: note() });
        const r = await post("/api/factory/references/teach", { id }); document.activeElement?.blur?.(); fcDraw(r); fcPoll();
        toast("Sent to Claude: it is studying the video and updating the skill");
      } catch (err) { toast(err.message, true); b.disabled = false; }
    };
    li.querySelector("[data-fc-refdel]").onclick = async () => {
      if (!confirm("Delete this reference video? What the skill already learned from it stays.")) return;
      try { const r = await post("/api/factory/references/delete", { id }); document.activeElement?.blur?.(); fcDrawRefs(r.references); toast("Reference deleted"); }
      catch (e) { toast(e.message, true); }
    };
  });
}

function fcMessages(d) {
  const ms = d.messages || [];
  return ms.length ? ms.map(fcBubble).join("") + (d.busy ? `<div class="flex items-center gap-2 text-xs text-violet-700 pl-1">${icon("sync", "text-sm animate-spin")}<span>Claude is working…</span></div>` : "")
    : `<div class="text-sm text-slate-500 space-y-3">
        <p>Talk to Claude Code inside your Shorts factory, as in the Claude Code app. Give it a <strong>topic</strong> and it writes and renders the Short;
        give it an <strong>instruction for every video</strong> and it writes it into the ${tip("skill", "explainer-short-style: the rules every video follows. CLAUDE.md tells Claude to update it whenever you give a lasting instruction.")}.</p>
        <div class="flex flex-wrap gap-2">${FC_EXAMPLES.map(([l, x]) => `<button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium" data-fc-example="${esc(x)}">${icon("lightbulb", "text-sm")}<span>${esc(l)}</span></button>`).join("")}</div>
      </div>`;
}

function fcDrawVideos(d) {
  $("#fc-videos").innerHTML = (d.videos || []).length ? d.videos.map(fcVideo).join("") : emptyState("movie", "No videos yet. Ask Claude for a Short.");
  document.querySelectorAll("[data-fc-meta]").forEach(dt => {
    dt.ontoggle = () => dt.open ? FC_OPEN.add(dt.dataset.fcMeta) : FC_OPEN.delete(dt.dataset.fcMeta);
    const t = dt.querySelector('[data-fc-field="title"]'); t.oninput = () => dt.querySelector('[data-fc-count="title"]').textContent = `${t.value.length}/100`;
  });
  document.querySelectorAll("[data-fc-play]").forEach(b => b.onclick = () => fcPlay(`/factory-out/${encodeURIComponent(b.dataset.fcPlay)}`));
  document.querySelectorAll("[data-fc-delete]").forEach(b => b.onclick = async () => {
    if (!confirm(`Delete the video "${b.dataset.fcTitle}"? Its script stays, so Claude can make it again.`)) return;
    try { const r = await post("/api/factory/delete", { slug: b.dataset.fcDelete }); document.activeElement?.blur?.(); fcDraw(r); toast("Video deleted"); }
    catch (e) { toast(e.message, true); }
  });
  document.querySelectorAll("[data-fc-queue]").forEach(b => b.onclick = async () => {
    const slug = b.dataset.fcQueue, date = document.querySelector(`[data-fc-date="${CSS.escape(slug)}"]`).value;
    const box = document.querySelector(`[data-fc-meta="${CSS.escape(slug)}"]`), body = { slug, date };
    if (box) box.querySelectorAll("[data-fc-field]").forEach(f => body[f.dataset.fcField] = f.value);
    b.disabled = true;
    try {
      const r = await post("/api/factory/queue", body); FC_OPEN.delete(slug); document.activeElement?.blur?.(); fcDraw(r);
      toast(`Moved to the Queue for ${date}: approve it there`);
    } catch (e) { toast(e.message, true); b.disabled = false; }
  });
}

function fcDraw(d) {
  $("#fc-log").innerHTML = fcMessages(d);
  if ((d.messages || []).length !== fcSeen) { $("#fc-log").scrollTop = $("#fc-log").scrollHeight; fcSeen = (d.messages || []).length; }
  $("#fc-send").disabled = d.busy;
  $("#fc-stop").classList.toggle("hidden", !d.busy);
  if (!document.activeElement?.closest?.("#fc-videos")) fcDrawVideos(d);   // never redraw the list while you are typing in it
  const sel = $("#fc-plan"), was = sel.value;
  if (sel.dataset.ids !== (d.plans || []).map(x => x.id).join(",")) {
    sel.innerHTML = `<option value="">${(d.plans || []).length ? "Pick one of your plans…" : "No plans waiting in Manual run"}</option>` +
      (d.plans || []).map(x => `<option value="${esc(x.id)}">${esc(x.title)} · ${esc(x.format)}${x.files ? ` · ${x.files} file${x.files > 1 ? "s" : ""}` : ""}</option>`).join("");
    sel.dataset.ids = (d.plans || []).map(x => x.id).join(","); sel.value = was;
  }
  if (d.references) fcDrawRefs(d.references);
  $("#fc-skillver").textContent = d.skill_version?.fingerprint ? `version ${d.skill_version.fingerprint}, changed ${ago(d.skill_version.changed)}` : "";
  $("#fc-skill").innerHTML = (d.skill || []).map(f => `<li class="flex items-center justify-between gap-2 py-1"><span class="font-mono text-[11px] text-slate-700 truncate">${esc(f.path)}</span><span class="text-[11px] text-slate-400 whitespace-nowrap">${esc(ago(f.changed))}</span></li>`).join("");
  document.querySelectorAll("[data-fc-example]").forEach(b => b.onclick = () => { $("#fc-text").value = b.dataset.fcExample; $("#fc-text").focus(); });
}

async function fcPoll() {
  clearTimeout(fcTimer);
  if (S.tab !== "factory" || !$("#fc-log")) return;
  try {
    const d = await api("/api/factory");
    fcDraw(d);
    fcTimer = setTimeout(fcPoll, d.busy ? 1500 : 8000);
  } catch (e) { fcTimer = setTimeout(fcPoll, 8000); }
}

async function renderFactory() {
  const d = await api("/api/factory");
  fcSeen = -1;
  $("#view").innerHTML = `
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold font-headline text-slate-900 tracking-tight flex items-center gap-2"><span>Factory</span>
          <span class="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-200/80 text-slate-700">YouTube Shorts</span></h1>
        <p class="text-sm text-slate-500 mt-1 flex items-center gap-1.5">${d.found
          ? `${icon("folder", "text-sm text-slate-400")}<span class="font-mono text-xs">${esc(d.factory)}</span>`
          : `${icon("error", "text-sm text-rose-500")}<span class="text-rose-700">The Shorts factory is not at ${esc(d.factory)}</span>`}</p>
      </div>
      <button id="fc-new" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors">${icon("add_comment", "text-sm")}<span>New chat</span></button>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      <section class="lg:col-span-7 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col h-[calc(100vh-14rem)] min-h-[480px]">
        <div id="fc-log" class="flex-1 overflow-y-auto p-5 space-y-3 bg-slate-50/50 rounded-t-xl"></div>
        <div class="p-3 border-t border-slate-200 flex flex-col gap-2">
          <div class="flex items-center gap-2">
            <label class="text-xs font-semibold text-slate-600 flex items-center gap-1 shrink-0" for="fc-plan">${icon("assignment", "text-sm text-slate-400")}<span>${tip("Use a plan", "One of your own YouTube plans from Manual run: its words, how you want it made, the problem read from your files, and the files themselves go into the message. Moving its video to the Queue marks the plan as made.")}</span></label>
            <select id="fc-plan" class="flex-1 min-w-0 text-xs border border-slate-300 rounded-md px-2 py-1.5 bg-white"></select>
          </div>
          <textarea id="fc-text" rows="3" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-y"
            placeholder="A topic for a new Short, or an instruction for every video (Enter sends, Shift+Enter for a new line)"></textarea>
          <div class="flex items-center justify-between gap-2">
            <span class="text-[11px] text-slate-400">Runs Claude Code in the factory on this computer. Videos are never uploaded from here: queue them.</span>
            <div class="flex items-center gap-2">
              <button id="fc-stop" class="hidden inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-rose-50 border border-rose-200 text-rose-700">${icon("stop", "text-sm")}<span>Stop</span></button>
              <button id="fc-send" class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50 disabled:cursor-not-allowed">${icon("send", "text-sm")}<span>Send</span></button>
            </div>
          </div>
        </div>
      </section>
      <aside class="lg:col-span-5 space-y-6">
        <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
          <div class="flex items-center gap-2"><div class="w-7 h-7 rounded-lg bg-rose-100 text-rose-700 flex items-center justify-center">${icon("movie", "text-base")}</div>
            <h2 class="text-lg font-bold font-headline text-slate-900">Videos</h2></div>
          <ul id="fc-videos" class="divide-y divide-slate-100"></ul>
        </section>
        <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
          <div class="flex items-center gap-2"><div class="w-7 h-7 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center">${icon("video_library", "text-base")}</div>
            <h2 class="text-lg font-bold font-headline text-slate-900">${tip("Reference videos", "Videos you like. Say what to learn from each one; Teach the skill sends Claude its frames and your comment, and Claude writes the lesson into the skill so every later Short follows it.")}</h2></div>
          <div class="space-y-2 rounded-lg bg-slate-50 border border-slate-200 p-3">
            <textarea id="fc-refnote" rows="2" class="w-full text-xs border border-slate-300 rounded-md px-2 py-1 resize-y bg-white" maxlength="4000"
              placeholder="What should the skill learn from it? (you can also write this later)"></textarea>
            <div class="flex flex-wrap items-center gap-1.5">
              <label class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-white hover:bg-slate-100 border border-slate-300 text-slate-700 text-xs font-semibold cursor-pointer">${icon("file_upload", "text-sm")}<span id="fc-refup-label">Upload a video</span>
                <input id="fc-refup" type="file" accept="video/*,.mkv" class="hidden"></label>
              <span class="text-[11px] text-slate-400">or</span>
              <input id="fc-reflink" type="url" class="flex-1 min-w-[8rem] text-xs border border-slate-300 rounded-md px-2 py-1 bg-white" placeholder="https://youtube.com/shorts/…">
              <button id="fc-refadd" class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-900 text-white text-xs font-semibold disabled:opacity-50">${icon("add_link", "text-sm")}<span>Add link</span></button>
            </div>
          </div>
          <ul id="fc-refs" class="divide-y divide-slate-100"></ul>
        </section>
        <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-2">
          <div class="flex items-center gap-2"><div class="w-7 h-7 rounded-lg bg-sky-100 text-sky-700 flex items-center justify-center">${icon("school", "text-base")}</div>
            <h2 class="text-lg font-bold font-headline text-slate-900">Skill</h2></div>
          <p class="text-xs text-slate-500">The rules every video follows, read fresh by the chat and by every scheduled run: <span id="fc-skillver" class="font-mono"></span></p>
          <ul id="fc-skill" class="divide-y divide-slate-100"></ul>
        </section>
      </aside>
    </div>
    <dialog id="fc-player" class="rounded-xl p-0 bg-black backdrop:bg-black/70">
      <video class="max-h-[85vh] max-w-[90vw]" controls></video>
      <form method="dialog" class="absolute top-2 right-2"><button class="w-8 h-8 rounded-full bg-white/90 text-slate-800 flex items-center justify-center">${icon("close", "text-base")}</button></form>
    </dialog>`;
  const send = async () => {
    const text = $("#fc-text").value.trim(); if (!text) return;
    try { fcDraw(await post("/api/factory/send", { text })); $("#fc-text").value = ""; fcPoll(); } catch (e) { toast(e.message, true); }
  };
  $("#fc-send").onclick = send;
  $("#fc-plan").onchange = async e => {
    if (!e.target.value) return;
    const cur = $("#fc-text").value.trim();
    if (cur && !confirm("Replace what you have typed with this plan?")) { e.target.value = ""; return; }
    try { const r = await api(`/api/factory/plan?id=${encodeURIComponent(e.target.value)}`); $("#fc-text").value = r.text; $("#fc-text").focus(); }
    catch (err) { toast(err.message, true); }
  };
  $("#fc-text").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("#fc-stop").onclick = async () => { try { fcDraw(await post("/api/factory/stop")); } catch (e) { toast(e.message, true); } };
  $("#fc-new").onclick = async () => { try { fcDraw(await post("/api/factory/reset")); } catch (e) { toast(e.message, true); } };
  const refBusy = (on, label) => { $("#fc-refadd").disabled = on; $("#fc-refup-label").textContent = label; };
  $("#fc-refup").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    refBusy(true, "Uploading…");
    try {
      const res = await fetch(`/api/factory/references/upload?name=${encodeURIComponent(f.name)}&comment=${encodeURIComponent($("#fc-refnote").value.trim())}`,
        { method: "POST", headers: { "X-Postcrew": "1", "Content-Type": "application/octet-stream" }, body: f });
      const r = await res.json(); if (!res.ok) throw new Error(r.error || "upload failed");
      $("#fc-refnote").value = ""; fcDrawRefs(r.references); toast("Reference added");
    } catch (err) { toast(err.message, true); }
    finally { refBusy(false, "Upload a video"); e.target.value = ""; }
  };
  $("#fc-refadd").onclick = async () => {
    const url = $("#fc-reflink").value.trim(); if (!url) return toast("Paste a link first", true);
    refBusy(true, "Upload a video"); $("#fc-refadd").querySelector("span:last-child").textContent = "Fetching…";
    try { const r = await post("/api/factory/references/link", { url, comment: $("#fc-refnote").value.trim() }); $("#fc-reflink").value = ""; $("#fc-refnote").value = ""; fcDrawRefs(r.references); toast("Reference added"); }
    catch (err) { toast(err.message, true); }
    finally { refBusy(false, "Upload a video"); $("#fc-refadd").querySelector("span:last-child").textContent = "Add link"; }
  };
  $("#fc-player").addEventListener("close", () => { const v = $("#fc-player video"); v.pause(); v.removeAttribute("src"); v.load(); });
  fcDraw(d);
  fcPoll();
}

VIEWS.factory = renderFactory;
