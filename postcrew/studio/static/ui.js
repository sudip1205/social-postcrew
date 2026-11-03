/* Studio components. Markup and classes are copied from the Stitch screens (design/stitch/*.html): every view builds its
   icons, status chips, app badges and tooltips here, so a design change is made in one place. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* Material Symbols Outlined. Names used here must exist in the vendored font: scripts/build_ui_assets.py picks up every
   icon("name") call in the Studio JS, and every icon in the Stitch screens. */
const icon = (name, cls = "", fill = false) =>
  `<span class="material-symbols-outlined ${fill ? "fill " : ""}${cls}" aria-hidden="true">${esc(name)}</span>`;

/* Status colour code (design.md): always colour + icon + word. state -> [bg/text/border classes, icon colour, icon, spins] */
const STATUS = {
  passed: ["bg-emerald-50 text-emerald-700 border-emerald-200", "text-emerald-600", "check_circle", false, "Passed"],
  running: ["bg-violet-50 text-violet-700 border-violet-200", "text-violet-600", "progress_activity", true, "Running"],
  scheduled: ["bg-violet-50 text-violet-700 border-violet-200", "text-violet-600", "timer", false, "Scheduled"],
  waiting: ["bg-amber-50 text-amber-700 border-amber-200", "text-amber-600", "schedule", false, "Awaiting approval"],
  warning: ["bg-orange-50 text-orange-700 border-orange-200", "text-orange-600", "warning", false, "Warning"],
  failed: ["bg-rose-50 text-rose-700 border-rose-200", "text-rose-600", "cancel", false, "Failed"],
  info: ["bg-blue-50 text-blue-700 border-blue-200", "text-blue-600", "info", false, "Info"],
  idle: ["bg-slate-100 text-slate-600 border-slate-200", "text-slate-400", "do_not_disturb_on", false, "Idle"],
};
// every state word the backend uses -> one of the kinds above
const STATE_KIND = {
  passed: "passed", succeeded: "passed", published: "passed", ok: "passed", connected: "passed", approved: "passed", written: "passed",
  running: "running", retrying: "running", working: "running",
  queued: "scheduled", scheduled: "scheduled",
  awaiting_approval: "waiting", waiting: "waiting", pending: "idle",
  expiring: "warning", warning: "warning", unreachable: "warning", dry_run: "info", info: "info", planned: "info",
  failed: "failed", error: "failed", vetoed: "failed", expired: "failed", blocked: "failed", not_connected: "failed",
  skipped: "idle", idle: "idle", unknown: "idle",
};
const statusKind = state => STATE_KIND[state] || "idle";
const WORDS = { passed: "Passed", succeeded: "Passed", published: "Published", ok: "Connected", running: "Running", retrying: "Retrying",
  queued: "Scheduled", scheduled: "Scheduled", awaiting_approval: "Awaiting approval", approved: "Approved", failed: "Failed",
  vetoed: "Vetoed", dry_run: "Practice run", skipped: "Skipped", pending: "Pending", expiring: "Expiring soon" };
// Pill with icon + word. `label` overrides the word; size "sm" is the stat-card chip, the default the table chip.
const chip = (state, label, size = "md") => {
  const [box, ic, name, spin] = STATUS[statusKind(state)];
  const text = label ?? WORDS[state] ?? String(state).replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
  const pad = size === "sm" ? "px-2 py-0.5 font-medium" : "px-2.5 py-1 font-semibold";
  return `<span class="inline-flex items-center gap-1.5 ${pad} rounded-full border text-xs ${box}">${icon(name, `${ic} ${size === "sm" ? "text-xs" : "text-sm"}${spin ? " animate-spin" : ""}`)}<span>${esc(text)}</span></span>`;
};

/* Apps. The brand colour is a badge (and a left border on cards): blue in-badge for LinkedIn, red play-badge for YouTube. */
const APPS = {
  linkedin: { label: "LinkedIn", hex: "#0A66C2", badge: `<span class="w-4 h-4 rounded bg-[#0A66C2] text-white flex items-center justify-center text-[10px] font-bold">in</span>`,
    border: "border-l-[#0A66C2]", text: "text-[#0A66C2]", soft: "bg-blue-50 text-blue-800 border-blue-200", dot: "bg-[#0A66C2]" },
  youtube: { label: "YouTube", hex: "#FF0033", badge: `<span class="w-4 h-4 rounded bg-[#FF0033] text-white flex items-center justify-center text-[9px] font-black">▶</span>`,
    border: "border-l-[#FF0033]", text: "text-[#FF0033]", soft: "bg-rose-50 text-rose-700 border-rose-200", dot: "bg-[#FF0033]" },
};
const appOf = id => APPS[id] || APPS.linkedin;
const appBadge = id => appOf(id).badge;
const appName = id => appOf(id).label;

