/* Postcrew Studio - no build step, no dependencies. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STEP_TITLES = { credentials: "Credential Monitor", topic: "Topic Scout", research: "Researcher", writer: "Writer",
  media: "Visual Designer", editor: "Editor Review", formatter: "Formatter", publisher: "Publisher" };
// state -> [ring colour, status text colour]
const STATE_COLORS = { pending: ["#cbd5e6", "#5b6b85"], running: ["#7c3aed", "#7c3aed"], retrying: ["#7c3aed", "#7c3aed"],
  passed: ["#059669", "#059669"], failed: ["#e11d48", "#e11d48"], skipped: ["#e1e7f2", "#94a3b8"], blocked: ["#fda4af", "#e11d48"],
  waiting: ["#f59e0b", "#b45309"] };
// an agent's colour comes from its team, so the colour tells you who works with whom; the icon tells you who it is
const TEAMS = { command: ["Command", "#7c3aed", "#a855f7"], plan: ["Planning", "#0284c7", "#06b6d4"], research: ["Research team", "#0d9488", "#10b981"],
  writing: ["Writing team", "#ea580c", "#f59e0b"], design: ["Design", "#db2777", "#f472b6"], quality: ["Quality", "#4f46e5", "#818cf8"],
  ops: ["Operations", "#334155", "#64748b"] };
const AGENTS = { supervisor: ["Orion", "command", "compass"], planner: ["Vega", "plan", "calendar"], topic: ["Nova", "plan", "radar"],
  research: ["Research team", "research", "search"], writer: ["Writing team", "writing", "pen"], reviewer: ["Iris", "writing", "eye"],
  media: ["Pixel", "design", "image"], editor: ["Quinn", "quality", "check"], formatter: ["Kai", "quality", "align"],
  credentials: ["Aegis", "ops", "shield"], publisher: ["Echo", "ops", "send"] };
const PROVIDERS = { "claude-code": "Claude Code (Claude plan)", anthropic: "Claude API", openai: "OpenAI API", "openai-compatible": "OpenAI-compatible server" };
const ICONS = { // 24x24 line icons
  compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12l6.4-6.4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
  pen: '<path d="M4 20l4.2-1 11-11a2.1 2.1 0 0 0-3-3l-11 11z"/><path d="M14.5 6.5l3 3"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 9"/>',
  check: '<rect x="5" y="4" width="14" height="17" rx="2.5"/><path d="M9 3.5h6v3H9zM9 13.5l2 2 4-4.5"/>',
  align: '<path d="M4 6h16M4 10h10M4 14h16M4 18h8"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  send: '<path d="M21 3L3 10.5l7 2.6L12.6 21z"/><path d="M10 13.1L21 3"/>' };
const teamOf = id => TEAMS[AGENTS[id]?.[1]] || TEAMS.ops;
const icon = id => ICONS[AGENTS[id]?.[2]] || ICONS.compass;
const agentName = id => (S.agents?.[id]?.members?.length ? S.agents[id].members.join(" · ") : null) || AGENTS[id]?.[0] || id;
const agentTitle = id => id === "supervisor" ? "Supervisor" : S.agents?.[id]?.title || STEP_TITLES[id] || id;
const avatar = (id, sm) => { const [team, h1, h2] = teamOf(id);
  return `<span class="avatar${sm ? " sm" : ""}" style="--h1:${h1};--h2:${h2}" title="${esc(team)}" aria-hidden="true"><svg viewBox="0 0 24 24">${icon(id)}</svg></span>`; };
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

const S = { agents: null, tab: "overview", overview: null, runId: null, run: null, events: [], lastT: 0, selected: null,
  poll: null, config: null, dirty: false };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Postcrew": "1", ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
const post = (path, body = {}) => api(path, { method: "POST", body });

let toastTimer;
function toast(msg, isErr) {
  const t = $("#toast"); t.textContent = msg; t.className = "show" + (isErr ? " error" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.className = "", isErr ? 7000 : 3500);
}
const chip = (state, label) => `<span class="chip ${esc(state)}">${esc(label ?? String(state).replace(/_/g, " "))}</span>`;
const ago = iso => { if (!iso) return ""; const s = (Date.now() - new Date(iso)) / 1000;
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; };
const fmtTime = iso => iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
const money = v => `$${(v || 0).toFixed(v < 0.1 ? 4 : 2)}`;
const fmtPost = s => esc(s).replace(/(^|\s)(#\w+)/g, '$1<span class="tag">$2</span>');

/* ---------- router ---------- */
function setTab(tab) {
  if (S.dirty && ["settings", "plan"].includes(S.tab) && tab !== S.tab && !confirm("You have unsaved changes. Leave anyway?")) {
    location.hash = S.tab; return;
  }
  S.dirty = false;
  S.tab = tab;
  document.querySelectorAll("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
  clearInterval(S.poll); S.poll = null;
  ({ overview: renderOverview, plan: renderPlan, team: renderTeam, workflow: renderWorkflow, queue: renderQueue, settings: renderSettings,
     credentials: renderCredentials }[tab] || renderOverview)();
}
window.addEventListener("hashchange", () => setTab(location.hash.slice(1).split("/")[0] || "overview"));

async function refreshOverview() {
  try { S.overview = await api("/api/overview"); } catch (e) { return; }
  const n = S.overview.notifications.length, c = $("#bell-count");
  c.hidden = !n; c.textContent = n;
}

function bannerHtml(o) {
  const out = [];
  const li = o.credentials?.linkedin, cl = o.credentials?.ai || o.credentials?.claude;
  if (o.config_errors?.length) out.push(["error", `Settings have ${o.config_errors.length} problem(s): ${o.config_errors[0]}`, "settings", "Fix settings"]);
  if (cl && cl.state !== "ok") out.push(["error", cl.message, "credentials", "Open Credentials"]);
  if (li && !["ok", "unreachable"].includes(li.state)) out.push([li.state === "expiring" ? "warning" : "error", li.message, "credentials", "Reconnect LinkedIn"]);
  if (o.paused) out.push(["warning", "Paused: nothing is generated or published until you resume.", null, null]);
  if (o.dry_run) out.push(["info", "Dry run is on: the crew writes and queues posts, but the publisher only logs what it would send.", "settings", "Change in Settings"]);
  return out.map(([lvl, msg, tab, label]) => `<div class="banner ${lvl}"><span class="grow">${esc(msg)}</span>${tab ? `<a class="btn" href="#${tab}">${esc(label)}</a>` : ""}</div>`).join("");
}

/* ---------- overview ---------- */
async function renderOverview() {
  await refreshOverview();
  const o = S.overview; if (!o) return;
  const [{ runs }, { queue }] = await Promise.all([api("/api/runs"), api("/api/queue")]);
  const li = o.credentials?.linkedin || {};
  const next = queue.filter(p => ["queued", "approved", "awaiting_approval"].includes(p.status)).sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))[0];
  $("#view").innerHTML = `
    <h1>Overview</h1><p class="sub">Workspace <span class="mono">${esc(o.workspace)}</span> · v${esc(o.version)}</p>
    ${bannerHtml(o)}
    <div class="grid g4">
      <div class="panel stat"><div class="label">Next post</div><div class="value">${next ? esc(next.date) : "—"}</div>
        <div class="hint">${next ? esc(next.topic) + " · " + chip(next.status) : "nothing queued"}</div></div>
      <div class="panel stat"><div class="label">Next crew run</div><div class="value">${esc(o.next.generate_time)}</div>
        <div class="hint">writes the post for ${esc(o.next.generate_for)} (${esc(o.next.category || "no category that day")}) · ${esc(o.next.timezone)}</div></div>
      <div class="panel stat"><div class="label">LinkedIn</div><div class="value">${chip(li.state || "unknown")}</div>
        <div class="hint">${esc(li.name || "")} ${li.days_left != null ? `· ${li.days_left} days left` : ""}</div></div>
      <div class="panel stat"><div class="label">Published</div><div class="value">${o.published}</div>
        <div class="hint">approval: ${esc(o.approval.replace(/_/g, " "))}</div></div>
    </div>
    <div class="panel" style="margin-top:16px">
      <div class="row"><h2 style="margin:0">Run the crew now</h2><span class="spacer"></span>
        <button id="pause">${o.paused ? "Resume schedule" : "Pause schedule"}</button></div>
      <p class="muted small">Runs every agent for one post date. "Rehearsal" runs everything except queueing, so nothing can be published.</p>
      <div class="row">
        <label class="f" style="width:170px">Post date<input type="date" id="run-date" value="${esc(o.next.generate_for)}"></label>
        <label class="f" style="width:240px">Category<select id="run-cat"><option value="">As scheduled for that day</option></select></label>
        <label class="checkline" style="margin-top:18px"><input type="checkbox" id="run-dry" checked> Rehearsal</label>
        <button class="primary" id="run-go" style="margin-top:18px" ${o.running ? "disabled" : ""}>${o.running ? "A run is in progress…" : "Start run"}</button>
      </div>
    </div>
    <div class="panel" style="margin-top:16px"><h2>Recent runs</h2>${runsTable(runs.slice(0, 10))}</div>`;
  const cfg = (await api("/api/config")).config;
  $("#run-cat").innerHTML += Object.entries(cfg.categories).map(([id, c]) => `<option value="${esc(id)}">${esc(c.label)}</option>`).join("");
  $("#run-go").onclick = startRun;
  $("#pause").onclick = async () => { await post("/api/pause", { paused: !o.paused }); renderOverview(); };
  bindRunRows();
}

