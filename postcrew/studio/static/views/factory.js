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
  return `<div class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
    <video class="w-full aspect-[9/16] bg-slate-900" controls preload="none" ${v.thumb ? `poster="/factory-out/${encodeURIComponent(v.thumb)}"` : ""} src="/factory-out/${encodeURIComponent(v.file)}"></video>
    <div class="p-3 space-y-2">
      <div class="text-xs font-semibold text-slate-900 line-clamp-2" title="${esc(v.title)}">${esc(v.title)}</div>
      <div class="text-[11px] text-slate-500">${esc(ago(v.made))} · ${v.mb} MB</div>
      ${v.has_meta ? `<div class="flex items-center gap-1.5">
        <input type="date" class="flex-1 min-w-0 text-xs border border-slate-300 rounded-md px-2 py-1" value="${today}" min="${today}" data-fc-date="${esc(v.slug)}">
        <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-100 hover:bg-violet-200 text-violet-800 text-xs font-semibold" data-fc-queue="${esc(v.slug)}">${icon("playlist_add", "text-sm")}<span>Queue</span></button></div>`
        : `<div class="text-[11px] text-slate-400">${tip("No youtube.json", "Ask Claude to write the title, description and tags for this episode, then it can be queued.")}</div>`}
    </div></div>`;
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

function fcDraw(d) {
  $("#fc-log").innerHTML = fcMessages(d);
  if ((d.messages || []).length !== fcSeen) { $("#fc-log").scrollTop = $("#fc-log").scrollHeight; fcSeen = (d.messages || []).length; }
  $("#fc-send").disabled = d.busy;
  $("#fc-stop").classList.toggle("hidden", !d.busy);
  $("#fc-videos").innerHTML = (d.videos || []).length ? d.videos.map(fcVideo).join("") : emptyState("movie", "No videos yet. Ask Claude for a Short.");
  $("#fc-skill").innerHTML = (d.skill || []).map(f => `<li class="flex items-center justify-between gap-2 py-1"><span class="font-mono text-[11px] text-slate-700 truncate">${esc(f.path)}</span><span class="text-[11px] text-slate-400 whitespace-nowrap">${esc(ago(f.changed))}</span></li>`).join("");
  document.querySelectorAll("[data-fc-example]").forEach(b => b.onclick = () => { $("#fc-text").value = b.dataset.fcExample; $("#fc-text").focus(); });
  document.querySelectorAll("[data-fc-queue]").forEach(b => b.onclick = async () => {
    const slug = b.dataset.fcQueue, date = document.querySelector(`[data-fc-date="${CSS.escape(slug)}"]`).value;
    try { await post("/api/factory/queue", { slug, date }); toast("Queued for YouTube: approve or schedule it in the Queue"); } catch (e) { toast(e.message, true); }
  });
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
          <div id="fc-videos" class="grid grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto"></div>
        </section>
        <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-2">
          <div class="flex items-center gap-2"><div class="w-7 h-7 rounded-lg bg-sky-100 text-sky-700 flex items-center justify-center">${icon("school", "text-base")}</div>
            <h2 class="text-lg font-bold font-headline text-slate-900">Skill</h2></div>
          <p class="text-xs text-slate-500">The rules every video follows, and when each file last changed.</p>
          <ul id="fc-skill" class="divide-y divide-slate-100"></ul>
        </section>
      </aside>
    </div>`;
  const send = async () => {
    const text = $("#fc-text").value.trim(); if (!text) return;
    try { fcDraw(await post("/api/factory/send", { text })); $("#fc-text").value = ""; fcPoll(); } catch (e) { toast(e.message, true); }
  };
  $("#fc-send").onclick = send;
  $("#fc-text").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("#fc-stop").onclick = async () => { try { fcDraw(await post("/api/factory/stop")); } catch (e) { toast(e.message, true); } };
  $("#fc-new").onclick = async () => { try { fcDraw(await post("/api/factory/reset")); } catch (e) { toast(e.message, true); } };
  fcDraw(d);
  fcPoll();
}

VIEWS.factory = renderFactory;
