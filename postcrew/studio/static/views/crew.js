/* Crew: every agent, the research and writing teams, former members and long-term memory.
   No Stitch screen: built from the shell, design.md and the same components (cards, sectionHead, chips, tables). */
"use strict";

const CREW_ROLE = { research: "Researchers", writer: "Writers" };
const CREW_BTN_DANGER = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-semibold border border-rose-200 transition-colors disabled:opacity-50";
const CREW_BTN_SMALL = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold border border-slate-300 transition-colors";

async function renderTeam() {
  const view = $("#view");
  view.innerHTML = `<div class="max-w-7xl mx-auto px-6 py-8">${emptyState("progress_activity", "Loading the crew...")}</div>`;
  let d, memory;
  try { [d, { memory }] = await Promise.all([api("/api/team"), api("/api/memory"), loadAgents()]); }
  catch (e) { view.innerHTML = `<div class="max-w-7xl mx-auto px-6 py-8">${errorBanner(e.message)}</div>`; return; }

  const dots = m => m.window.map(g => `<span class="w-2.5 h-2.5 rounded-full ${g ? "bg-emerald-500" : "bg-rose-500"}" title="${g ? "good" : "bad"}"></span>`).join("")
    || `<span class="text-xs text-slate-400">no posts yet</span>`;
  const member = m => {
    const s = m.stats, last = m.recent.at(-1);
    return `<div class="rounded-xl border border-slate-200 p-4 ${m.working ? "bg-white" : "bg-slate-50 border-dashed"}">
      <div class="flex items-center gap-3 flex-wrap">${avatar(m.role === "research" ? "research" : "writer")}
        <span class="font-bold text-slate-900">${esc(m.name)}</span>${chip(m.working ? "working" : "idle", m.working ? "Working" : "On the bench", "sm")}
        ${m.at_risk ? chip("warning", "At risk", "sm") : ""}<span class="flex-1"></span>
        <button class="${CREW_BTN_DANGER}" data-fire="${esc(m.id)}" data-name="${esc(m.name)}">${icon("swap_horiz", "text-sm")}<span>Replace</span></button></div>
      <p class="text-sm text-slate-600 mt-3">${esc(m.persona)}</p>
      <div class="flex items-center gap-1.5 mt-3 text-xs text-slate-500"><span>Last ${d.rules.fire_window} posts:</span>${dots(m)}</div>
      <div class="text-xs text-slate-500 mt-1.5">${s.tries} post(s) · ${s.good} good${m.role === "writer" ? ` · chosen ${s.chosen}× · Editor passed ${s.editor_passed}, failed ${s.editor_failed}` : ""}${m.model ? ` · model ${esc(m.model)}` : ""} · joined ${esc(fmtTime(m.hired_at))}</div>
      ${last && !last.good && last.problems?.length ? `<div class="flex items-start gap-1.5 text-xs text-rose-700 mt-2">${icon("error", "text-sm text-rose-600")}<span>Last problem: ${esc(last.problems[0].slice(0, 180))}</span></div>` : ""}</div>`;
  };
  const agentCard = a => `<div class="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4">${avatar(a.id, "w-10 h-10")}<div class="min-w-0">
      <div class="font-bold text-slate-900">${esc(agentName(a.id))}</div><div class="text-xs font-semibold text-slate-500">${esc(a.title)}</div>
      <p class="text-sm text-slate-600 mt-1.5">${esc(a.role)}</p>
      <p class="text-[11px] text-slate-400 mt-1.5 font-mono">${a.llm ? esc(a.llm.model || "default model") : "no AI: rules only"}</p></div></div>`;
  const all = Object.values(S.agents || {});
  const legend = `<div class="flex flex-wrap gap-x-4 gap-y-1.5 mt-5 text-xs text-slate-600">${Object.values(TEAMS).map(([n, h1, h2]) =>
    `<span class="inline-flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full" style="background:linear-gradient(135deg,${h1},${h2})"></span>${esc(n)}</span>`).join("")}</div>`;
  const groups = Object.keys(TEAMS).map(t => {
    const xs = all.filter(a => (AGENTS[a.id]?.[1] || "ops") === t);
    return xs.length ? `<div class="mt-5"><h3 class="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">${esc(TEAMS[t][0])}</h3>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">${xs.map(agentCard).join("")}</div></div>` : "";
  }).join("");

  const memRows = Object.entries(memory).flatMap(([step, rows]) => rows.map((r, i) => ({ step, i, ...r }))).reverse();
  const memHtml = memRows.length ? `<div class="space-y-3 mt-5">${memRows.map(r => `<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div class="flex items-center gap-2">${avatar(r.step, "w-7 h-7")}<span class="text-sm font-semibold text-slate-900">${esc(agentName(r.step))}</span>
        <span class="text-xs text-slate-500">${esc(fmtTime(r.at))}</span><span class="flex-1"></span>
        <button class="${CREW_BTN_SMALL}" data-forget="${esc(r.step)}:${r.i}">${icon("delete", "text-sm")}<span>Forget</span></button></div>
      <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mt-3">Problem</div><p class="text-sm text-slate-800 mt-0.5">${esc(r.problem)}</p>
      ${r.fix?.length ? `<div class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mt-3">What fixed it</div><ul class="list-disc pl-5 text-sm text-slate-800 mt-0.5 space-y-0.5">${r.fix.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`).join("")}</div>`
    : emptyState("psychology", "Nothing yet. When an agent's work is sent back and then fixed, the crew remembers the problem and the fix.");

  const teamCard = r => card(`<div class="p-6">
      <div class="flex items-start gap-3 flex-wrap">${sectionHead(r === "research" ? "search" : "edit_note", CREW_ROLE[r], `${d.size[r]} work on each post`, r === "research" ? "teal" : "orange")}
        <span class="flex-1"></span>${button("secondary", "person_add", "Hire another", `data-hire="${r}"`)}</div>
      <div class="grid gap-3 md:grid-cols-2 mt-5">${d.members.filter(m => m.role === r).map(member).join("")}</div>
      <h3 class="flex items-center gap-2 text-sm font-bold text-slate-900 mt-6">${icon("menu_book", "text-violet-600")}Lessons every ${r === "research" ? "researcher" : "writer"} follows</h3>
      ${(d.lessons[r] || []).length ? `<ul class="mt-2 divide-y divide-slate-100">${d.lessons[r].map((l, i) => `<li class="flex items-start gap-3 py-2"><span class="flex-1 text-sm text-slate-700">${esc(l)}</span>
        <button class="${CREW_BTN_SMALL}" data-lesson="${r}:${i}">${icon("close", "text-sm")}<span>Remove</span></button></li>`).join("")}</ul>`
        : `<p class="text-sm text-slate-500 mt-2">None yet. When a member is replaced, the team writes down what went wrong.</p>`}</div>`);

  const fired = d.fired.length ? `<div class="overflow-x-auto mt-5"><table class="w-full text-left text-sm border-collapse"><thead><tr class="bg-slate-50/80 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
      <th class="py-3 px-4" scope="col">Name</th><th class="py-3 px-4" scope="col">Role</th><th class="py-3 px-4" scope="col">Left</th><th class="py-3 px-4" scope="col">Why</th><th class="py-3 px-4" scope="col">Lessons they left</th></tr></thead>
      <tbody class="divide-y divide-slate-100">${d.fired.map(f => `<tr class="hover:bg-slate-50/60"><td class="py-3 px-4 font-semibold text-slate-900">${esc(f.name)}</td><td class="py-3 px-4 text-slate-600">${esc(f.role)}</td>
        <td class="py-3 px-4 text-slate-600">${esc(fmtTime(f.fired_at))}</td><td class="py-3 px-4 text-slate-600">${esc(f.reason)}</td>
        <td class="py-3 px-4 text-slate-600">${(f.lessons || []).map(esc).join("<br>")}</td></tr>`).join("")}</tbody></table></div>`
    : emptyState("groups", "Nobody has been replaced.");

  view.innerHTML = `<div class="max-w-7xl mx-auto px-6 py-8 space-y-6">
    <div><h1 class="text-2xl font-bold font-headline text-slate-900 tracking-tight flex items-center gap-2.5">${icon("groups", "text-violet-600")}<span>Crew</span></h1>
      <p class="text-xs text-slate-500 mt-1">Every agent, its name and its job. Orion, the Supervisor, checks each step and sends work back with the reasons it failed.</p></div>
    ${card(`<div class="p-6">${sectionHead("hub", "The crew", "Who does what, grouped by team.")}${legend}${groups}</div>`)}
    <div><h2 class="font-headline font-bold text-lg text-slate-900">Research and writing teams</h2>
      <p class="text-sm text-slate-500 mt-0.5 max-w-3xl">Several researchers and writers work on every post. Researchers' verified sources are combined; writers compete, ${d.rules.pre_review ? "every draft is pre-reviewed and the best is polished, " : ""}and only the best goes to the Editor.
      A member is replaced automatically when fewer than ${Math.round(d.rules.fire_min_success * 100)}% of their last ${d.rules.fire_window} posts were good; the new hire learns from the mistakes.</p></div>
    ${["research", "writer"].map(teamCard).join("")}
    ${card(`<div class="p-6">${sectionHead("history", "Former members", "Everyone who was replaced, and what they taught the team.", "slate")}${fired}</div>`)}
    ${card(`<div class="p-6">${sectionHead("psychology", "Long-term memory", "Problems the crew fixed in earlier runs. The 3 most recent for each step are given to that agent at the start of every run.", "indigo")}${memHtml}</div>`)}</div>`;

  const act = async (path, body, msg) => { try { await post(path, body); toast(msg); } catch (e) { toast(e.message, true); } renderTeam(); };
  view.querySelectorAll("[data-fire]").forEach(b => b.onclick = () => {
    if (!confirm(`Replace ${b.dataset.name}? A new member is hired with lessons from ${b.dataset.name}'s mistakes.`)) return;
    b.disabled = true; act("/api/team/fire", { id: b.dataset.fire }, `${b.dataset.name} was replaced`);
  });
  view.querySelectorAll("[data-forget]").forEach(b => b.onclick = () => {
    const [step, index] = b.dataset.forget.split(":"); act("/api/memory/forget", { step, index: +index }, "Forgotten");
  });
  view.querySelectorAll("[data-hire]").forEach(b => b.onclick = () => act("/api/team/hire", { role: b.dataset.hire }, "Hired"));
  view.querySelectorAll("[data-lesson]").forEach(b => b.onclick = () => {
    const [role, index] = b.dataset.lesson.split(":"); act("/api/team/lesson-remove", { role, index: +index }, "Lesson removed");
  });
}
VIEWS.team = renderTeam;