function runsTable(runs) {
  if (!runs.length) return `<div class="empty">No runs yet. Start one above, or wait for the scheduler.</div>`;
  return `<table><thead><tr><th>Run</th><th>Post</th><th>State</th><th>Result</th><th>Cost</th><th>Supervisor</th></tr></thead><tbody>${
    runs.map(r => `<tr class="click" data-run="${esc(r.run_id)}"><td class="mono">${esc(r.run_id)}<div class="muted small">${ago(r.started_at)}</div></td>
      <td>${esc(r.meta?.date)}<div class="muted small">${esc(r.meta?.label || r.meta?.category)}${r.meta?.dry_run ? " · rehearsal" : ""}</div></td>
      <td>${chip(r.state)}</td><td class="small">${esc(r.result || "")}</td><td>${money(r.cost_usd)}</td>
      <td class="small">${r.interventions ? `${r.interventions} intervention(s)` : "—"}</td></tr>`).join("")}</tbody></table>`;
}
function bindRunRows() {
  document.querySelectorAll("tr[data-run]").forEach(tr => tr.onclick = () => { S.runId = tr.dataset.run; location.hash = "workflow"; });
}

async function startRun() {
  try {
    const r = await post("/api/runs", { date: $("#run-date").value, category: $("#run-cat").value, dry_run: $("#run-dry").checked });
    S.runId = r.run_id; toast("Crew started"); location.hash = "workflow";
  } catch (e) { toast(e.message, true); }
}

/* ---------- workflow ---------- */
async function renderWorkflow() {
  const [{ runs }] = await Promise.all([api("/api/runs"), loadAgents()]);
  if (!S.runId && runs.length) S.runId = runs[0].run_id;
  $("#view").innerHTML = `
    <div class="row"><div><h1>Workflow</h1><p class="sub">Every agent, every attempt and every supervisor decision, live.</p></div>
      <span class="spacer"></span>
      <label class="f" style="min-width:300px">Run<select id="run-pick">${runs.map(r => `<option value="${esc(r.run_id)}" ${r.run_id === S.runId ? "selected" : ""}>
        ${esc(r.run_id)} · ${esc(r.meta?.category || "")} · ${esc(r.state)}</option>`).join("") || "<option>No runs yet</option>"}</select></label></div>
    <div class="panel" id="wf-panel"><div id="wf-head" class="row" style="margin-bottom:8px"></div><div id="wf-graph"></div></div>
    <div class="grid g2" style="margin-top:16px">
      <div class="panel"><h2 id="step-title">Step details</h2><div id="step-detail" class="muted">Click an agent in the graph.</div></div>
      <div class="panel"><div class="row"><h2 style="margin:0">Log</h2><span class="spacer"></span>
        <label class="checkline small"><input type="checkbox" id="log-filter"> Only this step</label></div>
        <div class="timeline" id="timeline" style="margin-top:10px"></div></div>
    </div>
    <div class="panel" style="margin-top:16px"><h2>Working memory</h2>
      <p class="muted small" style="margin-top:-6px">What went wrong during this run, who sent the work back and why. An agent that is sent
        back sees all of it, so a fix is not undone in a later round. Fixed problems are kept for future runs.</p>
      <div id="memory" class="memory-list"></div></div>`;
  $("#run-pick").onchange = e => { S.runId = e.target.value; S.selected = null; loadRun(true); };
  $("#log-filter").onchange = drawTimeline;
  if (!S.runId) { $("#wf-graph").innerHTML = graphSvg(null); return; }
  await loadRun(true);
  S.poll = setInterval(() => { if (S.run?.status.state === "running") loadRun(false); }, 1500);
}

async function loadRun(reset) {
  if (reset) { S.events = []; S.lastT = 0; }
  try {
    const d = await api(`/api/runs/${encodeURIComponent(S.runId)}?after=${S.lastT}`);
    S.run = d; S.events = S.events.concat(d.events);
    if (S.events.length) S.lastT = S.events[S.events.length - 1].t;
  } catch (e) { toast(e.message, true); return; }
  const st = S.run.status;
  $("#wf-head").innerHTML = `${chip(st.state)} <b>${esc(st.meta?.label || "")}</b> <span class="muted">for ${esc(st.meta?.date || "")}</span>
    ${st.meta?.dry_run ? chip("dry_run", "rehearsal") : ""}<span class="spacer"></span>
    <span class="muted small">started ${fmtTime(st.started_at)} · ${money(st.cost_usd)} · ${st.interventions} supervisor intervention(s)</span>
    ${st.result ? `<div class="small ${st.state === "failed" ? "" : "muted"}" style="flex-basis:100%;${st.state === "failed" ? "color:var(--bad)" : ""}">${esc(st.result)}</div>` : ""}`;
  drawGraph(reset);
  drawTimeline();
  drawMemory();
  if (S.selected) drawStep();
}

function memEntry(e) {
  const list = (lbl, xs) => xs?.length ? `<div class="lbl">${lbl}</div><ul>${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  if (e.kind === "passed") return `<div class="mem passed"><span class="who">${avatar(e.step, 1)} ${esc(agentName(e.step))}</span>
    <span class="muted small">· ${esc(STEP_TITLES[e.step] || e.step)} passed on attempt ${esc(e.attempt)}</span></div>`;
  return `<div class="mem"><span class="who">${avatar(e.step, 1)} ${esc(agentName(e.step))}</span>
    <span class="muted small">· ${esc(STEP_TITLES[e.step] || e.step)} sent back by ${esc(e.by)} · ${esc((e.at || "").slice(11, 19))}</span>
    ${list("Why it failed", e.why)}${list("What to change", e.instructions)}</div>`;
}
function drawMemory() {
  const el = $("#memory"); if (!el) return;
  const mem = S.run?.memory || [];
  el.innerHTML = mem.length ? mem.slice().reverse().map(memEntry).join("") : `<div class="empty">Nothing yet: no agent has been sent back in this run.</div>`;
}
function rebindNodes() {
  document.querySelectorAll(".wf .node").forEach(n => n.onclick = () => { S.selected = n.dataset.step;
    drawGraph(true); drawStep(); drawTimeline(); });
}

function graphSvg(st) {
  const steps = Object.keys(STEP_TITLES), GAP = 150, X0 = 80, CY = 240, R = 34;
  const width = X0 * 2 + (steps.length - 1) * GAP, SX = width / 2, SY = 62, cx = i => X0 + i * GAP;
  const supState = st ? (st.state === "running" ? "running" : st.state === "failed" ? "failed" : "passed") : "pending";
  const mk = (id, c) => `<marker id="${id}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`;
  let svg = `<svg class="wf" viewBox="0 0 ${width} 400" role="img" aria-label="Agent workflow"><defs>
    ${Object.entries(TEAMS).map(([k, [, c1, c2]]) => `<linearGradient id="g-${k}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient>`).join("")}
    ${mk("arr", "#cbd5e6")}${mk("arrd", "#059669")}${mk("arrr", "#e11d48")}</defs>`;
  steps.forEach((s, i) => { svg += `<path class="sup" d="M ${SX} 158 C ${SX} 190, ${cx(i)} 180, ${cx(i)} ${CY - R - 10}"/>`; });
  steps.forEach((s, i) => {
    if (i === steps.length - 1) return;
    const done = st && ["passed", "skipped"].includes(st.steps[s]?.state), next = st?.steps[steps[i + 1]]?.state;
    const d = `M ${cx(i) + R + 9} ${CY} L ${cx(i + 1) - R - 13} ${CY}`;
    svg += `<path class="edge ${done ? "done" : ""}" d="${d}" marker-end="url(#arr${done ? "d" : ""})"/>`;
    // work being handed over: a pulse travels into the agent that is working now
    if (done && ["running", "retrying"].includes(next)) svg += `<circle r="4.5" fill="#7c3aed"><animateMotion dur="1.1s" repeatCount="indefinite" path="${d}"/></circle>`;
  });
  svg += orb("supervisor", SX, SY, 30, supState, st ? `${st.interventions} intervention(s)` : "orchestrates the crew");
  steps.forEach((s, i) => {
    const info = st?.steps[s] || { state: "pending", attempts: 0 };
    const label = info.state === "retrying" ? `retrying · try ${info.attempts}` : info.state + (info.attempts > 1 ? ` · ${info.attempts} tries` : "");
    svg += orb(s, cx(i), CY, R, info.state, label, info.cost_usd);
  });
  // supervisor rewinds: a return arc under the crew from the step that failed back to where work restarted
  const rewinds = {};
  let failing = null;
  S.events.forEach(e => {
    if (e.kind === "rejected") failing = e.step;
    if (e.kind === "decision" && e.data?.action === "rewind" && failing) {
      const k = `${failing}>${e.data.target}`; rewinds[k] = (rewinds[k] || 0) + 1;
    }
  });
  Object.entries(rewinds).forEach(([k, n], idx) => {
    const [from, to] = k.split(">"), i = steps.indexOf(from), j = steps.indexOf(to);
    if (i < 0 || j < 0) return;
    const x1 = cx(i), x2 = cx(j), y = 352, dip = 26 + idx * 9;
    svg += `<path d="M ${x1} ${y} C ${x1} ${y + dip}, ${x2} ${y + dip}, ${x2} ${y}" fill="none" stroke="#e11d48" stroke-width="1.8"
      stroke-dasharray="5 4" marker-end="url(#arrr)"/><text x="${(x1 + x2) / 2}" y="${y + dip * .75 + 4}" text-anchor="middle" font-size="11"
      font-weight="600" fill="#e11d48">sent back ×${n}</text>`;
  });
  return svg + "</svg>";
}

function orb(id, x, y, r, state, label, cost) {
  const [, c1] = teamOf(id), [ring, tc] = STATE_COLORS[state] || STATE_COLORS.pending, team = AGENTS[id]?.[1] || "ops";
  const busy = state === "running" || state === "retrying", members = S.agents?.[id]?.members || [];
  const name = agentName(id), k = r * 0.9 / 12;
  let g = `<g class="node ${state} ${S.selected === id ? "selected" : ""}" data-step="${id}"><g class="wobble">
    <circle class="halo" cx="${x}" cy="${y}" r="${r + 6}" fill="${c1}"/>
    <g class="orb-shadow"><circle cx="${x}" cy="${y}" r="${r}" fill="url(#g-${team})"/></g>
    <circle cx="${x}" cy="${y}" r="${r - 6}" fill="none" stroke="#fff" stroke-opacity=".35"/>
    <g transform="translate(${x - 12 * k} ${y - 12 * k}) scale(${k})" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icon(id)}</g>
    <circle class="ring" cx="${x}" cy="${y}" r="${r + 6}" stroke="${ring}"/>`;
  members.forEach((m, n) => { // team members sit on their team's orb
    const bx = x - (members.length - 1) * 11 + n * 22, by = y + r + 4;
    g += `<circle cx="${bx}" cy="${by}" r="10" fill="#fff" stroke="${c1}" stroke-width="2"/>
      <text x="${bx}" y="${by + 3.5}" text-anchor="middle" font-size="10" font-weight="700" fill="${c1}">${esc(m[0])}</text>`;
  });
  const bx = x + r * .74, by = y - r * .74;
  if (state === "passed") g += `<g class="badge"><circle cx="${bx}" cy="${by}" r="9" fill="#059669" stroke="#fff" stroke-width="2"/>
    <path d="M ${bx - 4} ${by} l3 3 5-6" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round"/></g>`;
  if (state === "failed" || state === "blocked") g += `<g class="badge"><circle cx="${bx}" cy="${by}" r="9" fill="#e11d48" stroke="#fff" stroke-width="2"/>
    <text x="${bx}" y="${by + 4}" text-anchor="middle" font-size="12" font-weight="800" fill="#fff">!</text></g>`;
  if (busy && id === "supervisor") g += `<g class="orbit"><circle cx="${x}" cy="${y}" r="${r + 14}" fill="none"/><circle cx="${x + r + 14}" cy="${y}" r="4" fill="#7c3aed"/></g>`;
  g += `</g>`;
  const ty = y + r + (members.length ? 30 : 24);
  g += `<text class="nm" x="${x}" y="${ty}" text-anchor="middle" fill="#0f172a">${esc(name.length > 19 ? name.slice(0, 18) + "…" : name)}</text>
    <text class="ti" x="${x}" y="${ty + 14}" text-anchor="middle" fill="${c1}">${esc(id === "supervisor" ? "Supervisor" : STEP_TITLES[id])}</text>
    <text class="st" x="${x}" y="${ty + 30}" text-anchor="middle" fill="${tc}">${esc(label)}</text>`;
  if (busy && id !== "supervisor") g += `<g class="dots">${[0, 1, 2].map(n => `<circle cx="${x - 8 + n * 8}" cy="${ty + 42}" r="2.6" fill="${ring}"/>`).join("")}</g>`;
  else if (cost) g += `<text x="${x}" y="${ty + 45}" text-anchor="middle" font-size="10.5" font-family="monospace" fill="#5b6b85">${money(cost)}</text>`;
  return g + "</g>";
}

