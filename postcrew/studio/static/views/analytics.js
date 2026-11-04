/* Analytics: how the videos on your connected YouTube channel are doing, the crew's marked. No Stitch screen: built from the Overview's
   stat cards (ovStat) and the Queue's table and section styles. See design/DEVIATIONS.md. API: GET /api/youtube/analytics[?refresh=1]. */
"use strict";

const AN = { sort: "published", only: false };
const anNum = n => n == null ? "-" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? Math.round(n / 1e3) + "K" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n);
const anSecs = s => s == null ? "-" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const anDate = iso => iso ? new Date(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }) : "";

function anDaily(rows) {
  // one series (daily views): bars from the baseline, 4px rounded tops, 2px gaps, hover tooltip per bar, a table is the video list below
  if (!rows?.length) return "";
  const max = Math.max(1, ...rows.map(r => r.views || 0));
  const bars = rows.map(r => {
    const h = Math.max(2, Math.round((r.views || 0) / max * 100));
    const tip = `${new Date(r.day + "T12:00:00").toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}: ${r.views || 0} views, ${Math.round(r.estimatedMinutesWatched || 0)} min watched, +${r.subscribersGained || 0} / -${r.subscribersLost || 0} subscribers`;
    return `<div class="flex-1 h-full flex items-end group relative" title="${esc(tip)}"><div class="w-full rounded-t bg-violet-500 group-hover:bg-violet-700 transition-colors" style="height:${h}%"></div></div>`;
  }).join("");
  const total = rows.reduce((a, r) => a + (r.views || 0), 0), subs = rows.reduce((a, r) => a + (r.subscribersGained || 0) - (r.subscribersLost || 0), 0);
  return `<section class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 flex flex-col gap-4">
    <div class="flex flex-wrap items-end justify-between gap-2"><div><h2 class="font-headline font-bold text-lg text-slate-900">Daily views, last ${rows.length} days</h2>
      <p class="text-sm text-slate-500 mt-0.5">${anNum(total)} views and ${subs >= 0 ? "+" : ""}${subs} subscribers on the whole channel. Hover a bar for the day.</p></div>
      <span class="text-[11px] text-slate-400">YouTube Analytics is 2-3 days behind</span></div>
    <div class="flex items-end gap-[2px] h-40 border-b border-slate-200">${bars}</div>
    <div class="flex justify-between text-[11px] text-slate-400"><span>${esc(anDate(rows[0].day + "T12:00:00"))}</span><span>peak ${anNum(max)} views a day</span><span>${esc(anDate(rows.at(-1).day + "T12:00:00"))}</span></div></section>`;
}

