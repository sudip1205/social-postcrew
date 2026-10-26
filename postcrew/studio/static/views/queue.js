/* Queue view: copied from design/stitch/queue.html. Real data from /api/queue; actions POST /api/queue/<id>/<action>. */
"use strict";

const Q = { filter: null, search: "", sort: "date" };   // filter: null = the app chosen in the app switcher
const Q_CRITERIA = [["accuracy", "Accuracy"], ["clarity", "Clarity"], ["hook", "Hook"], ["value", "Value"], ["tone", "Tone"], ["format", "Format"]];
const qTone = v => v >= 85 ? ["text-emerald-600", "bg-emerald-500", "text-emerald-500"] : v >= 70 ? ["text-amber-600", "bg-amber-500", "text-amber-500"] : ["text-rose-600", "bg-rose-500", "text-rose-500"];
const qSlot = p => p.scheduled_at || p.date || "";
const qSlotText = p => { const s = qSlot(p); if (!s) return ""; const d = new Date(s);
  return isNaN(d) ? s : s.length > 10 ? fmtTime(s) : d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }); };
const qKind = p => p.status === "awaiting_approval" ? "awaiting" : p.status === "failed" ? "failed" : p.status === "vetoed" ? "vetoed" : "scheduled";
const qDisabled = `disabled title="Coming soon"`;

function qScorePanel(p) {
  const r = p.review;
  if (!r || typeof r.overall !== "number") return `<div class="lg:col-span-5 bg-slate-50/70 rounded-xl border border-slate-200/80 p-5 flex flex-col justify-between">
    <span class="text-xs font-bold uppercase tracking-wider text-slate-500">Quality Assurance</span>${emptyState("fact_check", "No Editor review for this post yet.")}</div>`;
  const [, , ring] = qTone(r.overall), flags = r.red_flags || [], ok = r.overall >= 80 && !flags.length;
  const bars = Q_CRITERIA.filter(([k]) => typeof r.scores?.[k] === "number").map(([k, label]) => { const v = r.scores[k], [t, bg] = qTone(v);
    return `<div><div class="flex justify-between text-[11px] mb-0.5"><span class="text-slate-600 font-medium">${label}</span><span class="font-bold ${t}">${v}%</span></div>
      <div class="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden"><div class="h-full ${bg} rounded-full" style="width: ${v}%"></div></div></div>`; }).join("");
  return `<div class="lg:col-span-5 bg-slate-50/70 rounded-xl border border-slate-200/80 p-5 flex flex-col justify-between"><div>
    <div class="flex items-center justify-between pb-3 border-b border-slate-200">
      <span class="text-xs font-bold uppercase tracking-wider text-slate-500">Quality Assurance</span>
      ${ok ? `<span class="text-[11px] px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded-full font-semibold flex items-center gap-1">${icon("check_circle", "text-[13px] text-emerald-600")}Passed Quality Gates</span>`
        : `<span class="text-[11px] px-2 py-0.5 bg-amber-100 text-amber-800 rounded-full font-semibold flex items-center gap-1">${icon("warning", "text-[13px] text-amber-600")}Needs a look</span>`}</div>
    <div class="flex items-center gap-4 my-4">
      <div class="relative w-16 h-16 flex items-center justify-center shrink-0">
        <svg class="w-full h-full -rotate-90" viewbox="0 0 36 36">
          <path class="text-slate-200" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" stroke-width="3.5"></path>
          <path class="${ring}" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" stroke-dasharray="${r.overall}, 100" stroke-linecap="round" stroke-width="3.5"></path>
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center"><span class="text-sm font-extrabold text-slate-900 leading-none">${r.overall}</span><span class="text-[9px] text-slate-500 font-medium">/100</span></div>
      </div>
      <div><h3 class="text-xs font-bold text-slate-900">${tip("Editor", "The Editor agent scores every post on six criteria and keeps the lowest result.")} score</h3>
        <p class="text-[11px] text-slate-500 leading-snug mt-0.5">${flags.length ? esc(flags.join("; ")) : "No red flags raised."}</p></div>
    </div>
    <div class="space-y-2 pt-2">${bars}</div></div>
    <p class="text-[10px] text-slate-400 mt-3 pt-2 border-t border-slate-200">Evaluated by <strong class="text-indigo-600">the Editor</strong>.</p></div>`;
}