// A key term with a dotted underline and a hover explanation (the Stitch "tooltip-anchor")
const tip = (term, explain) => `<span class="tooltip-anchor" title="${esc(explain)}">${esc(term)}</span>`;

/* Agents: gradient avatar by team (Command violet, Planning sky, Research teal, Writing orange, Design pink, Quality indigo, Operations slate) */
const TEAMS = { command: ["Command", "#7c3aed", "#a855f7"], plan: ["Planning", "#0284c7", "#06b6d4"], research: ["Research team", "#0d9488", "#10b981"],
  writing: ["Writing team", "#ea580c", "#f59e0b"], design: ["Design", "#db2777", "#f472b6"], quality: ["Quality", "#4f46e5", "#818cf8"],
  ops: ["Operations", "#334155", "#64748b"] };
const AGENTS = { supervisor: ["Orion", "command", "hub"], planner: ["Vega", "plan", "calendar_month"], topic: ["Nova", "plan", "radar"],
  research: ["Research team", "research", "search"], writer: ["Writing team", "writing", "edit_note"], reviewer: ["Iris", "writing", "visibility"],
  media: ["Pixel", "design", "image"], editor: ["Quinn", "quality", "fact_check"], formatter: ["Kai", "quality", "format_align_left"],
  credentials: ["Aegis", "ops", "shield"], publisher: ["Echo", "ops", "send"], voice: ["Echo Voice", "design", "mic"], video: ["Reel", "design", "movie"],
  video_review: ["Cut", "quality", "movie"], graphics: ["Sketch", "design", "draw"], hooks: ["Hook", "quality", "verified"],
  text_frames: ["Glyph", "design", "text_fields"], data_frames: ["Plot", "design", "bar_chart"],
  direction: ["Muse", "design", "psychology"], quality: ["Lens", "quality", "center_focus_strong"] };
const teamOf = id => TEAMS[AGENTS[id]?.[1]] || TEAMS.ops;
const avatar = (id, size = "w-9 h-9") => { const [team, h1, h2] = teamOf(id);
  return `<span class="${size} rounded-full flex items-center justify-center text-white shrink-0" style="background:linear-gradient(135deg,${h1},${h2})" title="${esc(team)}">${icon(AGENTS[id]?.[2] || "hub", "text-white")}</span>`; };

/* formatting */
const ago = iso => { if (!iso) return ""; const s = (Date.now() - new Date(iso)) / 1000;
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} mins ago` : s < 86400 ? `${Math.round(s / 3600)} hours ago` : `${Math.round(s / 86400)} days ago`; };
const fmtTime = iso => iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
const money = v => `$${(v || 0).toFixed(v < 0.1 ? 4 : 2)}`;
const tok = t => { const k = n => n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`;
  return `${k((t.in || 0) + (t.cached || 0))} in${t.cached ? ` (${k(t.cached)} cached)` : ""} · ${k(t.out || 0)} out`; };
