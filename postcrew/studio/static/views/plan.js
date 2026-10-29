/* Plan: the Monthly Content Plan (design/stitch/content-plan-monthly-editorial-board). A month calendar on the left, the generated
   plans on the right. Plans are written from the Topics in Settings and are never put on days by themselves: you assign each one to a
   date (YouTube: Short or Long). Published plans stay listed, struck through, and are never planned again. */
"use strict";

const PLAN = { month: null, status: "unassigned", topic: "", q: "", open: new Set(), assign: null, busy: "" };
const PLAN_PILLS = ["bg-cyan-50 text-cyan-700 border-cyan-100", "bg-indigo-50 text-indigo-700 border-indigo-100", "bg-amber-50 text-amber-800 border-amber-200",
  "bg-teal-50 text-teal-700 border-teal-100", "bg-rose-50 text-rose-700 border-rose-100", "bg-emerald-50 text-emerald-700 border-emerald-100"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MON3 = MONTHS.map(m => m.slice(0, 3));
const WDAY3 = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const planIso = (y, m, d) => `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
const planParts = iso => iso.split("-").map(Number);
const planNiceDay = iso => { const [y, m, d] = planParts(iso); return `${WDAY3[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]} ${d} ${MON3[m - 1]}`; };
const planShift = (month, by) => { const [y, m] = planParts(month); const t = y * 12 + (m - 1) + by; return `${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, "0")}`; };

async function renderPlan() {
  const view = $("#view");
  PLAN.month = PLAN.month || null;
  let d, counts = {};
  try {
    const [cur, ...all] = await Promise.all([api(`/api/plan?platform=${encodeURIComponent(S.platform)}${PLAN.month ? `&month=${PLAN.month}` : ""}`),
      ...PLATFORM_IDS.map(id => api(`/api/plan?platform=${id}`).then(x => [id, x.counts.assigned + x.counts.published]).catch(() => [id, 0]))]);
    d = cur; all.forEach(([id, n]) => counts[id] = n);
  } catch (e) { view.innerHTML = `<div class="p-8">${errorBanner(e.message)}</div>`; return; }
  S.dirty = false;
  PLAN.month = d.month;
  const app = appOf(S.platform), isYt = S.platform === "youtube", [Y, M] = planParts(d.month);
  const topicIds = [...new Set([...d.topics, ...d.items.map(i => i.topic)])];
  const pillOf = t => PLAN_PILLS[Math.max(0, topicIds.indexOf(t)) % PLAN_PILLS.length];
  const itemById = id => d.items.find(i => i.id === id);
  const free = iso => iso >= d.today && !d.days[iso];

  /* ---------- calendar ---------- */
  const first = new Date(Date.UTC(Y, M - 1, 1)), lead = (first.getUTCDay() + 6) % 7, dim = new Date(Date.UTC(Y, M, 0)).getUTCDate();
  const cells = [];
  for (let i = lead; i > 0; i--) { const t = new Date(Date.UTC(Y, M - 1, 1 - i)); cells.push({ out: true, n: t.getUTCDate(), m: MON3[t.getUTCMonth()] }); }
  for (let n = 1; n <= dim; n++) cells.push({ n, iso: planIso(Y, M, n) });
  for (let n = 1; cells.length % 7; n++) cells.push({ out: true, n, m: MON3[M % 12] });
  const dayCard = (x, it) => {
    const pub = it.status === "published", fmt = it.format === "long" ? "Long" : it.format === "short" ? "Short" : "";
    const tag = pub ? `<span class="text-[9px] px-1.5 py-0.5 rounded-full font-semibold bg-emerald-100 text-emerald-800 flex items-center gap-0.5">${icon("check", "text-[10px]")}Published</span>`
      : it.status === "written" ? `<span class="text-[9px] px-1.5 py-0.5 rounded-full font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">Written</span>`
      : `<span class="text-[9px] px-1.5 py-0.5 rounded-full font-semibold bg-blue-50 text-blue-700 border border-blue-200">Planned</span>`;
    return `<div class="min-h-[120px] rounded-xl border ${pub ? `border-emerald-200 bg-emerald-50/20` : x.iso === d.today ? `border-2 border-violet-600 bg-violet-50/30` : `border-slate-200 bg-white`} p-2 flex flex-col gap-1.5 group" data-cell="${x.iso}">
      <div class="flex items-center justify-between"><div class="flex items-center gap-1"><span class="text-xs font-mono font-bold ${x.iso === d.today ? `text-violet-700` : `text-slate-800`}">${x.n}</span>${x.iso === d.today ? `<span class="text-[9px] px-1 py-0.5 rounded bg-violet-600 text-white font-semibold">Today</span>` : ""}</div>${tag}</div>
      <button type="button" data-jump="${it.id}" class="text-left bg-white rounded-lg border-l-4 ${app.border} border border-slate-200 p-2 shadow-sm hover:border-violet-300">
        <div class="flex items-center gap-1 mb-1 flex-wrap">${fmt ? `<span class="px-1.5 py-0.5 text-[9px] font-bold rounded bg-red-50 ${appOf(`youtube`).text}">${fmt}</span>` : ""}<span class="px-1.5 py-0.5 text-[9px] font-semibold rounded border ${pillOf(it.topic)} max-w-[120px] truncate">${esc(it.topic)}</span></div>
        <p class="text-[11px] font-semibold text-slate-800 line-clamp-2 leading-snug ${pub ? `line-through` : ``}">${esc(it.title)}</p></button></div>`;
  };
  const dayCell = x => {
    if (x.out) return `<div class="min-h-[120px] rounded-xl border border-slate-200/50 bg-slate-100/50 p-2 opacity-50 flex flex-col justify-between"><span class="text-xs font-mono text-slate-400 font-medium">${x.n}</span><span class="text-[10px] text-slate-400 italic text-center">${x.m}</span></div>`;
    const it = d.days[x.iso];
    if (it) return dayCard(x, it);
    if (x.iso < d.today) return `<div class="min-h-[120px] rounded-xl border border-slate-200 bg-slate-50/70 p-2 flex flex-col justify-between"><span class="text-xs font-mono font-semibold text-slate-400">${x.n}</span></div>`;
    const picking = PLAN.assign && PLAN.assign.date === x.iso;
    return `<div class="min-h-[120px] rounded-xl border ${x.iso === d.today ? `border-2 border-violet-600 bg-violet-50/30` : picking ? `border-violet-400 bg-violet-50/40` : `border-slate-200 bg-white`} p-2 flex flex-col justify-between hover:border-slate-300 transition" data-cell="${x.iso}" data-drop="${x.iso}">
      <div class="flex items-center gap-1"><span class="text-xs font-mono font-semibold ${x.iso === d.today ? `text-violet-700` : `text-slate-600`}">${x.n}</span>${x.iso === d.today ? `<span class="text-[9px] px-1 py-0.5 rounded bg-violet-600 text-white font-semibold">Today</span>` : ""}</div>
      <button type="button" data-pick="${x.iso}" class="border border-dashed ${picking ? `border-violet-400 text-violet-600` : `border-slate-200 text-slate-400`} rounded-lg py-3 text-center text-[10px] hover:text-violet-600 hover:border-violet-300 cursor-pointer transition w-full">${picking ? "Assigning here" : "+ Assign"}</button></div>`;
  };
  const weekHead = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w, i) => `<div class="py-1 ${i > 4 ? `text-slate-400` : ``}">${w}</div>`).join("");

  /* ---------- plans ---------- */
  const shown = d.items.filter(i => (PLAN.status === "all" || (PLAN.status === "assigned" ? ["assigned", "written"].includes(i.status) : i.status === PLAN.status))
    && (!PLAN.topic || i.topic === PLAN.topic)
    && (!PLAN.q || `${i.title} ${i.angle} ${i.topic} ${i.context}`.toLowerCase().includes(PLAN.q.toLowerCase())));
  const block = (ic, label, body) => `<div class="bg-slate-50 rounded-lg p-2 border border-slate-100"><div class="font-semibold text-slate-700 mb-0.5 flex items-center gap-1">${icon(ic, "text-[12px] text-violet-600")}${label}</div>${body}</div>`;
  const details = i => `<div class="mt-3 pt-2.5 border-t border-slate-100 space-y-2 text-[10px]">
    ${block("help_center", "Context (why it matters)", `<p class="text-slate-500 leading-normal">${esc(i.context)}</p>`)}
    ${block("travel_explore", "Research topics", `<div class="flex flex-wrap gap-1">${(i.search_queries || []).map(q => `<span class="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-600 text-[9px]">${esc(q)}</span>`).join("")}</div>`)}
    ${block("deployed_code", "Real-world example", `<p class="text-slate-500 leading-normal">${esc(i.example)}</p>`)}
    ${block("lightbulb", "Takeaway", `<p class="text-slate-500 leading-normal">${esc(i.takeaway)}</p>`)}</div>`;
  const popover = i => {
    const a = PLAN.assign, days = [];
    for (let n = 1; n <= dim; n++) days.push(planIso(Y, M, n));
    const grid = ["M", "T", "W", "T", "F", "S", "S"].map(w => `<div class="text-center text-[9px] text-slate-400">${w}</div>`).join("")
      + Array(lead).fill("<div></div>").join("")
      + days.map(iso => { const ok = free(iso), on = a.date === iso;
        return `<button type="button" ${ok ? `data-date="${iso}"` : "disabled"} class="py-1 rounded text-[10px] font-medium ${on ? `bg-violet-600 text-white font-bold` : ok ? `text-slate-700 hover:bg-violet-50` : `text-slate-300 cursor-not-allowed`}">${+iso.slice(8)}</button>`; }).join("");
    const fmtOn = `bg-red-50 ${appOf("youtube").text} font-bold border border-red-200`, fmtOff = "text-slate-600 hover:bg-slate-50 font-medium";
    const fmtBtn = (v, ic, label) => `<button type="button" data-fmt="${v}" class="py-1 rounded text-center flex items-center justify-center gap-1 ${a.format === v ? fmtOn : fmtOff}">${icon(ic, "text-[12px]")}<span>${label}</span></button>`;
    return `<div class="mt-2.5 p-2.5 bg-slate-50 border border-slate-200 rounded-lg space-y-2 text-xs">
      <div class="flex items-center justify-between"><span class="text-[11px] font-semibold text-slate-700">Assign to date</span>
        <span class="text-[10px] font-bold text-violet-700 bg-white border border-violet-200 px-1.5 py-0.5 rounded">${a.date ? esc(planNiceDay(a.date)) : "Pick a day"}</span></div>
      <div class="grid grid-cols-7 gap-0.5 bg-white p-1.5 rounded-lg border border-slate-200">${grid}</div>
      ${isYt ? `<div class="text-[10px] font-medium text-slate-500">Video length</div>
        <div class="grid grid-cols-2 gap-1 bg-white p-1 rounded-lg border border-slate-200 text-[10px]">${fmtBtn("short", "smart_display", "Short · up to 60s")}${fmtBtn("long", "play_circle", "Long · 8 min")}</div>` : ""}
      <div class="flex items-center justify-end gap-1.5 pt-1"><button type="button" data-cancel class="px-2.5 py-1 text-[11px] rounded text-slate-600 hover:bg-slate-200">Cancel</button>
        <button type="button" data-confirm ${a.date ? "" : "disabled"} class="px-3 py-1 text-[11px] rounded-lg bg-violet-600 text-white font-semibold shadow-sm hover:bg-violet-700 disabled:opacity-50">${a.date ? `Assign to ${esc(planNiceDay(a.date))}` : "Pick a day"}</button></div></div>`;
  };
  const planCard = i => {
    const topic = `<span class="px-1.5 py-0.5 rounded text-[9px] font-semibold border ${pillOf(i.topic)}">${esc(i.topic)}</span>`;
    if (i.status === "published") return `<div class="p-3 bg-slate-50 rounded-xl border border-slate-200 opacity-85" data-plan="${i.id}"><div class="flex items-start justify-between gap-2">
        <span class="px-2 py-0.5 rounded text-[9px] font-semibold bg-slate-200 text-slate-700 flex items-center gap-1">${icon("check_circle", "text-[11px] text-emerald-600")}<span>Published</span></span><span class="text-[10px] text-slate-400 font-medium">Archive</span></div>
        <p class="font-headline font-semibold text-xs text-slate-600 mt-2 leading-snug line-through">${esc(i.title)}</p><p class="text-[10px] text-slate-400 mt-1 italic">Published, never planned again</p></div>`;
    if (i.assigned) { const a = i.assigned, written = i.status === "written";
      return `<div class="p-3 bg-emerald-50/40 rounded-xl border border-emerald-200/80 transition-all" data-plan="${i.id}"><div class="flex items-start justify-between gap-2">
        <span class="px-2 py-0.5 rounded text-[9px] font-semibold bg-emerald-100 text-emerald-800 flex items-center gap-1">${icon("check", "text-[11px]")}<span>Assigned to ${esc(planNiceDay(a.date))}</span></span>
        <span class="text-[10px] text-emerald-700 font-mono font-medium">${written ? "Written" : "Scheduled"}</span></div>
        <p class="font-headline font-semibold text-xs text-slate-800 mt-2 leading-snug">${esc(i.title)}</p><p class="text-[11px] text-slate-500 mt-1 line-clamp-2">${esc(i.angle)}</p>
        <div class="mt-2 pt-2 border-t border-emerald-100 text-[10px] text-slate-400 flex items-center justify-between"><span>${topic}${a.format ? ` · ${a.format === "long" ? "Long" : "Short"} video` : ""}</span>
          ${written ? "" : `<button type="button" data-unassign="${i.id}" class="text-slate-400 hover:text-rose-600 text-[10px] underline cursor-pointer">Unassign</button>`}</div></div>`; }
    const open = PLAN.open.has(i.id), assigning = PLAN.assign?.id === i.id;
    return `<div class="p-3 bg-white rounded-xl border ${assigning ? `border-2 border-violet-500 shadow-md` : open ? `border-violet-300 ring-2 ring-violet-100 shadow-sm` : `border-slate-200 hover:border-violet-300 hover:shadow-sm`} transition-all relative" data-plan="${i.id}" draggable="true">
      <div class="flex items-start justify-between gap-2">${topic}${assigning ? `<span class="text-[9px] font-semibold text-violet-700 bg-violet-100 px-1.5 py-0.5 rounded">Assigning…</span>`
        : `<button type="button" data-assign="${i.id}" class="text-[10px] font-semibold text-white bg-violet-600 hover:bg-violet-700 px-2.5 py-1 rounded-lg transition flex items-center gap-1 shadow-sm cursor-pointer"><span>Assign</span>${icon("calendar_add_on", "text-[11px]")}</button>`}</div>
      <p class="font-headline font-semibold text-xs text-slate-800 mt-2 leading-snug">${esc(i.title)}</p>
      <p class="text-[11px] text-slate-500 mt-1 ${open ? `` : `line-clamp-2`} leading-relaxed">${esc(i.angle)}</p>
      ${open ? details(i) : ""}${assigning ? popover(i) : ""}
      <div class="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[10px] text-slate-400"><button type="button" data-more="${i.id}" class="text-violet-600 font-medium hover:underline flex items-center gap-0.5"><span>${open ? "Collapse details" : "Details"}</span>${icon(open ? "expand_less" : "expand_more", "text-[12px]")}</button></div></div>`;
  };
  const stat = (k, label) => `<button type="button" data-status="${k}" class="px-2 py-0.5 rounded font-medium ${PLAN.status === k ? `bg-violet-600 text-white` : `bg-slate-100 text-slate-600 hover:bg-slate-200`}">${label}</button>`;
  const tchip = (t, label) => `<button type="button" data-topic="${esc(t)}" class="px-2 py-0.5 rounded-md shrink-0 ${PLAN.topic === t ? `bg-violet-100 text-violet-700 font-semibold` : `bg-slate-100 text-slate-600 hover:bg-slate-200`}">${esc(label)}</button>`;
  const appTab = id => { const a = appOf(id), on = id === S.platform;
    const countCls = on ? `${a.soft} ${a.text} border font-bold` : "bg-slate-200 text-slate-700";
    return `<button type="button" data-plan-app="${id}" class="flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors ${on ? `bg-white text-slate-900 shadow-sm border border-slate-200 font-semibold` : `text-slate-600 hover:text-slate-900`}">
      ${id === "youtube" ? icon("smart_display", `text-[16px] ${a.text}`, true) : `<span class="w-2.5 h-2.5 rounded-sm ${a.dot}"></span>`}<span>${esc(a.label)}</span>
      <span class="${countCls} text-[10px] px-1.5 py-0.5 rounded-full font-mono">${counts[id] || 0} scheduled</span></button>`; };
  const c = d.counts, noTopics = !d.topics.length, generated = d.generated_at ? new Date(d.generated_at).toLocaleDateString([], { month: "short", day: "numeric" }) : "";
  const empty = !d.items.length ? `<div class="p-4 text-center text-xs text-slate-500 space-y-2">${icon("auto_awesome", "text-2xl text-violet-300")}
      <p>${noTopics ? `No topics yet for ${esc(app.label)}. <a href="#settings" class="text-violet-600 font-medium hover:underline">Add topics in Settings</a>, then press Generate plan.`
        : "No plan for this month yet. Press Generate plan and the Planner writes 10 plans for each of your topics."}</p></div>`
    : !shown.length ? `<p class="text-xs text-slate-400 p-2">No plans match these filters.</p>` : "";

  view.innerHTML = `
