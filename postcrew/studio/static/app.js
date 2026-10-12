/* Postcrew Studio - no build step, no dependencies. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STEP_TITLES = { credentials: "Credential Monitor", topic: "Topic Scout", research: "Researcher", writer: "Writer",
  media: "Visual Designer", editor: "Editor Review", formatter: "Formatter", publisher: "Publisher" };
const STATE_COLORS = { pending: ["#ffffff", "#c9ced6", "#5d6470"], running: ["#f1ecfb", "#6941c6", "#6941c6"],
  retrying: ["#f1ecfb", "#6941c6", "#6941c6"], passed: ["#e6f4ec", "#0a7d43", "#0a7d43"], failed: ["#fdecea", "#b42318", "#b42318"],
  skipped: ["#f5f6f8", "#d5d9e0", "#8a919c"], blocked: ["#fdecea", "#f0a39b", "#b42318"], waiting: ["#fdf3e2", "#a15c07", "#a15c07"] };
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

const S = { tab: "overview", overview: null, runId: null, run: null, events: [], lastT: 0, selected: null,
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
  if (S.dirty && S.tab === "settings" && tab !== "settings" && !confirm("You have unsaved settings. Leave anyway?")) {
    location.hash = "settings"; return;
  }
  S.dirty = false;
  S.tab = tab;
  document.querySelectorAll("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
  clearInterval(S.poll); S.poll = null;
  ({ overview: renderOverview, plan: renderPlan, workflow: renderWorkflow, queue: renderQueue, settings: renderSettings,
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
  const li = o.credentials?.linkedin, cl = o.credentials?.claude;
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
  const { runs } = await api("/api/runs");
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
    </div>`;
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
  $("#wf-graph").innerHTML = graphSvg(st);
  rebindNodes();
  drawTimeline();
  if (S.selected) drawStep();
}
function rebindNodes() {
  document.querySelectorAll(".wf .node").forEach(n => n.onclick = () => { S.selected = n.dataset.step;
    $("#wf-graph").innerHTML = graphSvg(S.run.status); rebindNodes(); drawStep(); drawTimeline(); });
}

function graphSvg(st) {
  const steps = Object.keys(STEP_TITLES), W = 150, H = 66, GAP = 34, X0 = 20, Y = 128;
  const width = X0 * 2 + steps.length * W + (steps.length - 1) * GAP;
  const supX = width / 2 - 90, supY = 14;
  const supState = st ? (st.state === "running" ? "running" : st.state === "failed" ? "failed" : "passed") : "pending";
  let svg = `<svg class="wf" viewBox="0 0 ${width} 260" role="img" aria-label="Agent workflow">`;
  steps.forEach((s, i) => {
    const x = X0 + i * (W + GAP);
    svg += `<path class="sup" d="M ${supX + 90} ${supY + 50} C ${supX + 90} 90, ${x + W / 2} 90, ${x + W / 2} ${Y}"/>`;
    if (i < steps.length - 1) {
      const done = st && st.steps[s] && ["passed", "skipped"].includes(st.steps[s].state);
      svg += `<path class="edge ${done ? "done" : ""}" d="M ${x + W} ${Y + H / 2} L ${x + W + GAP - 6} ${Y + H / 2}" marker-end="url(#arr${done ? "d" : ""})"/>`;
    }
  });
  const [sf, ss, stx] = STATE_COLORS[supState];
  svg += `<defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#b8bfca"/></marker>
    <marker id="arrd" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#0a7d43"/></marker></defs>`;
  svg += `<g class="node ${S.selected === "supervisor" ? "selected" : ""}" data-step="supervisor"><rect x="${supX}" y="${supY}" width="180" height="50" rx="12" fill="${sf}" stroke="${ss}"/>
    <text x="${supX + 90}" y="${supY + 22}" text-anchor="middle" fill="#17191c">Supervisor</text>
    <text class="st" x="${supX + 90}" y="${supY + 39}" text-anchor="middle" fill="${stx}">${st ? st.interventions + " intervention(s)" : "orchestrates the crew"}</text></g>`;
  steps.forEach((s, i) => {
    const x = X0 + i * (W + GAP), info = st?.steps[s] || { state: "pending", attempts: 0 };
    const [fill, stroke, tc] = STATE_COLORS[info.state] || STATE_COLORS.pending;
    const label = info.state === "retrying" ? `retrying (try ${info.attempts})` : info.state + (info.attempts > 1 ? ` · ${info.attempts} tries` : "");
    svg += `<g class="node ${info.state} ${S.selected === s ? "selected" : ""}" data-step="${s}">
      <rect x="${x}" y="${Y}" width="${W}" height="${H}" rx="12" fill="${fill}" stroke="${stroke}"/>
      <text x="${x + W / 2}" y="${Y + 27}" text-anchor="middle" fill="#17191c">${esc(STEP_TITLES[s])}</text>
      <text class="st" x="${x + W / 2}" y="${Y + 46}" text-anchor="middle" fill="${tc}">${esc(label)}</text></g>`;
    if (info.cost_usd) svg += `<text x="${x + W / 2}" y="${Y + H + 18}" text-anchor="middle" font-size="11" fill="#5d6470">${money(info.cost_usd)}</text>`;
  });
  // supervisor rewinds: a return arrow under the graph from the step that failed back to where work restarted
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
    const x1 = X0 + i * (W + GAP) + W / 2, x2 = X0 + j * (W + GAP) + W / 2, y = Y + H, dip = 34 + idx * 10;
    svg += `<path d="M ${x1} ${y + 26} C ${x1} ${y + dip + 20}, ${x2} ${y + dip + 20}, ${x2} ${y + 26}" fill="none" stroke="#b42318"
      stroke-width="1.8" stroke-dasharray="5 4" marker-end="url(#arrr)"/>
      <text x="${(x1 + x2) / 2}" y="${y + dip + 22}" text-anchor="middle" font-size="11" font-weight="600" fill="#b42318">sent back ×${n}</text>`;
  });
  svg += `<defs><marker id="arrr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#b42318"/></marker></defs>`;
  return svg + "</svg>";
}

async function drawStep() {
  const s = S.selected, st = S.run.status;
  $("#step-title").textContent = s === "supervisor" ? "Supervisor" : STEP_TITLES[s];
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
    <span class="s">${esc(e.step)}</span><span class="m">${esc(e.kind)}: ${esc(e.message)}
    ${e.data ? `<details><summary class="small muted">details</summary><pre>${esc(JSON.stringify(e.data, null, 2))}</pre></details>` : ""}</span></div>`).join("")
    || `<div class="empty">No events yet.</div>`;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

/* ---------- queue ---------- */
async function renderQueue() {
  const { queue, history } = await api("/api/queue");
  const live = queue.filter(p => p.status !== "vetoed").sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  const vetoed = queue.filter(p => p.status === "vetoed");
  $("#view").innerHTML = `<h1>Queue</h1><p class="sub">Posts that passed the Editor Review. Approve, edit, veto or publish them here.</p>
    <div class="cards">${live.map(postCard).join("") || `<div class="panel empty">The queue is empty.</div>`}</div>
    ${vetoed.length ? `<h2 style="margin-top:28px">Vetoed</h2><div class="cards">${vetoed.map(postCard).join("")}</div>` : ""}
    <div class="panel" style="margin-top:28px"><h2>Published</h2>${history.length ? `<table><thead><tr><th>Date</th><th>Topic</th><th>Category</th><th>LinkedIn</th></tr></thead><tbody>${
      history.slice().reverse().map(h => `<tr><td>${esc(h.date)}</td><td>${esc(h.topic)}</td><td>${esc(h.category)}</td><td class="mono small">${esc(h.urn || "")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty">Nothing published yet.</div>`}</div>`;
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
  const src = { planner: ["queued", "Planner"], manual: ["approved", "You"], auto: ["ok", "Automatic"] };
  const row = r => {
    if (!r.category) return `<tr class="muted"><td><b>${esc(r.weekday)}</b><div class="small">${esc(r.date)}</div></td><td colspan="3" class="small">No post scheduled</td></tr>`;
    const head = `<td><b>${esc(r.weekday)}</b><div class="small muted">${esc(r.date)}</div></td><td class="small">${esc(r.label)}</td>`;
    if (r.written) return `<tr>${head}<td><b>${esc(r.written.topic)}</b><div class="small muted">Already written. Change it in the Queue.</div></td><td>${chip(r.written.status)}</td></tr>`;
    const e = r.entry, s = e ? src[e.source] || ["queued", e.source] : null;
    const note = e ? (e.rejected?.length ? `Rejected before: ${e.rejected.map(esc).join("; ")}` : "")
      : r.fixed ? "Chosen automatically when the plan is made." : r.plan_ahead ? "Not planned yet." : "Fresh news: the Topic Scout picks it the day before. Type a topic to choose it yourself.";
    return `<tr data-day="${esc(r.date)}">${head}
      <td><input class="p-topic" value="${esc(e?.topic || "")}" placeholder="${r.plan_ahead || r.fixed ? "Topic" : "Picked the day before (or type one)"}" maxlength="90">
        <input class="p-angle small" style="margin-top:6px" value="${esc(e?.angle || "")}" placeholder="Angle: what the reader will learn (optional)" maxlength="400">
        ${note ? `<div class="small muted" style="margin-top:4px">${note}</div>` : ""}
        <div class="row" style="margin-top:6px"><input class="p-hint small" style="flex:1;min-width:180px" placeholder="Optional: what you'd like instead" maxlength="300">
          <button class="p-suggest">Suggest another</button><button class="p-save primary">Save</button>${e ? `<button class="p-clear">Clear</button>` : ""}</div></td>
      <td>${s ? chip(s[0], s[1]) : chip("pending", "open")}</td></tr>`;
  };
  $("#view").innerHTML = `<h1>Plan</h1><p class="sub">The topic for every day until the end of next week. The Week Planner drafts next week every
    ${esc(DAY_NAMES[d.planning.weekday])} at ${esc(d.planning.time)}${d.planning.enabled ? "" : " (switched off in Settings)"}. Change any topic, or ask for a different one;
    the Topic Scout writes about whatever is here.</p>
    <div class="row" style="margin-bottom:12px"><button class="primary" id="p-fill">Plan open days now</button><span class="muted small" id="p-state">Next week: ${esc(d.next_week[0])} to ${esc(d.next_week[1])}</span></div>
    <div class="panel"><table><thead><tr><th style="width:120px">Day</th><th style="width:180px">Category</th><th>Topic</th><th style="width:110px">From</th></tr></thead>
    <tbody>${d.days.map(row).join("")}</tbody></table></div>`;
  const busy = (b, on, label) => { document.querySelectorAll("#view button").forEach(x => x.disabled = on); if (label) $("#p-state").textContent = label; };
  $("#p-fill").onclick = async () => {
    busy(null, true, "The Week Planner is working (about a minute)…");
    try { await post("/api/plan/fill"); toast("Plan updated"); } catch (e) { toast(e.message, true); }
    renderPlan(); refreshOverview();
  };
  document.querySelectorAll("tr[data-day]").forEach(tr => {
    const day = tr.dataset.day, q = s => tr.querySelector(s);
    const save = async topic => {
      try { await api(`/api/plan/${day}`, { method: "PUT", body: { topic, angle: topic ? q(".p-angle").value : "" } }); toast(topic ? "Saved" : "Cleared"); renderPlan(); }
      catch (e) { toast(e.message, true); }
    };
    q(".p-save").onclick = () => save(q(".p-topic").value.trim());
    if (q(".p-clear")) q(".p-clear").onclick = () => save("");
    q(".p-suggest").onclick = async () => {
      busy(null, true, `Asking the Week Planner for a new ${day} topic…`);
      try { await post(`/api/plan/${day}/suggest`, { hint: q(".p-hint").value.trim() }); toast("New topic suggested"); } catch (e) { toast(e.message, true); }
      renderPlan();
    };
  });
}

/* ---------- settings (configurator) ---------- */
async function renderSettings() {
  const [{ config }, { agents }] = await Promise.all([api("/api/config"), api("/api/agents")]);
  S.config = config;
  const c = config, cats = Object.keys(c.categories);
  const sel = (id, val, opts) => `<select data-k="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${v === val ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const inp = (id, val, type = "text", extra = "") => `<input data-k="${id}" type="${type}" value="${esc(val)}" ${extra}>`;
  $("#view").innerHTML = `<h1>Settings</h1><p class="sub">Everything the crew needs to know. Saved to <span class="mono">config.json</span> (no secrets here).</p>
  <div id="cfg-errors"></div>
  <div class="panel section"><h2>You</h2><div class="grid g2">
    <label class="f">Name${inp("profile.name", c.profile.name)}</label>
    <label class="f">Handle printed on posters${inp("profile.handle", c.profile.handle, "text", 'placeholder="linkedin.com/in/your-name"')}</label>
    <label class="f">Audience${inp("profile.audience", c.profile.audience)}</label>
    <label class="f">Voice${inp("profile.voice", c.profile.voice)}</label>
    <label class="f">True facts about you (one per line). The writer never invents experience; it may only use these.<textarea data-k="profile.about" data-list="1">${esc(c.profile.about.join("\n"))}</textarea></label>
    <label class="f">Blocked phrases (one per line). A post containing any of them is rejected.<textarea data-k="profile.blocklist" data-list="1">${esc(c.profile.blocklist.join("\n"))}</textarea></label>
  </div></div>
  <div class="panel section"><h2>Schedule</h2><div class="grid g4">
    <label class="f">Time zone${inp("schedule.timezone", c.schedule.timezone, "text", 'list="tzs"')}</label>
    <label class="f">Crew writes at${inp("schedule.generate_time", c.schedule.generate_time, "time")}</label>
    <label class="f">Post is published at${inp("schedule.post_time", c.schedule.post_time, "time")}</label>
    <label class="f">Write how many days ahead${inp("schedule.lead_days", c.schedule.lead_days, "number", 'min="0" max="7"')}</label>
    <label class="f">Credential check at${inp("schedule.credential_check_time", c.schedule.credential_check_time, "time")}</label>
  </div><h3>Week Planner</h3><div class="grid g4">
    <label class="checkline" style="margin-top:20px"><input type="checkbox" data-k="planning.enabled" ${c.planning.enabled ? "checked" : ""}> Plan next week's topics automatically</label>
    <label class="f">Plan on${sel("planning.weekday", c.planning.weekday, WEEKDAYS.map(d => [d, DAY_NAMES[d]]))}</label>
    <label class="f">Plan at${inp("planning.time", c.planning.time, "time")}</label>
  </div><h3>What to post each day</h3><div class="days">${WEEKDAYS.map(d => `<label class="f">${DAY_NAMES[d]}${sel("schedule.days." + d, c.schedule.days[d] || "", [["", "No post"], ...cats.map(id => [id, c.categories[id].label])])}</label>`).join("")}</div>
  <datalist id="tzs">${(Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : []).map(z => `<option value="${esc(z)}">`).join("")}</datalist></div>
  <div class="panel section"><h2>Publishing</h2><div class="grid g3">
    <label class="f">After a post passes review${sel("publishing.approval", c.publishing.approval, [["auto_with_veto", "Publish at post time unless I veto (default)"], ["manual", "Wait for my approval"], ["immediate", "Publish immediately"]])}</label>
    <label class="f">LinkedIn API version (YYYYMM)${inp("publishing.linkedin_api_version", c.publishing.linkedin_api_version)}</label>
    <label class="checkline" style="margin-top:20px"><input type="checkbox" data-k="publishing.dry_run" ${c.publishing.dry_run ? "checked" : ""}> Dry run: log what would be published, send nothing</label>
  </div></div>
  <div class="panel section"><h2>AI models (Claude Code)</h2>
    <p class="muted small">Every agent runs through your Claude Code login (<span class="mono">claude -p</span>), isolated from your own settings, with only the tools it needs.
      Model: <span class="mono">haiku</span>, <span class="mono">sonnet</span>, <span class="mono">opus</span> or a full model id. Budget is a hard stop per call.</p>
    <div class="grid g3"><label class="f">Claude Code command${inp("llm.claude_path", c.llm.claude_path)}</label></div>
    <table style="margin-top:10px"><thead><tr><th>Agent</th><th>What it does</th><th>Model</th><th>Timeout (s)</th><th>Max $ per call</th></tr></thead><tbody>${
      agents.filter(a => a.uses_llm).map(a => { const s = c.llm.agents[a.id] || {}; return `<tr><td><b>${esc(a.title)}</b></td><td class="small muted">${esc(a.role)}</td>
        <td>${inp(`llm.agents.${a.id}.model`, s.model ?? c.llm.defaults.model, "text", 'list="models" style="width:140px"')}</td>
        <td>${inp(`llm.agents.${a.id}.timeout_s`, s.timeout_s ?? c.llm.defaults.timeout_s, "number", 'min="30" max="3600" style="width:100px"')}</td>
        <td>${inp(`llm.agents.${a.id}.max_budget_usd`, s.max_budget_usd ?? c.llm.defaults.max_budget_usd, "number", 'step="0.05" min="0.05" max="20" style="width:100px"')}</td></tr>`; }).join("")}</tbody></table>
    <datalist id="models"><option value="haiku"><option value="sonnet"><option value="opus"></datalist></div>
  <div class="panel section"><h2>Quality gate &amp; limits</h2><div class="grid g3">
    <label class="f">Reviews per post (worst score counts)${inp("pipeline.review_runs", c.pipeline.review_runs, "number", 'min="1" max="5"')}</label>
    <label class="f">Minimum overall score${inp("pipeline.min_overall", c.pipeline.min_overall, "number", 'min="0" max="100"')}</label>
    <label class="f">Minimum sub-score${inp("pipeline.min_subscore", c.pipeline.min_subscore, "number", 'min="0" max="100"')}</label>
    <label class="f">Tries per agent${inp("pipeline.max_attempts_per_step", c.pipeline.max_attempts_per_step, "number", 'min="1" max="10"')}</label>
    <label class="f">Tries per run (all agents)${inp("pipeline.max_total_attempts", c.pipeline.max_total_attempts, "number", 'min="1" max="40"')}</label>
    <label class="f">Max $ per post${inp("pipeline.max_run_budget_usd", c.pipeline.max_run_budget_usd, "number", 'step="0.5" min="0.5" max="100"')}</label>
  </div></div>
  <div class="panel section"><h2>Notifications</h2><div class="row">
    <label class="checkline"><input type="checkbox" data-k="notifications.desktop" ${c.notifications.desktop ? "checked" : ""}> Desktop notifications</label>
    <label class="checkline"><input type="checkbox" data-k="notifications.email" ${c.notifications.email ? "checked" : ""}> Gmail email (set it up in Credentials)</label>
    <label class="checkline"><input type="checkbox" data-k="notifications.telegram" ${c.notifications.telegram ? "checked" : ""}> Telegram (set the bot in Credentials)</label>
    <label class="f" style="width:220px">Warn this many days before the LinkedIn token expires${inp("notifications.warn_days_before_expiry", c.notifications.warn_days_before_expiry, "number", 'min="1" max="30"')}</label>
    <button id="test-notify">Send a test notification</button></div></div>
  <div class="panel section"><div class="row"><h2 style="margin:0">Post categories</h2><span class="spacer"></span><button id="add-cat">Add category</button></div>
    <p class="muted small">What each kind of post contains. The brief is given to the Topic Scout, Writer and Editor.</p><div id="cats"></div></div>
  <div class="savebar"><span id="save-state" class="muted small">No changes</span><span class="spacer"></span>
    <button id="reset">Discard changes</button><button class="primary" id="save">Save settings</button></div>`;
  drawCats();
  $("#view").addEventListener("input", () => { S.dirty = true; $("#save-state").textContent = "Unsaved changes"; });
  $("#view").addEventListener("change", () => { S.dirty = true; $("#save-state").textContent = "Unsaved changes"; });
  $("#save").onclick = saveSettings;
  $("#reset").onclick = () => { S.dirty = false; renderSettings(); };
  $("#add-cat").onclick = () => {
    const id = prompt("Category id (lowercase letters, digits, dashes), e.g. career-tip"); if (!id) return;
    collectSettings(); S.config.categories[id] = { label: id, media: "poster", layouts: ["points"], kicker: id.toUpperCase().slice(0, 26),
      research: "optional", min_chars: 500, max_chars: 1800, fact_check: false, brief: "" }; drawCats(); S.dirty = true;
  };
  $("#test-notify").onclick = async () => { await post("/api/notifications/test"); toast("Sent"); refreshOverview(); };
}
function drawCats() {
  const c = S.config;
  $("#cats").innerHTML = Object.entries(c.categories).map(([id, k]) => `<div class="panel" style="margin-bottom:12px" data-cat="${esc(id)}">
    <div class="row"><b class="mono">${esc(id)}</b><span class="spacer"></span><button class="danger small" data-delcat="${esc(id)}">Remove</button></div>
    <div class="grid g4" style="margin-top:8px">
      <label class="f">Label<input data-c="label" value="${esc(k.label)}"></label>
      <label class="f">Media<select data-c="media">${["poster", "animation", "none"].map(m => `<option ${m === k.media ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <label class="f">Poster layouts (comma separated)<input data-c="layouts" value="${esc((k.layouts || []).join(", "))}" placeholder="points, steps, code, flow"></label>
      <label class="f">Kicker (poster pill)<input data-c="kicker" value="${esc(k.kicker || "")}" maxlength="26"></label>
      <label class="f">Research<select data-c="research">${["required", "optional", "off"].map(m => `<option ${m === (k.research || "optional") ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <label class="f">Min characters<input type="number" data-c="min_chars" value="${k.min_chars}"></label>
      <label class="f">Max characters<input type="number" data-c="max_chars" value="${k.max_chars}" max="3000"></label>
      <label class="f">Sources must be newer than (days)<input type="number" data-c="max_source_age_days" value="${esc(k.max_source_age_days ?? "")}" placeholder="any age"></label>
    </div>
    <label class="checkline" style="margin-top:8px"><input type="checkbox" data-c="fact_check" ${k.fact_check ? "checked" : ""}> Every number in the post must appear in a verified source</label>
    <label class="checkline" style="margin-top:8px"><input type="checkbox" data-c="plan_ahead" ${k.plan_ahead !== false ? "checked" : ""}> Plan this topic a week ahead (untick for fresh news, picked the day before)</label>
    <label class="f" style="margin-top:8px">Brief: what this kind of post must contain<textarea data-c="brief">${esc(k.brief)}</textarea></label></div>`).join("");
  document.querySelectorAll("[data-delcat]").forEach(b => b.onclick = () => {
    if (!confirm(`Remove category ${b.dataset.delcat}?`)) return;
    collectSettings(); delete S.config.categories[b.dataset.delcat];
    WEEKDAYS.forEach(d => { if (S.config.schedule.days[d] === b.dataset.delcat) S.config.schedule.days[d] = ""; });
    drawCats(); S.dirty = true;
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
    const k = cfg.categories[box.dataset.cat];
    box.querySelectorAll("[data-c]").forEach(el => {
      const f = el.dataset.c; let v = el.type === "checkbox" ? el.checked : el.value;
      if (f === "layouts") v = v.split(",").map(s => s.trim()).filter(Boolean);
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
      window.scrollTo({ top: 0, behavior: "smooth" }); return;
    }
    S.dirty = false; $("#cfg-errors").innerHTML = ""; $("#save-state").textContent = "Saved"; toast("Settings saved"); refreshOverview();
  } catch (e) { toast(e.message, true); }
}

/* ---------- credentials ---------- */
async function renderCredentials() {
  const d = await api("/api/credentials"), s = d.secrets, st = d.status || {}, li = st.linkedin || {}, cl = st.claude || {};
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
  <div class="panel"><div class="row"><h2 style="margin:0">Claude Code (the AI for every agent)</h2><span class="spacer"></span>${chip(cl.state || "unknown")}</div>
    <p>${esc(cl.message || "Not checked yet.")}</p>
    <div class="row"><button id="test-claude">Test with a tiny call</button><span class="muted small" id="claude-result"></span></div>
    <p class="muted small">Not logged in? Run <span class="mono">claude</span> once in a terminal and log in. No API key is needed.</p>
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
  $("#test-claude").onclick = async () => {
    const b = $("#test-claude"); b.disabled = true; $("#claude-result").textContent = "calling…";
    const r = await post("/api/credentials/test-claude").catch(e => ({ ok: false, error: e.message }));
    $("#claude-result").textContent = r.ok ? `OK: ${r.model} answered in ${r.seconds}s (${money(r.cost_usd)})` : `Failed: ${r.error}`; b.disabled = false;
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
refreshOverview().then(() => setTab(location.hash.slice(1) || "overview"));
