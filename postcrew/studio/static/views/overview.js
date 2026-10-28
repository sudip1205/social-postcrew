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
    : emptyState("terminal", "No runs yet. Start one above, or wait for the scheduler.");
  return `${table}
    <div class="p-4 bg-slate-50/50 border-t border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between text-xs text-slate-500 gap-2">
      <div class="flex items-center gap-2">${icon("info", "text-sm text-slate-400")}<span>Showing latest ${Math.min(runs.length, 10)} runs from ${total} total executions.</span></div>
      <div class="flex items-center gap-4"><span>Total cost of these runs: <strong>${esc(money(burn))}</strong></span><a class="text-violet-700 font-semibold hover:underline" href="#workflow">View comprehensive logs</a></div>
    </div>`;
}

function ovBindRuns() {
  document.querySelectorAll("#ov-runs button[data-run]").forEach(b => b.onclick = () => { S.runId = b.dataset.run; location.hash = "workflow"; });
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
  const [{ runs: allRuns }, { queue: allQueue }, cfgRes] = await Promise.all([api("/api/runs"), api("/api/queue"), api("/api/config")]);
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
        <button id="ov-runnow" class="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg bg-violet-600 hover:bg-violet-700 text-white shadow-sm shadow-violet-200 transition-all active:scale-95">${icon("bolt", "text-base")}<span>Run now</span></button>
      </div>
    </div>

    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      ${ovStat("schedule", "amber", next ? chip(next.status, null, "sm") : chip("idle", "Nothing queued", "sm"), "Next post",
        next ? esc(next.date) : "None yet", next ? `<span class="w-2 h-2 rounded-full ${a.dot}"></span><span>${esc(appName(app))} • ${esc(next.topic)}</span>` : "")}
      ${ovStat("auto_awesome", "violet", o.paused ? chip("warning", "Paused", "sm") : chip("scheduled", null, "sm"), "Next crew run",
        esc(o.next.generate_time), `${esc(`Writes the post for ${o.next.generate_for} (${o.next.category || "no category that day"}) · ${o.next.timezone}`)}`)}
      ${ovStat("verified_user", "emerald", connChip, "Connection", connValue, esc(connSub))}
      ${ovStat("send", "emerald", chip("info", `Approval: ${o.approval.replace(/_/g, " ")}`, "sm"), "Published", `${o.published} ${o.published === 1 ? "Post" : "Posts"}`, "")}
    </section>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      <section id="ov-run" class="lg:col-span-5 bg-white rounded-xl p-6 border border-slate-200 shadow-sm space-y-6">
        <div>
          <div class="flex items-center gap-2">
            <div class="w-7 h-7 rounded-lg bg-violet-100 text-violet-700 flex items-center justify-center">${icon("play_circle", "text-base")}</div>
            <h2 class="text-lg font-bold font-headline text-slate-900">Run the crew now</h2>
            <span class="flex-1"></span>
            <button id="pause" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors">${icon(o.paused ? "play_arrow" : "pause", "text-xs")}<span>${o.paused ? "Resume schedule" : "Pause schedule"}</span></button>
          </div>
          <p class="text-xs text-slate-500 mt-1 leading-relaxed">Trigger an on-demand multi-agent cycle outside of the scheduled cron jobs.</p>
        </div>
        <form class="space-y-4" onsubmit="event.preventDefault();">
          <div>
            <label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-1.5" for="run-date">${icon("event", "text-slate-400 text-sm")}<span>Target publication slot</span></label>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">${icon("calendar_today", "text-base")}</div>
              <input id="run-date" type="date" value="${esc(o.next.run_for || o.next.generate_for)}" class="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50/50 text-slate-800 font-medium focus:ring-2 focus:ring-violet-500 focus:border-violet-500 cursor-pointer"/>
            </div>
            <p class="text-[11px] text-slate-400 mt-1">Select the calendar cadence slot where drafts will be queued.</p>
          </div>
          <div>
            <label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-1.5" for="run-cat">${icon("lightbulb", "text-slate-400 text-sm")}<span>Category</span></label>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">${icon("feed", "text-base")}</div>
              <select id="run-cat" class="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-slate-200 bg-white text-slate-800 font-medium focus:ring-2 focus:ring-violet-500 focus:border-violet-500 appearance-none cursor-pointer"><option value="">As scheduled for that day</option>${cats}</select>
              <div class="absolute inset-y-0 right-0 pr-2.5 flex items-center pointer-events-none text-slate-400">${icon("expand_more", "text-base")}</div>
            </div>
            <p class="text-[11px] text-slate-400 mt-1">The topic and angle are chosen by the crew for this category.</p>
          </div>
          <div class="bg-violet-50/50 border border-violet-100 rounded-xl p-3.5 flex items-start justify-between gap-3">
            <div>
              <div class="flex items-center gap-1.5">
                ${icon("flag", "text-violet-600 text-base")}
                <span class="text-xs font-semibold text-slate-800">${tip("Rehearsal", "Runs every agent but skips the queue, so nothing can be published")} mode</span>
                <span class="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">Dry-Run</span>
              </div>
              <p class="text-[11px] text-slate-500 mt-1 leading-snug">Simulates agent writing and quality gates without creating live pending items.</p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer shrink-0 mt-0.5">
              <input id="run-dry" checked class="sr-only peer" type="checkbox" aria-label="Rehearsal mode"/>
              <div class="w-10 h-5 bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-violet-600"></div>
            </label>
          </div>
          <button id="run-go" class="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white font-semibold text-sm shadow-sm shadow-violet-200 transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed" type="button" ${o.running ? "disabled" : ""}>${icon("play_arrow", "text-lg")}<span>${o.running ? "A run is in progress…" : "Launch Crew Run"}</span></button>
        </form>
        ${pods ? `<div class="pt-4 border-t border-slate-100"><span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-2">Engaged Pod Squad</span><div class="flex flex-wrap gap-2 text-xs">${pods}</div></div>` : ""}
      </section>

      <section class="lg:col-span-7 bg-white rounded-xl p-6 border border-slate-200 shadow-sm space-y-4">
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
  $("#ov-runnow").onclick = () => { $("#ov-run").scrollIntoView({ behavior: "smooth", block: "start" }); $("#run-go").focus(); };
  $("#run-go").onclick = ovStartRun;
  $("#pause").onclick = async () => { await post("/api/pause", { paused: !o.paused }); renderOverview(); };
  ovBindRuns();
  if (runs.some(r => ["running", "retrying", "working"].includes(r.state))) { clearTimeout(ovTimer); ovTimer = setTimeout(ovPoll, 4000); }
}

async function ovStartRun() {
  try {
    const r = await post("/api/runs", { date: $("#run-date").value, category: $("#run-cat").value, dry_run: $("#run-dry").checked, platform: S.platform });
    S.runId = r.run_id; toast("Crew started"); location.hash = "workflow";
  } catch (e) { toast(e.message, true); }
}

VIEWS.overview = renderOverview;