const fmtPost = s => esc(s).replace(/(^|\s)(#\w+)/g, '$1<span class="text-violet-700 font-medium">$2</span>');

/* shared building blocks (class strings from the Stitch screens) */
const BTN = {
  primary: "inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold shadow-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
  secondary: "inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-white hover:bg-slate-50 text-slate-800 text-sm font-semibold border border-slate-300 shadow-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
  approve: "inline-flex items-center gap-2 px-4 py-2 rounded-full bg-emerald-700 hover:bg-emerald-800 text-white text-sm font-semibold shadow-sm transition-colors",
  veto: "inline-flex items-center gap-2 px-4 py-2 rounded-full bg-rose-50 hover:bg-rose-100 text-rose-700 text-sm font-semibold border border-rose-200 transition-colors",
};
const button = (kind, ic, text, attrs = "") => `<button class="${BTN[kind]}" ${attrs}>${ic ? icon(ic) : ""}<span>${esc(text)}</span></button>`;
const card = (inner, cls = "") => `<div class="bg-white rounded-2xl border border-slate-200 shadow-sm ${cls}">${inner}</div>`;
// a section heading with a tinted icon tile, as in "Run the crew now" / "Coming up" / "Recent runs"
const sectionHead = (ic, title, sub, tint = "violet") => `<div class="flex items-start gap-3">
  <span class="w-9 h-9 rounded-xl bg-${tint}-50 text-${tint}-600 flex items-center justify-center shrink-0">${icon(ic)}</span>
  <div><h2 class="font-headline font-bold text-lg text-slate-900">${esc(title)}</h2><p class="text-sm text-slate-500 mt-0.5">${esc(sub || "")}</p></div></div>`;
const emptyState = (ic, text) => `<div class="flex flex-col items-center gap-2 py-10 text-slate-400">${icon(ic, "text-3xl")}<p class="text-sm">${esc(text)}</p></div>`;
const errorBanner = msg => `<div class="flex items-center gap-2.5 bg-rose-50 border border-rose-200 text-rose-800 text-sm rounded-xl px-4 py-3">${icon("error", "text-rose-600 shrink-0")}<span>${esc(msg)}</span></div>`;

/* ---------- YouTube research of a plan (shared by the Plan and Manual run pages) ---------- */
const TREND_LOOK = { hot: ["Hot", "bg-orange-50 text-orange-700 border-orange-200", "local_fire_department"], steady: ["Steady", "bg-sky-50 text-sky-700 border-sky-200", "trending_up"],
  niche: ["Niche", "bg-slate-100 text-slate-600 border-slate-200", "bar_chart"] };
const kNum = n => n == null ? "n/a" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k` : `${Math.round(n)}`;
const agoDays = d => d == null ? "" : d < 1 ? "today" : d < 14 ? `${d}d ago` : d < 60 ? `${Math.round(d / 7)}w ago` : d < 700 ? `${Math.round(d / 30)}mo ago` : `${Math.round(d / 365)}y ago`;
/* the chips under a plan's title: how trendy, how fast it is watched, how liked, how many videos were studied */
function researchChips(r, cls = "") {
  if (!r) return "";
  if (r.unavailable) return `<div class="flex flex-wrap gap-1.5 mt-2 ${cls}"><span class="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md border border-slate-200 bg-slate-50 text-slate-500">${icon("cloud_off", "text-[12px]")}<span>No YouTube numbers for this plan</span></span></div>`;
  const [word, tone, ic] = TREND_LOOK[r.label] || TREND_LOOK.niche, pill = "inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md border border-slate-200 bg-slate-50 text-slate-600";
  return `<div class="flex flex-wrap gap-1.5 mt-2 ${cls}">
    <span class="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-md border ${tone}" title="Trend score from how fast recent videos on this are watched">${icon(ic, "text-[12px]")}<span>${word} ${r.trend_score ?? "?"}/100</span></span>
    ${r.views_per_day != null ? `<span class="${pill}">${icon("visibility", "text-[12px]")}<span>${kNum(r.views_per_day)} views/day</span></span>` : ""}
    ${r.engagement_pct != null ? `<span class="${pill}" title="Likes as a share of views, on the videos studied">${icon("favorite", "text-[12px]")}<span>${r.engagement_pct}% like rate</span></span>` : ""}
    ${r.videos?.length ? `<span class="${pill}">${icon("smart_display", "text-[12px]")}<span>${r.videos.length} ${r.videos.length === 1 ? "video" : "videos"} studied</span></span>` : ""}</div>`;
}
/* the expandable part: why now, what the trending videos cover, where they fall short, and the videos themselves */
function researchDetails(r) {
  if (!r) return "";
  const h = t => `<div class="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">${t}</div>`;
  const vids = (r.videos || []).slice(0, 4).map(v => `<a href="${esc(v.url || "#")}" target="_blank" rel="noopener" class="flex items-center justify-between gap-2 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 hover:border-violet-300">
      <span class="min-w-0"><span class="block text-[11px] font-semibold text-slate-800 truncate">${esc(v.title)}</span><span class="block text-[10px] text-slate-400 truncate">${esc(v.channel || "")}${v.age_days != null ? ` · ${agoDays(v.age_days)}` : ""}${v.engagement_pct != null ? ` · ${v.engagement_pct}% liked` : ""}</span></span>
      <span class="shrink-0 text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-100 rounded px-1.5 py-0.5">${kNum(v.views)} views</span></a>`).join("");
  return `<div class="bg-slate-50 rounded-lg p-2.5 border border-slate-100 space-y-2.5">
    ${r.why ? `<div>${h("Why this topic now")}<p class="text-[11px] text-slate-600 leading-snug">${esc(r.why)}</p></div>` : ""}
    ${r.covers?.length ? `<div>${h("What trending videos cover")}<div class="flex flex-wrap gap-1">${r.covers.map(c => `<span class="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-[10px] text-slate-600">${esc(c)}</span>`).join("")}</div></div>` : ""}
    ${r.gap ? `<div>${h("Where they fall short")}<p class="text-[11px] text-slate-600 leading-snug">${esc(r.gap)}</p></div>` : ""}
    ${vids ? `<div>${h("Videos studied")}<div class="space-y-1">${vids}</div></div>` : ""}
    ${r.niche?.videos ? `<div class="text-[10px] text-slate-400">The whole topic: ${kNum(r.niche.median_views)} median views, ${r.niche.engagement_pct ?? "?"}% like rate, ${r.niche.videos} videos read${r.researched_at ? ` on ${esc(String(r.researched_at).slice(0, 10))}` : ""}.</div>` : ""}</div>`;
}
