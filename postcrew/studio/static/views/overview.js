/* Overview. Markup and classes copied from design/stitch/overview-dashboard.html (main content). Real data only. */
"use strict";

const OV_DAY = d => new Date(d + "T12:00:00").toLocaleDateString([], { weekday: "short", day: "numeric" });
const OV_ISO = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function ovStat(ic, tint, chipHtml, label, value, sub) {
  return `<div class="bg-white rounded-xl p-5 border border-slate-200 shadow-sm relative overflow-hidden flex flex-col justify-between hover:border-slate-300 transition-all">
    <div class="flex items-start justify-between">
      <div class="w-10 h-10 rounded-lg bg-${tint}-50 border border-${tint}-200 flex items-center justify-center text-${tint}-600">${icon(ic)}</div>
      ${chipHtml}
    </div>
    <div class="mt-4">
      <span class="text-xs font-medium text-slate-500 uppercase tracking-wider block">${esc(label)}</span>
      <div class="text-xl font-bold font-headline text-slate-900 mt-1">${value}</div>
      ${sub ? `<p class="text-xs text-slate-500 mt-1 flex items-center gap-1.5">${sub}</p>` : ""}
    </div>
  </div>`;
}

function ovDayCard(date, item, app) {
  const a = appOf(app);
  if (!item) return `<div class="border-l-4 border-l-slate-300 bg-slate-50/50 rounded-lg p-2.5 border-t border-r border-b border-slate-200 flex flex-col justify-between min-h-[145px] hover:shadow-sm transition-all opacity-70">
    <div>
      <div class="flex items-center justify-between"><span class="text-[11px] font-bold text-slate-500">${esc(OV_DAY(date))}</span><span class="text-[10px] text-slate-400 font-medium">Rest</span></div>
      <div class="mt-2 text-xs font-medium text-slate-500 italic leading-snug">No scheduled broadcasts</div>
    </div>
    <div class="mt-3 pt-2 border-t border-slate-200/60 flex items-center gap-1 text-[11px] text-slate-400">${icon("bedtime", "text-xs")}<span>Buffer day</span></div>
  </div>`;
  return `<div class="border-l-4 ${a.border} bg-slate-50/80 rounded-lg p-2.5 border-t border-r border-b border-slate-200 flex flex-col justify-between min-h-[145px] hover:shadow-sm transition-all">
    <div>
      <div class="flex items-center justify-between"><span class="text-[11px] font-bold text-slate-700">${esc(OV_DAY(date))}</span>${a.badge}</div>
      <div class="mt-2 text-xs font-semibold text-slate-900 line-clamp-3 leading-snug" title="${esc(item.label)}">${esc(item.label)}</div>
    </div>
    <div class="mt-3 pt-2 border-t border-slate-200/60 flex items-center gap-1 text-[11px] font-medium text-slate-600">${icon("schedule", "text-xs text-slate-400")}<span>${esc(item.time)}</span></div>
  </div>`;
}

function ovRunRow(r) {
  const running = ["running", "retrying", "working"].includes(r.state), failed = statusKind(r.state) === "failed", passed = statusKind(r.state) === "passed";
  const app = r.meta?.platform || "linkedin";
  const name = r.meta?.label || r.meta?.category || r.run_id;
  const sub = failed && r.result
    ? `<div class="text-[11px] text-rose-600 mt-0.5 flex items-center gap-1 truncate">${icon("error", "text-xs")}<span class="tooltip-anchor" title="${esc(r.result)}">${esc(r.result.slice(0, 70))}</span></div>`
    : `<div class="text-[11px] text-slate-400 mt-0.5 truncate">${esc([r.meta?.date, r.meta?.dry_run ? "rehearsal" : "", running ? "" : r.result].filter(Boolean).join(" · "))}</div>`;
  const tokens = running
    ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-50 text-violet-700 font-mono text-xs border border-violet-200/60">${icon("sync", "text-xs text-violet-500")}${r.tokens ? esc(tok(r.tokens)) + " · " : ""}In progress</span>`
    : `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 ${failed ? "text-slate-600" : "text-slate-700"} font-mono text-xs border border-slate-200/60" title="fresh input + cached input + output">${icon("data_usage", "text-xs text-slate-400")}${r.tokens ? esc(tok(r.tokens)) + " " : ""}(${esc(money(r.cost_usd))})</span>`;
  const inspect = `<button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-100 hover:bg-violet-200 text-violet-800 font-semibold transition-colors" data-run="${esc(r.run_id)}">${icon("monitoring", "text-sm")}<span>Inspect log</span></button>`;
  const retry = `<button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-rose-50 text-rose-700 font-semibold border border-rose-200 disabled:opacity-50 disabled:cursor-not-allowed" disabled title="Coming soon">${icon("replay", "text-sm")}<span>Retry</span></button>`;
  const drafts = `<a class="inline-flex items-center gap-1 font-semibold text-violet-700 hover:text-violet-900 group-hover:underline" href="#queue"><span>View drafts</span>${icon("arrow_forward", "text-sm")}</a>`;
  return `<tr class="hover:bg-slate-50/80 transition-colors group${running ? " bg-violet-50/20" : ""}">
    <td class="py-4 px-6 whitespace-nowrap">${chip(r.state)}</td>
    <td class="py-4 px-6 max-w-[26rem]"><div class="flex items-center gap-2">${appBadge(app)}<span class="font-semibold text-slate-900">${esc(name)}</span></div>${sub}</td>
    <td class="py-4 px-6 whitespace-nowrap text-slate-500 text-xs"><span${running ? ' class="font-medium text-violet-700"' : ""}>${esc(ago(r.started_at))}</span></td>
    <td class="py-4 px-6 whitespace-nowrap">${tokens}</td>
    <td class="py-4 px-6 whitespace-nowrap text-right text-xs"><div class="inline-flex items-center gap-2">${failed ? retry : ""}${passed ? drafts : inspect}</div></td>
  </tr>`;
}