<div class="bg-white border-b border-slate-200 px-6 py-4"><div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
  <div class="flex flex-col gap-1"><nav class="flex items-center gap-2 text-xs text-slate-500 font-label mb-1"><span>Production Studio</span><span class="text-slate-300">/</span><span class="text-violet-700 font-medium">Content Planning</span></nav>
    <div class="flex items-center gap-3"><h1 class="font-headline font-bold text-2xl text-slate-900 tracking-tight">Content Plan</h1>
      <div class="flex items-center bg-slate-100 border border-slate-200 rounded-xl px-2.5 py-1 text-xs font-medium text-slate-700 gap-1.5">
        <button type="button" data-month="-1" class="hover:bg-slate-200 p-0.5 rounded text-slate-500 hover:text-slate-800 transition cursor-pointer" title="Previous month">${icon("chevron_left", "text-[16px]")}</button>
        ${icon("date_range", "text-[16px] text-slate-500")}<span class="font-semibold text-slate-900">${MONTHS[M - 1]} ${Y}</span>
        ${d.month === d.this_month ? `<span class="text-violet-600 bg-violet-100 px-1.5 py-0.5 rounded font-medium text-[11px]">This month</span>` : `<button type="button" data-month="now" class="text-violet-600 bg-violet-100 px-1.5 py-0.5 rounded font-medium text-[11px] hover:bg-violet-200">This month</button>`}
        <button type="button" data-month="1" class="hover:bg-slate-200 p-0.5 rounded text-slate-500 hover:text-slate-800 transition cursor-pointer" title="Next month">${icon("chevron_right", "text-[16px]")}</button></div></div></div>
  <div class="flex flex-wrap items-center gap-3">
    <div class="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200 font-medium text-xs">${PLATFORM_IDS.map(appTab).join("")}</div>
    <div class="hidden xl:flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-xl">${icon("assignment", "text-[16px] text-violet-600")}
      <span>${c.plans} plans</span><span class="text-slate-400">•</span><span class="text-emerald-700 font-semibold">${c.assigned} assigned</span><span class="text-slate-400">•</span><span class="text-amber-700 font-semibold">${c.unassigned} unassigned</span></div>
    <div class="flex flex-col items-end"><button id="p-gen" class="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold shadow-sm shadow-violet-200 active:scale-95 transition-all cursor-pointer disabled:opacity-50" ${d.month < d.this_month ? "disabled" : ""}>${icon("auto_awesome", "text-[16px]", true)}<span>Generate plan</span></button>
      <span id="p-state" class="text-[10px] text-slate-400 mt-1">${esc(PLAN.busy || `Also generated on the 1st of every month from your Topics in Settings${d.planning.enabled ? "" : " (switched off in Settings)"}`)}</span></div></div></div></div>
