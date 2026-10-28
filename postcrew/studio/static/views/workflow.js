/* Workflow view: copied from design/stitch/workflow-live-youtube-run.html. Logic (run picker, polling, step drawer, timeline,
   crew memory) comes from the old working Studio (design/legacy/app.js). Real run data only. */
"use strict";

const WF = { runs: [], steps: [], budget: null, filter: "all", search: "", graphKey: "", wfConfig: null,
  logSig: "", logN: 0, drawerSig: "", art: {}, open: new Set(), openD: new Set() };

/* A poll that finds nothing new must not touch the page: redraw an element only when its HTML changed (no flicker, no restarted
   spinners, no collapsed "View details"). Returns true when it did redraw, so the caller can attach its handlers again. */
function wfSet(el, html) { if (!el || el.dataset.sig === html) return false; el.innerHTML = html; el.dataset.sig = html; return true; }

const wfDur = info => { if (!info?.started_at) return ""; const a = new Date(info.started_at), b = info.finished_at ? new Date(info.finished_at) : new Date();
  const s = (b - a) / 1000; return s < 0 ? "" : s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`; };
const wfClock = ms => { const s = Math.max(0, Math.round(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const wfElapsed = st => st?.started_at ? wfClock((st.finished_at ? new Date(st.finished_at) : new Date()) - new Date(st.started_at)) : "00:00";
const wfTok = t => (t?.in || 0) + (t?.cached || 0) + (t?.out || 0);
const wfK = n => n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n || 0}`;

/* node look per state: [box classes, chip classes, chip icon, spins, word, text colour] (design.md colour code) */
const WF_NODE = {
  passed: ["bg-white border-2 border-emerald-500/80 shadow-sm hover:shadow-md", "text-emerald-700 bg-emerald-50 border-emerald-200 font-bold", "check_circle", false, "Done", "text-emerald-700"],
  running: ["bg-violet-50/70 border-2 border-violet-600 shadow-md ring-4 ring-violet-100", "text-violet-700 bg-violet-100 border-violet-300 font-bold", "progress_activity", true, "Active", "text-violet-700"],
  retrying: ["bg-violet-50/70 border-2 border-violet-600 shadow-md ring-4 ring-violet-100", "text-violet-700 bg-violet-100 border-violet-300 font-bold", "progress_activity", true, "Retrying", "text-violet-700"],
  waiting: ["bg-white border border-amber-300 shadow-sm opacity-80 hover:opacity-100", "text-amber-700 bg-amber-50 border-amber-200 font-semibold", "schedule", false, "Wait", "text-amber-700"],
  failed: ["bg-rose-50/40 border-2 border-rose-500 shadow-md ring-4 ring-rose-100", "text-rose-700 bg-rose-100 border-rose-300 font-bold", "cancel", false, "Flagged", "text-rose-700"],
  blocked: ["bg-rose-50/40 border-2 border-rose-500 shadow-md ring-4 ring-rose-100", "text-rose-700 bg-rose-100 border-rose-300 font-bold", "cancel", false, "Blocked", "text-rose-700"],
  skipped: ["bg-white border border-slate-200 shadow-sm opacity-60 hover:opacity-90", "text-slate-600 bg-slate-100 border-slate-200 font-semibold", "remove_circle_outline", false, "Skipped", "text-slate-500"],
  pending: ["bg-white border border-slate-200 shadow-sm opacity-60 hover:opacity-90", "text-slate-600 bg-slate-100 border-slate-200 font-semibold", "pause_circle", false, "Idle", "text-slate-500"],
};
const WF_LINE = { passed: "Completed", running: "Working now", retrying: "Trying again", waiting: "Waiting for approval", failed: "Sent back", blocked: "Blocked",
  skipped: "Not needed this run", pending: "Waiting for its turn" };

async function renderWorkflow() {
  const view = $("#view");
  view.innerHTML = `<main class="space-y-6" data-active-view="workflow"><div class="py-16">${emptyState("progress_activity", "Loading the workflow")}</div></main>`;
  try {
    const [{ runs }, ag, cfg] = await Promise.all([api("/api/runs"), api("/api/agents"), api("/api/config").catch(() => null), loadAgents()]);
    WF.runs = runs; WF.steps = ag.steps || []; WF.budget = cfg?.config?.pipeline?.max_run_budget_usd || null;
  } catch (e) { view.innerHTML = errorBanner(e.message); return; }
  const mineRuns = WF.runs;
  if ((!S.runId || !mineRuns.some(r => r.run_id === S.runId)) && mineRuns.length) { S.runId = mineRuns[0].run_id; S.selected = null; }
  view.innerHTML = `<main class="space-y-6" data-active-view="workflow">
    <section class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-4" id="wf-crumb"></div>
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-4" id="wf-head"></div>
    </section>
    <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-5 relative overflow-hidden">
      <div class="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-100">
        <div class="flex items-center gap-2">
          <div class="p-1.5 rounded-lg bg-violet-50 text-violet-700">${icon("schema", "text-[20px]")}</div>
          <div><h2 class="font-headline font-bold text-slate-900 text-sm">Assembly chain</h2>
            <p class="text-xs text-slate-500">Every agent in turn, live, with the work sent back when something is not good enough</p></div>
        </div>
        <div class="flex items-center gap-3 text-[11px] font-medium text-slate-600 overflow-x-auto py-1">
          <div class="flex items-center gap-1">${icon("check_circle", "text-[14px] text-emerald-600")}<span>Passed</span></div>
          <div class="flex items-center gap-1">${icon("progress_activity", "text-[14px] text-violet-600 animate-spin")}<span>Running</span></div>
          <div class="flex items-center gap-1">${icon("schedule", "text-[14px] text-amber-600")}<span>Waiting</span></div>
          <div class="flex items-center gap-1">${icon("cancel", "text-[14px] text-rose-600")}<span>Rejected / Loop</span></div>
        </div>
      </div>
      <div class="relative pt-6 pb-12 overflow-x-auto custom-scrollbar" id="wf-graph"></div>
    </section>
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      <section class="lg:col-span-8 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col overflow-hidden" id="wf-log"></section>
      <section class="lg:col-span-4 bg-white rounded-2xl border-2 border-violet-200 shadow-lg p-5 space-y-4" id="wf-drawer"></section>
    </div>
    <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <div class="flex items-center gap-2">${icon("psychology", "text-[20px] text-violet-700")}<h2 class="font-headline font-bold text-slate-900 text-base">Working memory</h2></div>
      <p class="text-xs text-slate-500 mt-1 mb-3">What went wrong during this run, who sent the work back and why. An agent that is sent back sees all of it, so a fix is not undone in a later round. Fixed problems are kept for future runs.</p>
      <div id="wf-memory" class="space-y-2"></div>
    </section></main>`;
  drawCrumb();
  if (!S.runId) { drawEmptyRun(); return; }
  await loadRun(true);
  S.poll = setInterval(() => { if (S.run?.status.state === "running") loadRun(false); }, 1500);
}

function drawEmptyRun() {
  $("#wf-head").innerHTML = `<div class="lg:col-span-12 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">${emptyState("schema", "No runs yet. Start the crew from the Overview and it will appear here, live.")}</div>`;
  $("#wf-graph").innerHTML = ""; $("#wf-log").innerHTML = ""; $("#wf-drawer").innerHTML = ""; $("#wf-memory").innerHTML = "";
}

function drawCrumb() {
  const st = S.run?.status, meta = st?.meta || {}, pf = meta.platform || S.platform;
  const picker = `<select id="wf-pick" class="inline-flex items-center gap-1 font-semibold text-slate-900 bg-white px-2 py-0.5 rounded border border-slate-200 shadow-sm text-xs md:text-sm" title="Choose a run">
    ${WF.runs.map(r => `<option value="${esc(r.run_id)}" ${r.run_id === S.runId ? "selected" : ""}>${esc(r.run_id)} · ${esc(r.meta?.category || "")} · ${esc(r.state)}</option>`).join("") || "<option>No runs yet</option>"}</select>`;
  const html = `<div class="flex items-center gap-2 text-xs md:text-sm text-slate-500">
      <span class="text-slate-600 font-medium">Workflow</span>${icon("chevron_right", "text-[16px] text-slate-400")}${picker}
      ${st ? `${icon("chevron_right", "text-[16px] text-slate-400")}
      <div class="inline-flex items-center gap-2 font-headline font-bold text-slate-900 text-sm md:text-base">
        <span class="border-l-4 ${appOf(pf).border} pl-2">${esc(meta.label || meta.category || S.runId)}</span>
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${appOf(pf).soft}">${appBadge(pf)}${esc(appName(pf))}${meta.dry_run ? " · practice run" : ""}</span>
      </div>` : ""}</div>
    <div class="flex items-center gap-2 text-xs text-slate-500">${icon("hub", "text-[16px] text-slate-400")}<span>${st ? `Started ${esc(fmtTime(st.started_at))}${meta.date ? ` for ${esc(meta.date)}` : ""}` : "No run selected"}</span></div>`;
  if (wfSet($("#wf-crumb"), html)) $("#wf-pick").onchange = e => { S.runId = e.target.value; S.selected = null; WF.graphKey = ""; loadRun(true); };
}

async function loadRun(reset) {
  if (reset) { S.events = []; S.lastT = 0; WF.logSig = ""; WF.logN = 0; WF.drawerSig = ""; WF.open.clear(); WF.openD.clear(); }
  try {
    const d = await api(`/api/runs/${encodeURIComponent(S.runId)}?after=${S.lastT}`);
    S.run = d; S.events = S.events.concat(d.events);
    if (S.events.length) S.lastT = S.events[S.events.length - 1].t;
  } catch (e) { toast(e.message, true); return; }
  if (!$("#wf-head")) return;   // the user left this view while the request was in flight
  if (!S.selected || !S.run.status.steps[S.selected]) {
    const o = Object.entries(S.run.status.steps);
    S.selected = (o.find(([, x]) => ["running", "retrying", "failed", "blocked"].includes(x.state)) || o.filter(([, x]) => x.state !== "pending").at(-1) || o[0] || [null])[0];
  }
  drawCrumb(); drawHead(); drawGraph(reset); drawLog(); drawMemory(); drawDrawer();
}

/* ---------- banner: status + controls, cost + tokens ---------- */
function drawHead() {
  const st = S.run.status, run = st.state, active = run === "running";
  const title = active ? "Pipeline active" : run === "failed" ? "Run failed" : run === "passed" || run === "succeeded" || run === "published" ? "Run finished" : `Run ${run}`;
  const cur = Object.entries(st.steps).find(([, x]) => ["running", "retrying"].includes(x.state));
  const done = Object.values(st.steps).filter(x => ["passed", "skipped"].includes(x.state)).length, total = Object.keys(st.steps).length;
  const t = st.tokens || {}, cost = st.cost_usd || 0, pct = WF.budget ? Math.min(100, cost / WF.budget * 100) : 0;
  const retries = Object.values(st.steps).reduce((a, x) => a + Math.max(0, (x.attempts || 0) - 1), 0);
  const html = `
    <div class="lg:col-span-7 bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center gap-3.5">
        <div class="w-10 h-10 rounded-xl bg-violet-100 text-violet-700 flex items-center justify-center">${icon(active ? "sync" : run === "failed" ? "error" : "check_circle", `text-[24px]${active ? " animate-spin" : ""}`)}</div>
        <div>
          <div class="flex items-center gap-2">
            <h1 class="font-headline font-bold text-slate-900 text-sm md:text-base">${esc(title)}${retries ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}` : ""}</h1>
            ${cur ? `<span class="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1">${icon("published_with_changes", "text-[13px]")}${esc(agentName(cur[0]))}</span>` : chip(run === "passed" ? "passed" : run)}
          </div>
          <p class="text-xs text-slate-500 mt-0.5 flex items-center gap-1.5">${icon("timer", "text-[14px] text-slate-400")}<span>Elapsed: <strong data-el class="font-mono text-slate-700">00:00</strong></span>
            <span class="text-slate-300">•</span><span>${tip(`${st.interventions || 0} supervisor intervention(s)`, "How many times the supervisor sent work back to an earlier agent")}</span></p>
          ${st.result ? `<p class="text-xs mt-1 ${run === "failed" ? "text-rose-700" : "text-slate-500"}">${esc(st.result)}</p>` : ""}
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button disabled title="Coming soon" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-700 text-xs font-semibold transition-colors active:scale-95 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed">${icon("pause", "text-[16px] text-slate-600")}<span>Pause run</span></button>
        <button disabled title="Coming soon" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-200 bg-red-50 hover:bg-red-100 text-red-700 text-xs font-semibold transition-colors active:scale-95 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed">${icon("stop", "text-[16px] text-red-600")}<span>Stop</span></button>
        <button disabled title="Coming soon" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold transition-colors active:scale-95 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed">${icon("replay", "text-[16px] text-slate-600")}<span>Re-run</span></button>
      </div>
    </div>
    <div class="lg:col-span-5 bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex flex-col justify-between gap-2.5">
      <div class="flex items-center justify-between text-xs">
        <div class="flex items-center gap-1 text-slate-600 font-medium">${icon("payments", "text-[16px] text-slate-400")}<span>Total cost: <strong class="text-slate-900 font-bold">${money(cost)}</strong>${WF.budget ? ` <span class="text-slate-400">/ $${WF.budget.toFixed(2)} cap</span>` : ""}</span></div>
        <div class="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">${icon("speed", "text-[13px]")}<span>${done} of ${total} steps done</span></div>
      </div>
      <div class="space-y-1">
        ${WF.budget ? `<div class="w-full bg-slate-100 rounded-full h-2 overflow-hidden flex"><div class="h-full bg-gradient-to-r from-emerald-500 to-violet-600 rounded-full transition-all duration-500" style="width: ${pct.toFixed(0)}%;"></div></div>` : ""}
        <div class="flex items-center justify-between text-[11px] text-slate-500">
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>${WF.budget ? tip(`${pct.toFixed(0)}% of budget used`, "Spent so far against the most one post is allowed to cost (Settings)") : "No spending cap set"}</span>
          <span class="font-mono">Tokens: <span class="text-slate-700 font-medium">${wfK(t.in)} fresh</span> · <span class="text-slate-500">${wfK(t.cached)} cached</span> · <span class="text-violet-700 font-medium">${wfK(t.out)} out</span></span>
        </div>
      </div>
    </div>`;
  wfSet($("#wf-head"), html);
  const clock = $("#wf-head [data-el]"); if (clock) clock.textContent = wfElapsed(st);   // only the clock ticks
}

/* ---------- pipeline of agent nodes ---------- */
function wfRewinds() {
  const rewinds = {}; let failing = null;
  S.events.forEach(e => {
    if (e.kind === "rejected") failing = e.step;
    if (e.kind === "decision" && e.data?.action === "rewind" && failing) { const k = `${failing}>${e.data.target}`; rewinds[k] = (rewinds[k] || 0) + 1; }
  });
  return Object.entries(rewinds).map(([k, n]) => [...k.split(">"), n]);
}

function nodeHtml(id, st) {
  const info = st.steps[id] || { state: "pending", attempts: 0 };
  const [box, chipCls, ic, spin, word, tc] = WF_NODE[info.state] || WF_NODE.pending;
  const sel = S.selected === id, selCls = sel && !/ring-4/.test(box) ? " ring-4 ring-violet-100" : "", dur = wfDur(info), team = teamOf(id);
  const line = info.state === "retrying" ? `Trying again · attempt ${info.attempts}` : `${WF_LINE[info.state] || info.state}${dur && info.state === "passed" ? ` · ${dur}` : ""}${info.state === "running" && info.attempts > 1 ? ` · attempt ${info.attempts}` : ""}`;
  return `<button type="button" data-step="${esc(id)}" class="flex-1 min-w-0 text-left rounded-xl p-3 flex flex-col justify-between transition-all cursor-pointer ${box}${selCls}">
    <div class="flex items-start justify-between gap-1 mb-2">
      ${avatar(id, "w-8 h-8").replace("text-white", "text-white shadow-sm")}
      <span class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${chipCls}">${icon(ic, `text-[12px]${spin ? " animate-spin" : ""}`)}<span>${esc(dur && info.state === "passed" ? dur : word)}</span></span>
    </div>
    <div>
      <div class="text-[10px] font-semibold tracking-wide ${info.state === "running" ? "text-violet-700" : "text-slate-400"} uppercase flex items-center gap-1"><span>${esc(agentTitle(id))}</span>${sel ? `<span class="w-1.5 h-1.5 rounded-full bg-violet-600" title="Selected agent"></span>` : ""}</div>
      <h3 class="font-headline font-bold text-slate-900 text-xs mt-0.5">${esc(agentName(id))}</h3>
      <p class="text-[11px] ${tc} font-medium mt-1">${esc(line)}</p>
    </div>
    <div class="mt-2 pt-2 border-t border-slate-100 text-[10px] text-slate-500 flex items-center justify-between"><span>${info.attempts > 1 ? `${info.attempts} tries` : "Tries"}</span><span class="font-semibold ${info.state === "passed" ? "text-emerald-600" : "text-slate-700"}">${info.cost_usd ? money(info.cost_usd) : info.attempts || 0}</span></div>
  </button>`;
}

function drawGraph(force) {
  const st = S.run?.status, el = $("#wf-graph"); if (!st || !el) return;
  const rw = wfRewinds();
  const key = JSON.stringify([st.state, st.interventions, Object.values(st.steps).map(x => [x.state, x.attempts, x.cost_usd]), S.selected, rw]);
  if (!force && key === WF.graphKey) return;
  WF.graphKey = key;
  const ids = Object.keys(st.steps);
  el.innerHTML = `<div class="flex items-stretch gap-2.5 min-w-[1240px] relative z-20 pt-4" id="wf-nodes">${ids.map((id, i) =>
    (i ? `<div class="flex items-center justify-center text-slate-300">${icon("arrow_forward", "text-[18px]")}</div>` : "") + nodeHtml(id, st)).join("")}</div>`;
  el.querySelectorAll("[data-step]").forEach(n => n.onclick = () => { S.selected = n.dataset.step; WF.graphKey = ""; drawGraph(true); drawDrawer(); drawLog(); });
  // sent-back arrows: measured from the real node positions
  const wrap = $("#wf-nodes");
  const at = id => { const n = wrap.querySelector(`[data-step="${CSS.escape(id)}"]`); return n ? [n.offsetLeft + n.offsetWidth / 2, n.offsetTop] : null; };
  let svg = "", labels = "";
  rw.forEach(([from, to, n], idx) => {
    const a = at(from), b = at(to); if (!a || !b) return;
    const up = -14 - idx * 10;
    svg += `<path d="M ${a[0]} ${a[1]} C ${a[0]} ${up}, ${b[0]} ${up}, ${b[0]} ${b[1] - 3}" fill="none" class="stroke-rose-600" stroke-dasharray="6 4" stroke-width="2.5"></path>
      <polygon class="fill-rose-600" points="${b[0]},${b[1]} ${b[0] - 5},${b[1] - 12} ${b[0] + 5},${b[1] - 12}"></polygon>`;
    labels += `<div class="absolute pointer-events-none transform -translate-x-1/2 -translate-y-1/2" style="left:${(a[0] + b[0]) / 2}px;top:${up * .75 + 4}px"><div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-rose-50 border border-rose-300 text-rose-700 text-[11px] font-bold shadow-md whitespace-nowrap">${icon("replay", "text-[14px] text-rose-600")}<span>Sent back to ${esc(agentName(to))}${n > 1 ? ` ×${n}` : ""}</span></div></div>`;
  });
  if (svg) wrap.insertAdjacentHTML("afterbegin", `<div class="absolute inset-x-0 top-0 pointer-events-none h-full z-10"><svg class="w-full h-full overflow-visible" fill="none">${svg}</svg>${labels}</div>`);
}

