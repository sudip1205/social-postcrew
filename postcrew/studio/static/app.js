/* Postcrew Studio core: state, API, router, shell (top bar, banner, footer) and the notifications drawer.
   Each screen lives in views/<name>.js and registers itself in VIEWS; their look comes from design/stitch (see ui.js). */
"use strict";

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };
const PROVIDERS = { "claude-code": "Claude Code (Claude plan)", anthropic: "Claude API", openai: "OpenAI API", "openai-compatible": "OpenAI-compatible server", demo: "Demo (scripted answers, no AI)" };
const PLATFORM_IDS = ["linkedin", "youtube"];
const TABS = [["overview", "Overview", "dashboard"], ["plan", "Plan", "calendar_month"], ["team", "Crew", "groups"], ["workflow", "Workflow", "schema"],
  ["queue", "Queue", "format_list_bulleted"], ["settings", "Settings", "settings"], ["credentials", "Credentials", "key"]];
// the <main> of each Stitch screen (design/stitch/<screen>.html): page width, padding and spacing differ per screen
const PAGE = {
  overview: "max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8",
  plan: "flex flex-col",   // Stitch: header bar, then <main class="flex-1 flex overflow-hidden"> (inside the view)
  queue: "w-full max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col gap-6",
  workflow: "w-full max-w-[1560px] mx-auto p-4 md:p-6 space-y-6",
  settings: "max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8",
  team: "max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6",     // no Stitch screen: same as Overview
  credentials: "max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6",
};
const VIEWS = {};   // tab id -> render function, registered by views/*.js

const S = { platform: "linkedin", agents: null, tab: "overview", overview: null, runId: null, run: null, events: [], lastT: 0, selected: null,
  poll: null, config: null, dirty: false };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Postcrew": "1", ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
const post = (path, body = {}) => api(path, { method: "POST", body });
const catsOf = (cfg, id) => id === "linkedin" ? cfg.categories : (cfg.platforms?.[id]?.categories || {});
const mine = p => (p.platform || "linkedin") === S.platform;
function setPath(obj, path, val) { const ks = path.split("."); let o = obj; ks.slice(0, -1).forEach(k => o = o[k] ??= {}); o[ks.at(-1)] = val; }

let toastTimer;
function toast(msg, isErr) {
  const t = $("#toast"); t.textContent = msg; t.className = `px-4 py-2.5 rounded-xl text-white text-sm font-medium shadow-lg show ${isErr ? "bg-rose-700" : "bg-slate-900"}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), isErr ? 7000 : 3500);
}

/* ---------- router ---------- */
function setTab(tab) {
  if (S.dirty && ["settings", "plan"].includes(S.tab) && tab !== S.tab && !confirm("You have unsaved changes. Leave anyway?")) {
    location.hash = S.tab; return;
  }
  S.dirty = false;
  S.tab = VIEWS[tab] ? tab : "overview";
  drawTabs();
  clearInterval(S.poll); S.poll = null;
  $("#view").className = `flex-1 ${PAGE[S.tab] || PAGE.overview}`;
  VIEWS[S.tab]();
}
function drawTabs() {
  const queued = S.overview ? Object.values(S.overview.queue || {}).reduce((a, b) => a + b, 0) : 0;
  $("#tabs").innerHTML = TABS.map(([id, label, ic]) => {
    const on = id === S.tab;
    return `<a href="#${id}" data-tab="${id}" class="flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors duration-150 active:scale-95 ${on
      ? "bg-violet-50 text-violet-700 font-semibold" : "text-slate-600 font-medium hover:text-slate-900 hover:bg-slate-100"}">
      ${icon(ic, on ? "text-violet-700" : "text-slate-500")}<span>${label}</span>${id === "queue" && queued ? `<span class="text-[11px] font-bold px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700">${queued}</span>` : ""}</a>`;
  }).join("");
}

/* ---------- shell ---------- */
async function refreshOverview() {
  try { S.overview = await api(`/api/overview?platform=${encodeURIComponent(S.platform)}`); } catch (e) { return; }
  const o = S.overview;
  $("#bell-dot").hidden = !o.notifications.length;
  drawAppSelect(o.platforms);
  drawTabs();
  $("#banner").innerHTML = bannerHtml(o);
  $("#foot-dot").className = `w-2 h-2 rounded-full ${o.paused ? "bg-amber-500" : o.running ? "bg-violet-500" : "bg-emerald-500"}`;
  $("#foot-state").textContent = `Postcrew v${o.version} · ${o.paused ? "Paused" : o.running ? "A crew run is in progress" : "Online"}`;
}

// the app switcher shows once a second app is switched on; Overview, Plan, Queue and runs follow it
function drawAppSelect(list) {
  const on = list.filter(a => a.enabled), el = $("#app-sel");
  if (!on.some(a => a.id === S.platform)) S.platform = "linkedin";
  el.hidden = on.length < 2;
  el.innerHTML = on.map(a => { const sel = a.id === S.platform;
    return `<button data-app="${esc(a.id)}" class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition-all ${sel
      ? "font-semibold bg-white text-slate-900 shadow-sm border border-slate-200/80" : "font-medium text-slate-600 hover:text-slate-900"}">${appBadge(a.id)}<span>${esc(a.label)}</span></button>`; }).join("");
}
document.addEventListener("click", e => { const b = e.target.closest("#app-sel [data-app]"); if (b) { S.platform = b.dataset.app; setTab(S.tab); refreshOverview(); } });

