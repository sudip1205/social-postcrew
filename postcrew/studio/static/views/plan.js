/* Plan: the Weekly Editorial Board (design/stitch/plan-weekly-editorial-board). Seven day columns plus the Ideas Bank. */
"use strict";

const PLAN_BRIEF_TEMPLATE = `Context: why this matters and what readers get wrong today (2-4 sentences)
Example: a concrete real-world scenario or public incident the post is built around
Example type: scenario
Takeaway: what the reader can do after reading
Pattern: problem-story
Tone: plain, specific, no hype
Must include:
- one thing the post has to say
Avoid:
- one thing to leave out
Question: a specific closing question for practitioners
Visual: system-flow
Systems:
- client | Browser | browser | the user's app
- api | API gateway | api-gateway | checks every call
- auth | Auth server | idp | issues tokens
Flow:
client > api | GET /orders | request | GET /orders | The browser calls the API
api > auth | Validate token | token | Authorization: Bearer ... | The gateway asks the auth server
auth > api | Token valid | response | active=true | The auth server confirms
`;

// category pill colours, cycled per category (classes copied from the Stitch day cards)
const PLAN_CAT_PILLS = [
  "bg-indigo-50 text-indigo-700 border-indigo-100", "bg-teal-50 text-teal-700 border-teal-100",
  "bg-amber-50 text-amber-800 border-amber-200", "bg-emerald-50 text-emerald-700 border-emerald-100",
  "bg-cyan-50 text-cyan-700 border-cyan-100",
];