/* ---------- audit timeline ---------- */
const WF_FILTERS = [["all", "All events"], ["agent", "Agent actions"], ["gate", "Revisions & gates"], ["system", "System & tokens"]];
const wfIsGate = e => ["rejected", "decision"].includes(e.kind);
const wfIsSystem = e => !S.run?.status.steps[e.step];
function wfEvents() {
  const q = WF.search.trim().toLowerCase(), only = S.selected && $("#wf-only")?.checked;
  return S.events.filter(e => (!only || e.step === S.selected)
    && (WF.filter === "all" || (WF.filter === "gate" ? wfIsGate(e) : WF.filter === "system" ? wfIsSystem(e) : !wfIsGate(e) && !wfIsSystem(e)))
    && (!q || `${e.step} ${e.kind} ${e.message}`.toLowerCase().includes(q)));
}

function drawLog() {
  const el = $("#wf-log"); if (!el) return;
  if (!$("#wf-rows")) {
    el.innerHTML = `<div class="p-4 border-b border-slate-100 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-2">${icon("receipt_long", "text-[20px] text-violet-700")}<h2 class="font-headline font-bold text-slate-900 text-base">Execution audit timeline</h2><span id="wf-count" class="px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700"></span></div>
        <label class="flex items-center gap-2 text-xs font-medium text-slate-600 cursor-pointer select-none"><input id="wf-only" class="w-4 h-4 rounded text-violet-600 border-slate-300 focus:ring-violet-500" type="checkbox"/><span class="flex items-center gap-1">${icon("filter_list", "text-[15px] text-emerald-600")}<span>Only the selected step</span></span></label>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div class="flex items-center gap-1.5 overflow-x-auto text-xs" id="wf-filters"></div>
        <div class="relative w-full sm:w-56">${icon("search", "absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-[17px]")}<input id="wf-search" class="w-full pl-8 pr-3 py-1 text-xs rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500" placeholder="Search event logs..." type="text"/></div>
      </div></div>
      <div class="divide-y divide-slate-100 max-h-[560px] overflow-y-auto custom-scrollbar p-2" id="wf-rows"></div>
      <div class="px-4 py-2.5 border-t border-slate-100 bg-slate-50/60 flex items-center justify-between text-[11px] text-slate-500"><span class="flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span id="wf-live"></span></span>
        <button id="wf-export" class="text-violet-700 font-semibold flex items-center gap-1 hover:underline">${icon("download", "text-[14px]")}<span>Export raw JSON logs</span></button></div>`;
    $("#wf-rows").addEventListener("toggle", ev => { const k = ev.target.dataset?.ek; if (k) ev.target.open ? WF.open.add(k) : WF.open.delete(k); }, true);   // remember opened details
    $("#wf-only").onchange = drawLog;
    $("#wf-search").oninput = e => { WF.search = e.target.value; drawLog(); };
    $("#wf-export").onclick = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(S.events, null, 2)], { type: "application/json" }));
      a.download = `${S.runId}-events.json`; a.click(); };
  }
  const gates = S.events.filter(wfIsGate).length;
  const filtersHtml = WF_FILTERS.map(([k, l]) => {
    const on = WF.filter === k, n = k === "all" ? ` (${S.events.length})` : k === "gate" ? ` (${gates})` : "";
    return `<button data-f="${k}" class="px-3 py-1 rounded-full ${on ? "font-semibold bg-violet-600 text-white shadow-sm" : k === "gate" ? "font-medium text-rose-700 bg-rose-50 border border-rose-200 hover:bg-rose-100 flex items-center gap-1" : "font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 transition-colors"}">${k === "gate" && !on ? icon("published_with_changes", "text-[13px]") : ""}<span>${l}${n}</span></button>`; }).join("");
  if (wfSet($("#wf-filters"), filtersHtml)) $("#wf-filters").querySelectorAll("[data-f]").forEach(b => b.onclick = () => { WF.filter = b.dataset.f; drawLog(); });
  const evs = wfEvents(), t0 = S.run?.status.started_at ? new Date(S.run.status.started_at) : null, rows = $("#wf-rows");
  const atBottom = rows.scrollHeight - rows.scrollTop - rows.clientHeight < 40;
  $("#wf-count").textContent = `${S.events.length} events`;
  $("#wf-live").textContent = S.run?.status.state === "running" ? "Live: updating every second" : "Run finished";
  const row = e => {
    const bad = wfIsGate(e) || e.level === "error", warn = e.level === "warning", t = t0 ? wfClock(new Date(e.ts) - t0) : esc(e.ts.slice(11, 19));
    return `<div class="p-3.5 rounded-lg ${bad ? "bg-rose-50/50 border border-rose-200 hover:bg-rose-50 my-1" : "hover:bg-slate-50"} transition-colors flex items-start gap-3.5">
      <div class="font-mono text-xs font-${bad ? "bold text-rose-700" : "semibold text-slate-500"} pt-0.5 whitespace-nowrap">${t}</div>
      ${avatar(e.step, "w-7 h-7").replace("text-white", "text-white shadow-sm")}
      <div class="flex-1 min-w-0 space-y-1">
        <div class="flex flex-wrap items-center gap-1.5"><span class="font-headline font-bold text-xs text-slate-900">${esc(agentName(e.step))}</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-bold border ${bad ? "bg-rose-100 text-rose-800 border-rose-300" : warn ? "bg-amber-50 text-amber-800 border-amber-200" : "bg-emerald-50 text-emerald-800 border-emerald-200"}">${esc(String(e.kind).replace(/_/g, " "))}</span></div>
        <p class="text-xs ${bad ? "text-slate-800 font-medium" : "text-slate-700"} leading-relaxed break-words">${esc(e.message)}</p>
        ${e.data ? `<details data-ek="${esc(String(e.t ?? e.ts))}" ${WF.open.has(String(e.t ?? e.ts)) ? "open" : ""} class="text-[11px]"><summary class="text-rose-700 font-semibold cursor-pointer underline">${icon("visibility", "text-[13px] align-middle")} View details</summary><pre class="mt-1 p-2 rounded bg-slate-50 border border-slate-200 text-[11px] overflow-x-auto">${esc(JSON.stringify(e.data, null, 2))}</pre></details>` : ""}
      </div></div>`; };
  // append only the new events when nothing about the view changed: the rows already on the page (and any open "View details") stay
  const sig = JSON.stringify([S.runId, WF.filter, WF.search, !!$("#wf-only")?.checked, $("#wf-only")?.checked ? S.selected : null]);
  if (sig === WF.logSig && WF.logN > 0 && evs.length >= WF.logN) {
    if (evs.length > WF.logN) rows.insertAdjacentHTML("beforeend", evs.slice(WF.logN).map(row).join(""));
  } else {
    rows.innerHTML = evs.map(row).join("") || `<div class="py-8">${emptyState("receipt_long", "No events yet.")}</div>`;
  }
  WF.logSig = sig; WF.logN = evs.length;
  if (atBottom) rows.scrollTop = rows.scrollHeight;
}