function ovRunsBody(runs, total) {
  const burn = runs.reduce((s, r) => s + (r.cost_usd || 0), 0);
  const table = runs.length ? `<div class="overflow-x-auto"><table class="w-full text-left text-sm border-collapse">
    <thead><tr class="bg-slate-50/80 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
      <th class="py-3 px-6" scope="col">Status &amp; Verdict</th><th class="py-3 px-6" scope="col">Pipeline Name</th><th class="py-3 px-6" scope="col">Timestamp</th>
      <th class="py-3 px-6" scope="col">Token Burn &amp; Cost</th><th class="py-3 px-6 text-right" scope="col">Actions</th></tr></thead>
    <tbody class="divide-y divide-slate-100">${runs.slice(0, 10).map(ovRunRow).join("")}</tbody></table></div>`
    : emptyState("terminal", "No runs yet. Wait for the scheduler, or start one in Manual run.");
  return `${table}
    <div class="p-4 bg-slate-50/50 border-t border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between text-xs text-slate-500 gap-2">
      <div class="flex items-center gap-2">${icon("info", "text-sm text-slate-400")}<span>Showing latest ${Math.min(runs.length, 10)} runs from ${total} total executions.</span></div>
      <div class="flex items-center gap-4"><span>Total cost of these runs: <strong>${esc(money(burn))}</strong></span><a class="text-violet-700 font-semibold hover:underline" href="#workflow">View comprehensive logs</a></div>
    </div>`;
}

function ovBindRuns() {
  document.querySelectorAll("#ov-runs button[data-run]").forEach(b => b.onclick = () => { S.runId = b.dataset.run; location.hash = "workflow"; });
}