function anTable(videos, deep) {
  const sorters = { published: (a, b) => String(b.published_at).localeCompare(String(a.published_at)), views: (a, b) => (b.views || 0) - (a.views || 0),
    watch: (a, b) => ((b.analytics?.averageViewPercentage) || 0) - ((a.analytics?.averageViewPercentage) || 0),
    likes: (a, b) => ((b.likes || 0) / Math.max(b.views || 1, 1)) - ((a.likes || 0) / Math.max(a.views || 1, 1)) };
  const list = videos.filter(v => !AN.only || v.crew).sort(sorters[AN.sort] || sorters.published);
  const AN_ON = "uppercase tracking-wider text-violet-700 font-bold", AN_OFF = "uppercase tracking-wider hover:text-slate-700";
  const th = (k, t, right = true) => { const cell = right ? "py-2 pr-3 text-right" : "py-2 pr-3", btn = AN.sort === k ? AN_ON : AN_OFF;
    return `<th class="${cell}">${k ? `<button type="button" data-ansort="${k}" class="${btn}">${t}</button>` : t}</th>`; };
  const rows = list.map(v => { const a = v.analytics || {}, pct = a.averageViewPercentage, ptsCls = (v.crew?.points || 0) > 0 ? "text-emerald-700 font-semibold" : "text-rose-700 font-semibold";
    return `<tr class="align-top">
      <td class="py-2.5 pr-3"><div class="flex items-start gap-3">${v.thumbnail ? `<img src="${esc(v.thumbnail)}" alt="" class="w-24 rounded-md border border-slate-200 shrink-0" loading="lazy">` : ""}
        <div class="min-w-0"><a href="https://youtu.be/${esc(v.id)}" target="_blank" rel="noopener" class="font-semibold text-slate-900 hover:text-violet-700">${esc(v.title)}</a>
        <div class="flex flex-wrap items-center gap-1.5 mt-1 text-[11px] text-slate-500"><span>${esc(anDate(v.published_at))}</span><span>·</span><span>${v.format === "long" ? "Long" : "Short"} ${anSecs(v.seconds)}</span>
          ${v.privacy && v.privacy !== "public" ? chip("idle", v.privacy, "sm") : ""}
          ${v.crew ? `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-violet-50 border border-violet-200 text-violet-700 font-semibold">${icon("smart_toy", "text-[13px]")}Made by the crew</span>` : ""}
          ${v.crew?.points ? `<span class="${ptsCls}">${v.crew.points > 0 ? "+" : ""}${v.crew.points} pts</span>` : ""}</div></div></div></td>
      <td class="py-2.5 pr-3 text-right font-semibold text-slate-900 tabular-nums">${anNum(v.views)}</td>
      <td class="py-2.5 pr-3 text-right text-slate-700 tabular-nums">${anNum(v.likes)}</td>
      <td class="py-2.5 pr-3 text-right text-slate-700 tabular-nums">${anNum(v.comments)}</td>
      ${deep ? `<td class="py-2.5 pr-3 text-right text-slate-700 tabular-nums">${a.estimatedMinutesWatched != null ? anNum(Math.round(a.estimatedMinutesWatched)) : "-"}</td>
      <td class="py-2.5 pr-3 text-right text-slate-700 tabular-nums">${anSecs(a.averageViewDuration)}</td>
      <td class="py-2.5 pr-3 text-right tabular-nums">${pct != null ? `<div class="inline-flex flex-col items-end gap-1"><span class="text-slate-900 font-semibold">${Math.round(pct)}%</span><span class="w-16 h-1 rounded-full bg-slate-100 overflow-hidden"><span class="block h-1 rounded-full bg-violet-500" style="width:${Math.min(100, Math.round(pct))}%"></span></span></div>` : "-"}</td>
      <td class="py-2.5 pr-3 text-right text-slate-700 tabular-nums">${a.subscribersGained != null ? "+" + a.subscribersGained : "-"}</td>
      <td class="py-2.5 text-right text-slate-700 tabular-nums">${a.shares ?? "-"}</td>` : ""}</tr>`; }).join("");
  return `<section class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 flex flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="font-headline font-bold text-lg text-slate-900">Every video on the channel</h2>
      <p class="text-sm text-slate-500 mt-0.5">Click a column to sort. ${deep ? tip("Watched", "Average share of the video people watched: the best sign of whether a video holds viewers.") + " is the share of each video people watch on average." : ""}</p></div>
      <label class="inline-flex items-center gap-2 text-xs font-medium text-slate-700"><input type="checkbox" id="an-only" ${AN.only ? "checked" : ""} class="rounded border-slate-300 text-violet-600 focus:ring-violet-500">Only the crew's videos</label></div>
    ${list.length ? `<div class="overflow-x-auto"><table class="w-full text-sm text-left"><thead class="text-xs text-slate-500 uppercase tracking-wider"><tr>
      ${th("published", "Video", false)}${th("views", "Views")}${th("likes", "Likes")}${th("", "Comments")}
      ${deep ? th("", "Minutes") + th("", "Avg view") + th("watch", "Watched") + th("", "Subs") + th("", "Shares") : ""}</tr></thead>
      <tbody class="divide-y divide-slate-100">${rows}</tbody></table></div>` : emptyState("smart_display", AN.only ? "The crew has not uploaded to this channel yet." : "No videos on this channel yet.")}</section>`;
}

async function renderAnalytics(refresh = false) {
  const view = $("#view");
  if (!refresh) view.innerHTML = emptyState("progress_activity", "Asking YouTube how your videos are doing...");
  let d;
  try { d = await api(`/api/youtube/analytics${refresh ? "?refresh=1" : ""}`); } catch (e) { view.innerHTML = card(`<div class="p-6">${emptyState("error", e.message)}</div>`); return; }
  const head = `<div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5"><div>
      <div class="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1"><span>Production Studio</span>${icon("chevron_right", "text-[14px]")}<span class="text-violet-600 font-semibold">Analytics</span></div>
      <h1 class="font-headline font-bold text-2xl text-slate-900 tracking-tight flex items-center gap-3">${appBadge("youtube")}<span>${esc(d.channel?.title || "YouTube")} analytics</span></h1>
      <p class="text-sm text-slate-600 mt-1">Every video on the channel Postcrew uploads to.${d.fetched_at ? " Updated " + esc(fmtTime(d.fetched_at)) + "." : ""}</p></div>
      ${button("secondary", "refresh", "Refresh", `id="an-refresh" type="button"`)}</div>`;
  if (!d.connected) { view.innerHTML = `<div class="flex flex-col gap-6">${head}${card(`<div class="p-6">${emptyState("link_off", d.message)}</div>`)}</div>`; wireAn(); return; }
  const s = d.summary || {}, ch = d.channel || {}, an = d.analytics || {}, deep = an.ok !== false && (d.videos || []).some(v => v.analytics);
  const stats = `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    ${ovStat("group", "violet", "", "Subscribers", anNum(ch.subscribers), `${anNum(ch.videos)} videos on the channel`)}
    ${ovStat("visibility", "sky", "", "Channel views", anNum(ch.views), "all time, every video")}
    ${ovStat("smart_toy", "emerald", "", "The crew's videos", `${s.crew_videos || 0}`, `${anNum(s.crew_views)} views · ${anNum(s.crew_likes)} likes · ${anNum(s.crew_comments)} comments`)}
    ${ovStat("schedule", "orange", "", "Crew watch time", deep ? `${anNum(s.crew_minutes)} min` : "-", s.best ? `Top: ${esc(s.best)}` : "")}</div>`;
  const note = an.ok === false ? `<div class="flex items-start gap-2 p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-800">${icon("lock", "text-[16px] text-amber-600")}<span>${esc(an.message)}</span></div>` : "";
  const err = d.error ? `<div class="flex items-start gap-2 p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">${icon("error", "text-[16px] text-rose-600")}<span>${esc(d.error)}${d.cached ? " (showing the last numbers)" : ""}</span></div>` : "";
  view.innerHTML = `<div class="flex flex-col gap-6">${head}${err}${note}${stats}${anDaily(an.daily)}${anTable(d.videos || [], deep)}</div>`;
  view._an = d;
  wireAn();
}

function wireAn() {
  const r = $("#an-refresh"); if (r) r.onclick = () => { r.disabled = true; renderAnalytics(true); };
  const o = $("#an-only"); if (o) o.onchange = () => { AN.only = o.checked; renderAnalytics(); };
  document.querySelectorAll("[data-ansort]").forEach(b => b.onclick = () => { AN.sort = b.dataset.ansort; renderAnalytics(); });
}

VIEWS.analytics = () => renderAnalytics();