/* ---------- crew memory ---------- */
function wfMemEntry(e) {
  const list = (lbl, xs) => xs?.length ? `<div class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mt-2">${lbl}</div><ul class="list-disc pl-5 text-xs text-slate-700 space-y-0.5">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const who = `<span class="inline-flex items-center gap-1.5 font-headline font-bold text-xs text-slate-900">${avatar(e.step, "w-6 h-6")} ${esc(agentName(e.step))}</span>`;
  if (e.kind === "passed") return `<div class="p-3 rounded-lg bg-emerald-50/50 border border-emerald-200 flex items-center gap-2 flex-wrap">${who}<span class="text-xs text-slate-600">${esc(agentTitle(e.step))} passed on attempt ${esc(e.attempt)}</span></div>`;
  return `<div class="p-3 rounded-lg bg-rose-50/50 border border-rose-200">${who}<span class="text-xs text-slate-600"> · ${esc(agentTitle(e.step))} sent back by ${esc(e.by)} · ${esc((e.at || "").slice(11, 19))}</span>${list("Why it failed", e.why)}${list("What to change", e.instructions)}</div>`;
}
function drawMemory() {
  const el = $("#wf-memory"); if (!el) return;
  const mem = S.run?.memory || [];
  wfSet(el, mem.length ? mem.slice().reverse().map(wfMemEntry).join("") : emptyState("check_circle", "Nothing yet: no agent has been sent back in this run."));
}

/* ---------- selected agent drawer ---------- */
async function drawDrawer() {
  const el = $("#wf-drawer"), s = S.selected, st = S.run?.status; if (!el || !s || !st) return;
  const info = st.steps[s] || {}, tk = info.tokens || {}, state = info.state || "pending";
  const back = (S.run.memory || []).filter(e => e.step === s && e.kind === "sent_back");
  const fixes = back.at(-1)?.instructions || [], working = ["running", "retrying"].includes(state);
  const clock = el.querySelector("[data-dur]"); if (clock) clock.textContent = wfDur(info) || "-";   // the running time keeps ticking
  const mine = (S.run.files || []).filter(f => f === `${s}.json` || f.startsWith(`${s}.rejected.`));
  const sig = JSON.stringify([S.runId, s, { ...info, started_at: 0, finished_at: info.finished_at || 0 }, back.length, fixes, mine]);
  if (sig === WF.drawerSig) return;   // nothing changed: leave the panel (and its video player) alone
  WF.drawerSig = sig;
  if (!el.dataset.bound) { el.dataset.bound = "1"; el.addEventListener("toggle", ev => { const k = ev.target.dataset?.ek; if (k) ev.target.open ? WF.openD.add(k) : WF.openD.delete(k); }, true); }
  const head = `<div class="flex items-start justify-between gap-3">
      <div class="flex items-center gap-3">${avatar(s, "w-12 h-12")}<div><div class="flex items-center gap-2"><h3 class="font-headline font-bold text-slate-900 text-lg">${esc(agentName(s))}</h3></div><p class="text-xs text-slate-500">${esc(agentTitle(s))}</p></div></div>
      ${chip(state)}</div>
    <div class="grid grid-cols-2 gap-2 text-xs">
      ${[["autorenew", "Attempts", `${info.attempts || 0}${back.length ? ` <span class="text-[10px] font-normal text-slate-400">sent back ${back.length}×</span>` : ""}`], ["payments", "Run cost", money(info.cost_usd)],
        ["timer", "Execution time", `<span data-dur>${wfDur(info) || "-"}</span>`], ["memory", "Tokens", wfK(wfTok(tk))]].map(([ic, l, v]) => `<div class="p-2.5 rounded-lg bg-slate-50 border border-slate-200/80"><div class="text-[11px] text-slate-500 flex items-center gap-1">${icon(ic, "text-[13px] text-slate-400")}<span>${l}</span></div><div class="font-headline font-bold text-slate-900 text-sm mt-0.5">${v}</div></div>`).join("")}
    </div>
    <div class="p-3 rounded-lg bg-violet-50/60 border border-violet-100 text-xs space-y-1.5">
      <div class="flex items-center justify-between font-semibold text-violet-900"><span class="flex items-center gap-1">${icon("memory", "text-[15px] text-violet-600")}<span>Token usage breakdown</span></span><span class="font-mono text-[11px]">${wfK(wfTok(tk))} total</span></div>
      <div class="text-[11px] text-slate-600 flex items-center justify-between"><span>Fresh: <strong class="text-slate-800">${wfK(tk.in)}</strong></span><span>Cached: <strong class="text-slate-800">${wfK(tk.cached)}</strong></span><span>Output: <strong class="text-violet-700">${wfK(tk.out)}</strong></span></div>
    </div>`;
  const summary = info.summary ? `<p class="text-xs text-slate-700">${esc(info.summary)}</p>` : "";
  const errs = info.errors?.length ? `<div class="space-y-1.5"><h4 class="font-headline font-bold text-xs text-slate-900 uppercase tracking-wider flex items-center gap-1">${icon("error", "text-[16px] text-rose-600")}<span>Problems found by validation</span></h4>
    ${info.errors.map(x => `<div class="p-2.5 rounded-lg bg-rose-50/70 border border-rose-200 text-[11px] text-rose-900">${esc(x)}</div>`).join("")}</div>` : "";
  const fixHtml = fixes.length ? `<div class="space-y-2.5 pt-1"><div class="flex items-center justify-between">
      <h4 class="font-headline font-bold text-xs text-slate-900 uppercase tracking-wider flex items-center gap-1">${icon("checklist", "text-[16px] text-rose-600")}<span>Exact fixes asked for</span></h4>
      <span class="text-[11px] font-semibold ${working ? "text-amber-700 bg-amber-50 border-amber-200" : "text-slate-600 bg-slate-50 border-slate-200"} px-2 py-0.5 rounded border">${working ? `${fixes.length} in progress` : `${fixes.length} sent`}</span></div>
      <p class="text-[11px] text-slate-500">Directives sent back to ${esc(agentName(s))} by ${esc(back.at(-1).by || "the supervisor")}:</p>
      <div class="space-y-2">${fixes.map((f, i) => `<div class="p-3 rounded-lg ${working ? "bg-amber-50/70 border border-amber-200" : "bg-slate-50 border border-slate-200"} space-y-1"><div class="flex items-start gap-2">${icon(working ? "check_box" : "check_box_outline_blank", `text-[18px] ${working ? "text-amber-700" : "text-slate-400"} mt-0.5`)}<div class="flex-1"><div class="text-xs font-semibold text-slate-900">Fix ${i + 1}</div><p class="text-[11px] text-slate-700 leading-snug mt-0.5">${esc(f)}</p>${working ? `<div class="mt-1 text-[10px] font-bold text-amber-800 flex items-center gap-1">${icon("progress_activity", "text-[12px] animate-spin")}<span>Re-drafting in ${esc(agentName(s))}</span></div>` : ""}</div></div></div>`).join("")}</div></div>` : "";
  const buttons = `<div class="pt-2 space-y-2 border-t border-slate-100">
      <button disabled title="Coming soon" class="w-full inline-flex items-center justify-center gap-2 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition-colors shadow-sm active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed">${icon("verified", "text-[17px]")}<span>Override and force pass</span></button>
      <div class="grid grid-cols-2 gap-2">
        <button disabled title="Coming soon" class="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed">${icon("difference", "text-[16px] text-slate-500")}<span>Inspect prompt diff</span></button>
        <button disabled title="Coming soon" class="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed">${icon("tune", "text-[16px] text-slate-500")}<span>Adjust threshold</span></button>
      </div></div>`;
  const base = `${head}${summary}${errs}${fixHtml}`;
  const artKey = `${S.runId}|${s}`;
  el.innerHTML = `${base}<div id="wf-art" class="space-y-3">${WF.art[artKey] || ""}</div>${buttons}`;   // the last pictures at once, refreshed below
  // artifacts of this step (output, rendered media, rejected attempts)
  let art = "";
  const rid = encodeURIComponent(S.runId), files = S.run.files || [];
  if (files.includes(`${s}.json`)) {
    try {
      const a = await (await fetch(`/api/runs/${rid}/artifact/${s}.json`)).json();
      if (s === "media" && a.path) {
        const url = `/api/runs/${rid}/file/${encodeURIComponent(a.path.split("/").pop())}`;
        art += `<h4 class="font-headline font-bold text-xs text-slate-900 uppercase tracking-wider">Rendered media</h4><div class="rounded-lg overflow-hidden border border-slate-200">${a.kind === "video" ? `<video class="w-full" src="${url}" controls muted playsinline></video>` : `<img class="w-full" src="${url}" alt="poster">`}</div>`;
      }
      if ((s === "writer" || s === "formatter") && a.text) art += `<h4 class="font-headline font-bold text-xs text-slate-900 uppercase tracking-wider">Text</h4><div class="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-800 whitespace-pre-wrap">${fmtPost(a.text)}</div>`;
      art += `<details data-ek="${esc(artKey)}" ${WF.openD.has(artKey) ? "open" : ""} class="text-xs"><summary class="cursor-pointer font-semibold text-slate-600">Output (JSON)</summary><pre class="mt-1 p-2 rounded bg-slate-50 border border-slate-200 text-[11px] overflow-x-auto">${esc(JSON.stringify(a, null, 2))}</pre></details>`;
    } catch (e) { /* artifact not readable yet */ }
  }
  const rej = files.filter(f => f.startsWith(`${s}.rejected.`));
  if (rej.length) art += `<h4 class="font-headline font-bold text-xs text-slate-900 uppercase tracking-wider">Rejected attempts</h4>` + rej.map(f => `<a href="/api/runs/${rid}/artifact/${encodeURIComponent(f)}" target="_blank" class="block text-[11px] font-mono text-violet-700 hover:underline">${esc(f)}</a>`).join("");
  const slot = $("#wf-art");
  if (slot && S.selected === s && WF.art[artKey] !== art) { WF.art[artKey] = art; slot.innerHTML = art; }   // only when it really changed
}

VIEWS.workflow = renderWorkflow;