/* redraw the graph only when something changed, so the animations keep running between polls */
function drawGraph(force) {
  const st = S.run?.status;
  const key = JSON.stringify([st?.state, st?.interventions, st && Object.values(st.steps).map(x => [x.state, x.attempts, x.cost_usd]),
    S.selected, S.events.filter(e => e.kind === "decision").length]);
  if (!force && key === S.graphKey) return;
  S.graphKey = key;
  $("#wf-graph").innerHTML = graphSvg(st);
  rebindNodes();
}

async function drawStep() {
  const s = S.selected, st = S.run.status;
  $("#step-title").innerHTML = `<span class="who">${avatar(s)} <span>${esc(agentName(s))}<br><span class="small muted">${esc(agentTitle(s))}</span></span></span>`;
  if (s === "supervisor") {
    const dec = S.events.filter(e => e.step === "supervisor" && e.kind === "decision");
    $("#step-detail").innerHTML = dec.length ? `<ol class="steps-list">${dec.map(e => `<li><b>${esc(e.data.action)} → ${esc(e.data.target)}</b>: ${esc(e.data.reason)}
      ${e.data.instructions?.length ? `<ul>${e.data.instructions.map(x => `<li class="small">${esc(x)}</li>`).join("")}</ul>` : ""}</li>`).join("")}</ol>`
      : `<p class="muted">No interventions: every agent passed validation first time.</p>`;
    return;
  }
  const info = st.steps[s] || {};
  let html = `<div class="row">${chip(info.state || "pending")}<span class="muted small">${info.attempts || 0} attempt(s) · ${money(info.cost_usd)}</span></div>
    ${info.summary ? `<p>${esc(info.summary)}</p>` : ""}
    ${info.errors?.length ? `<h3>Problems found by validation</h3><ul class="err-list">${info.errors.map(e => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}`;
  const back = (S.run.memory || []).filter(e => e.step === s && e.kind === "sent_back");
  if (back.length) html += `<h3>Sent back ${back.length}× — the reasons it was given</h3>` + back.map(memEntry).join("");
  if (S.run.files.includes(`${s}.json`)) {
    try {
      const r = await fetch(`/api/runs/${encodeURIComponent(S.runId)}/artifact/${s}.json`); const art = await r.json();
      if (s === "media" && art.path) {
        const name = art.path.split("/").pop(), url = `/api/runs/${encodeURIComponent(S.runId)}/file/${encodeURIComponent(name)}`;
        html += `<h3>Rendered media</h3><div class="media-prev">${art.kind === "video" ? `<video src="${url}" controls muted playsinline></video>` : `<img src="${url}" alt="poster">`}</div>`;
      }
      if ((s === "writer" || s === "formatter") && art.text) html += `<h3>Text</h3><div class="post"><div class="body">${fmtPost(art.text)}</div></div>`;
      html += `<details style="margin-top:10px"><summary>Output (JSON)</summary><pre class="json">${esc(JSON.stringify(art, null, 2))}</pre></details>`;
    } catch (e) { /* artifact not readable yet */ }
  }
  const rejected = S.run.files.filter(f => f.startsWith(`${s}.rejected.`));
  if (rejected.length) html += `<h3>Rejected attempts</h3>` + rejected.map(f => `<a href="/api/runs/${encodeURIComponent(S.runId)}/artifact/${encodeURIComponent(f)}" target="_blank" class="small mono">${esc(f)}</a>`).join("<br>");
  $("#step-detail").innerHTML = html;
}

function drawTimeline() {
  const only = $("#log-filter")?.checked && S.selected;
  const evs = S.events.filter(e => !only || e.step === S.selected);
  const el = $("#timeline"); if (!el) return;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  el.innerHTML = evs.map(e => `<div class="ev ${esc(e.level)} ${esc(e.step)}"><span class="t">${esc(e.ts.slice(11, 19))}</span>
    <span class="s">${avatar(e.step, 1)}${esc(AGENTS[e.step]?.[0] || e.step)}</span><span class="m">${esc(e.kind)}: ${esc(e.message)}
    ${e.data ? `<details><summary class="small muted">details</summary><pre>${esc(JSON.stringify(e.data, null, 2))}</pre></details>` : ""}</span></div>`).join("")
    || `<div class="empty">No events yet.</div>`;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

/* ---------- queue ---------- */
async function renderQueue() {
  const [{ queue, history }, { config }] = await Promise.all([api("/api/queue"), api("/api/config")]);
  const cats = config.categories;
  const live = queue.filter(p => p.status !== "vetoed").sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  const vetoed = queue.filter(p => p.status === "vetoed");
  $("#view").innerHTML = `<h1>Queue</h1><p class="sub">Posts that passed the Editor Review. Approve, edit, veto or publish them here.</p>
    <div class="cards">${live.map(postCard).join("") || `<div class="panel empty">The queue is empty.</div>`}</div>
    ${vetoed.length ? `<h2 style="margin-top:28px">Vetoed</h2><div class="cards">${vetoed.map(postCard).join("")}</div>` : ""}
    <div class="panel" style="margin-top:28px" id="published"><h2>Published</h2>
      <p class="muted small">Every topic here counts as already posted, so the crew never repeats it. Add posts you published yourself;
        remove one to allow its topic again. Removing only changes this list, never LinkedIn.</p>
      <div class="row" style="margin-bottom:12px"><input type="date" id="h-date" value="${new Date().toISOString().slice(0, 10)}" style="width:auto">
        <input id="h-topic" placeholder="Topic of a post you published, e.g. Kafka consumer groups" maxlength="150" style="flex:1;min-width:240px">
        <select id="h-cat" style="width:auto"><option value="">Topic type (optional)</option>${Object.entries(cats).map(([id, k]) => `<option value="${esc(id)}">${esc(k.label)}</option>`).join("")}</select>
        <button class="primary" id="h-add">Add to published</button></div>
      ${history.length ? `<table><thead><tr><th style="width:110px">Date</th><th>Topic</th><th>Topic type</th><th>LinkedIn</th><th style="width:90px"></th></tr></thead><tbody>${
      history.map((h, i) => [h, i]).sort((a, b) => (b[0].date || "").localeCompare(a[0].date || "")).map(([h, i]) => `<tr><td>${esc(h.date)}</td><td>${esc(h.topic)}</td>
        <td class="small">${esc(cats[h.category]?.label || h.category || "")}</td>
        <td class="mono small">${h.urn ? esc(h.urn) : `<span class="muted">${h.added_by_hand ? "added by you" : h.imported ? "imported" : ""}</span>`}${
          h.comment_status === "added" ? `<div class="muted">first comment added</div>`
          : h.comment_status === "failed" ? `<div class="bad" title="${esc(h.comment_error || "")}">first comment failed${(h.comment_tries || 0) < 3 ? " - will retry" : " - add it by hand"}</div>` : ""}</td>
        <td><button class="danger small" data-hrm="${i}">Remove</button></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty">Nothing published yet.</div>`}</div>`;
  $("#h-add").onclick = async () => {
    const topic = $("#h-topic").value.trim(); if (!topic) return $("#h-topic").focus();
    try { await post("/api/history", { date: $("#h-date").value, topic, category: $("#h-cat").value }); toast("Added to published"); renderQueue(); }
    catch (e) { toast(e.message, true); }
  };
  $("#h-topic").onkeydown = e => { if (e.key === "Enter") $("#h-add").click(); };
  document.querySelectorAll("[data-hrm]").forEach(b => b.onclick = async () => {
    const h = history[+b.dataset.hrm];
    if (!confirm(`Remove "${h.topic}" from the published list? The crew may then write about it again.${h.urn ? " The post stays on LinkedIn." : ""}`)) return;
    try { await post("/api/history/remove", { id: h.id, date: h.date, topic: h.topic }); toast("Removed"); renderQueue(); }
    catch (e) { toast(e.message, true); }
  });
  document.querySelectorAll("[data-q]").forEach(b => b.onclick = () => queueAction(b.dataset.id, b.dataset.q, b));
}
function postCard(p) {
  const media = !p.media ? "" : p.media_kind === "video" ? `<div class="media"><video src="/${esc(p.media)}" controls muted playsinline preload="metadata"></video></div>`
    : `<div class="media"><img src="/${esc(p.media)}" alt=""></div>`;
  const act = (q, label, cls = "") => `<button class="${cls}" data-q="${q}" data-id="${esc(p.id)}">${label}</button>`;
  const buttons = p.status === "vetoed" ? act("restore", "Restore") + act("delete", "Delete", "danger")
    : (p.status === "awaiting_approval" ? act("approve", "Approve", "primary") : "") + act("edit", "Edit") +
      act("publish_now", "Publish now") + `<span class="spacer"></span>` + act("veto", "Veto", "danger");
  return `<article class="post" id="post-${esc(p.id)}"><div class="head">${chip(p.status)}<b>${esc(p.date)}</b>
      <span class="muted small">${esc(p.category)} · ${p.text.length} chars · review ${p.review?.overall ?? "?"}</span>
      ${p.error ? `<div class="small" style="flex-basis:100%;color:var(--bad)">${esc(p.error)}</div>` : ""}</div>
    <div class="body">${fmtPost(p.text)}</div>${media}
    ${p.first_comment ? `<div class="foot small"><span class="muted">First comment:</span> ${esc(p.first_comment)}</div>` : ""}
    <div class="foot">${buttons}</div></article>`;
}
async function queueAction(id, action, btn) {
  if (action === "edit") return editPost(id);
  if (action === "publish_now" && !confirm("Publish this post to LinkedIn now?")) return;
  if (action === "delete" && !confirm("Delete this post from the queue?")) return;
  btn.disabled = true;
  try { const r = await post(`/api/queue/${encodeURIComponent(id)}/${action}`); toast(action === "publish_now" ? `Publish: ${r.status}` : "Done"); }
  catch (e) { toast(e.message, true); }
  renderQueue();
}
async function editPost(id) {
  const { queue } = await api("/api/queue"); const p = queue.find(x => x.id === id);
  const card = $(`#post-${CSS.escape(id)}`);
  card.querySelector(".body").innerHTML = `<label class="f">Text<textarea id="e-text">${esc(p.text)}</textarea></label>
    <div class="grid g2" style="margin-top:8px"><label class="f">Date<input type="date" id="e-date" value="${esc(p.date)}"></label>
    <label class="f">First comment<input id="e-fc" value="${esc(p.first_comment || "")}"></label></div>`;
  card.querySelector(".foot:last-child").innerHTML = `<span class="muted small" id="e-count">${p.text.length} / 3000</span><span class="spacer"></span>
    <button id="e-cancel">Cancel</button><button class="primary" id="e-save">Save</button>`;
  $("#e-text").oninput = e => $("#e-count").textContent = `${e.target.value.length} / 3000`;
  $("#e-cancel").onclick = renderQueue;
  $("#e-save").onclick = async () => {
    try { await post(`/api/queue/${encodeURIComponent(id)}/edit`, { text: $("#e-text").value, date: $("#e-date").value, first_comment: $("#e-fc").value });
      toast("Saved"); renderQueue(); } catch (e) { toast(e.message, true); }
  };
}

/* ---------- week plan ---------- */
async function renderPlan() {
  const d = await api("/api/plan");
  S.dirty = false;
  const src = { planner: ["queued", "Planner"], manual: ["approved", "You"], auto: ["ok", "Automatic"] };
  const fmtDay = iso => new Date(iso + "T12:00").toLocaleDateString([], { month: "short", day: "numeric" });
  const row = r => {
    const head = `<td><b>${esc(r.weekday)}</b><div class="small muted">${esc(fmtDay(r.date))}${r.date === d.today ? " · today" : ""}</div></td>`;
    if (!r.category) return `<tr class="muted">${head}<td colspan="3" class="small">No post scheduled</td></tr>`;
    const label = `<td class="small">${esc(r.label)}</td>`;
    if (r.written) return `<tr>${head}${label}<td><b>${esc(r.written.topic)}</b><div class="small muted">Already written. Change it in the Queue.</div></td><td>${chip(r.written.status)}</td></tr>`;
    if (r.past) return `<tr class="muted">${head}${label}<td class="small">${esc(r.entry?.topic || "")}${r.entry ? " · " : ""}Being written or past</td><td></td></tr>`;
    const e = r.entry, s = e ? src[e.source] || ["queued", e.source] : null;
    const note = e ? (e.rejected?.length ? `Rejected before: ${e.rejected.map(esc).join("; ")}` : "")
      : r.fixed ? "Chosen automatically when you plan." : r.plan_ahead ? "Not planned yet." : "Fresh news: picked the day before, unless you type a topic.";
    return `<tr data-day="${esc(r.date)}" data-topic="${esc(e?.topic || "")}" data-angle="${esc(e?.angle || "")}">${head}${label}
      <td><input class="p-topic" value="${esc(e?.topic || "")}" placeholder="${r.plan_ahead || r.fixed ? "Topic" : "Picked the day before (or type one)"}" maxlength="90">
        <input class="p-angle small" style="margin-top:6px" value="${esc(e?.angle || "")}" placeholder="Angle: what the reader will learn (optional)" maxlength="400">
        ${note ? `<div class="small muted" style="margin-top:4px">${note}</div>` : ""}
        <div class="row" style="margin-top:6px"><input class="p-hint small" style="flex:1;min-width:180px" placeholder="Optional: what you'd like instead" maxlength="300">
          <button class="p-suggest">Suggest another</button></div></td>
      <td>${s ? chip(s[0], s[1]) : chip("pending", "open")}</td></tr>`;
  };
  $("#view").innerHTML = `<h1>Plan</h1><p class="sub">This week's topics, ${esc(fmtDay(d.week[0]))} to ${esc(fmtDay(d.week[1]))}. Type over any topic (or empty it to let the
    Topic Scout choose the day before), then save. The crew writes about whatever is here.</p>
    <div class="row" style="margin-bottom:12px"><button id="p-fill">Plan open days</button><span class="muted small" id="p-state">The Week Planner also runs every
      ${esc(DAY_NAMES[d.planning.weekday])} at ${esc(d.planning.time)}${d.planning.enabled ? "" : " (switched off in Settings)"}.</span></div>
    <div class="panel"><table><thead><tr><th style="width:120px">Day</th><th style="width:180px">Topic type</th><th>Topic</th><th style="width:110px">From</th></tr></thead>
    <tbody>${d.days.map(row).join("")}</tbody></table></div>
    <div class="savebar"><span id="save-state" class="muted small">No changes</span><span class="spacer"></span>
      <button id="p-reset">Discard changes</button><button class="primary" id="p-save">Save plan</button></div>`;
  const changes = () => {
    const out = {};
    document.querySelectorAll("tr[data-day]").forEach(tr => {
      const topic = tr.querySelector(".p-topic").value.trim(), angle = tr.querySelector(".p-angle").value.trim();
      if (topic !== tr.dataset.topic || angle !== tr.dataset.angle) out[tr.dataset.day] = { topic, angle: topic ? angle : "" };
    });
    return out;
  };
  const savePlan = async () => {
    const days = changes();
    if (!Object.keys(days).length) { toast("Nothing to save"); return true; }
    try { await api("/api/plan", { method: "PUT", body: { days } }); S.dirty = false; toast(`Saved ${Object.keys(days).length} day(s)`); return true; }
    catch (e) { toast(e.message, true); return false; }
  };
  const busy = label => { document.querySelectorAll("#view button").forEach(x => x.disabled = true); $("#p-state").textContent = label; };
  $("#view").addEventListener("input", e => {
    if (!e.target.matches(".p-topic, .p-angle")) return;
    const n = Object.keys(changes()).length; S.dirty = n > 0;
    $("#save-state").textContent = n ? `${n} unsaved change(s)` : "No changes";
  });
  $("#p-save").onclick = async () => { if (await savePlan()) renderPlan(); };
  $("#p-reset").onclick = () => renderPlan();
  $("#p-fill").onclick = async () => {
    if (S.dirty && !(await savePlan())) return;
    busy("The Week Planner is working (about a minute)…");
    try { await post("/api/plan/fill"); toast("Plan updated"); } catch (e) { toast(e.message, true); }
    renderPlan(); refreshOverview();
  };
  document.querySelectorAll("tr[data-day]").forEach(tr => {
    const day = tr.dataset.day;
    tr.querySelector(".p-suggest").onclick = async () => {
      if (S.dirty && !(await savePlan())) return;
      busy(`Asking the Week Planner for a new ${tr.querySelector("b").textContent} topic…`);
      try { await post(`/api/plan/${day}/suggest`, { hint: tr.querySelector(".p-hint").value.trim() }); toast("New topic suggested"); } catch (e) { toast(e.message, true); }
      renderPlan();
    };
  });
}

/* ---------- team ---------- */
async function renderTeam() {
  const [d, { memory }] = await Promise.all([api("/api/team"), api("/api/memory"), loadAgents()]);
  const ROLE = { research: "Researchers", writer: "Writers" };
  const dots = m => m.window.map(g => `<span class="dot-${g ? "ok" : "bad"}" title="${g ? "good" : "bad"}"></span>`).join("") || `<span class="muted small">no posts yet</span>`;
  const card = m => {
    const s = m.stats, last = m.recent.at(-1);
    return `<div class="topic member${m.working ? "" : " bench"}">
      <div class="row">${avatar(m.role === "research" ? "research" : "writer", 1)}<b style="font-size:15px">${esc(m.name)}</b>${m.working ? chip("ok", "working") : chip("pending", "on the bench")}
        ${m.at_risk ? chip("warning", "at risk") : ""}<span class="spacer"></span>
        <button class="danger small" data-fire="${esc(m.id)}" data-name="${esc(m.name)}">Replace</button></div>
      <p class="small" style="margin:6px 0">${esc(m.persona)}</p>
      <div class="row small"><span class="muted">Last ${d.rules.fire_window} posts:</span> ${dots(m)}</div>
      <div class="small muted" style="margin-top:4px">${s.tries} post(s) · ${s.good} good${m.role === "writer" ? ` · chosen ${s.chosen}× · Editor passed ${s.editor_passed}, failed ${s.editor_failed}` : ""}
        ${m.model ? ` · model ${esc(m.model)}` : ""} · joined ${esc(fmtTime(m.hired_at))}</div>
      ${last && !last.good && last.problems?.length ? `<div class="small" style="margin-top:6px;color:var(--bad)">Last problem: ${esc(last.problems[0].slice(0, 180))}</div>` : ""}
    </div>`;
  };
  const agentCard = a => `<div class="agent-card" style="--c:${teamOf(a.id)[1]}">${avatar(a.id)}<div style="min-width:0">
      <div class="nm">${esc(agentName(a.id))}</div><div class="ti">${esc(a.title)}</div>
      <div class="small" style="margin-top:4px">${esc(a.role)}</div>
      ${a.llm ? `<div class="small muted mono" style="margin-top:4px">${esc(a.llm.model || "default model")}</div>` : `<div class="small muted mono" style="margin-top:4px">no AI: rules only</div>`}</div></div>`;
  const all = Object.values(S.agents || {});
  const legend = `<div class="legend">${Object.entries(TEAMS).map(([, [n, c]]) => `<span><i style="--c:${c}"></i>${esc(n)}</span>`).join("")}</div>`;
  const crew = legend + Object.keys(TEAMS).map(t => { const xs = all.filter(a => (AGENTS[a.id]?.[1] || "ops") === t);
    return xs.length ? `<div class="crew-group"><h3><i style="--c:${TEAMS[t][1]}"></i>${esc(TEAMS[t][0])}</h3><div class="grid g3">${xs.map(agentCard).join("")}</div></div>` : "";
  }).join("");
  const memRows = Object.entries(memory).flatMap(([step, rows]) => rows.map((r, i) => ({ step, i, ...r }))).reverse();
  const memHtml = memRows.length ? memRows.map(r => `<div class="mem passed"><div class="row"><span class="who">${avatar(r.step, 1)} ${esc(STEP_TITLES[r.step] || r.step)}</span>
      <span class="muted small">${esc(fmtTime(r.at))}</span><span class="spacer"></span><button class="small" data-forget="${esc(r.step)}:${r.i}">Forget</button></div>
      <div class="lbl" style="margin-top:6px">Problem</div><div>${esc(r.problem)}</div>
      ${r.fix?.length ? `<div class="lbl" style="margin-top:4px">What fixed it</div><ul>${r.fix.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`).join("")
    : `<div class="empty">Nothing yet. When an agent's work is sent back and then fixed, the crew remembers the problem and the fix.</div>`;
  $("#view").innerHTML = `<h1>Crew</h1><p class="sub">Every agent, its name and its job. Orion, the Supervisor, checks each step and sends work back
    with the reasons it failed.</p>
    <div class="panel section"><h2>The crew</h2>${crew}</div>
    <h2 style="margin-top:22px">Research and writing teams</h2><p class="sub">Several researchers and writers work on every post. Researchers' verified sources are combined;
    writers compete, ${d.rules.pre_review ? "every draft is pre-reviewed and the best is polished, " : ""}and only the best goes to the Editor.
    A member is replaced automatically when fewer than ${Math.round(d.rules.fire_min_success * 100)}% of their last ${d.rules.fire_window} posts were good;
    the new hire learns from the mistakes.</p>
    ${["research", "writer"].map(r => `<div class="panel section"><div class="row"><h2 style="margin:0">${ROLE[r]}</h2>
      <span class="muted small">${d.size[r]} work on each post</span><span class="spacer"></span><button data-hire="${r}">Hire another</button></div>
      <div class="grid g2" style="margin-top:12px">${d.members.filter(m => m.role === r).map(card).join("")}</div>
      <h3>Lessons every ${r === "research" ? "researcher" : "writer"} follows</h3>
      ${(d.lessons[r] || []).length ? `<ul class="lessons">${d.lessons[r].map((l, i) => `<li><span>${esc(l)}</span> <button class="small" data-lesson="${r}:${i}">Remove</button></li>`).join("")}</ul>`
        : `<p class="muted small">None yet. When a member is replaced, the team writes down what went wrong.</p>`}</div>`).join("")}
    <div class="panel section"><h2>Former members</h2>${d.fired.length ? `<table><thead><tr><th>Name</th><th>Role</th><th>Left</th><th>Why</th><th>Lessons they left</th></tr></thead><tbody>${
      d.fired.map(f => `<tr><td><b>${esc(f.name)}</b></td><td class="small">${esc(f.role)}</td><td class="small">${esc(fmtTime(f.fired_at))}</td>
        <td class="small">${esc(f.reason)}</td><td class="small">${(f.lessons || []).map(esc).join("<br>")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty">Nobody has been replaced.</div>`}</div>
    <div class="panel section"><h2>Long-term memory</h2><p class="muted small" style="margin-top:-6px">Problems the crew fixed in earlier runs.
      The 3 most recent for each step are given to that agent at the start of every run.</p><div class="memory-list">${memHtml}</div></div>`;
  const act = async (path, body, msg) => { try { await post(path, body); toast(msg); } catch (e) { toast(e.message, true); } renderTeam(); };
  document.querySelectorAll("[data-fire]").forEach(b => b.onclick = () => {
    if (!confirm(`Replace ${b.dataset.name}? A new member is hired with lessons from ${b.dataset.name}'s mistakes.`)) return;
    b.disabled = true; act("/api/team/fire", { id: b.dataset.fire }, `${b.dataset.name} was replaced`);
  });
  document.querySelectorAll("[data-forget]").forEach(b => b.onclick = () => {
    const [step, index] = b.dataset.forget.split(":"); act("/api/memory/forget", { step, index: +index }, "Forgotten");
  });
  document.querySelectorAll("[data-hire]").forEach(b => b.onclick = () => act("/api/team/hire", { role: b.dataset.hire }, "Hired"));
  document.querySelectorAll("[data-lesson]").forEach(b => b.onclick = () => {
    const [role, index] = b.dataset.lesson.split(":"); act("/api/team/lesson-remove", { role, index: +index }, "Lesson removed");
  });
}

/* ---------- settings (configurator) ---------- */
async function renderSettings() {
  const [{ config }, { agents }, planInfo] = await Promise.all([api("/api/config"), api("/api/agents"), api("/api/plan")]);
  S.config = config; S.ideaUse = planInfo.ideas;
  const c = config;
  const sel = (id, val, opts) => `<select data-k="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${v === val ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const inp = (id, val, type = "text", extra = "") => `<input data-k="${id}" type="${type}" value="${esc(val)}" ${extra}>`;
  const check = (id, val, label) => `<label class="checkline"><input type="checkbox" data-k="${id}" ${val ? "checked" : ""}> ${label}</label>`;
  $("#view").innerHTML = `<h1>Settings</h1><p class="sub">Three steps: choose your topics, pick which topic goes on which day, and tell the crew about you.</p>
  <div id="cfg-errors"></div>

  <div class="panel section" id="ideas"><div class="step"><span class="num">1</span><div class="grow"><h2>Topics</h2>
    <p class="muted small">The kinds of posts you want. Under each one, list your own ideas (one per line); the Week Planner uses them before inventing its own.</p></div></div>
    <div class="grid g2" id="topics"></div>
    <div class="row" style="margin-top:12px"><input id="new-topic" placeholder="New topic, e.g. Career advice" style="max-width:320px" maxlength="60">
      <button id="add-topic">Add topic</button></div></div>

  <div class="panel section"><div class="step"><span class="num">2</span><div class="grow"><h2>Weekly schedule</h2>
    <p class="muted small">Which topic goes out on each day. The menus list the topics from step 1.</p></div></div>
    <div class="days" id="days"></div>
    <div class="grid g4" style="margin-top:16px">
      <label class="f">Publish at${inp("schedule.post_time", c.schedule.post_time, "time")}</label>
      <label class="f">Write it the day before at${inp("schedule.generate_time", c.schedule.generate_time, "time")}</label>
      <label class="f">Time zone${inp("schedule.timezone", c.schedule.timezone, "text", 'list="tzs"')}</label>
    </div>
    <div class="row inline-fields" style="margin-top:14px">${check("planning.enabled", c.planning.enabled, "Plan this week's topics every")}
      ${sel("planning.weekday", c.planning.weekday, WEEKDAYS.map(d => [d, DAY_NAMES[d]]))} <span>at</span> ${inp("planning.time", c.planning.time, "time")}</div>
    <label class="f" style="margin-top:12px">Focus for the next plan (optional)<input data-k="planning.focus" value="${esc(c.planning.focus || "")}" maxlength="600"
      placeholder="e.g. This week is about Kubernetes; keep examples in Python"></label>
    <div class="row" style="margin-top:12px"><button class="primary" id="ideas-plan">Save and plan open days</button>
      <button id="ideas-replan">Save and re-plan this week</button><a class="small" href="#plan">Open the Plan</a>
      <span class="muted small" id="ideas-state">Re-plan replaces the planner's topics; topics you typed in the Plan are kept.</span></div>
    <datalist id="tzs">${(Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : []).map(z => `<option value="${esc(z)}">`).join("")}</datalist></div>

  <div class="panel section"><div class="step"><span class="num">3</span><div class="grow"><h2>About you</h2>
    <p class="muted small">The writer only claims what you list here about yourself.</p></div></div>
    <div class="grid g2">
      <label class="f">Your name${inp("profile.name", c.profile.name)}</label>
      <label class="f">Profile link printed on posters${inp("profile.handle", c.profile.handle, "text", 'placeholder="linkedin.com/in/your-name"')}</label>
      <label class="f">Who reads your posts${inp("profile.audience", c.profile.audience)}</label>
      <label class="f">How you write${inp("profile.voice", c.profile.voice)}</label>
      <label class="f" style="grid-column:1/-1">True facts about you (one per line)<textarea data-k="profile.about" data-list="1" rows="3" placeholder="e.g. 10 years building Java backends">${esc(c.profile.about.join("\n"))}</textarea></label>
    </div></div>

  <div class="panel section"><h2>Publishing and alerts</h2><div class="grid g2">
    <label class="f">When a post is ready${sel("publishing.approval", c.publishing.approval, [["auto_with_veto", "Publish at post time unless I veto it"], ["manual", "Wait for my approval"], ["immediate", "Publish right away"]])}</label>
    <div style="padding-top:22px">${check("publishing.dry_run", c.publishing.dry_run, "<b>Practice mode</b>: write posts but never send them to LinkedIn")}</div></div>
    <div class="row" style="margin-top:14px"><span class="muted small">Alert me by:</span>
      ${check("notifications.desktop", c.notifications.desktop, "Desktop")}
      ${check("notifications.email", c.notifications.email, "Gmail")}
      ${check("notifications.telegram", c.notifications.telegram, "Telegram")}
      <button id="test-notify" class="small">Send a test</button><span class="muted small">Gmail and Telegram are set up in Credentials.</span></div></div>

  <details class="panel section adv"><summary><h2 style="display:inline">Advanced</h2> <span class="muted small">AI models, quality bar, limits. The defaults work.</span></summary>
    <h3>AI provider</h3>
    <div class="grid g2">
      <label class="f">Which AI runs the crew${sel("llm.backend", c.llm.backend, [["claude-code", "Claude Pro / Max / Team plan (Claude Code login, no API key)"],
        ["anthropic", "Claude API (Anthropic API key)"], ["openai", "OpenAI API (OpenAI API key)"],
        ["openai-compatible", "OpenAI-compatible: Ollama, LM Studio, OpenRouter, Groq, vLLM..."]])}</label>
      <label class="f">Server address (OpenAI-compatible; optional for OpenAI)${inp("llm.api.base_url", c.llm.api.base_url, "url", 'placeholder="http://localhost:11434/v1"')}</label></div>
    <p class="muted small">API keys go in <a href="#credentials">Credentials</a>. OpenAI-compatible servers have no web search: researchers then suggest pages they know, and every page is still downloaded and checked.</p>
    ${c.llm.backend === "claude-code" ? "" : `<div class="grid g3">${[["opus", "Strongest (opus)"], ["sonnet", "Balanced (sonnet)"], ["haiku", "Fastest (haiku)"]].map(([t, l]) =>
      `<label class="f">${l} model${inp(`llm.api.models.${c.llm.backend}.${t}`, c.llm.api.models[c.llm.backend]?.[t] || "", "text", 'placeholder="model id"')}</label>`).join("")}</div>
      <p class="muted small">Agents ask for a tier; these are the ${esc(c.llm.backend)} models used for each. Prices for the cost estimate are in <span class="mono">config.json</span> (<span class="mono">llm.api.prices</span>).</p>`}
    <h3>AI models</h3>
    <p class="muted small">Model per agent: a tier (<span class="mono">haiku</span> = cheapest, <span class="mono">sonnet</span>, <span class="mono">opus</span> = strongest) or a full model id.
      "Max $" stops a single call. Save after changing the provider to see its model fields.</p>
    <table><thead><tr><th>Agent</th><th>What it does</th><th>Model</th><th>Timeout (s)</th><th>Max $ per call</th></tr></thead><tbody>${
      agents.filter(a => a.uses_llm).map(a => { const s = c.llm.agents[a.id] || {}; return `<tr><td><span class="who">${avatar(a.id, 1)}<b>${esc(a.name || a.title)}</b></span><div class="small muted">${esc(a.title)}</div></td><td class="small muted">${esc(a.role)}</td>
        <td>${inp(`llm.agents.${a.id}.model`, s.model ?? c.llm.defaults.model, "text", 'list="models" style="width:120px"')}</td>
        <td>${inp(`llm.agents.${a.id}.timeout_s`, s.timeout_s ?? c.llm.defaults.timeout_s, "number", 'min="30" max="3600" style="width:90px"')}</td>
        <td>${inp(`llm.agents.${a.id}.max_budget_usd`, s.max_budget_usd ?? c.llm.defaults.max_budget_usd, "number", 'step="0.05" min="0.05" max="20" style="width:90px"')}</td></tr>`; }).join("")}</tbody></table>
    <datalist id="models"><option value="haiku"><option value="sonnet"><option value="opus"></datalist>
    <h3>Quality bar and limits</h3><div class="grid g3">
      <label class="f">Minimum review score${inp("pipeline.min_overall", c.pipeline.min_overall, "number", 'min="0" max="100"')}</label>
      <label class="f">Minimum score on any single criterion${inp("pipeline.min_subscore", c.pipeline.min_subscore, "number", 'min="0" max="100"')}</label>
      <label class="f">Reviews per post (worst counts)${inp("pipeline.review_runs", c.pipeline.review_runs, "number", 'min="1" max="5"')}</label>
      <label class="f">Tries per agent${inp("pipeline.max_attempts_per_step", c.pipeline.max_attempts_per_step, "number", 'min="1" max="10"')}</label>
      <label class="f">Tries per post (all agents)${inp("pipeline.max_total_attempts", c.pipeline.max_total_attempts, "number", 'min="1" max="40"')}</label>
      <label class="f">Max $ per post${inp("pipeline.max_run_budget_usd", c.pipeline.max_run_budget_usd, "number", 'step="0.5" min="0.5" max="100"')}</label>
    </div>
    <h3>Team</h3><div class="grid g3">
      <label class="f">Researchers per post${inp("team.research", c.team.research, "number", 'min="1" max="4"')}</label>
      <label class="f">Writers per post${inp("team.writer", c.team.writer, "number", 'min="1" max="4"')}</label>
      <div style="padding-top:22px">${check("team.pre_review", c.team.pre_review, "Pre-review and polish drafts before the Editor")}</div>
      <label class="f">Judge members on their last (posts)${inp("team.fire_window", c.team.fire_window, "number", 'min="3" max="20"')}</label>
      <label class="f">Replace a member below (share of good posts, 0-1)${inp("team.fire_min_success", c.team.fire_min_success, "number", 'step="0.05" min="0" max="1"')}</label>
    </div>
    <h3>Other</h3><div class="grid g3">
      <label class="f">Write how many days ahead${inp("schedule.lead_days", c.schedule.lead_days, "number", 'min="0" max="7"')}</label>
      <label class="f">Check credentials daily at${inp("schedule.credential_check_time", c.schedule.credential_check_time, "time")}</label>
      <label class="f">Warn days before the LinkedIn token expires${inp("notifications.warn_days_before_expiry", c.notifications.warn_days_before_expiry, "number", 'min="1" max="30"')}</label>
      <label class="f">Claude Code command${inp("llm.claude_path", c.llm.claude_path)}</label>
      <label class="f">Longest AI answer (tokens, API providers)${inp("llm.api.max_output_tokens", c.llm.api.max_output_tokens, "number", 'min="1000" max="200000"')}</label>
      <label class="f">LinkedIn API version (YYYYMM)${inp("publishing.linkedin_api_version", c.publishing.linkedin_api_version)}</label>
      <label class="f">Blocked phrases (one per line)<textarea data-k="profile.blocklist" data-list="1" rows="3">${esc(c.profile.blocklist.join("\n"))}</textarea></label>
    </div></details>

  <div class="savebar"><span id="save-state" class="muted small">No changes</span><span class="spacer"></span>
    <button id="reset">Discard changes</button><button class="primary" id="save">Save settings</button></div>`;
  drawTopics(); drawDays();
  const dirty = () => { S.dirty = true; $("#save-state").textContent = "Unsaved changes"; };
  $("#view").addEventListener("input", e => { dirty(); if (e.target.dataset.c === "label") drawDays(); });
  $("#view").addEventListener("change", e => { dirty(); if (e.target.closest("#days")) drawTopicDays(); });
  $("#save").onclick = saveSettings;
  const planFromIdeas = replan => async () => {
    if (!(await saveSettings())) return;
    document.querySelectorAll("#ideas-plan, #ideas-replan").forEach(b => b.disabled = true);
    $("#ideas-state").textContent = "The Week Planner is working (about a minute)…";
    try { await post("/api/plan/fill", { replan }); toast("Plan updated"); location.hash = "plan"; }
    catch (e) { toast(e.message, true); document.querySelectorAll("#ideas-plan, #ideas-replan").forEach(b => b.disabled = false);
      $("#ideas-state").textContent = e.message; }
  };
  $("#ideas-plan").onclick = planFromIdeas(false);
  $("#ideas-replan").onclick = planFromIdeas(true);
  $("#reset").onclick = () => { S.dirty = false; renderSettings(); };
  const addTopic = () => {
    const name = $("#new-topic").value.trim(); if (!name) return $("#new-topic").focus();
    collectSettings();
    let id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 28) || "topic";
    for (let n = 2; S.config.categories[id]; n++) id = id.replace(/-\d+$/, "") + "-" + n;
    S.config.categories[id] = { label: name, media: "poster", layouts: ["points"], kicker: name.toUpperCase().slice(0, 26), research: "optional",
      min_chars: 500, max_chars: 1800, fact_check: false, ideas: [],
      brief: `A useful post about ${name}: a hook, the key points a reader can act on, a question, and 3-4 hashtags.` };
    $("#new-topic").value = ""; drawTopics(); drawDays(); dirty();
    $(`[data-cat="${id}"] [data-c="ideas"]`).focus();
  };
  $("#add-topic").onclick = addTopic;
  $("#new-topic").onkeydown = e => { if (e.key === "Enter") addTopic(); };
  $("#test-notify").onclick = async () => { await post("/api/notifications/test"); toast("Sent"); refreshOverview(); };
}
function isFixedTopic(id, k) { return k.media === "animation" || id === "week-recap"; }
function drawTopics() {
  const c = S.config;
  const opt = (f, val, opts) => `<select data-c="${f}">${opts.map(([v, l]) => `<option value="${v}" ${v === val ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  $("#topics").innerHTML = Object.entries(c.categories).map(([id, k]) => {
    const fixed = isFixedTopic(id, k), used = (S.ideaUse?.[id] || []).filter(x => x.used_on);
    return `<div class="topic" data-cat="${esc(id)}">
      <div class="row"><input data-c="label" value="${esc(k.label)}" class="topic-name" maxlength="60" aria-label="Topic name">
        <button class="danger small" data-delcat="${esc(id)}" title="Remove this topic">Remove</button></div>
      <div class="small muted topic-days" style="margin:4px 0 6px"></div>
      ${fixed ? `<div class="muted small fixed">${k.media === "animation" ? "Picks the next algorithm from the built-in library automatically." : "Sums up the week's posts automatically."}</div>`
        : `<textarea data-c="ideas" rows="4" placeholder="Your ideas, one per line&#10;e.g. Kafka consumer groups">${esc((k.ideas || []).join("\n"))}</textarea>`}
      ${used.length ? `<div class="small muted" style="margin-top:4px">Already used: ${used.map(x => `${esc(x.idea)} (${esc(x.used_on)})`).join("; ")}</div>` : ""}
      <details class="more"><summary class="small">More options</summary><div class="grid g2" style="margin-top:8px">
        <label class="f">Picture${opt("media", k.media, [["poster", "Poster image"], ["animation", "Algorithm video"], ["none", "No picture"]])}</label>
        <label class="f">Research${opt("research", k.research || "optional", [["required", "Always, with sources"], ["optional", "When useful"], ["off", "None"]])}</label>
        <label class="f">Poster style<input data-c="layouts" value="${esc((k.layouts || []).join(", "))}" placeholder="points, steps, code, flow"></label>
        <label class="f">Label on the poster<input data-c="kicker" value="${esc(k.kicker || "")}" maxlength="26"></label>
        <label class="f">Shortest post (characters)<input type="number" data-c="min_chars" value="${k.min_chars}"></label>
        <label class="f">Longest post (characters)<input type="number" data-c="max_chars" value="${k.max_chars}" max="3000"></label>
        <label class="f">Sources newer than (days)<input type="number" data-c="max_source_age_days" value="${esc(k.max_source_age_days ?? "")}" placeholder="any age"></label>
        <div style="padding-top:20px"><label class="checkline"><input type="checkbox" data-c="plan_ahead" ${k.plan_ahead !== false ? "checked" : ""}> Plan a week ahead</label>
          <label class="checkline"><input type="checkbox" data-c="fact_check" ${k.fact_check ? "checked" : ""}> Every number needs a source</label></div>
      </div><label class="f" style="margin-top:8px">What this kind of post must contain<textarea data-c="brief" rows="3">${esc(k.brief)}</textarea></label></details>
    </div>`; }).join("");
  document.querySelectorAll("[data-delcat]").forEach(b => b.onclick = () => {
    const id = b.dataset.delcat;
    if (!confirm(`Remove the topic "${S.config.categories[id].label}"? Days that use it will have no post.`)) return;
    collectSettings(); delete S.config.categories[id];
    WEEKDAYS.forEach(d => { if (S.config.schedule.days[d] === id) S.config.schedule.days[d] = ""; });
    drawTopics(); drawDays(); S.dirty = true; $("#save-state").textContent = "Unsaved changes";
  });
  drawTopicDays();
}
function topicNames() {
  const out = {};
  document.querySelectorAll("#topics [data-cat]").forEach(box => out[box.dataset.cat] = box.querySelector('[data-c="label"]').value.trim() || box.dataset.cat);
  return out;
}
function drawDays() {
  // the day menus are rebuilt from the topic cards, keeping each day's choice
  const names = topicNames(), cur = {};
  WEEKDAYS.forEach(d => { const el = $(`#days [data-k="schedule.days.${d}"]`); cur[d] = el ? el.value : (S.config.schedule.days[d] || ""); });
  $("#days").innerHTML = WEEKDAYS.map(d => `<label class="f">${DAY_NAMES[d]}<select data-k="schedule.days.${d}">
    <option value="">No post</option>${Object.entries(names).map(([id, n]) => `<option value="${esc(id)}" ${id === cur[d] ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>`).join("");
  drawTopicDays();
}
function drawTopicDays() {
  document.querySelectorAll("#topics [data-cat]").forEach(box => {
    const id = box.dataset.cat, days = WEEKDAYS.filter(d => ($(`#days [data-k="schedule.days.${d}"]`)?.value ?? S.config.schedule.days[d]) === id);
    box.querySelector(".topic-days").innerHTML = days.length ? `Posted on ${days.map(d => DAY_NAMES[d]).join(", ")}`
      : `<span style="color:var(--warn)">Not on the schedule yet. Pick it for a day in step 2.</span>`;
  });
}
function setPath(obj, path, val) { const ks = path.split("."); let o = obj; ks.slice(0, -1).forEach(k => o = o[k] ??= {}); o[ks.at(-1)] = val; }
function collectSettings() {
  const cfg = S.config;
  document.querySelectorAll("[data-k]").forEach(el => {
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.list) v = v.split("\n").map(s => s.trim()).filter(Boolean);
    else if (el.type === "number") v = el.step && el.step.includes(".") ? parseFloat(v) : parseInt(v, 10);
    setPath(cfg, el.dataset.k, v);
  });
  document.querySelectorAll("[data-cat]").forEach(box => {
    const k = cfg.categories[box.dataset.cat]; if (!k) return;
    box.querySelectorAll("[data-c]").forEach(el => {
      const f = el.dataset.c; let v = el.type === "checkbox" ? el.checked : el.value;
      if (f === "layouts") v = v.split(",").map(s => s.trim()).filter(Boolean);
      if (f === "ideas") v = v.split("\n").map(s => s.trim()).filter(Boolean);
      if (["min_chars", "max_chars"].includes(f)) v = parseInt(v, 10);
      if (f === "max_source_age_days") { if (v === "") { delete k[f]; return; } v = parseInt(v, 10); }
      k[f] = v;
    });
  });
  return cfg;
}
async function saveSettings() {
  const cfg = collectSettings();
  try {
    const r = await api("/api/config", { method: "PUT", body: { config: cfg } });
    if (!r.ok) {
      $("#cfg-errors").innerHTML = `<div class="banner error"><div class="grow"><b>Not saved. Fix these:</b><ul class="err-list">${r.errors.map(e => `<li>${esc(e)}</li>`).join("")}</ul></div></div>`;
      window.scrollTo({ top: 0, behavior: "smooth" }); return false;
    }
    S.dirty = false; $("#cfg-errors").innerHTML = ""; $("#save-state").textContent = "Saved"; toast("Settings saved"); refreshOverview(); return true;
  } catch (e) { toast(e.message, true); return false; }
}

/* ---------- credentials ---------- */
async function renderCredentials() {
  const d = await api("/api/credentials"), s = d.secrets, st = d.status || {}, li = st.linkedin || {}, cl = st.ai || st.claude || {};
  const set = v => v ? `<span class="secret-state" style="color:var(--ok)">saved</span>` : `<span class="secret-state muted">not set</span>`;
  $("#view").innerHTML = `<h1>Credentials</h1><p class="sub">Stored only in <span class="mono">workspace/secrets.json</span> (readable by you only). The browser can set them but never read them back.</p>
  <div class="grid g2">
  <div class="panel"><div class="row"><h2 style="margin:0">LinkedIn</h2><span class="spacer"></span>${chip(li.state || "unknown")}</div>
    <p>${esc(li.message || "Not checked yet.")}</p>
    ${s.linkedin_name ? `<p class="small">Connected as <b>${esc(s.linkedin_name)}</b>${s.linkedin_token_expires_at ? ` · token valid until <b>${esc(s.linkedin_token_expires_at.slice(0, 10))}</b>` : ""}</p>` : ""}
    <div class="row"><a class="btn primary" href="/oauth/start">${s.linkedin_access_token ? "Reconnect LinkedIn" : "Connect LinkedIn"}</a>
      <button id="check">Check now</button>${s.linkedin_access_token ? `<button class="danger" id="disconnect">Disconnect</button>` : ""}</div>
    <p class="muted small">Checked ${ago(st.checked_at) || "never"}. The Credential Monitor checks daily and before every publish, and notifies you ${esc((await api("/api/config")).config.notifications.warn_days_before_expiry)} days before the token expires.</p>
    <h3>LinkedIn app</h3>
    <div class="grid g2"><label class="f">Client ID ${set(s.linkedin_client_id)}<input id="cid" value="${esc(s.linkedin_client_id || "")}" autocomplete="off"></label>
      <label class="f">Client Secret ${set(s.linkedin_client_secret)}<input id="csecret" type="password" placeholder="${s.linkedin_client_secret ? "•••••••• (saved, type to replace)" : ""}" autocomplete="new-password"></label></div>
    <div class="row" style="margin-top:10px"><button id="save-app">Save app details</button></div>
    <details style="margin-top:14px"><summary><b>How to create the LinkedIn app (5 minutes, free)</b></summary><ol class="steps-list small" style="margin-top:8px">
      <li>Open <a href="https://www.linkedin.com/developers/apps" target="_blank" rel="noopener">linkedin.com/developers/apps</a> and click <b>Create app</b>. It must be linked to a LinkedIn Page; create a free one if you have none.</li>
      <li>On <b>Products</b>, add <b>Share on LinkedIn</b> and <b>Sign In with LinkedIn using OpenID Connect</b>.</li>
      <li>On <b>Auth</b>, add this redirect URL exactly: <span class="mono">${esc(d.redirect_uri)}</span></li>
      <li>Copy the <b>Client ID</b> and <b>Client Secret</b> from the Auth tab into the fields above and save.</li>
      <li>Click <b>Connect LinkedIn</b>, sign in and allow. Scopes requested: <span class="mono">${esc(d.scopes)}</span>.</li>
      <li>Tokens last about 60 days. When the monitor warns you, click <b>Reconnect LinkedIn</b>.</li></ol></details></div>
  <div class="panel"><div class="row"><h2 style="margin:0">AI provider: ${esc(PROVIDERS[d.backend] || d.backend)}</h2><span class="spacer"></span>${chip(cl.backend && cl.backend !== d.backend ? "unknown" : cl.state || "unknown")}</div>
    <p>${esc(cl.backend && cl.backend !== d.backend ? "Not checked yet: click Check now." : cl.message || "Not checked yet.")}</p>
    <div class="row"><button id="test-ai">Test with a tiny call</button><span class="muted small" id="ai-result"></span></div>
    <p class="muted small">${d.backend === "claude-code" ? `Uses your Claude Pro / Max / Team plan. Not logged in? Run <span class="mono">claude</span> once in a terminal and log in. No API key is needed.`
      : d.backend === "openai-compatible" ? `Server: <span class="mono">${esc(d.base_url || "not set")}</span>. The key is optional (local servers such as Ollama need none).` : `Pay-as-you-go with your own API key.`}
      Change the provider in <a href="#settings">Settings > Advanced</a>.</p>
    ${d.backend === "claude-code" ? "" : (() => { const k = { anthropic: ["anthropic_api_key", "Anthropic API key", "sk-ant-...", "https://console.anthropic.com/settings/keys"],
        openai: ["openai_api_key", "OpenAI API key", "sk-...", "https://platform.openai.com/api-keys"], "openai-compatible": ["llm_api_key", "API key (optional)", "", ""] }[d.backend];
      return `<div class="grid g2"><label class="f">${k[1]} ${set(s[k[0]])}<input id="ai-key" type="password" placeholder="${s[k[0]] ? "•••••••• (saved, type to replace)" : k[2]}" autocomplete="new-password"></label>
        <div style="padding-top:22px"><button id="save-ai" data-k="${k[0]}">Save key</button>${s[k[0]] ? ` <button class="danger" id="del-ai" data-k="${k[0]}">Remove</button>` : ""}</div></div>
        ${k[3] ? `<p class="muted small">Create one at <a href="${k[3]}" target="_blank" rel="noopener">${k[3].replace("https://", "")}</a>. Stored only in <span class="mono">workspace/secrets.json</span>.</p>` : ""}`; })()}
    <h3>Gmail notifications (optional)</h3>
    <ol class="muted small"><li>Turn on <a href="https://myaccount.google.com/signinoptions/two-step-verification" target="_blank" rel="noopener">2-Step Verification</a> for the Gmail account.</li>
      <li>Create an <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">App Password</a> (name it "Postcrew") and paste the 16 characters below. Never use your normal Gmail password.</li></ol>
    <div class="grid g2"><label class="f">Gmail address ${set(s.gmail_address)}<input id="gm-addr" type="email" value="${esc(s.gmail_address || "")}" placeholder="you@gmail.com"></label>
      <label class="f">App password ${set(s.gmail_app_password)}<input id="gm-pass" type="password" placeholder="${s.gmail_app_password ? "•••••••• (saved)" : "16 characters"}" autocomplete="new-password"></label>
      <label class="f">Send to (optional) ${set(s.email_to)}<input id="gm-to" type="email" value="${esc(s.email_to || "")}" placeholder="same as the Gmail address"></label></div>
    <div class="row" style="margin-top:10px"><button id="save-gm">Save Gmail</button><button id="test-gm">Send a test email</button><span class="muted small" id="gm-result"></span></div>
    <p class="muted small">Turn on Gmail email in Settings > Notifications after saving.</p>
    <h3>Telegram notifications (optional)</h3>
    <div class="grid g2"><label class="f">Bot token ${set(s.telegram_bot_token)}<input id="tg-token" type="password" placeholder="${s.telegram_bot_token ? "•••••••• (saved)" : "from @BotFather"}" autocomplete="new-password"></label>
      <label class="f">Chat id ${set(s.telegram_chat_id)}<input id="tg-chat" value="${esc(s.telegram_chat_id || "")}"></label></div>
    <div class="row" style="margin-top:10px"><button id="save-tg">Save Telegram</button></div>
    <p class="muted small">Turn on Telegram in Settings > Notifications after saving.</p></div></div>`;
  $("#check").onclick = async () => { const b = $("#check"); b.disabled = true; try { await post("/api/credentials/check"); toast("Checked"); } catch (e) { toast(e.message, true); } renderCredentials(); refreshOverview(); };
  if ($("#disconnect")) $("#disconnect").onclick = async () => { if (!confirm("Remove the LinkedIn token from this computer?")) return; await post("/api/credentials/disconnect"); renderCredentials(); };
  $("#save-app").onclick = async () => {
    const body = { linkedin_client_id: $("#cid").value.trim() }; if ($("#csecret").value) body.linkedin_client_secret = $("#csecret").value.trim();
    try { await api("/api/credentials", { method: "PUT", body }); toast("App details saved"); renderCredentials(); } catch (e) { toast(e.message, true); }
  };
  $("#save-gm").onclick = async () => {
    const body = { gmail_address: $("#gm-addr").value.trim(), email_to: $("#gm-to").value.trim() }; if ($("#gm-pass").value) body.gmail_app_password = $("#gm-pass").value.trim();
    try { await api("/api/credentials", { method: "PUT", body }); toast("Gmail saved"); renderCredentials(); } catch (e) { toast(e.message, true); }
  };
  $("#test-gm").onclick = async () => {
    const b = $("#test-gm"); b.disabled = true; $("#gm-result").textContent = "sending…";
    const r = await post("/api/notifications/test-email").catch(e => ({ ok: false, error: e.message }));
    $("#gm-result").textContent = r.ok ? `Sent to ${r.to}. Check the inbox (and spam).` : `Failed: ${r.error}`; b.disabled = false;
  };
  $("#save-tg").onclick = async () => {
    const body = { telegram_chat_id: $("#tg-chat").value.trim() }; if ($("#tg-token").value) body.telegram_bot_token = $("#tg-token").value.trim();
    try { await api("/api/credentials", { method: "PUT", body }); toast("Telegram saved"); renderCredentials(); } catch (e) { toast(e.message, true); }
  };
  const saveKey = (k, v) => api("/api/credentials", { method: "PUT", body: { [k]: v } }).then(async () => {
    toast(v ? "Key saved" : "Key removed"); await post("/api/credentials/check"); renderCredentials(); refreshOverview(); }).catch(e => toast(e.message, true));
  if ($("#save-ai")) $("#save-ai").onclick = e => { const v = $("#ai-key").value.trim(); if (v) saveKey(e.target.dataset.k, v); else $("#ai-key").focus(); };
  if ($("#del-ai")) $("#del-ai").onclick = e => { if (confirm("Remove this API key from this computer?")) saveKey(e.target.dataset.k, ""); };
  $("#test-ai").onclick = async () => {
    const b = $("#test-ai"); b.disabled = true; $("#ai-result").textContent = "calling…";
    const r = await post("/api/credentials/test-ai").catch(e => ({ ok: false, error: e.message }));
    $("#ai-result").textContent = r.ok ? `OK: ${r.model} answered in ${r.seconds}s (${money(r.cost_usd)})` : `Failed: ${r.error}`; b.disabled = false;
  };
}

/* ---------- notifications drawer ---------- */
$("#bell").onclick = async () => {
  const dr = $("#drawer");
  if (!dr.hidden) { dr.hidden = true; return; }
  const { items } = await api("/api/notifications");
  dr.innerHTML = `<div class="row"><h2 style="margin:0">Notifications</h2><span class="spacer"></span><button id="mark-read">Mark all read</button></div><div style="margin-top:12px">${
    items.slice().reverse().map(n => `<div class="note ${esc(n.level)} ${n.read ? "" : "unread"}"><div class="title">${esc(n.title)}</div>
      <div class="small">${esc(n.message)}</div><div class="row small muted" style="margin-top:4px">${ago(n.ts)}<span class="spacer"></span>
      ${n.action ? `<a href="#${esc(n.action.tab)}" class="small">${esc(n.action.label)}</a>` : ""}</div></div>`).join("") || `<div class="empty">Nothing yet.</div>`}</div>`;
  dr.hidden = false;
  $("#mark-read").onclick = async () => { await post("/api/notifications/read", {}); dr.hidden = true; refreshOverview(); };
  dr.querySelectorAll("a[href^='#']").forEach(a => a.addEventListener("click", () => dr.hidden = true));
};

window.addEventListener("beforeunload", e => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
setInterval(refreshOverview, 15000);
async function loadAgents() {
  try { S.agents = Object.fromEntries((await api("/api/agents")).agents.map(a => [a.id, a])); } catch (e) { /* names fall back to AGENTS */ }
}
Promise.all([refreshOverview(), loadAgents()]).then(() => setTab(location.hash.slice(1) || "overview"));