async function renderPlan() {
  const [d, cfg] = await Promise.all([api(`/api/plan?platform=${encodeURIComponent(S.platform)}`), S.config ? Promise.resolve(S.config) : api("/api/config").catch(() => null)]);
  S.dirty = false;
  const app = appOf(S.platform);
  const fmtDay = iso => new Date(iso + "T12:00").toLocaleDateString([], { month: "short", day: "numeric" });
  const fmtFull = iso => new Date(iso + "T12:00").toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  const shortDay = r => `${r.weekday.slice(0, 3)} ${new Date(r.date + "T12:00").getDate()}`;
  const catIds = [...new Set(d.days.map(r => r.category).filter(Boolean))];
  const pillOf = id => PLAN_CAT_PILLS[Math.max(0, catIds.indexOf(id)) % PLAN_CAT_PILLS.length];
  const src = { planner: "Chosen by the Planner", manual: "Set by you", auto: "Chosen automatically" };
  const isOpen = r => r.category && !r.written && !r.past;      // can be edited
  const planned = d.days.filter(r => r.category && (r.written || r.entry));
  const withPost = d.days.filter(r => r.category);
  const openDays = d.days.filter(r => isOpen(r) && !r.entry);

  const dayChip = (cls, ic, icCls, text) => `<span class="text-[11px] font-semibold ${cls} px-2 py-0.5 rounded-full flex items-center gap-1">${icon(ic, `text-[13px] ${icCls}`)}<span>${esc(text)}</span></span>`;
  const statusPill = r => {
    if (r.written) return chip(r.written.status, undefined, "sm");
    if (r.entry) return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-semibold border border-blue-200">${icon("event", "text-[12px] text-blue-600")}<span>Planned</span></span>`;
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 text-[10px] font-semibold border border-amber-200">${icon("radio_button_unchecked", "text-[12px] text-amber-600")}<span>Open</span></span>`;
  };
  const header = r => {
    let c;
    if (!r.category) c = dayChip("text-slate-500 bg-slate-100 border border-slate-200", "nightlight", "text-slate-400", "Rest day");
    else if (r.written) c = dayChip("text-emerald-700 bg-emerald-50 border border-emerald-200", "check_circle", "text-emerald-600", "1 item");
    else if (r.entry) c = dayChip("text-blue-700 bg-blue-50 border border-blue-200", "calendar_today", "text-blue-600", "1 item");
    else if (r.past) c = dayChip("text-slate-500 bg-slate-100 border border-slate-200", "history", "text-slate-400", "Past");
    else c = dayChip("text-amber-700 bg-amber-50 border border-amber-200", "radio_button_unchecked", "text-amber-600", "Open slot");
    return `<div class="flex items-center justify-between pb-2 border-b border-slate-200"><div>
      <div class="font-headline font-bold text-sm text-slate-900">${esc(shortDay(r))}</div>
      <div class="text-[11px] text-slate-500 font-medium">${esc(fmtFull(r.date))}${r.date === d.today ? " · today" : ""}</div></div>${c}</div>`;
  };
  const catPill = r => `<div class="flex flex-wrap items-center gap-1"><span class="inline-block px-2 py-0.5 rounded text-[10px] font-semibold border ${pillOf(r.category)}">${esc(r.label || r.category)}</span>${fmtChip(r)}</div>`;
  const appPill = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md ${app.soft} text-[10px] font-bold border">${appBadge(S.platform)}<span>${esc(app.label)}</span></span>`;
  const cardCls = `bg-white rounded-xl border-l-4 ${app.border} border-y border-r border-slate-200 shadow-sm p-3.5 flex flex-col gap-3 hover:shadow-md transition-shadow group`;
  const isYt = S.platform === "youtube", ytCfg = cfg?.platforms?.youtube || {}, ytVideo = ytCfg.video || {};
  const fmtOf = r => { const c = ytCfg.categories?.[r.category] || {}, e = r.entry || {};
    const f = e.format || c.format || ytVideo.format || "short", secs = +(e.target_seconds || c.target_seconds || ytVideo.target_seconds || (f === "long" ? 480 : 45));
    return f === "long" ? `Long · ${secs >= 120 ? Math.round(secs / 60) + " min" : secs + "s"}` : `Short · ${secs}s`; };
  const fmtChip = r => isYt && r.category ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">${icon("movie", "text-[12px]")}<span>${esc(fmtOf(r))}</span></span>` : "";
  const ownLink = r => isYt ? `<button type="button" class="text-[10px] text-violet-600 hover:underline font-medium flex items-center gap-0.5" data-p="p-own">${icon("drive_folder_upload", "text-[12px]")}<span>Use my own files</span></button>` : "";
  const ytControls = e => !isYt ? "" : `<div class="grid grid-cols-2 gap-2 text-[10px] text-slate-500">
    <label class="flex flex-col gap-0.5">Format<select class="bg-slate-50 border border-slate-200 rounded-lg px-1.5 py-1 text-[10px] text-slate-700" data-p="p-format">
      ${[["", "Inherit"], ["short", "Short"], ["long", "Long"]].map(([v, l]) => `<option value="${v}"${(e?.format || "") === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
    <label class="flex flex-col gap-0.5">Length (seconds)<input type="number" min="15" max="1800" class="bg-slate-50 border border-slate-200 rounded-lg px-1.5 py-1 text-[10px] text-slate-700" data-p="p-secs" value="${esc(e?.target_seconds || "")}" placeholder="Inherit"></label></div>`;
  const tmplBtn = `<button type="button" class="text-[10px] font-medium text-violet-600 hover:text-violet-800" data-p="p-template">Insert template</button>`;

  const column = r => {
    let body;
    if (!r.category) {
      body = `<div class="bg-slate-100/70 border border-slate-200 rounded-xl p-4 flex flex-col items-center justify-center text-center gap-2 min-h-[160px]">
        <div class="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center text-slate-500">${icon("bedtime", "text-[18px]")}</div>
        <div class="text-xs font-semibold text-slate-700">Scheduled Rest</div>
        <p class="text-[10px] text-slate-500 max-w-[120px]">No post is scheduled for this day.</p>
        <button disabled title="Coming soon" class="mt-1 text-[10px] font-medium text-violet-600 flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed">${icon("add", "text-[12px]")}<span>Add slot anyway</span></button></div>`;
    } else if (r.written) {
      body = `<div class="${cardCls}"><div class="flex items-center justify-between gap-1 flex-wrap">${appPill}${statusPill(r)}</div>${catPill(r)}
        <h3 class="font-headline font-semibold text-xs text-slate-900 leading-snug">${esc(r.written.topic)}</h3>
        <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-[10px]"><span class="text-slate-400 flex items-center gap-1">${icon("lock", "text-[12px]")}<span>Already written</span></span>
          ${ownLink(r)}<a href="#queue" class="text-violet-600 hover:underline font-medium">Open in Queue</a></div></div>`;
    } else if (r.past) {
      body = `<div class="${cardCls} opacity-70"><div class="flex items-center justify-between gap-1 flex-wrap">${appPill}${statusPill(r)}</div>${catPill(r)}
        <h3 class="font-headline font-semibold text-xs text-slate-900 leading-snug">${esc(r.entry?.topic || "No topic")}</h3>
        <p class="text-[9px] text-slate-400 italic">Being written or past</p></div>`;
    } else {
      const e = r.entry;
      const note = e ? (e.rejected?.length ? `Rejected before: ${e.rejected.join("; ")}` : src[e.source] || "")
        : r.fixed ? "Chosen automatically when you plan." : r.plan_ahead ? "Not planned yet." : "Fresh news: picked the day before, unless you type a topic.";
      const brief = r.briefing === "off" ? "" : `<details class="" data-p="p-briefbox"${r.brief_text ? " open" : ""}><summary class="text-[10px] text-slate-500 cursor-pointer">Brief${r.brief_text ? " (set)" : ""}</summary>
        <textarea class="w-full mt-1.5 bg-slate-50 rounded-lg p-2.5 border border-slate-100 text-[10px] font-mono text-slate-600" data-p="p-brief" rows="8" placeholder="Key: value lines. Use the template to see all fields.">${esc(r.brief_text)}</textarea>${tmplBtn}</details>`;
      const empty = !e;
      body = `<div class="${empty ? "border-2 border-dashed border-slate-300 hover:border-violet-400 rounded-xl p-5 bg-white/50 hover:bg-violet-50/40 min-h-[310px]" : cardCls} flex flex-col gap-3 transition-all">
        ${empty ? `<div class="flex flex-col items-center text-center gap-2.5">
          <div class="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">${icon("add", "text-[20px]")}</div>
          <p class="font-headline font-semibold text-xs text-slate-700">Slot is open</p>
          <p class="text-[10px] text-slate-400 leading-tight">Drag from Idea Bank, type a topic, or let the Agent draft one</p></div>`
          : `<div class="flex items-center justify-between gap-1 flex-wrap">${appPill}${statusPill(r)}</div>${catPill(r)}`}
        <div class="relative group/title">
          <input class="w-full font-headline font-semibold text-xs text-slate-900 leading-snug bg-transparent border-b border-transparent hover:border-slate-200 focus:border-violet-400 focus:outline-none pr-4" data-p="p-topic" value="${esc(e?.topic || "")}" maxlength="90" placeholder="${r.plan_ahead || r.fixed ? "Topic" : "Picked the day before (or type one)"}">
          ${icon("edit", "text-[14px] text-slate-400 absolute right-0 top-0 opacity-0 group-hover/title:opacity-100 pointer-events-none")}</div>
        <textarea class="text-[11px] text-slate-600 leading-relaxed bg-transparent border-b border-transparent hover:border-slate-200 focus:border-violet-400 focus:outline-none resize-none" data-p="p-angle" rows="3" maxlength="400" placeholder="Angle: what the reader will learn (optional)">${esc(e?.angle || "")}</textarea>
        ${ytControls(e)}${brief}
        <input class="text-[10px] bg-slate-50 border border-slate-200 rounded-lg px-2 py-1 placeholder-slate-400" data-p="p-hint" maxlength="300" placeholder="Optional: what you'd like instead">
        <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-[10px]">
          <span class="text-slate-400">${esc(note)}</span>${ownLink(r)}
          <button type="button" class="text-slate-400 hover:text-violet-600 flex items-center gap-0.5 font-medium transition" data-p="p-suggest" title="Ask the Planner for a fresh topic">${icon("auto_awesome", "text-[13px]")}<span>${empty ? "Let Agent draft" : "Suggest"}</span></button></div></div>`;
    }
    const attrs = isOpen(r) ? ` data-day="${esc(r.date)}" data-topic="${esc(r.entry?.topic || "")}" data-angle="${esc(r.entry?.angle || "")}" data-brief="${esc(r.brief_text)}" data-format="${esc(r.entry?.format || "")}" data-secs="${esc(r.entry?.target_seconds || "")}"` : "";
    return `<div class="flex flex-col gap-3 min-w-[185px]" data-p="plan-col" data-date="${esc(r.date)}"${attrs}>${header(r)}${body}</div>`;
  };

  // Ideas Bank
  const used = (cid, i) => i.used_on;
  const ideas = Object.entries(d.ideas || {}).flatMap(([cid, rows]) => rows.map(i => ({ cid, label: d.days.find(r => r.category === cid)?.label || cid, idea: i.idea, used_on: i.used_on })));
  const ideaCard = i => i.used_on
    ? `<div class="p-3 bg-emerald-50/40 rounded-xl border border-emerald-200/80 transition-all opacity-85" data-idea>
        <div class="flex items-start justify-between gap-2"><span class="px-2 py-0.5 rounded text-[9px] font-semibold bg-emerald-100 text-emerald-800 flex items-center gap-1">${icon("check", "text-[11px]")}<span>Used on ${esc(fmtDay(i.used_on))}</span></span></div>
        <p class="font-headline font-semibold text-xs mt-2 leading-snug line-through text-slate-500">${esc(i.idea)}</p></div>`
    : `<div class="p-3 bg-white rounded-xl border border-slate-200 hover:border-violet-300 hover:shadow-sm transition-all cursor-grab active:cursor-grabbing group" data-p="p-idea" draggable="true" data-idea data-cat="${esc(i.cid)}" data-text="${esc(i.idea)}">
        <div class="flex items-start justify-between gap-2"><div class="flex items-center gap-1.5">${icon("drag_indicator", "text-[16px] text-slate-300 group-hover:text-slate-500")}
          <span class="px-1.5 py-0.5 rounded text-[9px] font-semibold border ${pillOf(i.cid)}">${esc(i.label)}</span></div>
          <button type="button" class="text-[10px] font-semibold text-violet-600 hover:text-violet-800 bg-violet-50 hover:bg-violet-100 px-2 py-0.5 rounded transition flex items-center gap-0.5" data-p="p-assign"><span>Assign</span>${icon("arrow_forward", "text-[11px]")}</button></div>
        <p class="font-headline font-semibold text-xs text-slate-800 mt-2 leading-snug">${esc(i.idea)}</p></div>`;
  const cats = [...new Set(ideas.map(i => i.cid))];
  const chipBtn = (id, label, on) => `<button type="button" data-filter="${esc(id)}" data-p="p-filter" class="px-2.5 py-1 rounded-md shrink-0 ${on ? "bg-violet-100 text-violet-700 font-semibold" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}">${esc(label)}</button>`;
  const backlog = ideas.filter(i => !i.used_on).length;

  const appTab = id => { const a = appOf(id), on = id === S.platform;
    return `<button type="button" data-plan-app="${id}" class="flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors ${on ?"bg-white text-slate-900 shadow-sm border border-slate-200 font-semibold" : "text-slate-600 hover:text-slate-900"}">
      ${id === "youtube" ? icon("smart_display", `text-[16px] ${a.text}`, true) : `<span class="w-2.5 h-2.5 rounded-sm ${a.dot}"></span>`}<span>${esc(a.label)}</span></button>`; };

  $("#view").innerHTML = `
<div class="bg-white border-b border-slate-200 px-6 py-4"><div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
  <div><nav class="flex items-center gap-2 text-xs text-slate-500 font-label mb-1"><span>Production Studio</span><span class="text-slate-300">/</span><span class="text-violet-700 font-medium">Content Planning</span></nav>
    <div class="flex items-center gap-3"><h1 class="font-headline font-bold text-2xl text-slate-900 tracking-tight">Editorial Week Plan</h1>
      <div class="flex items-center bg-slate-100 border border-slate-200 rounded-xl px-2.5 py-1 text-xs font-medium text-slate-700 gap-1.5">
        <button disabled title="Coming soon" class="p-0.5 rounded text-slate-500 disabled:opacity-50 disabled:cursor-not-allowed">${icon("chevron_left", "text-[16px]")}</button>
        ${icon("date_range", "text-[16px] text-slate-500")}<span class="font-semibold text-slate-900">${esc(fmtDay(d.week[0]))} – ${esc(fmtFull(d.week[1]))}</span>
        <span class="text-violet-600 bg-violet-100 px-1.5 py-0.5 rounded font-medium text-[11px]">(This Week)</span>
        <button disabled title="Coming soon" class="p-0.5 rounded text-slate-500 disabled:opacity-50 disabled:cursor-not-allowed">${icon("chevron_right", "text-[16px]")}</button></div></div></div>
  <div class="flex flex-wrap items-center gap-3">
    <div class="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200 font-medium text-xs">${PLATFORM_IDS.map(appTab).join("")}</div>
    <div class="hidden xl:flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-xl">${icon("pie_chart", "text-[16px] text-amber-500")}
      <span>${planned.length} of ${withPost.length} days planned</span><span class="text-slate-400">•</span><span class="text-amber-700 font-semibold">${openDays.length} slots open</span></div>
    <div class="flex items-center gap-2">
      <button id="p-replan" class="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold shadow-sm active:scale-95 transition-all disabled:opacity-50" title="Replaces the Planner's own topics for the rest of the week (yours are kept)">${icon("sync", "text-[16px] text-slate-500")}<span>Re-plan this week</span></button>
      <button id="p-fill" class="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold shadow-sm shadow-violet-200 active:scale-95 transition-all disabled:opacity-50">${icon("auto_awesome", "text-[16px]", true)}<span>Plan the open days</span></button></div></div></div>
  <p class="text-[11px] text-slate-500 mt-3" id="p-state">The Week Planner also runs every ${esc(DAY_NAMES[d.planning.weekday])} at ${esc(d.planning.time)}${d.planning.enabled ? "" : " (switched off in Settings)"}. Empty a topic to let the Topic Scout choose the day before.</p></div>
<div class="flex-1 flex overflow-hidden h-[calc(100vh-11rem)] min-h-[560px]">
  <section class="flex-1 overflow-x-auto custom-scrollbar p-6 bg-slate-50/60"><div class="min-w-[1360px] grid grid-cols-7 gap-4">${d.days.map(column).join("")}</div>
    <div class="flex items-center gap-3 mt-6"><span id="save-state" class="text-xs text-slate-500">No changes</span><span class="flex-1"></span>
      <button id="p-reset" class="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold shadow-sm disabled:opacity-50">${icon("undo", "text-[16px] text-slate-500")}<span>Discard changes</span></button>
      <button id="p-save" class="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold shadow-sm shadow-violet-200 disabled:opacity-50">${icon("save", "text-[16px]")}<span>Save plan</span></button></div></section>
  <aside class="w-[340px] border-l border-slate-200 bg-white flex flex-col shrink-0">
    <div class="p-4 border-b border-slate-200">
      <div class="flex items-center justify-between mb-1.5"><div class="flex items-center gap-2">${icon("lightbulb", "text-amber-500 text-[20px]", true)}<h2 class="font-headline font-bold text-sm text-slate-900">Your Ideas Bank</h2></div>
        <span class="text-[10px] font-mono font-semibold bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">${backlog} in backlog</span></div>
      <p class="text-[11px] text-slate-500 leading-normal">Drag any idea onto an open day card or click <span class="font-semibold text-slate-700">Assign</span>. Ideas live in Settings, under each topic type.</p>
      <div class="mt-3 relative"><input disabled title="Coming soon" class="w-full text-xs bg-slate-50 border border-slate-200 rounded-lg pl-3 pr-8 py-2 placeholder-slate-400 disabled:opacity-60" placeholder="+ Quick drop a new idea..." type="text">
        <button disabled title="Coming soon" class="absolute right-2 top-2 text-slate-400">${icon("subdirectory_arrow_left", "text-[16px]")}</button></div>
      <div class="mt-2.5 relative">${icon("search", "text-[16px] text-slate-400 absolute left-2.5 top-2")}
        <input id="p-search" class="w-full text-xs bg-white border border-slate-200 rounded-lg pl-8 pr-3 py-1.5 placeholder-slate-400 text-slate-800 focus:outline-none focus:ring-1 focus:ring-violet-500" placeholder="Search by theme, hook, or tag..." type="text"></div>
      <div class="flex items-center gap-1 mt-2.5 overflow-x-auto text-[10px] font-medium">${chipBtn("", "All Topics", true)}${cats.map(c => chipBtn(c, ideas.find(i => i.cid === c).label, false)).join("")}</div></div>
    <div id="p-ideas" class="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-2.5 bg-slate-50/50">${ideas.length ? ideas.map(ideaCard).join("") : `<p class="text-xs text-slate-400 p-2">No ideas yet. Add them to a topic type in Settings.</p>`}</div>
    <div class="p-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-[11px] text-slate-500">
      <span class="flex items-center gap-1">${icon("sync", "text-[14px] text-emerald-600")}<span>Used ideas are matched to posts automatically</span></span>
      <button disabled title="Coming soon" class="text-violet-700 font-medium disabled:opacity-50">Export CSV</button></div></aside></div>`;

  const view = $("#view");
  const cols = () => [...view.querySelectorAll("[data-p=plan-col][data-day]")];
  const changes = () => {
    const out = {};
    cols().forEach(c => {
      const topic = c.querySelector("[data-p=p-topic]").value.trim(), angle = c.querySelector("[data-p=p-angle]").value.trim();
      const bf = c.querySelector("[data-p=p-brief]"), brief = bf ? bf.value.trim() : null;
      const bchanged = bf && brief !== c.dataset.brief.trim();
      const ff = c.querySelector("[data-p=p-format]"), fs = c.querySelector("[data-p=p-secs]");
      const fchanged = ff && ff.value !== c.dataset.format, schanged = fs && fs.value.trim() !== c.dataset.secs;
      if (topic !== c.dataset.topic || angle !== c.dataset.angle || bchanged || ((fchanged || schanged) && topic)) {
        const o = Object.assign({ topic, angle: topic ? angle : "" }, bchanged ? { brief: topic ? brief : "" } : {});
        if (ff && topic) { o.format = ff.value; o.target_seconds = fs.value.trim() ? Math.max(0, parseInt(fs.value, 10) || 0) : ""; }
        out[c.dataset.day] = o;
      }
    });
    return out;
  };
  const refreshDirty = () => { const n = Object.keys(changes()).length; S.dirty = n > 0; $("#save-state").textContent = n ? `${n} unsaved change(s)` : "No changes"; };
  const savePlan = async () => {
    const days = changes();
    if (!Object.keys(days).length) { toast("Nothing to save"); return true; }
    try { await api("/api/plan", { method: "PUT", body: { days, platform: S.platform } }); S.dirty = false; toast(`Saved ${Object.keys(days).length} day(s)`); return true; }
    catch (e) { toast(e.message, true); return false; }
  };
  const busy = label => { view.querySelectorAll("button").forEach(x => x.disabled = true); $("#p-state").textContent = label; };
  const setTopic = (col, text) => { const t = col.querySelector("[data-p=p-topic]"); t.value = text.slice(0, 90); t.dispatchEvent(new Event("input", { bubbles: true })); t.focus(); };

  view.addEventListener("input", e => { if (e.target.matches("[data-p=p-topic], [data-p=p-angle], [data-p=p-brief], [data-p=p-format], [data-p=p-secs]")) refreshDirty(); });
  view.addEventListener("change", e => { if (e.target.matches("[data-p=p-format]")) refreshDirty(); });
  view.querySelectorAll("[data-p=plan-col]").forEach(c => { const o = c.querySelector("[data-p=p-own]"); if (o) o.onclick = () => openUploadForDate(c.dataset.day || c.dataset.date); });
  $("#p-save").onclick = async () => { if (await savePlan()) renderPlan(); };
  $("#p-reset").onclick = () => renderPlan();
  $("#p-fill").onclick = async () => {
    if (S.dirty && !(await savePlan())) return;
    busy("The Week Planner is working (about a minute)…");
    try { await post("/api/plan/fill", { platform: S.platform }); toast("Plan updated"); } catch (e) { toast(e.message, true); }
    renderPlan(); refreshOverview();
  };
  $("#p-replan").onclick = async () => {
    if (S.dirty && !(await savePlan())) return;
    busy("The Week Planner is re-planning the week (about a minute)…");
    try { await post("/api/plan/fill", { platform: S.platform, replan: true }); toast("Week re-planned"); } catch (e) { toast(e.message, true); }
    renderPlan(); refreshOverview();
  };
  view.querySelectorAll("[data-plan-app]").forEach(b => b.onclick = () => { if (b.dataset.planApp !== S.platform) { S.platform = b.dataset.planApp; setTab("plan"); refreshOverview(); } });
  cols().forEach(c => {
    const day = c.dataset.day;
    const tb = c.querySelector("[data-p=p-template]");
    if (tb) tb.onclick = () => { const bf = c.querySelector("[data-p=p-brief]"); if (!bf.value.trim()) { bf.value = PLAN_BRIEF_TEMPLATE; bf.dispatchEvent(new Event("input", { bubbles: true })); } };
    c.querySelector("[data-p=p-suggest]").onclick = async () => {
      if (S.dirty && !(await savePlan())) return;
      busy(`Asking the Week Planner for a new ${c.querySelector(".font-headline").textContent.trim()} topic…`);
      try { await post(`/api/plan/${day}/suggest`, { hint: c.querySelector("[data-p=p-hint]").value.trim(), platform: S.platform }); toast("New topic suggested"); } catch (e) { toast(e.message, true); }
      renderPlan();
    };
    // drop an idea from the bank onto an open day
    c.addEventListener("dragover", e => { e.preventDefault(); c.classList.add("ring-2", "ring-violet-300", "rounded-xl"); });
    c.addEventListener("dragleave", () => c.classList.remove("ring-2", "ring-violet-300", "rounded-xl"));
    c.addEventListener("drop", e => { e.preventDefault(); c.classList.remove("ring-2", "ring-violet-300", "rounded-xl"); const t = e.dataTransfer.getData("text/plain"); if (t) setTopic(c, t); });
  });
  view.querySelectorAll("[data-p=p-idea]").forEach(el => {
    el.addEventListener("dragstart", e => e.dataTransfer.setData("text/plain", el.dataset.text));
    el.querySelector("[data-p=p-assign]").onclick = () => {
      const free = cols().find(c => !c.querySelector("[data-p=p-topic]").value.trim()) ;
      if (!free) { toast("No open day left this week. Empty a day's topic first.", true); return; }
      setTopic(free, el.dataset.text);
    };
  });
  let filter = "";
  const applyFilter = () => { const q = $("#p-search").value.trim().toLowerCase();
    view.querySelectorAll("#p-ideas [data-idea]").forEach(el => { const t = (el.textContent || "").toLowerCase();
      el.hidden = (filter && el.dataset.cat !== filter) || (q && !t.includes(q)); }); };
  $("#p-search").oninput = applyFilter;
  view.querySelectorAll("[data-p=p-filter]").forEach(b => b.onclick = () => { filter = b.dataset.filter;
    view.querySelectorAll("[data-p=p-filter]").forEach(x => x.className = `px-2.5 py-1 rounded-md shrink-0 ${x === b ? "bg-violet-100 text-violet-700 font-semibold" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`); applyFilter(); });
}
VIEWS.plan = renderPlan;