function qMedia(p) {
  if (!p.media) return "";
  if (p.media_kind === "video") return `<div class="rounded-lg border border-slate-200 bg-white overflow-hidden"><video class="w-full max-h-80 bg-slate-900" src="/${esc(p.media)}" ${p.poster_image ? `poster="/${esc(p.poster_image)}"` : ""} controls muted playsinline preload="metadata"></video></div>`;
  return `<div class="rounded-lg border border-slate-200 bg-white overflow-hidden"><img class="w-full max-h-80 object-cover" src="/${esc(p.media)}" alt=""></div>`;
}

const Q_SCENE_COLORS = ["bg-indigo-500", "bg-sky-500", "bg-violet-600", "bg-emerald-500", "bg-orange-500", "bg-teal-500"];
const qMediaUrl = path => path ? "/media/" + String(path).replace(/^\/?media\//, "") : "";
const qDur = s => `${Math.floor((+s || 0) / 60)}:${String(Math.round(+s || 0) % 60).padStart(2, "0")}`;

function qYoutubeBody(p) {
  const y = p.youtube || {}, long = y.format === "long", src = y.source || {}, scenes = y.scenes || [];
  const total = scenes.reduce((a, s) => a + (+s.seconds || 0), 0) || +y.seconds || 0;
  const title = y.title || p.topic || "", desc = y.description || p.text || "", tags = y.tags || [];
  const frame = long ? "aspect-video w-full" : "w-28 sm:w-full aspect-[9/16]";
  const video = p.media ? `<video class="absolute inset-0 w-full h-full object-cover bg-slate-900" src="${esc(qMediaUrl(p.media))}${p.youtube?.format === "short" ? "#t=0.1" : ""}" ${p.poster_image && p.youtube?.format !== "short" ? `poster="${esc(qMediaUrl(p.poster_image))}"` : ""} controls preload="metadata" playsinline></video>`
    : `<div class="absolute inset-0 flex items-center justify-center text-slate-400">${icon("play_arrow", "text-[28px]")}</div>`;
  let t0 = 0;
  const bar = scenes.map((sc, i) => { const from = t0; t0 += +sc.seconds || 0;
    return `<div class="${Q_SCENE_COLORS[i % Q_SCENE_COLORS.length]} rounded-sm flex items-center justify-center truncate px-0.5" style="flex: ${Math.max(+sc.seconds || 1, 1)} 1 0" title="${esc(`${String(i + 1).padStart(2, "0")} [${Math.round(from)}-${Math.round(t0)}s] On screen: ${sc.on_screen || ""} / Narration: ${sc.narration || ""}`)}">${String(i + 1).padStart(2, "0")}</div>`; }).join("");
  const badgeCls = "text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 font-medium";
  const own = [["voice", "Your voice"], ["video", "Your video"], ["script", "Your script"]].filter(([k]) => src[k] === "own").map(([, l]) => `<span class="${badgeCls}">${l}</span>`).join("");
  const voice = y.voice && y.voice !== "none" ? `<span class="text-xs font-bold text-slate-900">${esc(y.voice)}</span><span class="${badgeCls}">${src.voice === "own" ? "Your voice" : "AI Voice"}</span>` : `<span class="text-xs font-bold text-slate-900">No voice-over</span>`;
  const overrides = [["video_call", "Use my own video", "video"], ["mic", "Use my own voice", "voice"], ["description", "Use my own script", "script"]].map(([ic, t, k]) =>
    `<button class="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-slate-700 bg-white border border-slate-200 rounded hover:bg-slate-100 active:scale-95 transition-all" type="button" data-upload="${k}" data-id="${esc(p.id)}">${icon(ic, "text-[14px] text-slate-500")}<span>${t}</span></button>`).join("");
  const field = "w-full px-2.5 py-1.5 text-xs bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-violet-500";
  return `<div class="lg:col-span-7 flex flex-col justify-between space-y-4" data-yt="${esc(p.id)}"><div>
    <div class="flex items-center justify-between mb-2"><span class="text-xs font-bold uppercase tracking-wider text-slate-400">${long ? "Video" : "Short Video"} &amp; Voiceover Synthesis</span>
      <span class="flex items-center gap-3"><span class="text-xs font-semibold text-slate-500">Duration: ${Math.round(+y.seconds || total)}s</span>
      <button class="text-xs text-violet-600 font-medium inline-flex items-center gap-1 hover:underline" type="button" data-yedit="${esc(p.id)}">${icon("edit", "text-[14px]")}Inline edit</button></span></div>
    <div data-yview><h2 class="text-base font-bold text-slate-900 mb-1">${esc(title)}</h2>
      <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-line mb-2">${esc(desc)}</p>
      ${tags.length ? `<div class="flex flex-wrap gap-1 mb-3">${tags.map(t => `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">#${esc(t)}</span>`).join("")}</div>` : ""}</div>
    <div class="hidden flex-col gap-2 mb-3" data-yform>
      <input class="${field}" data-yf="title" maxlength="100" value="${esc(title)}" placeholder="Title">
      <textarea class="${field}" data-yf="description" rows="5" placeholder="Description">${esc(desc)}</textarea>
      <input class="${field}" data-yf="tags" value="${esc(tags.join(", "))}" placeholder="Tags, comma separated">
      <div class="flex gap-2"><button class="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold" type="button" data-ysave="${esc(p.id)}">${icon("save", "text-[14px]")}<span>Save</span></button>
        <button class="inline-flex items-center px-3 py-1 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-100" type="button" data-ycancel="${esc(p.id)}">Cancel</button></div></div>
    <div class="grid grid-cols-1 sm:grid-cols-12 gap-4 bg-slate-50/70 p-4 rounded-xl border border-slate-200">
      <div class="${long ? "sm:col-span-6" : "sm:col-span-4"} flex flex-col items-center">
        <div class="relative ${frame} rounded-lg bg-slate-900 border border-slate-800 overflow-hidden shadow-md">${video}
          <div class="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-black/60 text-[10px] text-white font-mono font-medium pointer-events-none">${qDur(y.seconds || total)}</div></div></div>
      <div class="${long ? "sm:col-span-6" : "sm:col-span-8"} flex flex-col justify-between space-y-3">
        <div class="p-2.5 rounded-lg border border-slate-200 bg-white flex items-center gap-2">
          <div class="w-7 h-7 rounded-full bg-indigo-50 border border-indigo-200 flex items-center justify-center text-indigo-700">${icon("record_voice_over", "text-[16px]")}</div>
          <div class="flex flex-wrap items-center gap-1.5">${voice}${own}</div></div>
        <div><div class="flex items-center justify-between text-[11px] text-slate-500 mb-1"><span class="font-semibold text-slate-700">Scene Progression Timeline</span><span class="font-mono">${scenes.length} Scenes (Total ${Math.round(total)}s)</span></div>
          <div class="flex gap-1 h-6 rounded-md overflow-hidden bg-slate-200 p-0.5 text-[10px] font-bold text-white text-center">${bar}</div>
          <div class="flex justify-between text-[9px] text-slate-400 font-mono mt-1"><span>0s</span><span>${Math.round(total)}s</span></div></div>
        <div><p class="text-[11px] font-medium text-slate-600 mb-1.5">Asset Overrides (Bypass Pod Output):</p><div class="flex flex-wrap gap-1.5">${overrides}</div></div>
        ${y.url ? `<a class="inline-flex items-center gap-1 text-xs font-medium text-violet-600 hover:underline" href="${esc(y.url)}" target="_blank" rel="noopener">${icon("open_in_new", "text-[14px]")}<span>Watch on YouTube</span></a>` : ""}</div></div></div>
    <p class="text-[11px] text-slate-400 flex items-center gap-1.5">${icon("info", "text-[15px] text-sky-500")}<span>Audio and background visuals generated autonomously. You can replace any layer prior to veto expiry.</span></p></div>`;
}

function qBody(p) {
  if (p.platform === "youtube") return qYoutubeBody(p);
  const yt = p.platform === "youtube";
  const fc = p.first_comment ? `<p class="text-[11px] text-slate-500"><span class="font-semibold text-slate-600">First comment:</span> ${esc(p.first_comment)}</p>` : "";
  const overrides = yt ? `<div><p class="text-[11px] font-medium text-slate-600 mb-1.5">Asset Overrides (Bypass Pod Output):</p><div class="flex flex-wrap gap-1.5">${
    [["video_call", "Use my own video", "video"], ["mic", "Use my own voice", "voice"], ["description", "Use my own script", "script"]].map(([ic, t, k]) =>
      `<button class="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-slate-700 bg-white border border-slate-200 rounded hover:bg-slate-100 active:scale-95 transition-all" type="button" data-upload="${k}" data-id="${esc(p.id)}">${icon(ic, "text-[14px] text-slate-500")}<span>${t}</span></button>`).join("")}</div></div>` : "";
  return `<div class="lg:col-span-7 flex flex-col justify-between space-y-4"><div>
    <div class="flex items-center justify-between mb-2"><span class="text-xs font-bold uppercase tracking-wider text-slate-400">${yt ? "Short Video &amp; Voiceover Synthesis" : "Post Hook &amp; Narrative"}</span>
      <button class="text-xs text-violet-600 font-medium inline-flex items-center gap-1 hover:underline" type="button" data-q="edit" data-id="${esc(p.id)}">${icon("edit", "text-[14px]")}Inline edit</button></div>
    ${p.topic ? `<h2 class="text-base font-bold text-slate-900 mb-3">${esc(p.topic)}</h2>` : ""}
    <div class="p-4 rounded-xl border border-slate-200 bg-slate-50/50 space-y-3">
      <div class="text-xs text-slate-700 leading-relaxed whitespace-pre-line">${fmtPost(p.text || "")}</div>${qMedia(p)}${fc}
      ${p.error ? `<p class="text-[11px] text-rose-700 flex items-center gap-1">${icon("error", "text-[14px] text-rose-600")}${esc(p.error)}</p>` : ""}</div>
    ${overrides ? `<div class="mt-4">${overrides}</div>` : ""}</div>
    <p class="text-[11px] text-slate-400 flex items-center gap-1.5">${icon("psychology", "text-[15px] text-teal-600")}<span>${esc(p.category || "")} · ${(p.text || "").length} chars</span></p></div>`;
}

function qCard(p) {
  const app = appOf(p.platform || "linkedin"), yt = p.platform === "youtube", k = qKind(p);
  const status = k === "awaiting" ? `<div class="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 text-xs font-medium">${icon("schedule", "text-[16px] text-amber-600")}<span>Awaiting approval</span></div>` : chip(p.status);
  const act = (q, ic, label, cls, icCls = "") => `<button class="${cls}" type="button" data-q="${q}" data-id="${esc(p.id)}">${icon(ic, icCls)}<span>${label}</span></button>`;
  const left = p.status === "vetoed"
    ? act("restore", "undo", "Restore", "inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs active:scale-95 transition-all", "text-[17px]")
      + act("delete", "cancel", "Delete", "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-700 font-medium text-xs active:scale-95 transition-all", "text-[17px] text-rose-600")
    : (p.status === "awaiting_approval" ? act("approve", "check_circle", "Approve", "inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs active:scale-95 transition-all", "text-[17px]") : "")
      + act("edit", "edit_note", "Edit draft", "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 font-medium text-xs active:scale-95 transition-all", "text-[17px] text-slate-500")
      + act("veto", "cancel", "Veto", "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-700 font-medium text-xs active:scale-95 transition-all", "text-[17px] text-rose-600");
  const right = p.status === "vetoed" ? "" : act("publish_now", "send", "Publish now", "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-slate-700 hover:bg-slate-200/70 text-xs font-medium transition-colors", "text-[16px] text-slate-500")
    + `<button class="p-1.5 rounded-lg hover:bg-slate-200/70 text-slate-500 transition-colors" type="button" ${qDisabled}>${icon("more_vert", "text-[18px]")}</button>`;
  return `<article class="bg-white rounded-xl border border-slate-200 border-l-[6px] ${app.border} shadow-sm hover:shadow-md transition-shadow duration-200 overflow-hidden" id="post-${esc(p.id)}">
    <div class="px-6 py-4 border-b border-slate-100 flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r ${yt ? "from-red-50/20" : "from-blue-50/25"} to-white">
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-1.5 px-2.5 py-1 rounded ${app.soft} font-semibold text-xs border">
          ${yt ? icon("play_circle", `text-[15px] ${app.text}`) : `<span class="font-bold">in</span>`}<span>${esc(app.label)}</span></div>
        <div class="flex items-center gap-1 text-xs text-slate-500">${icon("schedule", "text-[16px] text-slate-400")}<span>Scheduled slot:</span><span class="font-semibold text-slate-700">${esc(qSlotText(p))}</span></div>
      </div>${status}</div>
    <div class="p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">${qBody(p)}${qScorePanel(p)}</div>
    <div class="px-6 py-3 bg-slate-50 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2">${left}</div><div class="flex items-center gap-2">${right}</div></div></article>`;
}

function qChip(id, label, count, inner, cls, active, countCls) {
  const on = "bg-slate-900 text-white shadow-sm", cnt = active ? "bg-slate-700 text-white" : countCls;
  return `<button class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs ${active ? "font-semibold " + on : cls}" type="button" data-f="${id}">${active ? "" : inner}<span>${label}</span><span class="${cnt} px-1.5 rounded-full text-[11px]">${count}</span></button>`;
}

function qHistory(history, cats) {
  const rows = history.map((h, i) => [h, i]).sort((a, b) => (b[0].date || "").localeCompare(a[0].date || ""));
  return `<section class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 flex flex-col gap-4" id="published">
    <div><h2 class="font-headline font-bold text-lg text-slate-900">Published</h2>
    <p class="text-sm text-slate-500 mt-0.5">Every topic here counts as already posted, so the crew never repeats it. Add posts you published yourself; remove one to allow its topic again. Removing only changes this list, never the platform.</p></div>
    <div class="flex flex-wrap items-center gap-2">
      <input type="date" id="h-date" value="${new Date().toISOString().slice(0, 10)}" class="px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg">
      <input id="h-topic" placeholder="Topic of a post you published, e.g. Kafka consumer groups" maxlength="150" class="flex-1 min-w-[240px] px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-violet-500 focus:bg-white">
      <select id="h-cat" class="px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"><option value="">Topic type (optional)</option>${Object.entries(cats).map(([id, k]) => `<option value="${esc(id)}">${esc(k.label)}</option>`).join("")}</select>
      ${button("primary", "add", "Add to published", `id="h-add"`)}</div>
    ${rows.length ? `<div class="overflow-x-auto"><table class="w-full text-sm text-left"><thead class="text-xs text-slate-500 uppercase tracking-wider"><tr><th class="py-2 pr-3">Date</th><th class="py-2 pr-3">Topic</th><th class="py-2 pr-3">Topic type</th><th class="py-2 pr-3">Post</th><th></th></tr></thead><tbody class="divide-y divide-slate-100">${
      rows.map(([h, i]) => `<tr><td class="py-2 pr-3 whitespace-nowrap text-slate-600">${esc(h.date)}</td><td class="py-2 pr-3 text-slate-900">${esc(h.topic)}</td>
        <td class="py-2 pr-3 text-xs text-slate-500">${esc(cats[h.category]?.label || h.category || "")}</td>
        <td class="py-2 pr-3 text-xs font-mono text-slate-500">${h.urn ? esc(h.urn) : `<span class="text-slate-400">${h.added_by_hand ? "added by you" : h.imported ? "imported" : ""}</span>`}${
          h.comment_status === "added" ? `<div class="text-emerald-700">first comment added</div>`
          : h.comment_status === "failed" ? `<div class="text-rose-700" title="${esc(h.comment_error || "")}">first comment failed${(h.comment_tries || 0) < 3 ? " - will retry" : " - add it by hand"}</div>` : ""}</td>
        <td class="py-2 text-right"><button class="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-rose-700 bg-rose-50 border border-rose-200 rounded hover:bg-rose-100" type="button" data-hrm="${i}">${icon("delete", "text-[14px] text-rose-600")}<span>Remove</span></button></td></tr>`).join("")}</tbody></table></div>`
      : emptyState("history", "Nothing published yet.")}</section>`;
}

async function renderQueue() {
  const [all, { config }] = await Promise.all([api("/api/queue"), api("/api/config")]);
  const queue = all.queue, history = all.history.filter(mine), cats = catsOf(config, S.platform);
  const plat = p => p.platform || "linkedin", f = Q.filter || S.platform;
  const count = fn => queue.filter(fn).length;
  const filters = { all: () => true, linkedin: p => plat(p) === "linkedin", youtube: p => plat(p) === "youtube",
    awaiting: p => p.status === "awaiting_approval", scheduled: p => ["queued", "scheduled", "approved"].includes(p.status), failed: p => p.status === "failed" };
  const q = Q.search.trim().toLowerCase();
  let list = queue.filter(filters[f] || filters.all).filter(p => !q || `${p.topic} ${p.text} ${p.category}`.toLowerCase().includes(q));
  list.sort(Q.sort === "score" ? (a, b) => (b.review?.overall ?? -1) - (a.review?.overall ?? -1)
    : Q.sort === "platform" ? (a, b) => plat(a).localeCompare(plat(b)) || qSlot(a).localeCompare(qSlot(b)) : (a, b) => qSlot(a).localeCompare(qSlot(b)));
  const live = list.filter(p => p.status !== "vetoed"), vetoed = list.filter(p => p.status === "vetoed");
  const nAwait = count(filters.awaiting), idle = "font-medium text-slate-600 hover:bg-slate-100", gray = "bg-slate-100 text-slate-600";
  const chips = qChip("all", "All", queue.length, "", idle + " hover:text-slate-900", f === "all", gray)
    + qChip("linkedin", "LinkedIn", count(filters.linkedin), `<span class="w-2 h-2 rounded-full ${APPS.linkedin.dot}"></span>`, idle + " hover:text-slate-900 transition-colors", f === "linkedin", gray)
    + qChip("youtube", "YouTube", count(filters.youtube), `<span class="w-2 h-2 rounded-full ${APPS.youtube.dot}"></span>`, idle + " hover:text-slate-900 transition-colors", f === "youtube", gray)
    + `<div class="w-px h-4 bg-slate-200 mx-1"></div>`
    + qChip("awaiting", "Awaiting approval", nAwait, icon("schedule", "text-[14px] text-amber-600"), "font-medium text-amber-700 bg-amber-50/70 border border-amber-200/60 hover:bg-amber-100 transition-colors", f === "awaiting", "bg-amber-200 text-amber-800 font-bold")
    + qChip("scheduled", "Scheduled", count(filters.scheduled), icon("check_circle", "text-[14px] text-emerald-600"), idle + " transition-colors", f === "scheduled", gray)
    + qChip("failed", "Failed", count(filters.failed), icon("error", "text-[14px] text-rose-600"), idle + " transition-colors", f === "failed", "bg-rose-100 text-rose-700 font-semibold");
  const ghost = (ic, t, cls, icCls) => `<button class="inline-flex items-center gap-1.5 ${cls}" type="button" ${qDisabled}>${icon(ic, icCls)}<span>${t}</span></button>`;
  $("#view").innerHTML = `<div class="flex flex-col gap-6">
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5"><div>
      <div class="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1"><span>Production Studio</span>${icon("chevron_right", "text-[14px]")}<span class="text-violet-600 font-semibold">Review Queue</span></div>
      <h1 class="font-headline font-bold text-2xl text-slate-900 tracking-tight flex items-center gap-3"><span>Review &amp; Publish Queue</span>
        ${nAwait ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">${icon("hourglass_top", "text-[14px] text-amber-600")}<span>${nAwait} Awaiting approval</span></span>` : ""}</h1>
      <p class="text-sm text-slate-600 mt-1">Inspect agent-synthesized drafts, inspect quality scores, override assets, or approve autonomous broadcasts.</p></div>
      <div class="flex items-center flex-wrap gap-2.5">
        <button class="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 shadow-sm active:scale-95 transition-all" type="button" id="q-refresh">${icon("refresh", "text-[18px] text-slate-500")}<span>Refresh</span></button>
        ${ghost("pause_circle", "Pause Auto-Publish", "px-3 py-2 text-xs font-medium text-amber-800 bg-amber-50 border border-amber-200 rounded-lg disabled:opacity-50", "text-[18px] text-amber-600")}
        ${ghost("done_all", `Bulk Approve (${nAwait})`, "px-3.5 py-2 text-xs font-semibold text-white bg-emerald-600 rounded-lg shadow-sm disabled:opacity-50", "text-[18px]")}</div></div>
    <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-white p-2.5 rounded-xl border border-slate-200 shadow-sm">
      <div class="flex items-center gap-1.5 overflow-x-auto custom-scrollbar pb-1 lg:pb-0">${chips}</div>
      <div class="flex items-center gap-2.5 self-end lg:self-auto">
        <div class="relative">${icon("search", "text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 text-[18px]")}
          <input id="q-search" value="${esc(Q.search)}" class="w-48 sm:w-56 pl-8 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-violet-500 focus:bg-white text-slate-800 placeholder-slate-400" placeholder="Search queue..." type="text"/></div>
        <div class="relative"><select id="q-sort" class="appearance-none bg-slate-50 border border-slate-200 text-slate-700 text-xs font-medium rounded-lg pl-2.5 pr-7 py-1.5 hover:bg-slate-100 focus:outline-none focus:ring-1 focus:ring-violet-500 cursor-pointer">
          ${[["date", "Publish date (soonest)"], ["score", "Quality Score (highest)"], ["platform", "Platform (grouped)"]].map(([v, t]) => `<option value="${v}"${Q.sort === v ? " selected" : ""}>${t}</option>`).join("")}</select>
          ${icon("expand_more", "absolute right-2 top-1/2 -translate-y-1/2 text-[16px] text-slate-400 pointer-events-none")}</div>
        <div class="flex items-center p-0.5 bg-slate-100 rounded-lg border border-slate-200">
          <button class="p-1 rounded bg-white text-slate-800" title="Cards View" type="button">${icon("view_agenda", "text-[18px]")}</button>
          <button class="p-1 rounded text-slate-500" type="button" disabled title="Coming soon">${icon("table_rows", "text-[18px]")}</button></div></div></div>
    <div class="space-y-6">${live.map(qCard).join("") || card(emptyState("inbox", "The queue is empty."))}</div>
    ${vetoed.length ? `<h2 class="font-headline font-bold text-lg text-slate-900">Vetoed</h2><div class="space-y-6">${vetoed.map(qCard).join("")}</div>` : ""}
    ${qHistory(history, cats)}</div>`;

  $("#q-refresh").onclick = renderQueue;
  document.querySelectorAll("[data-f]").forEach(b => b.onclick = () => { Q.filter = b.dataset.f; renderQueue(); });
  $("#q-sort").onchange = e => { Q.sort = e.target.value; renderQueue(); };
  $("#q-search").onkeydown = e => { if (e.key === "Enter") { Q.search = e.target.value; renderQueue(); } };
  $("#q-search").onchange = e => { Q.search = e.target.value; renderQueue(); };
  document.querySelectorAll("[data-q]").forEach(b => b.onclick = () => queueAction(b.dataset.id, b.dataset.q, b));
  document.querySelectorAll("[data-yedit]").forEach(b => b.onclick = () => ytToggle(b.dataset.yedit, true));
  document.querySelectorAll("[data-ycancel]").forEach(b => b.onclick = () => ytToggle(b.dataset.ycancel, false));
  document.querySelectorAll("[data-ysave]").forEach(b => b.onclick = async () => {
    const c = document.querySelector(`[data-yt="${CSS.escape(b.dataset.ysave)}"]`), v = k => c.querySelector(`[data-yf=${k}]`).value;
    try { await post(`/api/queue/${encodeURIComponent(b.dataset.ysave)}/edit`, { title: v("title").trim(), description: v("description"), tags: v("tags").split(",").map(t => t.trim().replace(/^#/, "")).filter(Boolean) });
      toast("Saved"); renderQueue(); } catch (e) { toast(e.message, true); }
  });
  document.querySelectorAll("[data-upload]").forEach(b => b.onclick = () => openUploadDialog(queue.find(x => x.id === b.dataset.id), b.dataset.upload));
  $("#h-add").onclick = async () => {
    const topic = $("#h-topic").value.trim(); if (!topic) return $("#h-topic").focus();
    try { await post("/api/history", { date: $("#h-date").value, topic, category: $("#h-cat").value, platform: S.platform }); toast("Added to published"); renderQueue(); }
    catch (e) { toast(e.message, true); }
  };
  $("#h-topic").onkeydown = e => { if (e.key === "Enter") $("#h-add").click(); };
  document.querySelectorAll("[data-hrm]").forEach(b => b.onclick = async () => {
    const h = history[+b.dataset.hrm];
    if (!confirm(`Remove "${h.topic}" from the published list? The crew may then write about it again.${h.urn ? " The post stays published." : ""}`)) return;
    try { await post("/api/history/remove", { id: h.id, date: h.date, topic: h.topic }); toast("Removed"); renderQueue(); }
    catch (e) { toast(e.message, true); }
  });
}

function ytToggle(id, on) {
  const c = document.querySelector(`[data-yt="${CSS.escape(id)}"]`); if (!c) return;
  c.querySelector("[data-yview]").classList.toggle("hidden", on);
  const f = c.querySelector("[data-yform]"); f.classList.toggle("hidden", !on); f.classList.toggle("flex", on);
  if (on) f.querySelector("input").focus();
}

async function queueAction(id, action, btn) {
  if (action === "edit") { const yc = document.querySelector(`[data-yt="${CSS.escape(id)}"]`); return yc ? ytToggle(id, true) : editPost(id); }
  if (action === "publish_now" && !confirm("Publish this post now?")) return;
  if (action === "delete" && !confirm("Delete this post from the queue?")) return;
  btn.disabled = true;
  try { const r = await post(`/api/queue/${encodeURIComponent(id)}/${action}`); toast(action === "publish_now" ? `Publish: ${r.status}` : "Done"); refreshOverview(); }
  catch (e) { toast(e.message, true); }
  renderQueue();
}

// Edit dialog: text, first comment, date (same fields and endpoint as before)
async function editPost(id) {
  const { queue } = await api("/api/queue"); const p = queue.find(x => x.id === id); if (!p) return renderQueue();
  const dlg = document.createElement("div");
  dlg.className = "fixed inset-0 z-50 flex items-start justify-center pt-16 px-4 bg-slate-900/40 backdrop-blur-md";
  const field = "w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-violet-500 focus:bg-white";
  dlg.innerHTML = `<div class="w-full max-w-2xl bg-white rounded-xl shadow-2xl flex flex-col overflow-hidden">
    <div class="px-6 pt-6 pb-4 flex items-center justify-between"><h2 class="font-headline font-bold text-xl text-slate-900 flex items-center gap-2">${icon("edit_note", "text-slate-700")}Edit draft</h2>
      <button class="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100" type="button" aria-label="Close dialog" id="e-x">${icon("close", "text-[22px]")}</button></div>
    <div class="px-6 pb-4 flex flex-col gap-3">
      <label class="text-xs font-semibold text-slate-700 flex flex-col gap-1">Text<textarea id="e-text" rows="10" class="${field}">${esc(p.text)}</textarea></label>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label class="text-xs font-semibold text-slate-700 flex flex-col gap-1">Date<input type="date" id="e-date" value="${esc(p.date)}" class="${field}"></label>
        <label class="text-xs font-semibold text-slate-700 flex flex-col gap-1">First comment<input id="e-fc" value="${esc(p.first_comment || "")}" class="${field}"></label></div></div>
    <div class="px-6 py-4 bg-slate-50 flex items-center justify-between"><span class="text-xs text-slate-500" id="e-count">${p.text.length} / 3000</span>
      <div class="flex items-center gap-2"><button class="inline-flex items-center px-4 py-2 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-100" type="button" id="e-cancel">Cancel</button>
      ${button("primary", "save", "Save", `id="e-save"`)}</div></div></div>`;
  document.body.appendChild(dlg);
  const close = () => dlg.remove();
  $("#e-text", dlg).oninput = e => $("#e-count", dlg).textContent = `${e.target.value.length} / 3000`;
  $("#e-cancel", dlg).onclick = close; $("#e-x", dlg).onclick = close;
  $("#e-save", dlg).onclick = async () => {
    try { await post(`/api/queue/${encodeURIComponent(id)}/edit`, { text: $("#e-text", dlg).value, date: $("#e-date", dlg).value, first_comment: $("#e-fc", dlg).value });
      toast("Saved"); close(); renderQueue(); } catch (e) { toast(e.message, true); }
  };
}

VIEWS.queue = renderQueue;
