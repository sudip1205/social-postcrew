/* Manual run view: copied from design/stitch/manual-run.html. The only place a run is started by hand: pick a plan that is not on the calendar
   and make it now (YouTube: as a Short or a Long video). The scheduled runs are never started from the other pages. Real data only (/api/manual). */
"use strict";

const MAN = { items: [], topic: "", q: "", sort: "trend", fmt: {}, open: new Set(), busy: null, running: false, formats: false, def: "short", poll: null };

const manSort = {
  trend: (a, b) => ((b.research?.trend_score ?? -1) - (a.research?.trend_score ?? -1)) || a.title.localeCompare(b.title),
  views: (a, b) => ((b.research?.views_per_day ?? -1) - (a.research?.views_per_day ?? -1)) || a.title.localeCompare(b.title),
  newest: (a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")),
};
const manShown = () => MAN.items.filter(i => (!MAN.topic || i.topic === MAN.topic) && (!MAN.q || `${i.title} ${i.angle} ${i.topic}`.toLowerCase().includes(MAN.q.toLowerCase())))
  .sort(manSort[MAN.sort] || manSort.trend);

function manCard(i) {
  const fmt = MAN.fmt[i.id] || MAN.def, busy = MAN.busy === i.id, open = MAN.open.has(i.id), r = i.research;
  const segBtn = (v, ic, label) => `<button type="button" data-fmt="${v}" data-id="${i.id}" class="flex items-center gap-1 px-3 py-1 rounded-lg ${fmt === v ? "bg-white text-slate-900 shadow-sm border border-slate-200/70 font-bold" : "text-slate-500 hover:text-slate-900 font-medium transition-colors"}">${icon(ic, `text-[15px] ${fmt === v ? "text-red-600" : "text-slate-400"}`)}<span>${label}</span></button>`;
  const dis = busy || MAN.running;
  return `<div class="bg-white rounded-2xl ${busy ? "border-2 border-violet-300 ring-4 ring-violet-50" : "border-2 border-slate-200 hover:border-violet-300"} transition-all shadow-sm relative overflow-hidden group" data-plan="${i.id}">
    <div class="p-6">
      <div class="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
        <div class="space-y-3 flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-violet-50 text-violet-700 border border-violet-100"><span class="w-1.5 h-1.5 rounded-full bg-violet-600"></span>${esc(i.topic)}</span>
            ${busy ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-violet-100 text-violet-700 border border-violet-200">${icon("progress_activity", "text-[14px] animate-spin")}<span>Starting the crew</span></span>` : ""}
            <span class="text-xs text-slate-400 font-mono">${esc(i.month || "")}</span>
          </div>
          <h2 class="text-lg font-bold text-slate-900 group-hover:text-violet-700 transition-colors leading-snug">${esc(i.title)}</h2>
          <p class="text-xs text-slate-600 leading-relaxed font-medium"><span class="font-bold text-slate-700">Angle:</span> ${esc(i.angle)}</p>
          ${researchChips(r, "pt-1")}
          ${r && !r.unavailable ? `<div class="pt-1"><button type="button" data-more="${i.id}" class="inline-flex items-center gap-1 text-xs font-bold text-violet-600 hover:text-violet-800 transition-colors">${icon(open ? "expand_less" : "expand_more", "text-[16px]")}<span>Research details</span></button></div>` : ""}
        </div>
        <div class="flex flex-col items-start lg:items-end justify-between shrink-0 gap-3 min-w-[210px] pt-1">
          ${MAN.formats ? `<div class="inline-flex p-1 bg-slate-100 rounded-xl border border-slate-200 text-xs font-semibold self-start lg:self-end">${segBtn("short", "electric_bolt", "Short")}${segBtn("long", "video_library", "Long")}</div>` : ""}
          <div class="w-full flex flex-col items-start lg:items-end gap-1.5">
            <button type="button" data-run="${i.id}" ${dis ? "disabled" : ""} class="w-full lg:w-auto px-5 py-2.5 ${busy ? "bg-violet-100 text-violet-700" : "bg-violet-600 hover:bg-violet-700 active:bg-violet-800 text-white"} font-bold text-sm rounded-xl flex items-center justify-center gap-2 shadow-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed">${icon(busy ? "progress_activity" : "play_arrow", `text-[18px] ${busy ? "animate-spin" : ""}`, !busy)}<span>${busy ? "Starting…" : "Run now"}</span></button>
            ${busy ? `<a href="#workflow" class="inline-flex items-center gap-1 text-xs font-bold text-violet-700 hover:text-violet-900">Open in Workflow ${icon("arrow_forward", "text-[14px]")}</a>`
              : `<span class="text-[11px] font-medium text-slate-400 text-right">${MAN.formats ? (fmt === "long" ? "about 25 minutes, about $2.50" : "about 15 minutes, about $1.50") : "about 10 minutes, about $0.50"}</span>`}
          </div>
        </div>
      </div>
      ${open && r ? `<div class="mt-5 pt-4 border-t border-slate-100">${researchDetails(r)}</div>` : ""}
    </div>
    ${busy ? `<div class="h-1.5 bg-violet-100"><div class="h-1.5 bg-gradient-to-r from-violet-500 to-fuchsia-500 w-1/2 animate-pulse"></div></div>` : ""}
  </div>`;
}

function manDraw() {
  const list = $("#man-list"); if (!list) return;
  const shown = manShown();
  list.innerHTML = (shown.length ? shown.map(manCard).join("") : "") + `<div class="border-2 border-dashed border-slate-200 rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${shown.length ? "" : "bg-white"}">
    <div class="flex items-center gap-4"><div class="w-12 h-12 rounded-xl bg-white border border-slate-200 text-violet-600 flex items-center justify-center shadow-sm">${icon("inventory_2", "text-2xl")}</div>
      <div><h3 class="font-headline font-bold text-sm text-slate-900">${MAN.items.length ? "That is every plan waiting" : "No plans waiting"}</h3>
        <p class="text-xs text-slate-500">Generate this month's plan in the Plan page and the extra plans appear here.</p></div></div>
    <a href="#plan" class="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 shadow-sm">${icon("calendar_month", "text-[16px] text-violet-600")}<span>Go to Plan page</span>${icon("arrow_forward", "text-[14px]")}</a></div>`;
  const cnt = $("#man-count"); if (cnt) cnt.textContent = `${MAN.items.length} ${MAN.items.length === 1 ? "plan" : "plans"} waiting`;
  list.querySelectorAll("[data-fmt]").forEach(b => b.onclick = () => { MAN.fmt[b.dataset.id] = b.dataset.fmt; manDraw(); });
  list.querySelectorAll("[data-more]").forEach(b => b.onclick = () => { MAN.open.has(b.dataset.more) ? MAN.open.delete(b.dataset.more) : MAN.open.add(b.dataset.more); manDraw(); });
  list.querySelectorAll("[data-run]").forEach(b => b.onclick = () => manRun(b.dataset.run));
  const st = $("#man-status");
  if (st) st.innerHTML = MAN.running
    ? `<span class="relative flex h-2 w-2"><span class="relative inline-flex rounded-full h-2 w-2 bg-violet-500"></span></span><span>Crew busy</span><span class="text-violet-600 font-normal">· a run is in progress</span>`
    : `<span class="relative flex h-2 w-2"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span><span>Crew idle</span><span class="text-emerald-600 font-normal">· Ready for tasks</span>`;
  if (st) st.className = `flex items-center gap-2 px-3 py-1.5 ${MAN.running ? "bg-violet-50 text-violet-800 border-violet-200" : "bg-emerald-50 text-emerald-800 border-emerald-200"} border rounded-xl text-xs font-semibold shadow-sm`;
}

async function manRun(id) {
  const it = MAN.items.find(x => x.id === id); if (!it) return;
  const fmt = MAN.formats ? (MAN.fmt[id] || MAN.def) : null;
  if (!confirm(`Make "${it.title}" now${fmt ? ` as a ${fmt === "long" ? "Long" : "Short"} video` : ""}? The crew writes it, then it follows your approval setting (it may be published).`)) return;
  MAN.busy = id; manDraw();
  try {
    const r = await post("/api/manual/run", { platform: S.platform, id, ...(fmt ? { format: fmt } : {}) });
    S.runId = r.run_id; toast("Crew started"); location.hash = "workflow"; refreshOverview();
  } catch (e) { toast(e.message, true); MAN.busy = null; manLoad(); }
}

async function manLoad() {
  try {
    const d = await api(`/api/manual?platform=${S.platform}`);
    Object.assign(MAN, { items: d.items, formats: d.formats, def: d.default_format || "short", running: d.running });
    const topics = [...new Set(d.items.map(i => i.topic))];
    if (MAN.topic && !topics.includes(MAN.topic)) MAN.topic = "";
    const bar = $("#man-topics");
    if (bar) {
      bar.innerHTML = [["", "All topics"], ...topics.map(t => [t, t])].map(([v, l]) => `<button type="button" data-topic="${esc(v)}" class="px-3 py-1.5 rounded-xl whitespace-nowrap transition-colors ${MAN.topic === v ? "bg-violet-600 text-white font-bold shadow-sm hover:bg-violet-700" : "bg-slate-100 hover:bg-slate-200/80 text-slate-700 font-medium border border-slate-200/60"}">${esc(l)}</button>`).join("");
      bar.querySelectorAll("[data-topic]").forEach(b => b.onclick = () => { MAN.topic = b.dataset.topic; manLoadView(); });
    }
    manDraw();
  } catch (e) { toast(e.message, true); }
}
const manLoadView = () => { const bar = $("#man-topics"); if (bar) bar.querySelectorAll("[data-topic]").forEach(b => { const on = b.dataset.topic === MAN.topic; b.className = `px-3 py-1.5 rounded-xl whitespace-nowrap transition-colors ${on ? "bg-violet-600 text-white font-bold shadow-sm hover:bg-violet-700" : "bg-slate-100 hover:bg-slate-200/80 text-slate-700 font-medium border border-slate-200/60"}`; }); manDraw(); };

function renderManual() {
  const view = $("#view"), a = appOf(S.platform);
  view.innerHTML = `<main class="space-y-6" data-active-view="manual">
    <div class="flex flex-col md:flex-row md:items-end justify-between gap-4">
      <div>
        <nav class="flex items-center gap-1.5 text-xs text-slate-500 mb-1.5"><span>Production Studio</span>${icon("chevron_right", "text-[14px] text-slate-400")}<span class="text-violet-700 font-medium">Manual run</span></nav>
        <h1 class="font-headline text-3xl font-extrabold tracking-tight text-slate-900">Manual Run</h1>
        <p class="text-sm text-slate-500 mt-1">Pick a plan that is not on the calendar and make it now. Scheduled runs are never started from here.</p>
      </div>
      <div class="flex items-center flex-wrap gap-2.5">
        <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border ${a.border || "border-slate-200"} bg-white text-xs font-semibold text-slate-700 shadow-sm">${appBadge(S.platform)}<span>${esc(a.name || S.platform)}</span></span>
        <div id="man-status" class="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-xl text-xs font-semibold shadow-sm"></div>
      </div>
    </div>
    <div class="bg-white rounded-2xl p-4 border border-slate-200/90 shadow-sm flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
      <div class="relative flex-1 max-w-md">${icon("search", "absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 text-[20px]")}
        <input id="man-q" type="text" placeholder="Search plans..." class="w-full pl-10 pr-4 py-2 bg-slate-50 hover:bg-slate-100/80 focus:bg-white text-sm rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition-all placeholder:text-slate-400 font-medium"/></div>
      <div id="man-topics" class="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 text-xs"></div>
      <div class="flex items-center gap-3 shrink-0">
        <div class="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-xs font-medium text-slate-600">${icon("sort", "text-[16px] text-slate-400")}
          <select id="man-sort" class="bg-transparent focus:outline-none font-semibold text-slate-700 cursor-pointer" aria-label="Sort plans"><option value="trend">Most trending first</option><option value="views">Highest views a day</option><option value="newest">Recently generated</option></select></div>
        <div class="px-3 py-1.5 bg-violet-50 text-violet-700 font-bold text-xs rounded-xl border border-violet-200 flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-violet-600"></span><span id="man-count">0 plans waiting</span></div>
      </div>
    </div>
    <div id="man-list" class="space-y-4">${emptyState("progress_activity", "Loading the plans")}</div>
  </main>`;
  $("#man-q").oninput = e => { MAN.q = e.target.value; manDraw(); };
  $("#man-sort").value = MAN.sort; $("#man-sort").onchange = e => { MAN.sort = e.target.value; manDraw(); };
  manLoad();
  clearInterval(MAN.poll); MAN.poll = setInterval(() => { if (S.tab !== "manual") clearInterval(MAN.poll); else if (!MAN.busy) manLoad(); }, 8000);
}

VIEWS.manual = renderManual;