// warnings first; the blue practice-mode bar is the Stitch banner
function bannerHtml(o) {
  // each app shows its own connection problems: LinkedIn's on LinkedIn, YouTube's on YouTube
  const li = S.platform === "linkedin" ? o.credentials?.linkedin : null, cl = o.credentials?.ai || o.credentials?.claude;
  const yt = S.platform === "youtube" ? o.credentials?.youtube : null;
  const bar = (tone, ic, html, tab, label) => `<div class="bg-${tone}-50 border-b border-${tone}-200 px-6 py-2.5"><div class="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
    <div class="flex items-center gap-2.5 text-${tone}-900 text-sm">${icon(ic, `text-${tone}-600 shrink-0`)}<span>${html}</span></div>
    ${tab ? `<a href="#${tab}" class="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1 rounded-lg bg-${tone}-100 hover:bg-${tone}-200 text-${tone}-800 transition-colors border border-${tone}-300 shrink-0">${icon("tune", "text-sm")}<span>${esc(label)}</span></a>` : ""}</div></div>`;
  const out = [];
  if (o.config_errors?.length) out.push(bar("rose", "error", `<strong class="font-semibold">Settings have ${o.config_errors.length} problem(s):</strong> ${esc(o.config_errors[0])}`, "settings", "Fix settings"));
  if (cl && cl.state !== "ok") out.push(bar("rose", "error", esc(cl.message), "credentials", "Open Credentials"));
  if (li && !["ok", "unreachable"].includes(li.state)) out.push(bar(li.state === "expiring" ? "orange" : "rose", li.state === "expiring" ? "warning" : "error", esc(li.message), "credentials", "Reconnect LinkedIn"));
  if (yt && !["ok", "unreachable"].includes(yt.state) && !o.dry_run) out.push(bar("rose", "error", esc(yt.message), "credentials", "Open Credentials"));
  if (o.paused) out.push(bar("amber", "pause_circle", "<strong class=\"font-semibold\">Paused</strong> — nothing is generated or published until you resume."));
  if (o.dry_run) out.push(bar("blue", "info", "<strong class=\"font-semibold\">You are currently in Practice Mode</strong> — the crew writes and queues content, but nothing is published to the app.", "settings", "Change in Settings"));
  return out.join("");
}

async function loadAgents() {
  try { S.agents = Object.fromEntries((await api("/api/agents")).agents.map(a => [a.id, a])); } catch (e) { /* names fall back to AGENTS */ }
}
const agentName = id => (S.agents?.[id]?.members?.length ? S.agents[id].members.join(" · ") : null) || AGENTS[id]?.[0] || id;
const agentTitle = id => id === "supervisor" ? "Supervisor" : S.agents?.[id]?.title || id;

/* ---------- notifications drawer ---------- */
const NOTE_TONE = { error: ["rose", "error"], warning: ["orange", "warning"], info: ["blue", "info"], success: ["emerald", "check_circle"] };
$("#bell").onclick = async () => {
  const dr = $("#drawer");
  if (!dr.hidden) { dr.hidden = true; return; }
  const { items } = await api("/api/notifications");
  dr.innerHTML = `<div class="flex items-center gap-2 mb-4"><h2 class="font-headline font-bold text-lg text-slate-900 flex-1">Notifications</h2>
    ${button("secondary", "done_all", "Mark all read", 'id="mark-read"')}</div><div class="space-y-3">${
    items.slice().reverse().map(n => { const [t, ic] = NOTE_TONE[n.level] || NOTE_TONE.info;
      return `<div class="rounded-xl border bg-${t}-50 border-${t}-200 p-3 ${n.read ? "opacity-70" : ""}"><div class="flex items-start gap-2">${icon(ic, `text-${t}-600 mt-0.5`)}
        <div class="flex-1"><div class="text-sm font-semibold text-${t}-900">${esc(n.title)}</div><div class="text-xs text-${t}-800 mt-0.5">${esc(n.message)}</div>
        <div class="flex items-center text-[11px] text-slate-500 mt-2"><span>${ago(n.ts)}</span><span class="flex-1"></span>
        ${n.action ? `<a href="#${esc(n.action.tab)}" class="font-semibold text-violet-700 hover:underline">${esc(n.action.label)}</a>` : ""}</div></div></div></div>`; }).join("")
    || emptyState("notifications_off", "Nothing yet.")}</div>`;
  dr.hidden = false;
  $("#mark-read").onclick = async () => { await post("/api/notifications/read", {}); dr.hidden = true; refreshOverview(); };
  dr.querySelectorAll("a[href^='#']").forEach(a => a.addEventListener("click", () => dr.hidden = true));
};

window.addEventListener("hashchange", () => setTab(location.hash.slice(1).split("/")[0] || "overview"));
window.addEventListener("beforeunload", e => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
function boot() {
  setInterval(refreshOverview, 15000);
  Promise.all([refreshOverview(), loadAgents()]).then(() => setTab(location.hash.slice(1).split("/")[0] || "overview"));
}
