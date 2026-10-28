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
  video_review: ["Cut", "quality", "movie"] };
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
