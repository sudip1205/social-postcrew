/* Settings view: Stitch "Settings > Apps & Schedules" (design/stitch/settings-apps-schedules.html).
   Three sub-tabs: Apps & Schedules (topics, schedule, publishing), Brand Voice & Tone (about you, alerts), Quality Gates (the old
   Advanced). All three live in one DOM so collectSettings() reads every field, exactly like the old configurator. */
"use strict";

const settingsView = (() => {
  const T = { tab: "apps", app: "linkedin", month: null, prev: {} };   // sub-tab, selected app, calendar month, last topic per day
  const SOON = [["instagram", "Instagram", "Reels, carousels & stories", "photo_camera", "bg-gradient-to-tr from-slate-400 to-slate-500"],
    ["tiktok", "TikTok", "Short-form viral vertical clips", "music_video", "bg-slate-400"]];
  const APP_INFO = { linkedin: ["Articles, text posts & polls", "calendar_today"], youtube: ["Shorts & long-form videos", "videocam"] };
  const FREQ = ["weekly", "every_n_days", "dates"];
  const TOPIC_COL = [
    { sel: "border-amber-300 bg-amber-50 text-amber-900 focus:ring-amber-500", ic: "text-amber-700", leg: "text-amber-800 bg-amber-50 border-amber-200", dot: "bg-amber-500" },
    { sel: "border-sky-300 bg-sky-50 text-sky-900 focus:ring-sky-500", ic: "text-sky-700", leg: "text-sky-800 bg-sky-50 border-sky-200", dot: "bg-sky-500" },
    { sel: "border-emerald-300 bg-emerald-50 text-emerald-900 focus:ring-emerald-500", ic: "text-emerald-700", leg: "text-emerald-800 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500" },
    { sel: "border-violet-300 bg-violet-50 text-violet-900 focus:ring-violet-500", ic: "text-violet-700", leg: "text-violet-800 bg-violet-50 border-violet-200", dot: "bg-violet-500" },
    { sel: "border-rose-300 bg-rose-50 text-rose-900 focus:ring-rose-500", ic: "text-rose-700", leg: "text-rose-800 bg-rose-50 border-rose-200", dot: "bg-rose-500" }];
  const TINT = { violet: "bg-violet-100 text-violet-700", sky: "bg-sky-100 text-sky-700", indigo: "bg-indigo-100 text-indigo-700",
    emerald: "bg-emerald-100 text-emerald-700", red: "bg-red-100 text-red-700", amber: "bg-amber-100 text-amber-700", slate: "bg-slate-100 text-slate-600" };
  const SW_BIG = "w-11 h-6", SW_SM = "w-9 h-5", SW_BIG_KNOB = "after:h-5 after:w-5", SW_SM_KNOB = "after:h-4 after:w-4", SHOWN = "", HIDDEN = "hidden";
  const CARD = "bg-white rounded-xl p-6 border border-slate-200 shadow-sm space-y-4";
  const FIELD = "w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white text-slate-800 font-medium focus:ring-2 focus:ring-violet-500 focus:border-violet-500";
  const FIELD_I = "w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-white text-slate-800 font-medium focus:ring-2 focus:ring-violet-500 focus:border-violet-500";
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const own = id => id === "linkedin" ? S.config : (S.config.platforms?.[id] || {});
  const K = (id, p) => (id === "linkedin" ? "" : `platforms.${id}.`) + p;
  const enabledOf = id => S.config.platforms?.[id]?.enabled ?? id === "linkedin";
  // brand classes built from ui.js so no colour code is written here
  const brand = id => { const a = appOf(id); return { bg: a.dot, border: a.dot.replace("bg-", "border-"), text: a.text, peer: "peer-checked:" + a.dot,
    accent: a.dot.replace("bg-", "accent-"), soft: id === "youtube" ? "bg-red-100" : "bg-blue-100", wash: id === "youtube" ? "bg-red-50/30" : "bg-blue-50/30",
    line: id === "youtube" ? "border-red-200" : "border-blue-200", ring: id === "youtube" ? "ring-red-400" : "ring-blue-400" }; };
  const dv = (id, p) => $(`[data-k="${K(id, p)}"]`)?.value;

  const opts = (list, val) => list.map(([v, l]) => `<option value="${esc(v)}" ${v === val ? "selected" : ""}>${esc(l)}</option>`).join("");
  const sel = (path, val, list, cls = FIELD + " appearance-none") => `<select data-k="${path}" class="${cls}">${opts(list, val)}</select>`;
  const inp = (path, val, type = "text", extra = "") => `<input data-k="${path}" type="${type}" value="${esc(val)}" class="${FIELD}" ${extra}>`;
  const area = (attrs, val, rows, ph = "") => `<textarea ${attrs} rows="${rows}" placeholder="${esc(ph)}" class="${FIELD}">${esc(val)}</textarea>`;
  // a labelled field with a helper line (Stitch: helper text under every field)
  const field = (label, ic, control, help, cls = "") => `<div class="${cls}"><label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-1.5">${icon(ic, "text-slate-400 text-sm")}<span>${label}</span></label>${control}${help ? `<p class="text-[11px] text-slate-400 mt-1">${help}</p>` : ""}</div>`;
  const iconIn = (ic, control) => `<div class="relative"><div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">${icon(ic, "text-base")}</div>${control}</div>`;
  const head = (ic, tint, title, sub, right = "") => `<div class="flex items-center justify-between gap-3"><div class="flex items-center gap-2.5"><div class="w-8 h-8 rounded-lg ${TINT[tint]} flex items-center justify-center shrink-0">${icon(ic)}</div>
    <div><h3 class="text-base font-bold font-headline text-slate-900">${title}</h3><p class="text-xs text-slate-500">${sub}</p></div></div>${right}</div>`;
  const sw = (attrs, on, peer = "peer-checked:bg-violet-600", big = false) => `<label class="relative inline-flex items-center cursor-pointer shrink-0"><input ${on ? "checked" : ""} class="sr-only peer" type="checkbox" ${attrs}/>
    <div class="${big ? SW_BIG : SW_SM} bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full ${big ? SW_BIG_KNOB : SW_SM_KNOB} after:transition-all ${peer}"></div></label>`;
  const swRow = (path, on, title, help) => `<div class="flex items-start justify-between gap-4 py-2"><div><span class="text-sm font-semibold text-slate-800">${title}</span><p class="text-[11px] text-slate-400">${help}</p></div>${sw(`data-k="${path}"`, on)}</div>`;
  const isFixedTopic = (id, k) => k.media === "animation" || id === "week-recap";

  /* ---------- topics of an app: names from the editor cards (LinkedIn) or the config ---------- */
  function topicNames(id) {
    const out = {};
    const boxes = document.querySelectorAll(`#topics-${id} [data-cat]`);
    if (boxes.length) boxes.forEach(box => out[box.dataset.cat] = box.querySelector('[data-c="label"]').value.trim() || box.dataset.cat);
    else Object.entries(catsOf(S.config, id)).forEach(([cid, k]) => out[cid] = k.label || cid);
    return out;
  }
  const colOf = (names, cid) => TOPIC_COL[Math.max(0, Object.keys(names).indexOf(cid)) % TOPIC_COL.length];

  /* ---------- the left column ---------- */
  function appSummary(c, id) {
    const o = own(id), s = o.schedule || {}, fr = s.frequency || "weekly";
    const n = WEEKDAYS.filter(d => (s.days || {})[d]).length;
    const when = fr === "weekly" ? `${n} day${n === 1 ? "" : "s"}/week` : fr === "every_n_days" ? `every ${s.every_n || 2} days` : `${(s.dates || []).length} chosen dates`;
    return `${when} · ${s.post_time || ""}`;
  }
  function appCards(c) {
    return PLATFORM_IDS.map(id => {
      const b = brand(id), on = enabledOf(id), cur = T.app === id, a = appOf(id);
      const curCls = cur ? "border-2 shadow-md " + b.border : "border border-slate-200 shadow-sm hover:border-slate-300 transition-all cursor-pointer";
      const dotCls = on ? "bg-emerald-500" : "bg-slate-300", stCls = on ? "text-emerald-600" : "text-slate-500";
      const tile = id === "linkedin" ? `<span class="font-headline font-black text-xl tracking-tight">in</span>` : `<span class="text-xl font-black">▶</span>`;
      return `<div data-app-pick="${id}" class="bg-white rounded-xl p-4 ${curCls} relative group">
        ${cur ? `<div class="absolute -top-2.5 right-4 px-2 py-0.5 rounded-full ${b.bg} text-white text-[10px] font-bold uppercase tracking-wider shadow-sm flex items-center gap-1">${icon("edit", "text-[11px]")}<span>Currently Editing</span></div>` : ""}
        <div class="flex items-start justify-between gap-3"><div class="flex items-center gap-3">
          <div class="w-12 h-12 rounded-xl ${b.bg} flex items-center justify-center text-white shadow-sm shrink-0">${tile}</div>
          <div><div class="flex items-center gap-2"><h3 class="font-bold text-slate-900 text-base leading-tight">${esc(a.label)}</h3>
            <span class="w-2 h-2 rounded-full ${dotCls}" title="${on ? "On" : "Off"}"></span></div>
            <p class="text-xs text-slate-500 mt-0.5">${esc(APP_INFO[id][0])}</p>
            <span class="inline-flex items-center gap-1 text-[11px] font-medium text-slate-600 mt-1.5">${icon(APP_INFO[id][1], "text-xs text-slate-400")}<span data-app-sum="${id}">${esc(appSummary(c, id))}</span></span></div></div>
          <span class="mt-1" data-sw>${sw(`data-k="platforms.${id}.enabled" data-appon="${id}"`, on, b.peer)}</span></div>
        <div class="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
          <span class="flex items-center gap-1 font-medium ${stCls}">${icon(on ? "check_circle" : "pause_circle", "text-xs")}<span data-app-state="${id}">${on ? "Active schedule" : "Switched off"}</span></span>
          ${cur ? `<span class="text-xs font-bold ${b.text} flex items-center gap-1"><span>Selected</span>${icon("arrow_right_alt", "text-xs")}</span>`
            : `<span class="text-violet-600 font-semibold group-hover:underline flex items-center gap-0.5"><span>Configure</span>${icon("chevron_right", "text-xs")}</span>`}</div></div>`;
    }).join("") + SOON.map(([id, name, sub, ic, bg]) => `<div class="bg-slate-100/70 rounded-xl p-4 border border-dashed border-slate-300 opacity-75 relative" title="Coming soon">
      <div class="flex items-start justify-between gap-3"><div class="flex items-center gap-3">
        <div class="w-12 h-12 rounded-xl ${bg} flex items-center justify-center text-white shrink-0">${icon(ic, "text-2xl")}</div>
        <div><div class="flex items-center gap-2"><h3 class="font-bold text-slate-600 text-base leading-tight">${name}</h3><span class="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-200 text-slate-600">Coming soon</span></div>
          <p class="text-xs text-slate-600 mt-0.5">${sub}</p></div></div>
        <label class="relative inline-flex items-center cursor-not-allowed shrink-0 mt-1 opacity-50"><input class="sr-only" disabled type="checkbox"/><div class="w-9 h-5 bg-slate-300 rounded-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4"></div></label></div></div>`).join("");
  }
  function summaryCard() {
    const ids = PLATFORM_IDS.filter(enabledOf), per = ids.reduce((a, id) => { const s = own(id).schedule || {};
      return a + ((s.frequency || "weekly") === "weekly" ? WEEKDAYS.filter(d => (s.days || {})[d]).length : 0); }, 0);
    return `<div class="bg-gradient-to-br from-violet-50 to-indigo-50/60 rounded-xl p-4 border border-violet-100 text-xs space-y-2 mt-4">
      <div class="flex items-center gap-2 font-semibold text-violet-900">${icon("insights", "text-violet-700 text-base")}<span>Channel Throughput Summary</span></div>
      <p class="text-slate-600 leading-relaxed">Your crew is set to write <strong class="text-slate-900 font-semibold">${per} weekly ${per === 1 ? "post" : "posts"}</strong> across ${ids.length} ${ids.length === 1 ? "app" : "apps"} (weekly-day schedules only; other cadences are counted in the Plan).</p>
      <div class="pt-2 border-t border-violet-200/50 flex items-center justify-end text-[11px] text-violet-800"><a class="font-semibold underline hover:text-violet-950" href="#credentials">Manage Credentials</a></div></div>`;
  }

  /* ---------- option cards ---------- */
  function freqCards(id, val) {
    const items = [["weekly", "date_range", "Weekly days", "Publish repeatedly on selected days of the week (e.g. every Tuesday & Friday).", "Active selection", "Weekday schedule"],
      ["every_n_days", "hourglass_top", "Every N days", "Run continuously with a rolling interval gap, such as every 3 or 4 days.", "Active selection", "Interval spacing"],
      ["dates", "event_note", "Specific dates", "Manual editorial calendar: only create content on hand-picked milestone dates.", "Active selection", "Custom ad-hoc dates"]];
    return items.map(([v, ic, t, d, onFoot, offFoot]) => v === val
      ? `<div data-freq="${id}|${v}" class="border-2 border-violet-600 bg-violet-50/40 rounded-xl p-4 cursor-pointer relative shadow-sm transition-all"><div class="absolute top-3 right-3 text-violet-600">${icon("check_circle", "text-lg", true)}</div>
          <div class="w-10 h-10 rounded-lg bg-violet-100 text-violet-700 flex items-center justify-center mb-3">${icon(ic, "text-xl")}</div><h4 class="font-bold text-sm text-slate-900">${t}</h4>
          <p class="text-xs text-slate-600 mt-1 leading-relaxed">${d}</p><div class="mt-3 text-[11px] font-semibold text-violet-700 flex items-center gap-1"><span>${onFoot}</span></div></div>`
      : `<div data-freq="${id}|${v}" class="border border-slate-200 bg-white hover:border-slate-300 rounded-xl p-4 cursor-pointer relative transition-all"><div class="absolute top-3 right-3 text-slate-300">${icon("radio_button_unchecked", "text-lg")}</div>
          <div class="w-10 h-10 rounded-lg bg-slate-100 text-slate-600 flex items-center justify-center mb-3">${icon(ic, "text-xl")}</div><h4 class="font-bold text-sm text-slate-900">${t}</h4>
          <p class="text-xs text-slate-600 mt-1 leading-relaxed">${d}</p><div class="mt-3 text-[11px] font-medium text-slate-600"><span>${offFoot}</span></div></div>`).join("");
  }
  function approvalCards(id, val) {
    const items = [["auto_with_veto", "shield", "emerald", "Publish unless I veto", "Posts go out at the post time unless you veto them in the Queue first.", "verified", "Active policy", "Autonomous with a veto window",
        "border-emerald-500 bg-emerald-50/30 border-2 shadow-sm", "border-emerald-300 bg-emerald-50/20 hover:border-emerald-400 border", "text-emerald-900", "text-emerald-700"],
      ["manual", "hourglass_empty", "amber", "Wait for my approval", "The draft stays in the Queue until you review and approve it.", "verified", "Active policy", "Manual human-in-loop",
        "border-amber-500 bg-amber-50/30 border-2 shadow-sm", "border-amber-300 bg-amber-50/20 hover:border-amber-400 border", "text-amber-950", "text-amber-800"],
      ["immediate", "warning", "rose", "Publish right away", "Direct zero-touch dispatch as soon as all automated quality checks pass.", "bolt", "Active policy", "Fully autonomous",
        "border-rose-500 bg-rose-50/30 border-2 border-dashed shadow-sm", "border-rose-400 bg-rose-50/20 hover:border-rose-500 border-2 border-dashed", "text-rose-950", "text-rose-700"]];
    return items.map(([v, ic, tint, t, d, fic, onFoot, offFoot, onCls, offCls, tcol, fcol]) => { const footW = v === val ? "font-semibold" : "font-medium"; return `<div data-appr="${id}|${v}" class="${v === val ? onCls : offCls} rounded-xl p-4 cursor-pointer relative transition-all">
      <div class="flex items-start justify-between"><div class="w-8 h-8 rounded-lg ${TINT[tint]} flex items-center justify-center mb-2">${icon(ic, "text-lg")}</div>${icon(v === val ? "check_circle" : "radio_button_unchecked", `text-lg ${v === val ? fcol : "text-slate-300"}`, v === val)}</div>
      <div class="flex items-center gap-1.5 mt-1"><h4 class="font-bold text-sm ${tcol}">${t}</h4>${v === "immediate" ? `<span class="text-[9px] font-bold uppercase px-1 rounded bg-rose-200 text-rose-800">Caution</span>` : ""}</div>
      <p class="text-xs text-slate-600 mt-1 leading-relaxed">${d}</p>
      <div class="mt-3 text-[11px] ${footW} ${fcol} flex items-center gap-1">${v === val ? icon(fic, "text-xs") : ""}<span>${v === val ? onFoot : offFoot}</span></div></div>`; }).join("");
  }

  /* ---------- one app's sections ---------- */
  function appSection(c, id) {
    const o = own(id), li = id === "linkedin", s = o.schedule || {}, pn = o.planning || {}, pub = o.publishing || {}, b = brand(id), k = p => K(id, p);
    const en = enabledOf(id), freq = FREQ.includes(s.frequency) ? s.frequency : "weekly", a = appOf(id);
    const dates = (s.dates || []).map(e => [e.date, e.category || "", e.time || ""].join(" | ").replace(/( \| )+$/, "")).join("\n");
    const tile = li ? `<span class="font-headline font-black text-2xl tracking-tight">in</span>` : `<span class="text-2xl font-black">▶</span>`;
    return `<div data-appsec="${id}" class="space-y-6 ${T.app === id ? SHOWN : HIDDEN}">
      <div class="bg-white rounded-xl p-5 border border-slate-200 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div class="flex items-center gap-3.5"><div class="w-12 h-12 rounded-xl ${b.bg} flex items-center justify-center text-white shadow-md shrink-0">${tile}</div>
          <div><div class="flex items-center gap-2"><h2 class="text-xl font-bold font-headline text-slate-900">${esc(a.label)} Configuration</h2>
            <span class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full ${a.soft} border">${icon(APP_INFO[id][1], "text-xs")}<span>${li ? "Text channel" : "Video Channel"}</span></span></div>
            <p class="text-xs text-slate-500 mt-0.5">Every setting here is this app's own: schedule, topics, planning and publishing.</p></div></div>
        <div class="flex items-center gap-2">
          <button type="button" data-testapi="${id}" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">${icon("sync", "text-sm")}<span>Test API</span></button>
          <button type="button" data-pause="${id}" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 transition-colors">${icon(en ? "pause_circle" : "play_circle", "text-sm")}<span data-pause-label="${id}">${en ? "Pause App" : "Resume App"}</span></button></div></div>

      <div class="${CARD}">${head("repeat", "violet", "How often", `How often ${esc(a.label)} gets a post. ${tip("Weekly days", "Posts go out on the weekdays you tick below, each with its own topic.")} is the usual choice.`,
        `<span class="text-xs font-semibold text-violet-700 bg-violet-50 px-2.5 py-1 rounded-lg">Cadence Type</span>`)}
        <input type="hidden" data-k="${k("schedule.frequency")}" value="${freq}">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3.5 pt-1" data-freqbox="${id}">${freqCards(id, freq)}</div>
        <div data-everyn="${id}" class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1 ${freq === "every_n_days" ? SHOWN : HIDDEN}">
          ${field("Every N days", "hourglass_top", inp(k("schedule.every_n"), s.every_n ?? 2, "number", 'min="1" max="60"'), "A whole number from 1 to 60.")}
          ${field("Starting on", "event", inp(k("schedule.start_date"), s.start_date || "", "date"), "The first posting day; the count runs from here.")}
          ${field("Topics to cycle through (topic ids, one per line)", "autorenew", area(`data-k="${k("schedule.rotation")}" data-list="1"`, (s.rotation || []).join("\n"), 2), "Blank = the topics chosen in the weekly days.", "md:col-span-2")}</div>
        <p class="text-[11px] text-slate-500 pt-1">${tip("Weekly days", "Weekly recurrence repeats on the same weekdays every week.")} give steady audience retention. You can still add one-off dates below.</p></div>

      <div class="${CARD} space-y-5">${head("view_week", "sky", "Weekly cadence schedule", "Toggle active days, assign a topic and optionally a different time for each day.",
        `<span data-daycount="${id}" class="text-xs font-semibold px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200"></span>`)}
        <div class="grid grid-cols-1 md:grid-cols-7 gap-3" data-days="${id}"></div>
        <div class="flex flex-wrap items-center justify-between gap-3 pt-2 text-xs border-t border-slate-100"><div class="flex flex-wrap items-center gap-4" data-legend="${id}"></div>
          <span class="text-[11px] text-slate-500">Each day slot gets its own topic, planned and written by the ${tip("Writing team", "The crew agents that research and write the post for that day's topic.")}.</span></div></div>

      <div class="${CARD}">${head("calendar_month", "red", "One-off special dates", "Click a date on the calendar to add or remove a standalone post outside the recurring days.",
        `<div class="flex items-center gap-2"><span class="text-xs font-bold text-slate-800" data-calmonth="${id}"></span><div class="flex items-center bg-slate-100 rounded-lg p-0.5 border border-slate-200">
          <button type="button" data-calnav="-1" class="w-6 h-6 flex items-center justify-center text-slate-600 hover:text-slate-900" title="Previous month">${icon("chevron_left", "text-sm")}</button>
          <button type="button" data-calnav="1" class="w-6 h-6 flex items-center justify-center text-slate-600 hover:text-slate-900" title="Next month">${icon("chevron_right", "text-sm")}</button></div></div>`)}
        <div class="border border-slate-200 rounded-xl overflow-hidden bg-slate-50/40"><div class="grid grid-cols-7 text-center bg-slate-100/70 border-b border-slate-200 text-[11px] font-semibold text-slate-500 py-2">
          ${WEEKDAYS.map(d => `<span>${DAY_NAMES[d].slice(0, 3)}</span>`).join("")}</div><div class="grid grid-cols-7 text-xs divide-x divide-y divide-slate-200/60 bg-white" data-cal="${id}"></div></div>
        <div class="flex items-center justify-between text-[11px] text-slate-500 pt-1"><span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full ${b.bg}"></span>
          <span>Selected dates become ${tip("one-off posts", "A one-off date is written on top of the weekly schedule and uses the topic you name, or the planner's choice.")}. Click any unselected date to add.</span></span>
          <span class="font-semibold text-slate-700" data-datecount="${id}"></span></div>
        <details class="text-xs"><summary class="cursor-pointer font-semibold text-slate-600">Edit dates as text (topic and time are optional)</summary>
          ${field("One per line: date | topic id | time", "edit_note", area(`data-dates="${k("schedule.dates")}"`, dates, 3), "For example 2026-11-03 | topic id | 21:00", "pt-2")}</details></div>

      <div class="${CARD}">${head("schedule", "indigo", "Time and timezone", "When posts are written and published, in your audience's time zone.")}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
          ${field("Default release time", "alarm", iconIn("schedule", `<input data-k="${k("schedule.post_time")}" type="time" value="${esc(s.post_time || "")}" class="${FIELD_I}">`), "Default hour for days without their own time.")}
          ${field("Target timezone", "public", iconIn("map", `<input data-k="${k("schedule.timezone")}" type="text" list="tzs" value="${esc(s.timezone || "")}" class="${FIELD_I}">`), "An IANA name such as America/Chicago; it follows daylight saving.")}
          ${field("Write it ahead at", "edit_calendar", iconIn("schedule", `<input data-k="${k("schedule.generate_time")}" type="time" value="${esc(s.generate_time || "")}" class="${FIELD_I}">`), "When the crew starts writing, on the lead day.")}
          ${field("Days ahead", "event_upcoming", inp(k("schedule.lead_days"), s.lead_days ?? 1, "number", 'min="0" max="7"'), "Write this many days before the post time (0 to 7).")}</div>
        <div data-preview="${id}" class="bg-gradient-to-r from-red-50 via-slate-50 to-indigo-50 border border-red-100 rounded-xl p-3.5 flex items-center justify-between"></div></div>

      <div class="${CARD}">${head("event_available", "violet", "Weekly planning", `The Week Planner picks each day's topic from your ideas. ${tip("Re-plan", "Replaces the planner's topics; topics you typed in the Plan are kept.")} replaces its choices.`)}
        ${swRow(k("planning.enabled"), pn.enabled, "Plan this week's topics automatically", "The planner runs on the day and time below.")}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          ${field("Plan every", "event_repeat", sel(k("planning.weekday"), pn.weekday, WEEKDAYS.map(d => [d, DAY_NAMES[d]])), "The weekday the plan is made.")}
          ${field("Plan at", "schedule", inp(k("planning.time"), pn.time || "", "time"), "Time of day, in the time zone above.")}</div>
        ${field("Focus for the next plan (optional)", "center_focus_strong", `<input data-k="${k("planning.focus")}" value="${esc(pn.focus || "")}" maxlength="600" placeholder="e.g. This week is about Kubernetes; keep examples in Python" class="${FIELD}">`, "A direction for the whole plan; blank lets the planner choose.")}
        <div class="flex flex-wrap items-center gap-3 pt-1">${button("primary", "event_available", "Save and plan open days", `data-plan="${id}|0"`)}${button("secondary", "refresh", "Save and re-plan this week", `data-plan="${id}|1"`)}
          <a class="text-xs font-semibold text-violet-600 hover:underline" href="#plan">Open the Plan</a><span class="text-[11px] text-slate-400" data-plan-state="${id}"></span></div></div>

      <div class="${CARD}" ${li ? 'id="ideas"' : ""}>${head("lightbulb", "amber", "Topics", `The kinds of posts you want. List your own ideas under each (one per line); the Week Planner uses them before inventing its own.`)}
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4" id="topics-${id}" data-topics="${id}"></div>
        <div class="flex items-center gap-2 pt-1"><input data-newtopic="${id}" placeholder="New topic, e.g. ${li ? "Career advice" : "Explain a concept"}" maxlength="60" class="${FIELD} max-w-xs">${button("secondary", "add", "Add topic", `data-addtopic="${id}"`)}</div>
        <p class="text-[11px] text-slate-400">Each topic needs a name and a brief; ideas, context and planning notes are optional.</p></div>

      ${id === "youtube" ? youtubeCard() : ""}

      <div class="${CARD}">${head("gavel", "emerald", "When a post is ready", "Governance rules for when the agents finish a draft.", `<span class="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600">Approval Policy</span>`)}
        <input type="hidden" data-k="${k("publishing.approval")}" value="${esc(pub.approval || "auto_with_veto")}">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3.5 pt-1" data-apprbox="${id}">${approvalCards(id, pub.approval || "auto_with_veto")}</div>
        ${id === "youtube" ? ytPublishing() : ""}
        <p class="text-[11px] text-slate-400 pt-1">The ${tip("veto window", "Between the draft being ready and the post time you can veto or edit it in the Queue.")} protects your voice while keeping the crew hands-off.</p></div>

      <div class="bg-blue-50/60 border border-blue-200 rounded-xl p-5 flex items-start justify-between gap-4"><div class="flex items-start gap-3">
        <div class="w-10 h-10 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center shrink-0 mt-0.5">${icon("info", "text-xl")}</div>
        <div><div class="flex items-center gap-2"><h3 class="font-bold text-sm text-blue-950">Practice mode</h3><span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-200 text-blue-800 uppercase tracking-wider">Dry-Run Shield</span></div>
          <p class="text-xs text-blue-900 mt-1 leading-relaxed">Write posts and run the whole crew, but never send anything to ${esc(a.label)}.</p>
          <p class="text-[11px] text-blue-700 mt-1.5 flex items-center gap-1">${icon("help_outline", "text-xs")}<span>Useful for testing your voice and the schedule before going live.</span></p></div></div>
        ${sw(`data-k="${k("publishing.dry_run")}"`, pub.dry_run, "peer-checked:bg-blue-600", true)}</div></div>`;
  }
  // YouTube-only settings: video format, length, ElevenLabs voice, renderer. Fields carry data-k so collectSettings() saves them.
  const DOCS = "https://github.com/sudip1205/social-postcrew/blob/main/docs/";
  const VRANGE = { short: { min: 15, max: 60, step: 5, def: 45, ticks: ["15s", "30s", "45s", "60s"] },
    long: { min: 60, max: 1800, step: 30, def: 480, ticks: ["1 min", "10 min", "20 min", "30 min"] } };
  const secsLabel = (f, n) => f === "long" ? `${n % 60 ? (n / 60).toFixed(1) : n / 60} min` : `${n} seconds`;
  const SPIN = "inline-flex items-center justify-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-slate-900 text-white shadow-sm shrink-0 disabled:opacity-50 disabled:cursor-not-allowed";
  function typeCards(f) {
    const items = [["short", "stay_current_portrait", "Short", "Vertical (9:16), up to 60s runtime"], ["long", "laptop_chromebook", "Long", "Horizontal (16:9), chapters & b-roll"]];
    return items.map(([v, ic, t, d]) => `<div data-vtype="${v}" class="${v === f ? "border-2 border-red-500 bg-red-50/40" : "border border-slate-200 bg-white hover:border-slate-300"} rounded-xl p-3.5 flex items-center justify-between cursor-pointer transition-all">
      <div class="flex items-center gap-3"><div class="w-9 h-9 rounded-lg ${v === f ? "bg-red-500 text-white" : "bg-slate-100 text-slate-600"} flex items-center justify-center">${icon(ic, "text-xl")}</div>
        <div><span class="text-sm font-bold text-slate-900 block">${t}</span><span class="text-xs text-slate-500">${esc(d)}</span></div></div>
      <input ${v === f ? "checked" : ""} class="w-4 h-4 border-slate-300 pointer-events-none" type="radio" tabindex="-1" aria-label="${t}"/></div>`).join("");
  }
  const ticksHtml = f => VRANGE[f].ticks.map(t => `<span>${t}</span>`).join("");
  function youtubeCard() {
    const v = own("youtube").video || {}, f = v.format === "long" ? "long" : "short", R = VRANGE[f], vo = v.voice || {}, m = v.mcp || {}, k = p => K("youtube", "video." + p);
    const secs = Math.min(R.max, Math.max(R.min, parseInt(v.target_seconds, 10) || R.def)), ytAccent = brand("youtube").accent;
    const voiceOpt = vo.voice_id ? `<option value="${esc(vo.voice_id)}" selected>${esc(vo.voice_name || vo.voice_id)}</option>` : "";
    return `<div class="bg-white rounded-xl p-6 border-2 border-red-200 shadow-sm space-y-5 relative overflow-hidden" data-ytcard><div class="absolute -right-12 -top-12 w-32 h-32 bg-red-50 rounded-full pointer-events-none"></div>
      <div class="flex items-center gap-2.5 relative"><div class="w-8 h-8 rounded-lg bg-red-100 text-red-700 flex items-center justify-center">${icon("movie_edit")}</div>
        <div><h3 class="text-base font-bold font-headline text-slate-900">YouTube Video Settings</h3>
          <p class="text-xs text-slate-500">Video format, length, the ElevenLabs voice and how the video is drawn.</p></div></div>
      <div class="space-y-5 relative"><div><label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-2">${icon("aspect_ratio", "text-slate-400 text-sm")}<span>Video type &amp; aspect framing</span></label>
        <input type="hidden" data-k="${k("format")}" id="yt-format" value="${f}">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3" id="yt-types">${typeCards(f)}</div>
        <p class="text-[11px] text-slate-400 mt-1.5">Shorts go to the algorithmic feed; long-form builds multi-scene videos with chapters. A topic can override this.</p></div>
        <div class="pt-2 border-t border-slate-100"><div class="flex items-center justify-between mb-2"><label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700">${icon("timer", "text-slate-400 text-sm")}<span>Target video duration</span></label>
          <span id="yt-secs-label" class="text-xs font-bold text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded-md">${secsLabel(f, secs)}</span></div>
          <input id="yt-secs" data-k="${k("target_seconds")}" class="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer ${ytAccent}" type="range" min="${R.min}" max="${R.max}" step="${R.step}" value="${secs}"/>
          <div id="yt-ticks" class="flex justify-between text-[10px] text-slate-400 mt-1">${ticksHtml(f)}</div>
          <p class="text-[11px] text-slate-400 mt-1">The script length will be matched to this audio timing.</p></div>
        <div class="pt-2 border-t border-slate-100"><label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 mb-1.5">${icon("record_voice_over", "text-slate-400 text-sm")}<span>AI Voice Narrator (ElevenLabs)</span></label>
          <input type="hidden" data-k="${k("voice.voice_name")}" id="yt-voice-name" value="${esc(vo.voice_name || "")}">
          <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5"><div class="relative flex-1">${iconIn("mic", `<select data-k="${k("voice.voice_id")}" id="yt-voice" class="${FIELD_I} appearance-none"><option value="">No voice chosen yet</option>${voiceOpt}</select>`)}</div>
            <button class="${SPIN}" type="button" id="yt-play">${icon("play_arrow", "text-sm text-red-400")}<span>Play sample</span></button></div>
          <p class="text-[11px] text-slate-400 mt-1" id="yt-voice-msg">A short sample of the chosen ElevenLabs voice.</p></div>
        <div class="pt-2 border-t border-slate-100 space-y-4"><div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          ${field("Video renderer", "movie", sel(k("renderer"), v.renderer || "ffmpeg", [["ffmpeg", "Built-in slides + captions"], ["blackboard", "Blackboard: drawn by hand to the voice"], ["mcp", "Animation MCP server"]]).replace("<select ", '<select id="yt-renderer" '), "How the picture is made.")}
          <div class="flex items-end">${swRow(k("captions"), v.captions !== false, "Burn in captions", "Subtitles drawn on the video.").replace('class="flex items-start', 'class="w-full flex items-start')}</div></div>
          <div id="yt-mcp" class="grid grid-cols-1 md:grid-cols-2 gap-4 ${v.renderer === "mcp" ? SHOWN : HIDDEN}">
            ${field("Command", "terminal", inp(k("mcp.command"), m.command || "", "text", 'placeholder="npx"'), "The program that starts the MCP server.")}
            ${field("Tool name", "build", inp(k("mcp.tool"), m.tool || "", "text", 'placeholder="render_scene"'), "The tool called once per scene.")}
            ${field("Arguments (one per line)", "list", area(`data-k="${k("mcp.args")}" data-list="1"`, (m.args || []).join("\n"), 3), "Each line is one argument.")}
            ${field("Timeout (seconds)", "hourglass_top", inp(k("mcp.timeout_s"), m.timeout_s ?? 600, "number", 'min="30" max="7200"'), "How long one render may take.")}</div>
          <p class="text-[11px] text-slate-400">${icon("menu_book", "text-xs")} <a class="text-violet-600 font-semibold hover:underline" href="${DOCS}video-and-voice.md" target="_blank" rel="noopener">Animated video with an MCP server</a> explains the setup.</p></div></div></div>`;
  }
  function ytPublishing() {
    const pub = own("youtube").publishing || {}, k = p => K("youtube", p);
    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-slate-100">
      ${field("Visibility on YouTube", "visibility", sel(k("publishing.visibility"), pub.visibility || "private", [["public", "Public"], ["unlisted", "Unlisted"], ["private", "Private"]]), "Unverified Google apps always upload as private.")}
      <div class="pt-5">${swRow(k("publishing.made_for_kids"), pub.made_for_kids, "Made for kids", "Tick only if the videos are aimed at children.")}</div></div>`;
  }
  function ytLabel() { const f = $("#yt-format").value, n = parseInt($("#yt-secs").value, 10); $("#yt-secs-label").textContent = secsLabel(f, n); }
  function ytType(f) {
    $("#yt-format").value = f; $("#yt-types").innerHTML = typeCards(f);
    const R = VRANGE[f], r = $("#yt-secs"); r.min = R.min; r.max = R.max; r.step = R.step; r.value = R.def;
    $("#yt-ticks").innerHTML = ticksHtml(f); ytLabel(); dirty();
  }
  async function ytInit() {
    if (T.voicesLoaded || T.app !== "youtube" || !$("#yt-voice")) return;
    T.voicesLoaded = true; const msg = $("#yt-voice-msg"), selEl = $("#yt-voice");
    const cred = '<a class="text-violet-600 font-semibold hover:underline" href="#credentials">Credentials</a>';
    try {
      const d = await api("/api/credentials");
      if (!d.secrets?.elevenlabs_api_key) { msg.innerHTML = `Add your ElevenLabs key in ${cred} to pick a voice.`; return; }
      const { voices } = await api("/api/voices"), cur = selEl.value;
      selEl.innerHTML = `<option value="">No voice chosen yet</option>` + voices.map(x => `<option value="${esc(x.id)}" ${x.id === cur ? "selected" : ""}>${esc(x.name)}${x.category ? ` (${esc(x.category)})` : ""}</option>`).join("");
      if (cur && !voices.some(x => x.id === cur)) selEl.insertAdjacentHTML("beforeend", `<option value="${esc(cur)}" selected>${esc($("#yt-voice-name").value || cur)}</option>`);
    } catch (e) { T.voicesLoaded = false; msg.innerHTML = `${esc(e.message)}. Check the key in ${cred}.`; }
  }
  async function ytPlay() {
    const id = $("#yt-voice").value, b = $("#yt-play"); if (!id) return toast("Choose a voice first", true);
    b.disabled = true; b.innerHTML = `${icon("progress_activity", "text-sm animate-spin")}<span>Loading</span>`;
    try { const r = await post("/api/voices/sample", { voice_id: id }); await new Audio(r.url).play(); }
    catch (e) { toast(e.message || "Could not play the sample", true); }
    b.disabled = false; b.innerHTML = `${icon("play_arrow", "text-sm text-red-400")}<span>Play sample</span>`;
  }
  async function testApi(id, btn) {
    btn.disabled = true;
    try { await post("/api/credentials/check"); const st = (await api("/api/credentials")).status?.[id] || {};
      toast(`${appName(id)}: ${st.message || st.state || "checked"}`, statusKind(st.state) !== "passed"); refreshOverview(); }
    catch (e) { toast(e.message, true); }
    btn.disabled = false;
  }

  /* ---------- the other tabs ---------- */
  function brandPanel(c) {
    return `<div class="max-w-4xl mx-auto space-y-6">
      <div class="${CARD}">${head("person", "violet", "About you", "The writer only claims what you list here about yourself.")}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          ${field("Your name", "badge", inp("profile.name", c.profile.name), "Printed on posters and used in the writer's voice.")}
          ${field("Profile link printed on posters", "link", inp("profile.handle", c.profile.handle, "text", 'placeholder="linkedin.com/in/your-name"'), "Shown on the picture of each post.")}
          ${field("Who reads your posts", "groups", inp("profile.audience", c.profile.audience), "The audience the writer has in mind.")}
          ${field("How you write", "record_voice_over", inp("profile.voice", c.profile.voice), "Tone and style, in a sentence.")}
          ${field("True facts about you (one per line)", "fact_check", area('data-k="profile.about" data-list="1"', c.profile.about.join("\n"), 3, "e.g. 10 years building Java backends"), "The writer never claims anything that is not listed here.", "md:col-span-2")}
          ${field("Blocked phrases (one per line)", "block", area('data-k="profile.blocklist" data-list="1"', c.profile.blocklist.join("\n"), 3), "Words and phrases no post may contain.", "md:col-span-2")}</div></div>
      <div class="${CARD}">${head("notifications", "amber", "Alert channels", "How the crew reaches you when a post needs attention.")}
        <div class="divide-y divide-slate-100">${swRow("notifications.desktop", c.notifications.desktop, "Desktop", "A notification on this computer.")}
          ${swRow("notifications.email", c.notifications.email, "Gmail", "A styled email. Set up Gmail in Credentials.")}
          ${swRow("notifications.telegram", c.notifications.telegram, "Telegram", "A Telegram message. Set up Telegram in Credentials.")}</div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">${field("Warn days before the LinkedIn token expires", "event_busy", inp("notifications.warn_days_before_expiry", c.notifications.warn_days_before_expiry, "number", 'min="1" max="30"'), "You get an alert this many days ahead (1 to 30).")}</div>
        <div class="flex items-center gap-3">${button("secondary", "send", "Send a test", 'id="test-notify" type="button"')}<span class="text-[11px] text-slate-400">Sends a test alert to every channel switched on above.</span></div></div></div>`;
  }
  function qualityPanel(c, agents) {
    const bk = c.llm.backend, g = (n, ...x) => `<div class="grid grid-cols-1 md:grid-cols-${n} gap-4">${x.join("")}</div>`;
    const th = "text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider px-3 py-2";
    return `<div class="max-w-4xl mx-auto space-y-6">
      <div class="${CARD}">${head("psychology", "indigo", "AI provider", `Which AI runs the crew. API keys go in <a class="text-violet-600 font-semibold hover:underline" href="#credentials">Credentials</a>.`)}
        ${g(2, field("Which AI runs the crew", "smart_toy", sel("llm.backend", bk, [["claude-code", "Claude Pro / Max / Team plan (Claude Code login, no API key)"], ["anthropic", "Claude API (Anthropic API key)"],
          ["openai", "OpenAI API (OpenAI API key)"], ["openai-compatible", "OpenAI-compatible: Ollama, LM Studio, OpenRouter, Groq, vLLM..."], ["demo", "Demo: scripted answers, no AI (for trying Postcrew)"]]), "Save after changing it to see that provider's model fields."),
          field("Server address (OpenAI-compatible; optional for OpenAI)", "dns", inp("llm.api.base_url", c.llm.api.base_url, "url", 'placeholder="http://localhost:11434/v1"'), "OpenAI-compatible servers have no web search: researchers suggest pages they know, and every page is still downloaded and checked."))}
        ${["claude-code", "demo"].includes(bk) ? "" : g(3, ...[["opus", "Strongest (opus)"], ["sonnet", "Balanced (sonnet)"], ["haiku", "Fastest (haiku)"]].map(([t, l]) =>
          field(`${l} model`, "memory", inp(`llm.api.models.${bk}.${t}`, c.llm.api.models[bk]?.[t] || "", "text", 'placeholder="model id"'), `Agents ask for a tier; this is the ${esc(bk)} model used for it.`)))}</div>
      <div class="${CARD}">${head("tune", "sky", "AI models per agent", `A ${tip("tier", "haiku = cheapest, sonnet = balanced, opus = strongest; or a full model id.")} or a full model id for each agent. "Max $" stops a single call.`)}
        <div class="overflow-x-auto border border-slate-200 rounded-xl"><table class="w-full text-sm"><thead class="bg-slate-50"><tr><th class="${th}">Agent</th><th class="${th}">What it does</th><th class="${th}">Model</th><th class="${th}">Timeout (s)</th><th class="${th}">Max $ per call</th></tr></thead>
          <tbody class="divide-y divide-slate-100">${agents.filter(a => a.uses_llm).map(a => { const s = c.llm.agents[a.id] || {};
            return `<tr><td class="px-3 py-2"><span class="flex items-center gap-2">${avatar(a.id, "w-8 h-8")}<span><b class="text-slate-900">${esc(a.name || a.title)}</b><span class="block text-[11px] text-slate-500">${esc(a.title)}</span></span></span></td>
              <td class="px-3 py-2 text-xs text-slate-500">${esc(a.role)}</td>
              <td class="px-3 py-2">${inp(`llm.agents.${a.id}.model`, s.model ?? c.llm.defaults.model, "text", 'list="models"')}</td>
              <td class="px-3 py-2">${inp(`llm.agents.${a.id}.timeout_s`, s.timeout_s ?? c.llm.defaults.timeout_s, "number", 'min="30" max="3600"')}</td>
              <td class="px-3 py-2">${inp(`llm.agents.${a.id}.max_budget_usd`, s.max_budget_usd ?? c.llm.defaults.max_budget_usd, "number", 'step="0.05" min="0.05" max="20"')}</td></tr>`; }).join("")}</tbody></table></div>
        <p class="text-[11px] text-slate-400">Prices for the cost estimate are in config.json (llm.api.prices).</p>
        <datalist id="models"><option value="haiku"><option value="sonnet"><option value="opus"></datalist></div>
      <div class="${CARD}">${head("shield", "emerald", "Quality bar and limits", "A post goes out only when its review scores clear the bar.")}
        ${g(3, field("Minimum review score", "grade", inp("pipeline.min_overall", c.pipeline.min_overall, "number", 'min="0" max="100"'), "Overall score, 0 to 100."),
          field("Minimum score on any single criterion", "rule", inp("pipeline.min_subscore", c.pipeline.min_subscore, "number", 'min="0" max="100"'), "The weakest criterion must clear this too."),
          field("Reviews per post (worst counts)", "reviews", inp("pipeline.review_runs", c.pipeline.review_runs, "number", 'min="1" max="5"'), "1 to 5 reviews; the lowest score counts."),
          field("Tries per agent", "replay", inp("pipeline.max_attempts_per_step", c.pipeline.max_attempts_per_step, "number", 'min="1" max="10"'), "How often one agent may retry a step."),
          field("Tries per post (all agents)", "repeat", inp("pipeline.max_total_attempts", c.pipeline.max_total_attempts, "number", 'min="1" max="40"'), "A cap across every agent for one post."),
          field("Max $ per post", "payments", inp("pipeline.max_run_budget_usd", c.pipeline.max_run_budget_usd, "number", 'step="0.5" min="0.5" max="100"'), "The run stops when its cost reaches this."))}</div>
      <div class="${CARD}">${head("groups", "violet", "Team", "How many agents work on each post, and when a member is replaced.")}
        ${g(3, field("Researchers per post", "search", inp("team.research", c.team.research, "number", 'min="1" max="4"'), "1 to 4."), field("Writers per post", "edit_note", inp("team.writer", c.team.writer, "number", 'min="1" max="4"'), "1 to 4."),
          `<div class="pt-4">${swRow("team.pre_review", c.team.pre_review, "Pre-review and polish", "Drafts are reviewed and polished before the Editor.")}</div>`,
          field("Judge members on their last (posts)", "history", inp("team.fire_window", c.team.fire_window, "number", 'min="3" max="20"'), "3 to 20 posts."),
          field("Replace a member below (share of good posts, 0-1)", "person_remove", inp("team.fire_min_success", c.team.fire_min_success, "number", 'step="0.05" min="0" max="1"'), "A member under this share is replaced."))}</div>
      <div class="${CARD}">${head("settings", "slate", "Other", "Rarely changed. The defaults work.")}
        ${g(3, field("Check credentials daily at", "key", inp("schedule.credential_check_time", c.schedule.credential_check_time, "time"), "Time of day, in your time zone."),
          field("Claude Code command", "terminal", inp("llm.claude_path", c.llm.claude_path), "The command that starts Claude Code."),
          field("Longest AI answer (tokens, API providers)", "short_text", inp("llm.api.max_output_tokens", c.llm.api.max_output_tokens, "number", 'min="1000" max="200000"'), "1,000 to 200,000."),
          field("LinkedIn API version (YYYYMM)", "api", inp("publishing.linkedin_api_version", c.publishing.linkedin_api_version), "For example 202601."))}</div></div>`;
  }

  /* ---------- page ---------- */
  const TABS3 = [["apps", "tune", "Apps & Schedules", "Apps & Publishing Schedules", "auto_schedule", "Automated Cadence", "Configure topics, run schedules and post-approval guardrails for each connected app."],
    ["brand", "palette", "Brand Voice & Tone", "Brand Voice & Tone", "record_voice_over", "Your voice", "Tell the crew who you are and how to reach you."],
    ["quality", "shield", "Quality Gates", "Quality Gates", "verified_user", "AI and quality", "Which AI runs the crew, the quality bar and the team limits."]];
  function headerHtml() {
    const [, , name, title, cic, chipText, sub] = TABS3.find(t => t[0] === T.tab);
    return `<div class="bg-white border-b border-slate-200 px-6 py-3.5"><div class="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4"><div>
      <div class="flex items-center gap-2 text-xs text-slate-500 mb-1"><span class="flex items-center gap-1">${icon("settings", "text-sm")}<span>Settings</span></span><span class="text-slate-300">/</span><span class="text-slate-900 font-semibold">${esc(name)}</span></div>
      <h1 class="text-2xl font-bold font-headline text-slate-900 tracking-tight flex items-center gap-2.5"><span>${esc(title)}</span>
        <span class="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200">${icon(cic, "text-xs")}<span>${esc(chipText)}</span></span></h1>
      <p class="text-xs text-slate-500 mt-1">${esc(sub)}</p></div>
      <div class="flex items-center gap-1.5 p-1 bg-slate-100/90 rounded-xl border border-slate-200 text-xs font-medium self-start md:self-auto">${TABS3.map(([id, ic, label]) => id === T.tab
        ? `<a data-stab="${id}" href="#settings" class="px-3 py-1.5 rounded-lg bg-white text-slate-900 shadow-sm font-semibold flex items-center gap-1.5">${icon(ic, "text-violet-600 text-sm")}<span>${esc(label)}</span></a>`
        : `<a data-stab="${id}" href="#settings" class="px-3 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 transition-colors flex items-center gap-1.5">${icon(ic, "text-slate-400 text-sm")}<span>${esc(label)}</span></a>`).join("")}</div></div></div>`;
  }

  /* ---------- live drawing ---------- */
  function drawDays(id, override = {}) {
    const box = $(`[data-days="${id}"]`); if (!box) return;
    const names = topicNames(id), has = Object.keys(names).length > 0, s = own(id).schedule || {}, b = brand(id), k = p => K(id, p);
    const cur = {}, times = {};
    WEEKDAYS.forEach(d => { const e = $(`[data-k="${k(`schedule.days.${d}`)}"]`), t = $(`[data-k="${k(`schedule.day_times.${d}`)}"]`);
      cur[d] = d in override ? override[d] : e ? e.value : (s.days || {})[d] || ""; times[d] = t ? t.value : (s.day_times || {})[d] || ""; });
    let n = 0;
    box.innerHTML = WEEKDAYS.map(d => {
      const on = !!cur[d] && (!has || cur[d] in names); if (on) n++;
      const col = colOf(names, cur[d]), nm = DAY_NAMES[d].slice(0, 3);
      const selEl = has ? `<select data-k="${k(`schedule.days.${d}`)}" data-dayval="${d}" class="w-full text-[11px] font-semibold py-1 pl-2 pr-5 rounded-md ${col.sel} appearance-none"><option value="">No post</option>${opts(Object.entries(names), cur[d])}</select>` : "";
      const timeEl = `<input data-k="${k(`schedule.day_times.${d}`)}" type="time" value="${esc(times[d])}" title="Different time on this day; blank = the default time" class="w-full text-[11px] font-medium border-0 p-0 text-slate-700 focus:ring-0">`;
      const chk = `<input type="checkbox" data-daychk="${d}" ${on ? "checked" : ""} ${has ? "" : 'disabled title="Add a topic first"'} class="w-4 h-4 rounded ${b.text} focus:ring-red-400 border-slate-300">`;
      return on ? `<div class="rounded-xl border-2 ${b.border} ${b.wash} p-3 flex flex-col justify-between shadow-sm"><div class="flex items-center justify-between"><span class="font-bold text-xs ${b.text} flex items-center gap-1"><span>${nm}</span><span class="w-1.5 h-1.5 rounded-full ${b.bg}"></span></span>${chk}</div>
          <div class="my-2 space-y-1.5"><div class="relative">${selEl}${icon("expand_more", `text-xs ${col.ic} absolute right-1 top-1.5 pointer-events-none`)}</div>
          <div class="flex items-center gap-1 bg-white border border-slate-200 rounded-md px-1.5 py-0.5">${icon("schedule", "text-slate-400 text-xs")}${timeEl}</div></div>
          <div class="text-[10px] ${b.text} font-semibold border-t ${b.line} pt-1 flex items-center justify-between"><span>Post day</span>${appBadge(id)}</div></div>`
        : `<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-3 flex flex-col justify-between opacity-70 hover:opacity-100 transition-all"><div class="flex items-center justify-between"><span class="font-bold text-xs text-slate-600">${nm}</span>${chk}</div>
          <div class="my-3 text-center"><span class="text-[11px] text-slate-600 font-medium italic">Off day</span></div><div class="hidden">${selEl}${timeEl}</div>
          <div class="text-[10px] text-slate-600 border-t border-slate-200 pt-1.5 text-center">No post</div></div>`;
    }).join("");
    const cnt = $(`[data-daycount="${id}"]`); if (cnt) cnt.textContent = `${n} of 7 Days Active`;
    const lg = $(`[data-legend="${id}"]`);
    if (lg) lg.innerHTML = `<span class="text-slate-600 font-medium">Topic Color Tagging:</span>${has ? Object.entries(names).map(([cid, nm]) => { const c = colOf(names, cid);
      return `<span class="inline-flex items-center gap-1.5 text-[11px] font-semibold ${c.leg} px-2 py-0.5 rounded border"><span class="w-2 h-2 rounded-full ${c.dot}"></span><span>${esc(nm)}</span></span>`; }).join("") : `<span class="text-[11px] text-slate-500">No topics yet.</span>`}`;
    drawTopicDays(id);
  }
  function drawTopicDays(app) {
    document.querySelectorAll(`#topics-${app} [data-cat]`).forEach(box => {
      const id = box.dataset.cat, days = WEEKDAYS.filter(d => ($(`[data-k="${K(app, `schedule.days.${d}`)}"]`)?.value ?? (own(app).schedule?.days || {})[d]) === id);
      box.querySelector("[data-topic-days]").innerHTML = days.length ? `Posted on ${days.map(d => DAY_NAMES[d]).join(", ")}`
        : `<span class="text-amber-700 font-medium">Not on the schedule yet. Pick it for a day in the weekly schedule.</span>`;
    });
  }
  const parseDates = text => text.split("\n").map(l => l.trim()).filter(Boolean).map(l => { const [date, category, time] = l.split("|").map(x => x.trim()); return { date, category, time }; });
  // what one app posts on a given day (iso date): { label, time } or null. Reads the live form so the preview follows unsaved edits.
  function postOn(id, iso, wd, names) {
    const s = own(id).schedule || {}, freq = dv(id, "schedule.frequency") || s.frequency || "weekly", base = dv(id, "schedule.post_time") || s.post_time || "";
    const one = parseDates($(`[data-dates="${K(id, "schedule.dates")}"]`)?.value || "").find(e => e.date === iso);
    if (one) return { one: true, label: one.category ? (names[one.category] || one.category) : "One-off special", time: one.time || base };
    if (freq === "weekly") { const d = WEEKDAYS[wd], v = dv(id, `schedule.days.${d}`); return v ? { label: names[v] || v, time: dv(id, `schedule.day_times.${d}`) || base } : null; }
    if (freq === "every_n_days") { const st = dv(id, "schedule.start_date"), n = parseInt(dv(id, "schedule.every_n"), 10);
      if (!st || !n) return null; const diff = Math.round((Date.parse(iso) - Date.parse(st)) / 864e5); return diff >= 0 && diff % n === 0 ? { label: "Post", time: base } : null; }
    return null;
  }
  function drawCal(id) {
    const box = $(`[data-cal="${id}"]`); if (!box) return;
    const now = new Date(), m = T.month || (T.month = { y: now.getFullYear(), m: now.getMonth() }), names = topicNames(id), b = brand(id);
    const first = new Date(Date.UTC(m.y, m.m, 1)), lead = (first.getUTCDay() + 6) % 7, days = new Date(Date.UTC(m.y, m.m + 1, 0)).getUTCDate();
    const cells = Math.ceil((lead + days) / 7) * 7; let html = "", ones = 0;
    for (let i = 0; i < cells; i++) {
      const dt = new Date(Date.UTC(m.y, m.m, 1 - lead + i)), iso = dt.toISOString().slice(0, 10), dn = dt.getUTCDate(), wd = (dt.getUTCDay() + 6) % 7;
      if (dt.getUTCMonth() !== m.m) { html += `<div class="p-2 text-slate-300 min-h-[64px] bg-slate-50/30">${dn}</div>`; continue; }
      const p = postOn(id, iso, wd, names);
      if (p?.one) { ones++; html += `<div data-caldate="${iso}" class="p-2 font-medium min-h-[64px] ${b.bg} text-white rounded-lg shadow-sm m-0.5 relative group cursor-pointer ring-2 ${b.ring}"><div class="flex justify-between items-center"><span class="font-black text-sm">${dn}</span>${icon("grade", "text-xs")}</div>
        <div class="mt-1 text-[10px] font-bold leading-tight truncate">${esc(p.label)}</div><span class="text-[9px] text-slate-100 block">${esc(p.time)} one-off</span></div>`; }
      else if (p) { const borderL = b.border.replace("border-", "border-l-"); html += `<div class="p-2 font-medium text-slate-800 min-h-[64px] ${b.wash} border-l-2 ${borderL}"><div class="flex justify-between items-center"><span class="font-bold text-slate-900">${dn}</span><span class="text-[9px] ${b.text} font-bold">${DAY_NAMES[WEEKDAYS[wd]].slice(0, 3)}</span></div>
        <div class="mt-1 text-[10px] text-slate-600 truncate bg-white px-1 py-0.5 rounded border border-slate-200">${esc(p.label)}</div></div>`; }
      else html += `<div data-caldate="${iso}" class="p-2 font-medium text-slate-700 min-h-[64px] hover:bg-slate-50 cursor-pointer">${dn}</div>`;
    }
    box.innerHTML = html;
    $(`[data-calmonth="${id}"]`).textContent = `${first.toLocaleString([], { month: "long", timeZone: "UTC" })} ${m.y}`;
    $(`[data-datecount="${id}"]`).textContent = `${ones} one-off ${ones === 1 ? "post" : "posts"} this month`;
  }
  function drawPreview(id) {
    const box = $(`[data-preview="${id}"]`); if (!box) return;
    const tz = dv(id, "schedule.timezone") || "UTC", names = topicNames(id), b = brand(id);
    let next = null, err = false;
    try {
      const p = new Intl.DateTimeFormat("en-CA", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(new Date());
      const g = t => +p.find(x => x.type === t).value, base = Date.UTC(g("year"), g("month") - 1, g("day")), nowMin = g("hour") * 60 + g("minute");
      for (let i = 0; i < 400 && !next; i++) {
        const dt = new Date(base + i * 864e5), iso = dt.toISOString().slice(0, 10), q = postOn(id, iso, (dt.getUTCDay() + 6) % 7, names);
        if (!q || !/^\d\d:\d\d$/.test(q.time)) continue;
        const [h, mi] = q.time.split(":").map(Number); if (i === 0 && h * 60 + mi <= nowMin) continue;
        next = `${DAY_NAMES[WEEKDAYS[(dt.getUTCDay() + 6) % 7]].slice(0, 3)} ${dt.getUTCDate()} ${MON[dt.getUTCMonth()]} at ${h % 12 || 12}:${String(mi).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
      }
    } catch (e) { err = true; }
    box.innerHTML = `<div class="flex items-center gap-3"><div class="w-9 h-9 rounded-lg ${b.bg} text-white flex items-center justify-center shadow-sm">${icon("schedule")}</div>
      <div><span class="text-[11px] font-semibold text-red-700 uppercase tracking-wider block">Live Delivery Forecast</span>
        <div class="text-sm font-bold text-slate-900 mt-0.5">${err ? "Check the time zone" : next ? `Next post: <span class="${b.text}">${esc(next)}</span> (${esc(tz)})` : "No upcoming post on this schedule"}</div></div></div>
      <div class="hidden sm:flex items-center gap-1.5 text-xs text-slate-500 bg-white/80 px-2.5 py-1 rounded-lg border border-slate-200">${icon(next ? "check_circle" : "warning", `${next ? "text-emerald-600" : "text-amber-600"} text-xs`)}<span>${next ? "Cadence validated" : "Nothing planned"}</span></div>`;
  }
  const drawAll = () => PLATFORM_IDS.forEach(id => { drawCal(id); drawPreview(id); });

  function drawTopics(app = "linkedin") {
    const c = S.config, yt = app === "youtube", cats = catsOf(c, app), ta = (f, label, v, rows, ph = "", help = "") => `<label class="block"><span class="text-xs font-semibold text-slate-700">${label}</span><textarea data-c="${f}" rows="${rows}" placeholder="${esc(ph)}" class="${FIELD} mt-1">${esc(v)}</textarea>${help ? `<span class="text-[11px] text-slate-400">${help}</span>` : ""}</label>`;
    $(`#topics-${app}`).innerHTML = Object.entries(cats).map(([id, k]) => {
      const fixed = isFixedTopic(id, k), used = (S.ideaUse?.[id] || []).filter(x => x.used_on);
      return `<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-4 space-y-3" data-cat="${esc(id)}" data-app="${app}">
        <div class="flex items-center gap-2"><input data-c="label" value="${esc(k.label)}" maxlength="60" aria-label="Topic name" title="Click to rename" class="${FIELD} font-bold">
          <button type="button" data-delcat="${esc(id)}" data-app="${app}" title="Remove this topic" class="inline-flex items-center gap-1 px-2.5 py-2 text-xs font-semibold rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 transition-colors shrink-0">${icon("delete", "text-sm")}<span>Remove</span></button></div>
        <div class="text-[11px] text-slate-500" data-topic-days></div>
        ${fixed ? `<div class="text-xs text-slate-500">${k.media === "animation" ? "Picks the next algorithm from the built-in library automatically." : "Sums up the week's posts automatically."}</div>`
          : ta("ideas", "Your ideas (one per line)", (k.ideas || []).join("\n"), 4, "e.g. Circuit breaker :: closed, open, half-open; fail fast", "Add :: and a few words of context after the title; the planner and the writer use them.")}
        ${used.length ? `<div class="text-[11px] text-slate-500">Already used: ${used.map(x => `${esc(x.idea)} (${esc(x.used_on)})`).join("; ")}</div>` : ""}
        ${ta("context", "About this type of topic (context)", k.context || "", 3, "What this topic is about, who it is for, your angle and experience.", "Helps the writer keep your angle.")}
        ${ta("plan_context", "How to plan it", k.plan_context || "", 3, "How the week planner should choose topics of this type.", "Guidance for the Week Planner.")}
        ${ta("brief", yt ? "What this kind of video must contain" : "What this kind of post must contain", k.brief, 3, "", yt ? "The script, scenes and thumbnail come from each day's plan and brief." : "Research always runs. The picture and its label come from each day's plan and brief.")}
        ${yt ? `<div class="grid grid-cols-2 gap-3"><label class="block"><span class="text-xs font-semibold text-slate-700">Format (optional)</span><select data-c="format" class="${FIELD} mt-1 appearance-none">${opts([["", "Inherit"], ["short", "Short"], ["long", "Long"]], k.format || "")}</select></label>
          <label class="block"><span class="text-xs font-semibold text-slate-700">Length (seconds)</span><input data-c="target_seconds" type="number" min="15" max="1800" value="${esc(k.target_seconds ?? "")}" placeholder="Inherit" class="${FIELD} mt-1"></label></div>` : ""}</div>`; }).join("");
    document.querySelectorAll(`#topics-${app} [data-delcat]`).forEach(b => b.onclick = () => {
      const id = b.dataset.delcat;
      if (!confirm(`Remove the topic "${cats[id].label}"? Days that use it will have no post.`)) return;
      collectSettings(); delete catsOf(S.config, app)[id];
      const sc = own(app).schedule; WEEKDAYS.forEach(d => { if (sc.days[d] === id) sc.days[d] = ""; });
      drawTopics(app); drawDays(app); drawAll(); dirty();
    });
    drawTopicDays(app);
  }

  /* ---------- config <-> form (same payload as the old configurator) ---------- */
  function collectSettings() {
    const cfg = S.config, root = $("[data-st]");
    root.querySelectorAll("[data-k]").forEach(el => {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.dataset.list) v = v.split("\n").map(s => s.trim()).filter(Boolean);
      else if (el.type === "number" || el.type === "range") v = el.step && el.step.includes(".") ? parseFloat(v) : parseInt(v, 10);
      setPath(cfg, el.dataset.k, v);
    });
    root.querySelectorAll("[data-dates]").forEach(el => {
      setPath(cfg, el.dataset.dates, el.value.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
        const [date, category, time] = l.split("|").map(x => x.trim()); const e = { date };
        if (category) e.category = category; if (time) e.time = time; return e; }));
    });
    [cfg, ...Object.values(cfg.platforms || {})].forEach(o => {   // a weekday left blank keeps the normal time
      const dt = o.schedule?.day_times; if (dt) Object.keys(dt).forEach(d => { if (!dt[d]) delete dt[d]; });
    });
    root.querySelectorAll("[data-cat]").forEach(box => {
      const k = catsOf(cfg, box.dataset.app || "linkedin")[box.dataset.cat]; if (!k) return;
      box.querySelectorAll("[data-c]").forEach(el => {
        const f = el.dataset.c; let v = el.type === "checkbox" ? el.checked : el.value;
        if (f === "layouts") v = v.split(",").map(s => s.trim()).filter(Boolean);
        if (f === "ideas") v = v.split("\n").map(s => s.trim()).filter(Boolean);
        if (["min_chars", "max_chars"].includes(f)) v = parseInt(v, 10);
        if (f === "format") { if (!v) delete k[f]; else k[f] = v; return; }
        if (f === "target_seconds") { v = parseInt(v, 10); if (!v) delete k[f]; else k[f] = v; return; }
        if (f === "max_source_age_days") { if (v === "") { delete k[f]; return; } v = parseInt(v, 10); }
        k[f] = v;
      });
    });
    return cfg;
  }
  function dirty() {
    S.dirty = true; const el = $("#save-state");
    if (el) el.innerHTML = `<span class="text-sm font-bold text-amber-900 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span><span>Unsaved changes</span></span>`;
    const n = $("#save-note"); if (n) n.textContent = "The scheduler will not apply updates until saved.";
  }
  async function saveSettings() {
    const cfg = collectSettings();
    try {
      const r = await api("/api/config", { method: "PUT", body: { config: cfg } });
      if (!r.ok) {
        $("#cfg-errors").innerHTML = `<div class="flex items-start gap-2.5 bg-rose-50 border border-rose-200 text-rose-800 text-sm rounded-xl px-4 py-3 mb-4">${icon("error", "text-rose-600 shrink-0")}<div><b>Not saved. Fix these:</b><ul class="list-disc pl-5 mt-1">${r.errors.map(e => `<li>${esc(e)}</li>`).join("")}</ul></div></div>`;
        window.scrollTo({ top: 0, behavior: "smooth" }); return false;
      }
      S.dirty = false; $("#cfg-errors").innerHTML = "";
      $("#save-state").innerHTML = `<span class="text-sm font-bold text-emerald-700 flex items-center gap-1.5">${icon("check_circle", "text-base")}<span>Saved</span></span>`;
      $("#save-note").textContent = "The scheduler is using these settings."; toast("Settings saved"); refreshOverview(); return true;
    } catch (e) { toast(e.message, true); return false; }
  }
  const syncApp = id => {   // the left card and banner follow the on/off switch
    const on = $(`[data-appon="${id}"]`)?.checked; if (on === undefined) return;
    const st = $(`[data-app-state="${id}"]`); if (st) st.textContent = on ? "Active schedule" : "Switched off";
    const pl = $(`[data-pause-label="${id}"]`); if (pl) pl.textContent = on ? "Pause App" : "Resume App";
    const dot = $(`[data-app-pick="${id}"] .rounded-full.w-2`); if (dot) dot.className = `w-2 h-2 rounded-full ${on ? "bg-emerald-500" : "bg-slate-300"}`;
  };
  const showTab = () => {
    document.querySelectorAll("[data-spanel]").forEach(p => p.classList.toggle("hidden", p.dataset.spanel !== T.tab));
    document.querySelectorAll("[data-appsec]").forEach(p => p.classList.toggle("hidden", p.dataset.appsec !== T.app));
    $("#st-head").innerHTML = headerHtml();
  };

  /* ---------- render ---------- */
  async function render() {
    const [{ config }, { agents }, planInfo] = await Promise.all([api("/api/config"), api("/api/agents"), api("/api/plan")]);
    S.config = config; S.ideaUse = planInfo.ideas; const c = config;
    T.app = PLATFORM_IDS.includes(S.platform) ? S.platform : "linkedin"; T.tab = "apps"; T.voicesLoaded = false;
    const active = PLATFORM_IDS.filter(enabledOf).length;
    $("#view").innerHTML = `<div data-st class="pb-24"><div id="st-head"></div>
      <div class="max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8"><div id="cfg-errors"></div>
        <datalist id="tzs">${(Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : []).map(z => `<option value="${esc(z)}">`).join("")}</datalist>
        <div data-spanel="apps" class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          <aside class="lg:col-span-4 space-y-4"><div class="flex items-center justify-between px-1"><div class="flex items-center gap-2">${icon("apps", "text-slate-600 text-base")}<h2 class="text-sm font-bold uppercase tracking-wider text-slate-600 font-headline">Connected Apps</h2></div>
            <span class="text-xs text-slate-600 font-medium">${active} Active</span></div><div class="space-y-3">${appCards(c)}</div>${summaryCard()}</aside>
          <section class="lg:col-span-8 space-y-6">${PLATFORM_IDS.map(id => appSection(c, id)).join("")}</section></div>
        <div data-spanel="brand" class="hidden">${brandPanel(c)}</div>
        <div data-spanel="quality" class="hidden">${qualityPanel(c, agents)}</div></div>
      <aside aria-label="Unsaved changes bar" class="fixed bottom-0 inset-x-0 bg-white/95 backdrop-blur-md border-t border-slate-200 shadow-xl z-40 py-3.5 px-6"><div class="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
        <div class="flex items-center gap-2.5"><div class="w-8 h-8 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center shrink-0">${icon("pending", "text-lg")}</div>
          <div><div id="save-state"><span class="text-sm font-bold text-slate-700">No changes</span></div><p class="text-[11px] text-slate-400" id="save-note">Changes apply to the scheduler once saved.</p></div></div>
        <div class="flex items-center gap-3 w-full sm:w-auto justify-end"><button class="px-4 py-2 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors" type="button" id="reset">Discard changes</button>
          <button class="inline-flex items-center gap-2 px-5 py-2 text-xs font-semibold rounded-lg bg-violet-600 hover:bg-violet-700 text-white shadow-sm shadow-violet-200 transition-all active:scale-95" type="button" id="save">${icon("save", "text-sm")}<span>Save settings</span></button></div></div></aside></div>`;
    $("#st-head").innerHTML = headerHtml();
    PLATFORM_IDS.forEach(id => drawTopics(id)); PLATFORM_IDS.forEach(id => drawDays(id)); drawAll(); showTab(); ytInit();

    const view = $("#view"), mine = e => S.tab === "settings" && e.target.closest("[data-st]");
    view.oninput = e => { if (!mine(e)) return; dirty(); if (e.target.id === "yt-secs") ytLabel(); if (e.target.dataset.c === "label") { PLATFORM_IDS.forEach(id => drawDays(id)); } drawAll(); };
    view.onchange = e => {
      if (!mine(e)) return; const t = e.target;
      if (t.dataset.daychk) {   // a day chip on/off: the topic menu is the truth ("" = no post)
        const id = t.closest("[data-days]").dataset.days, d = t.dataset.daychk, sl = $(`[data-k="${K(id, `schedule.days.${d}`)}"]`), names = Object.keys(topicNames(id));
        if (!t.checked && sl?.value) T.prev[`${id}${d}`] = sl.value;
        drawDays(id, { [d]: t.checked ? (T.prev[`${id}${d}`] in topicNames(id) ? T.prev[`${id}${d}`] : names[0] || "") : "" });
      } else if (t.dataset.dayval) drawDays(t.closest("[data-days]").dataset.days);
      if (t.dataset.appon) syncApp(t.dataset.appon);
      if (t.id === "yt-voice") $("#yt-voice-name").value = t.value ? t.selectedOptions[0].text.replace(/ \([^)]*\)$/, "") : "";
      if (t.id === "yt-renderer") $("#yt-mcp").classList.toggle("hidden", t.value !== "mcp");
      dirty(); drawAll();
    };
    view.onclick = async e => {
      if (!mine(e)) return; const t = e.target, hit = q => t.closest(q);
      if (hit("[data-sw]")) return;
      let x;
      if ((x = hit("[data-stab]"))) { e.preventDefault(); T.tab = x.dataset.stab; showTab(); window.scrollTo({ top: 0 }); return; }
      if ((x = hit("[data-app-pick]"))) { T.app = x.dataset.appPick; redrawApps(); return; }
      if ((x = hit("[data-pause]"))) { const sw1 = $(`[data-appon="${x.dataset.pause}"]`); sw1.checked = !sw1.checked; syncApp(x.dataset.pause); dirty(); return; }
      if ((x = hit("[data-freq]"))) { const [id, v] = x.dataset.freq.split("|"); $(`[data-k="${K(id, "schedule.frequency")}"]`).value = v; $(`[data-freqbox="${id}"]`).innerHTML = freqCards(id, v);
        $(`[data-everyn="${id}"]`).classList.toggle("hidden", v !== "every_n_days"); dirty(); drawAll(); return; }
      if ((x = hit("[data-appr]"))) { const [id, v] = x.dataset.appr.split("|"); $(`[data-k="${K(id, "publishing.approval")}"]`).value = v; $(`[data-apprbox="${id}"]`).innerHTML = approvalCards(id, v); dirty(); return; }
      if ((x = hit("[data-calnav]"))) { const m = T.month; const dt = new Date(Date.UTC(m.y, m.m + +x.dataset.calnav, 1)); T.month = { y: dt.getUTCFullYear(), m: dt.getUTCMonth() }; drawAll(); return; }
      if ((x = hit("[data-caldate]"))) {
        const id = x.closest("[data-cal]").dataset.cal, ta = $(`[data-dates="${K(id, "schedule.dates")}"]`), iso = x.dataset.caldate;
        const lines = ta.value.split("\n").filter(l => l.trim()), i = lines.findIndex(l => l.split("|")[0].trim() === iso);
        if (i >= 0) lines.splice(i, 1); else lines.push(iso);
        ta.value = lines.join("\n"); dirty(); drawAll(); return;
      }
      if ((x = hit("[data-plan]"))) { const [id, rp] = x.dataset.plan.split("|"); await planFrom(id, rp === "1"); return; }
      if ((x = hit("[data-addtopic]"))) return addTopic(x.dataset.addtopic);
      if ((x = hit("[data-testapi]"))) return testApi(x.dataset.testapi, x);
      if ((x = hit("[data-vtype]"))) return ytType(x.dataset.vtype);
      if (hit("#yt-play")) return ytPlay();
      if (hit("#test-notify")) { await post("/api/notifications/test"); toast("Sent"); refreshOverview(); return; }
      if (hit("#reset")) { S.dirty = false; render(); return; }
      if (hit("#save")) await saveSettings();
    };
    $("#view").onkeydown = e => { if (e.key === "Enter" && e.target.dataset.newtopic && mine(e)) { e.preventDefault(); addTopic(e.target.dataset.newtopic); } };

    function redrawApps() {   // only the card column and the visible section change
      const kept = {}; PLATFORM_IDS.forEach(id => kept[id] = $(`[data-appon="${id}"]`)?.checked);
      $("[data-spanel='apps'] aside .space-y-3").innerHTML = appCards(S.config);
      document.querySelectorAll("[data-appsec]").forEach(p => p.classList.toggle("hidden", p.dataset.appsec !== T.app)); ytInit();
      // the cards were rebuilt: restore their switches from the form state kept in the config copy
      PLATFORM_IDS.forEach(id => { const el = $(`[data-appon="${id}"]`); if (el) el.checked = !!kept[id]; syncApp(id); });
    }
    async function planFrom(id, replan) {
      if (!(await saveSettings())) return;
      const btns = document.querySelectorAll("[data-plan]"), state = $(`[data-plan-state="${id}"]`);
      btns.forEach(b => b.disabled = true); state.textContent = "The Week Planner is working (about a minute)…";
      try { await post("/api/plan/fill", { replan, platform: id }); toast("Plan updated"); location.hash = "plan"; }
      catch (e) { toast(e.message, true); btns.forEach(b => b.disabled = false); state.textContent = e.message; }
    }
    function addTopic(app = "linkedin") {
      const inpEl = $(`[data-newtopic="${app}"]`), name = inpEl.value.trim(); if (!name) return inpEl.focus();
      collectSettings();
      let id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 28) || "topic";
      const cats = app === "linkedin" ? S.config.categories : (own(app).categories ??= {});
      for (let n = 2; cats[id]; n++) id = id.replace(/-\d+$/, "") + "-" + n;
      cats[id] = { label: name, media: app === "youtube" ? "video" : "auto", research: "optional", fact_check: false, ideas: [], context: "", plan_context: "",
        brief: app === "youtube" ? `A useful video about ${name}: a hook, the key points a viewer can act on, and a closing question.` : `A useful post about ${name}: a hook, the key points a reader can act on, a question, and 3-4 hashtags.` };
      inpEl.value = ""; drawTopics(app); drawDays(app); drawAll(); dirty();
      $(`#topics-${app} [data-cat="${id}"] [data-c="ideas"]`)?.focus();
    }
  }
  return render;
})();

async function renderSettings() { return settingsView(); }
VIEWS.settings = renderSettings;