<main class="flex-1 flex overflow-hidden h-[calc(100vh-11rem)] min-h-[560px]" data-active-view="plan">
  <section class="flex-1 overflow-y-auto custom-scrollbar p-5 bg-slate-50/60"><div class="max-w-[1100px] mx-auto">
    <div class="grid grid-cols-7 gap-2 mb-2 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">${weekHead}</div>
    <div class="grid grid-cols-7 gap-2.5">${cells.map(dayCell).join("")}</div></div></section>
  <aside class="w-[380px] border-l border-slate-200 bg-white flex flex-col shrink-0">
    <div class="p-4 border-b border-slate-200">
      <div class="flex items-center justify-between mb-1.5"><div class="flex items-center gap-2">${icon("auto_awesome", "text-violet-600 text-[20px]", true)}<h2 class="font-headline font-bold text-sm text-slate-900">Generated plans</h2></div>
        <span class="text-[10px] font-mono font-semibold bg-violet-50 text-violet-700 px-2 py-0.5 rounded-full border border-violet-100">${c.plans} plans · ${topicIds.length} ${topicIds.length === 1 ? "topic" : "topics"}</span></div>
      <p class="text-[11px] text-slate-500 leading-normal">${d.per_topic} plans per topic. Assign any plan to a day.</p>
      <div class="mt-2.5 relative">${icon("search", "text-[16px] text-slate-400 absolute left-2.5 top-2")}<input id="p-search" value="${esc(PLAN.q)}" class="w-full text-xs bg-slate-50 border border-slate-200 rounded-lg pl-8 pr-3 py-1.5 placeholder-slate-400 text-slate-800 focus:outline-none focus:ring-1 focus:ring-violet-500 focus:bg-white" placeholder="Search plans…" type="text"></div>
      <div class="flex items-center gap-1 mt-2.5 overflow-x-auto text-[10px] font-medium pb-1">${tchip("", "All topics")}${topicIds.map(t => tchip(t, t)).join("")}</div>
      <div class="flex items-center gap-1 mt-1.5 text-[10px]"><span class="text-slate-400 mr-1">Status:</span>${stat("unassigned", `Unassigned (${c.unassigned})`)}${stat("assigned", `Assigned (${c.assigned})`)}${stat("published", `Published (${c.published})`)}${stat("all", "All")}</div></div>
    <div id="p-list" class="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-3 bg-slate-50/50">${shown.map(planCard).join("")}${empty}</div>
    <div class="p-3 bg-slate-50 border-t border-slate-200 flex flex-col gap-1 text-[11px] text-slate-500"><div class="flex items-center justify-between font-medium">
      <span class="flex items-center gap-1">${icon("calendar_today", "text-[14px] text-violet-600")}<span>${generated ? `Plan generated ${esc(generated)} · from ${d.plan_topics.length} ${d.plan_topics.length === 1 ? "topic" : "topics"}` : "No plan generated for this month yet"}</span></span>
      <span class="text-violet-700 font-semibold">Next ${esc(planNiceDay(d.next_plan).replace(/^\w+ /, ""))}</span></div>
      <p class="text-[10px] text-slate-400">A new plan is written on the 1st of every month. Unassigned plans stay in their month; published plans are never planned again.</p></div></aside></main>`;

  /* ---------- behaviour ---------- */
  const again = () => renderPlan();
  const setAssign = (id, date = null) => { const it = itemById(id); PLAN.assign = { id, date, format: it?.assigned?.format || d.default_format || "short" }; PLAN.open.add(id); };
  const doAssign = async () => {
    const a = PLAN.assign; if (!a?.date) return;
    try { await post("/api/plan/assign", { platform: S.platform, id: a.id, date: a.date, format: isYt ? a.format : undefined, month: d.month });
      toast(`Assigned to ${planNiceDay(a.date)}`); PLAN.assign = null; refreshOverview(); } catch (e) { toast(e.message, true); }
    again();
  };
  view.querySelectorAll("[data-plan-app]").forEach(b => b.onclick = () => { if (b.dataset.planApp !== S.platform) { S.platform = b.dataset.planApp; PLAN.assign = null; PLAN.topic = ""; setTab("plan"); refreshOverview(); } });
  view.querySelectorAll("[data-month]").forEach(b => b.onclick = () => { PLAN.month = b.dataset.month === "now" ? d.this_month : planShift(d.month, +b.dataset.month); PLAN.assign = null; again(); });
  view.querySelectorAll("[data-status]").forEach(b => b.onclick = () => { PLAN.status = b.dataset.status; again(); });
  view.querySelectorAll("[data-topic]").forEach(b => b.onclick = () => { PLAN.topic = b.dataset.topic; again(); });
  const search = $("#p-search"); search.oninput = () => { PLAN.q = search.value; const pos = search.selectionStart; again().then?.(() => 0); setTimeout(() => { const s = $("#p-search"); if (s) { s.focus(); s.setSelectionRange(pos, pos); } }, 60); };
  view.querySelectorAll("[data-more]").forEach(b => b.onclick = () => { PLAN.open.has(b.dataset.more) ? PLAN.open.delete(b.dataset.more) : PLAN.open.add(b.dataset.more); again(); });
  view.querySelectorAll("[data-assign]").forEach(b => b.onclick = () => { setAssign(b.dataset.assign, PLAN.assign?.date && free(PLAN.assign.date) ? PLAN.assign.date : null); again(); });
  view.querySelectorAll("[data-date]").forEach(b => b.onclick = () => { PLAN.assign.date = b.dataset.date; again(); });
  view.querySelectorAll("[data-fmt]").forEach(b => b.onclick = () => { PLAN.assign.format = b.dataset.fmt; again(); });
  view.querySelectorAll("[data-cancel]").forEach(b => b.onclick = () => { PLAN.assign = null; again(); });
  view.querySelectorAll("[data-confirm]").forEach(b => b.onclick = doAssign);
  view.querySelectorAll("[data-unassign]").forEach(b => b.onclick = async () => {
    try { await post("/api/plan/unassign", { platform: S.platform, id: b.dataset.unassign, month: d.month }); toast("Plan unassigned"); refreshOverview(); } catch (e) { toast(e.message, true); }
    again(); });
  view.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => { PLAN.status = "all"; PLAN.topic = ""; PLAN.open.add(b.dataset.jump); again().then?.(() => 0);
    setTimeout(() => $(`[data-plan="${b.dataset.jump}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 80); });
  // a day of the calendar picks the date for the plan being assigned; with no plan chosen it says what to do
  view.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => {
    if (PLAN.assign) { PLAN.assign.date = b.dataset.pick; return again(); }
    const first = shown.find(i => !i.assigned && i.status === "unassigned");
    if (!first) return toast(c.plans ? "Every plan is already assigned or published" : "Generate the plan first, then assign its plans to days", !c.plans);
    setAssign(first.id, b.dataset.pick); PLAN.status = "unassigned"; again(); });
  // drag a plan onto a day
  view.querySelectorAll("[data-plan][draggable]").forEach(el => el.addEventListener("dragstart", e => e.dataTransfer.setData("text/plain", el.dataset.plan)));
  view.querySelectorAll("[data-drop]").forEach(cell => {
    cell.addEventListener("dragover", e => { e.preventDefault(); cell.classList.add("ring-2", "ring-violet-300"); });
    cell.addEventListener("dragleave", () => cell.classList.remove("ring-2", "ring-violet-300"));
    cell.addEventListener("drop", e => { e.preventDefault(); const id = e.dataTransfer.getData("text/plain"); if (!itemById(id)) return;
      setAssign(id, cell.dataset.drop); if (isYt) return again(); doAssign(); });
  });
  $("#p-gen").onclick = async () => {
    if (!d.topics.length) { toast(`Add topics for ${app.label} in Settings first`, true); location.hash = "settings"; return; }
    view.querySelectorAll("button").forEach(x => x.disabled = true);
    $("#p-state").textContent = "The Planner is writing the plans for your topics (about a minute per topic)…";
    try { const r = await post("/api/plan/generate", { platform: S.platform, month: d.month });
      toast(r.added ? `${r.added} plan(s) written${r.failed ? `; ${r.failed} topic(s) failed` : ""}` : "Every topic already has its 10 plans"); refreshOverview(); }
    catch (e) { toast(e.message, true); }
    PLAN.busy = ""; again();
  };
}
VIEWS.plan = renderPlan;