// Missed: scheduled posts that were never made (the Studio was off, or the run failed). Every app, newest last.
function ovMissed(m) {
  const items = m?.items || [];
  if (!items.length) return "";
  const waiting = items.filter(x => x.queued).length, open = items.length - waiting;
  const row = x => `<li class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 py-2">
      <div class="flex items-center gap-2 min-w-0">${appBadge(x.platform)}<span class="text-xs font-bold text-slate-700 whitespace-nowrap">${esc(OV_DAY(x.date))}</span><span class="text-xs text-slate-600 truncate" title="${esc(x.label)}">${esc(x.label)}</span></div>
      <div class="flex items-center gap-2 shrink-0">${x.queued
        ? chip("queued", "Waiting to run", "sm")
        : `<button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-100 hover:bg-violet-200 text-violet-800 text-xs font-semibold transition-colors" data-miss-run="${esc(x.platform)}|${esc(x.date)}">${icon("play_arrow", "text-sm")}<span>Run</span></button>`}
        <button class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-colors" data-miss-skip="${esc(x.platform)}|${esc(x.date)}">${icon("close", "text-sm")}<span>Skip</span></button>
      </div></li>`;
  return `<section id="ov-missed" class="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-2">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div class="flex items-start gap-2">
        <div class="w-7 h-7 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center shrink-0">${icon("event_busy", "text-base")}</div>
        <div><h2 class="text-sm font-bold font-headline text-slate-900">${items.length} scheduled ${items.length === 1 ? "post was" : "posts were"} missed</h2>
          <p class="text-xs text-slate-600 mt-0.5">${tip("Missed", "A scheduled date whose crew run never happened in the last 7 days: the Studio was off, or the run failed.")} posts are made one at a time, oldest first, and published as soon as they are ready${m.paused ? ". Resume the schedule to run them" : ""}.</p></div>
      </div>
      ${open > 1 ? `<button id="ov-miss-all" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-violet-600 hover:bg-violet-700 text-white transition-colors shrink-0">${icon("fast_forward", "text-sm")}<span>Run all ${open}</span></button>` : ""}
    </div>
    <ul class="divide-y divide-amber-200/70">${items.map(row).join("")}</ul>
  </section>`;
}

function ovBindMissed() {
  const act = async (path, body, msg) => {
    try { await post(path, body); if (msg) toast(msg); renderOverview(); } catch (e) { toast(e.message || String(e), true); }
  };
  const split = v => { const [platform, date] = v.split("|"); return { platform, date }; };
  document.querySelectorAll("#ov-missed [data-miss-run]").forEach(b => b.onclick = () => act("/api/missed/run", split(b.dataset.missRun), "Queued: the scheduler starts it within a minute"));
  document.querySelectorAll("#ov-missed [data-miss-skip]").forEach(b => b.onclick = () => act("/api/missed/dismiss", split(b.dataset.missSkip)));
  const all = $("#ov-miss-all"); if (all) all.onclick = () => act("/api/missed/run", { all: true }, "Queued: the scheduler makes them one at a time");
}

let ovTimer = null;
async function ovPoll() {
  clearTimeout(ovTimer);
  if (S.tab !== "overview" || !$("#ov-runs")) return;
  try {
    const { runs: all } = await api("/api/runs");
    const runs = all.filter(r => (r.meta?.platform || "linkedin") === S.platform);
    $("#ov-runs").innerHTML = ovRunsBody(runs, runs.length); ovBindRuns();
    if (runs.some(r => ["running", "retrying", "working"].includes(r.state))) ovTimer = setTimeout(ovPoll, 4000);
  } catch (e) { /* next tick of the global refresh will retry */ }
}

async function renderOverview() {
  await refreshOverview();
  const o = S.overview; if (!o) return;
  const [{ runs: allRuns }, { queue: allQueue }, cfgRes, missedRes] = await Promise.all([api("/api/runs"), api("/api/queue"), api("/api/config"),
    api("/api/missed").catch(() => null)]);
  const cfg = cfgRes.config, app = S.platform, a = appOf(app);
  const runs = allRuns.filter(r => (r.meta?.platform || "linkedin") === app), queue = allQueue.filter(mine);
  const li = o.credentials?.linkedin || {}, isLi = app === "linkedin";
  const next = queue.filter(p => ["queued", "approved", "awaiting_approval"].includes(p.status)).sort((x, y) => (x.scheduled_at || "").localeCompare(y.scheduled_at || ""))[0];

  // Coming up: the next 7 calendar days, each filled from o.upcoming or a rest day
  const byDate = Object.fromEntries((o.upcoming || []).map(u => [u.date, u]));
  const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return OV_ISO(d); });
  const planned = days.filter(d => byDate[d]).length;

  const cats = Object.entries(catsOf(cfg, app)).map(([id, c]) => `<option value="${esc(id)}">${esc(c.label)}</option>`).join("");
  const pods = Object.values(S.agents || {}).filter(x => x.uses_llm).map(x => `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 font-medium"><span class="w-2 h-2 rounded-full" style="background:${teamOf(x.id)[1]}"></span> ${esc(x.title)}</span>`).join("");
  const connChip = isLi ? chip(li.state || "unknown") : chip("queued", "connector soon");
  const connValue = isLi ? esc(li.name || WORDS[li.state] || "Not checked yet") : "Connector coming soon";
  const connSub = isLi ? (li.days_left != null ? `${li.days_left} days left on the token` : "") : "";

  $("#view").innerHTML = `
    <div class="space-y-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold font-headline text-slate-900 tracking-tight flex items-center gap-2"><span>Overview</span>
          <span class="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-200/80 text-slate-700">${esc(appName(app))}</span></h1>
        <p class="text-sm text-slate-500 mt-1 flex items-center gap-1.5">${o.paused
          ? `<span class="w-2 h-2 rounded-full bg-amber-500"></span><span>Schedule paused: nothing is generated or published until you resume</span>`
          : `<span class="w-2 h-2 rounded-full ${o.running ? "bg-violet-500" : "bg-emerald-500"} animate-pulse"></span><span>${o.running ? "A crew run is in progress" : "The crew is on its autonomous schedule"}</span>`}</p>
      </div>
      <div class="flex items-center gap-2.5">
        <button id="ov-sync" class="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 shadow-sm transition-all active:scale-95">${icon("refresh", "text-slate-500 text-base")}<span>Sync Pipelines</span></button>
        <button id="pause" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors">${icon(o.paused ? "play_arrow" : "pause", "text-xs")}<span>${o.paused ? "Resume schedule" : "Pause schedule"}</span></button>
      </div>
    </div>

    ${ovMissed(missedRes)}

    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      ${ovStat("schedule", "amber", next ? chip(next.status, null, "sm") : chip("idle", "Nothing queued", "sm"), "Next post",
        next ? esc(next.date) : "None yet", next ? `<span class="w-2 h-2 rounded-full ${a.dot}"></span><span>${esc(appName(app))} • ${esc(next.topic)}</span>` : "")}
      ${ovStat("auto_awesome", "violet", o.paused ? chip("warning", "Paused", "sm") : chip("scheduled", null, "sm"), "Next crew run",
        esc(o.next.generate_time), `${esc(`Writes the post for ${o.next.generate_for} (${o.next.category || "no category that day"}) · ${o.next.timezone}`)}`)}
      ${ovStat("verified_user", "emerald", connChip, "Connection", connValue, esc(connSub))}
      ${ovStat("send", "emerald", chip("info", `Approval: ${o.approval.replace(/_/g, " ")}`, "sm"), "Published", `${o.published} ${o.published === 1 ? "Post" : "Posts"}`, "")}
    </section>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      <section class="lg:col-span-12 bg-white rounded-xl p-6 border border-slate-200 shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-lg bg-sky-100 text-sky-700 flex items-center justify-center">${icon("calendar_month", "text-base")}</div>
              <h2 class="text-lg font-bold font-headline text-slate-900">Coming up</h2>
            </div>
            <p class="text-xs text-slate-500 mt-1 leading-relaxed">Scheduled agent deliveries and editorial milestones across the next 7 days.</p>
          </div>
          <a class="inline-flex items-center gap-1 text-xs font-semibold text-violet-700 hover:text-violet-800 transition-colors" href="#plan"><span>View Full Calendar</span>${icon("arrow_forward", "text-sm")}</a>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5 pt-2">${days.map(d => ovDayCard(d, byDate[d], app)).join("")}</div>
        <div class="mt-3 bg-slate-50 border border-slate-200/70 rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between text-xs text-slate-600 gap-2">
          <div class="flex items-center gap-3"><span class="flex items-center gap-1.5 font-medium"><span class="w-2.5 h-2.5 rounded-full ${a.dot}"></span><span>${planned} ${esc(appName(app))} ${planned === 1 ? "post" : "posts"} planned</span></span></div>
        </div>
        <div class="pt-2 flex items-center justify-end text-xs text-slate-500"><span class="mr-1.5">Want to make something right now?</span><a class="inline-flex items-center gap-1 font-semibold text-violet-700 hover:text-violet-800 transition-colors" href="#manual"><span>Open Manual run</span>${icon("arrow_forward", "text-sm")}</a></div>
        ${pods ? `<div class="pt-4 border-t border-slate-100"><span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-2">Engaged Pod Squad</span><div class="flex flex-wrap gap-2 text-[11px]">${pods}</div></div>` : ""}
      </section>
    </div>

    <section class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div class="p-6 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <div class="w-7 h-7 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center">${icon("terminal", "text-base")}</div>
            <h2 class="text-lg font-bold font-headline text-slate-900">Recent runs</h2>
          </div>
          <p class="text-xs text-slate-500 mt-1">Audit log of automated crew passes, execution status, and token consumption.</p>
        </div>
        <div class="flex items-center gap-2">
          <button class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 text-slate-700 disabled:opacity-50 disabled:cursor-not-allowed" disabled title="Coming soon">${icon("filter_list", "text-xs")}<span>Filter</span></button>
          <button class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 text-slate-700 disabled:opacity-50 disabled:cursor-not-allowed" disabled title="Coming soon">${icon("download", "text-xs")}<span>Export CSV</span></button>
        </div>
      </div>
      <div id="ov-runs">${ovRunsBody(runs, runs.length)}</div>
    </section>
    </div>`;

  $("#ov-sync").onclick = () => renderOverview();
  $("#pause").onclick = async () => { await post("/api/pause", { paused: !o.paused }); renderOverview(); };
  ovBindRuns(); ovBindMissed();
  if (runs.some(r => ["running", "retrying", "working"].includes(r.state))) { clearTimeout(ovTimer); ovTimer = setTimeout(ovPoll, 4000); }
}

VIEWS.overview = renderOverview;
