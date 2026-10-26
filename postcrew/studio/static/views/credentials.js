/* Credentials: connected apps (LinkedIn today), the AI provider, and notification channels (Gmail, Telegram).
   No Stitch screen: built from the shell, design.md and the Settings > Connected apps components.
   Secrets are never read back: the server only says whether one is saved. */
"use strict";

const CRED_INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-violet-500 focus:ring-1 focus:ring-violet-500";
const CRED_DANGER = "inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-rose-50 hover:bg-rose-100 text-rose-700 text-sm font-semibold border border-rose-200 transition-colors disabled:opacity-50";
const CRED_MONO = "font-mono text-xs bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded";
const CRED_LINK = "text-violet-700 font-medium hover:underline";

async function renderCredentials() {
  const view = $("#view");
  let d, cfg;
  try { [d, { config: cfg }] = await Promise.all([api("/api/credentials"), api("/api/config")]); }
  catch (e) { view.innerHTML = `<div class="max-w-7xl mx-auto px-6 py-8">${errorBanner(e.message)}</div>`; return; }
  const s = d.secrets, st = d.status || {}, li = st.linkedin || {}, cl = st.ai || st.claude || {};
  const set = v => v ? `<span class="text-[11px] font-semibold text-emerald-700">saved</span>` : `<span class="text-[11px] font-medium text-slate-400">not set</span>`;
  const field = (label, state, input) => `<label class="block"><span class="flex items-center justify-between text-xs font-semibold text-slate-700 mb-1">${label}${state}</span>${input}</label>`;
  const hint = html => `<p class="text-xs text-slate-500 mt-3">${html}</p>`;
  const a = (href, text) => `<a class="${CRED_LINK}" href="${href}" target="_blank" rel="noopener">${text}</a>`;
  const result = id => `<span class="text-xs text-slate-500" id="${id}"></span>`;
  const sub = title => `<h3 class="text-sm font-bold text-slate-900 mt-6 mb-3">${title}</h3>`;
  const aiDown = cl.backend && cl.backend !== d.backend;

  const linkedin = `<div class="bg-white rounded-2xl border border-slate-200 border-l-4 ${APPS.linkedin.border} shadow-sm p-6">
    <div class="flex items-start gap-3 flex-wrap"><div class="w-12 h-12 rounded-xl ${APPS.linkedin.dot} text-white flex items-center justify-center text-lg font-bold shrink-0">in</div>
      <div><h2 class="font-headline font-bold text-lg text-slate-900 flex items-center gap-2">LinkedIn ${appBadge("linkedin")}</h2>
        <p class="text-sm text-slate-500 mt-0.5">${esc(li.message || "Not checked yet.")}</p></div><span class="flex-1"></span>${chip(li.state || "unknown")}</div>
    ${s.linkedin_name ? `<p class="text-sm text-slate-700 mt-4">Connected as <b>${esc(s.linkedin_name)}</b>${s.linkedin_token_expires_at ? ` · token valid until <b>${esc(s.linkedin_token_expires_at.slice(0, 10))}</b>` : ""}</p>` : ""}
    <div class="flex items-center gap-2 flex-wrap mt-4"><a class="${BTN.primary}" href="/oauth/start">${icon("link")}<span>${s.linkedin_access_token ? "Reconnect LinkedIn" : "Connect LinkedIn"}</span></a>
      ${button("secondary", "sync", "Check now", 'id="check"')}${s.linkedin_access_token ? `<button class="${CRED_DANGER}" id="disconnect">${icon("link_off")}<span>Disconnect</span></button>` : ""}</div>
    ${hint(`Checked ${esc(ago(st.checked_at) || "never")}. The Credential Monitor checks daily and before every publish, and notifies you ${esc(cfg.notifications.warn_days_before_expiry)} days before the token expires.`)}
    ${sub("LinkedIn app")}
    <div class="grid gap-3 md:grid-cols-2">${field("Client ID", set(s.linkedin_client_id), `<input class="${CRED_INPUT}" id="cid" value="${esc(s.linkedin_client_id || "")}" autocomplete="off">`)}
      ${field("Client Secret", set(s.linkedin_client_secret), `<input class="${CRED_INPUT}" id="csecret" type="password" placeholder="${s.linkedin_client_secret ? "•••••••• (saved, type to replace)" : ""}" autocomplete="new-password">`)}</div>
    <div class="mt-4">${button("secondary", "save", "Save app details", 'id="save-app"')}</div>
    <details class="mt-5 rounded-xl bg-slate-50 border border-slate-200 px-4 py-3"><summary class="cursor-pointer text-sm font-semibold text-slate-800">How to create the LinkedIn app (5 minutes, free)</summary>
      <ol class="list-decimal pl-5 mt-3 space-y-1.5 text-sm text-slate-600">
      <li>Open ${a("https://www.linkedin.com/developers/apps", "linkedin.com/developers/apps")} and click <b>Create app</b>. It must be linked to a LinkedIn Page; create a free one if you have none.</li>
      <li>On <b>Products</b>, add <b>Share on LinkedIn</b> and <b>Sign In with LinkedIn using OpenID Connect</b>.</li>
      <li>On <b>Auth</b>, add this redirect URL exactly: <span class="${CRED_MONO}">${esc(d.redirect_uri)}</span></li>
      <li>Copy the <b>Client ID</b> and <b>Client Secret</b> from the Auth tab into the fields above and save.</li>
      <li>Click <b>Connect LinkedIn</b>, sign in and allow. Scopes requested: <span class="${CRED_MONO}">${esc(d.scopes)}</span>.</li>
      <li>Tokens last about 60 days. When the monitor warns you, click <b>Reconnect LinkedIn</b>.</li></ol></details></div>`;

  const yt = st.youtube || {}, DOCS = "https://github.com/sudip1205/social-postcrew/blob/main/docs/";
  const ytReady = s.youtube_client_id && s.youtube_client_secret, ytConn = s.youtube_refresh_token;
  const youtube = `<div class="bg-white rounded-2xl border border-slate-200 border-l-4 ${APPS.youtube.border} shadow-sm p-6">
    <div class="flex items-start gap-3 flex-wrap"><div class="w-12 h-12 rounded-xl ${APPS.youtube.dot} text-white flex items-center justify-center shrink-0">${icon("smart_display", "text-2xl")}</div>
      <div><h2 class="font-headline font-bold text-lg text-slate-900 flex items-center gap-2">YouTube ${appBadge("youtube")}</h2>
        <p class="text-sm text-slate-500 mt-0.5">${esc(yt.message || "Not checked yet.")}</p></div><span class="flex-1"></span>${chip(yt.state || "unknown")}</div>
    ${ytConn && (s.youtube_channel_title || yt.name) ? `<p class="text-sm text-slate-700 mt-4">Connected channel: <b>${esc(s.youtube_channel_title || yt.name)}</b></p>` : ""}
    <div class="flex items-center gap-2 flex-wrap mt-4">${ytReady ? `<a class="${BTN.primary}" href="/oauth/youtube/start">${icon("link")}<span>${ytConn ? "Reconnect YouTube" : "Connect YouTube"}</span></a>`
        : button("primary", "link", "Connect YouTube", 'disabled title="Save the client ID and secret first"')}
      ${button("secondary", "sync", "Check connection", 'id="yt-check"')}${ytConn ? `<button class="${CRED_DANGER}" id="yt-disconnect">${icon("link_off")}<span>Disconnect</span></button>` : ""}</div>
    ${sub("Google OAuth client")}
    <div class="grid gap-3 md:grid-cols-2">${field("Client ID", set(s.youtube_client_id), `<input class="${CRED_INPUT}" id="yt-cid" value="${esc(s.youtube_client_id || "")}" autocomplete="off">`)}
      ${field("Client secret", set(s.youtube_client_secret), `<input class="${CRED_INPUT}" id="yt-csecret" type="password" placeholder="${s.youtube_client_secret ? "•••••••• (saved, type to replace)" : ""}" autocomplete="new-password">`)}</div>
    <div class="mt-4">${button("secondary", "save", "Save app details", 'id="yt-save"')}</div>
    <details class="mt-5 rounded-xl bg-slate-50 border border-slate-200 px-4 py-3"><summary class="cursor-pointer text-sm font-semibold text-slate-800">How to connect a YouTube channel (10 minutes, free)</summary>
      <ol class="list-decimal pl-5 mt-3 space-y-1.5 text-sm text-slate-600">
      <li>Create a project in the ${a("https://console.cloud.google.com/projectcreate", "Google Cloud console")}.</li>
      <li>Open <b>APIs &amp; Services &gt; Library</b> and enable <b>YouTube Data API v3</b>.</li>
      <li>Set up the <b>OAuth consent screen</b> (External, add yourself as a test user), then create an <b>OAuth client ID</b> of type <b>Web application</b>.</li>
      <li>Add this authorised redirect URI exactly: <span class="${CRED_MONO}">${esc(window.location.origin + "/oauth/youtube/callback")}</span></li>
      <li>Paste the client ID and secret above, save, then click <b>Connect YouTube</b> and allow access.</li>
      <li>Good to know: an app Google has not verified uploads videos as <b>private</b>, and the default quota allows about 6 uploads a day. See ${a(DOCS + "youtube-setup.md", "the YouTube setup guide")}.</li></ol></details></div>`;

  const el = st.elevenlabs || {};
  const eleven = `<div class="bg-white rounded-2xl border border-slate-200 border-l-4 border-l-violet-500 shadow-sm p-6">
    <div class="flex items-start gap-3 flex-wrap">${sectionHead("record_voice_over", "ElevenLabs voice", el.message || "The AI narrator for YouTube videos. Not checked yet.", "violet")}<span class="flex-1"></span>${chip(el.state || "unknown")}</div>
    <div class="grid gap-3 md:grid-cols-[1fr_auto] items-end mt-5">${field("API key", set(s.elevenlabs_api_key), `<input class="${CRED_INPUT}" id="el-key" type="password" placeholder="${s.elevenlabs_api_key ? "•••••••• (saved, type to replace)" : "paste your ElevenLabs API key"}" autocomplete="new-password">`)}
      <div class="flex gap-2 flex-wrap">${button("secondary", "save", "Save", 'id="el-save"')}${button("secondary", "bolt", "Test key", 'id="el-test"')}${s.elevenlabs_api_key ? `<button class="${CRED_DANGER}" id="el-del">${icon("delete")}<span>Remove</span></button>` : ""}</div></div>
    <div class="mt-3">${result("el-result")}${el.characters_left != null ? `<span class="text-xs text-slate-500">${esc(Number(el.characters_left).toLocaleString())} characters left this month.</span>` : ""}</div>
    ${hint(`Create a key at ${a("https://elevenlabs.io/app/settings/api-keys", "elevenlabs.io/app/settings/api-keys")} (it needs access to text to speech and voices). Stored only in <span class="${CRED_MONO}">workspace/secrets.json</span>.`)}</div>`;

  const keyInfo = { anthropic: ["anthropic_api_key", "Anthropic API key", "sk-ant-...", "https://console.anthropic.com/settings/keys"],
    openai: ["openai_api_key", "OpenAI API key", "sk-...", "https://platform.openai.com/api-keys"], "openai-compatible": ["llm_api_key", "API key (optional)", "", ""] }[d.backend];
  const keyForm = keyInfo ? `<div class="grid gap-3 md:grid-cols-[1fr_auto] items-end mt-5">
      ${field(keyInfo[1], set(s[keyInfo[0]]), `<input class="${CRED_INPUT}" id="ai-key" type="password" placeholder="${s[keyInfo[0]] ? "•••••••• (saved, type to replace)" : keyInfo[2]}" autocomplete="new-password">`)}
      <div class="flex gap-2">${button("secondary", "save", "Save key", `id="save-ai" data-k="${keyInfo[0]}"`)}${s[keyInfo[0]] ? `<button class="${CRED_DANGER}" id="del-ai" data-k="${keyInfo[0]}">${icon("delete")}<span>Remove</span></button>` : ""}</div></div>
      ${keyInfo[3] ? hint(`Create one at ${a(keyInfo[3], keyInfo[3].replace("https://", ""))}. Stored only in <span class="${CRED_MONO}">workspace/secrets.json</span>.`) : ""}` : "";
  const aiNote = d.backend === "claude-code" ? `Uses your Claude Pro / Max / Team plan. Not logged in? Run <span class="${CRED_MONO}">claude</span> once in a terminal and log in. No API key is needed.`
    : d.backend === "demo" ? "Scripted answers for trying Postcrew: no AI is called and it only writes one made-up AI news story."
    : d.backend === "openai-compatible" ? `Server: <span class="${CRED_MONO}">${esc(d.base_url || "not set")}</span>. The key is optional (local servers such as Ollama need none).` : "Pay-as-you-go with your own API key.";
  const ai = card(`<div class="p-6"><div class="flex items-start gap-3 flex-wrap">${sectionHead("smart_toy", `AI provider: ${PROVIDERS[d.backend] || d.backend}`,
      aiDown ? "Not checked yet: click Test." : cl.message || "Not checked yet.", "violet")}<span class="flex-1"></span>${chip(aiDown ? "unknown" : cl.state || "unknown")}</div>
    <div class="flex items-center gap-3 flex-wrap mt-4">${button("secondary", "bolt", "Test with a tiny call", 'id="test-ai"')}${result("ai-result")}</div>
    ${hint(`${aiNote} Change the provider in <a class="${CRED_LINK}" href="#settings">Settings &gt; Advanced</a>.`)}${keyForm}</div>`);

  const gmail = card(`<div class="p-6">${sectionHead("mail", "Gmail notifications (optional)", "Get styled email alerts when a run needs you.", "rose")}
    <ol class="list-decimal pl-5 mt-4 space-y-1 text-xs text-slate-600"><li>Turn on ${a("https://myaccount.google.com/signinoptions/two-step-verification", "2-Step Verification")} for the Gmail account.</li>
      <li>Create an ${a("https://myaccount.google.com/apppasswords", "App Password")} (name it "Postcrew") and paste the 16 characters below. Never use your normal Gmail password.</li></ol>
    <div class="grid gap-3 md:grid-cols-2 mt-4">${field("Gmail address", set(s.gmail_address), `<input class="${CRED_INPUT}" id="gm-addr" type="email" value="${esc(s.gmail_address || "")}" placeholder="you@gmail.com">`)}
      ${field("App password", set(s.gmail_app_password), `<input class="${CRED_INPUT}" id="gm-pass" type="password" placeholder="${s.gmail_app_password ? "•••••••• (saved)" : "16 characters"}" autocomplete="new-password">`)}
      ${field("Send to (optional)", set(s.email_to), `<input class="${CRED_INPUT}" id="gm-to" type="email" value="${esc(s.email_to || "")}" placeholder="same as the Gmail address">`)}</div>
    <div class="flex items-center gap-3 flex-wrap mt-4">${button("secondary", "save", "Save Gmail", 'id="save-gm"')}${button("secondary", "forward_to_inbox", "Send a test email", 'id="test-gm"')}${result("gm-result")}</div>
    ${hint("Turn on Gmail email in Settings &gt; Notifications after saving.")}</div>`);

  const telegram = card(`<div class="p-6">${sectionHead("chat", "Telegram notifications (optional)", "Get alerts in a Telegram chat.", "sky")}
    <div class="grid gap-3 md:grid-cols-2 mt-4">${field("Bot token", set(s.telegram_bot_token), `<input class="${CRED_INPUT}" id="tg-token" type="password" placeholder="${s.telegram_bot_token ? "•••••••• (saved)" : "from @BotFather"}" autocomplete="new-password">`)}
      ${field("Chat id", set(s.telegram_chat_id), `<input class="${CRED_INPUT}" id="tg-chat" value="${esc(s.telegram_chat_id || "")}">`)}</div>
    <div class="mt-4">${button("secondary", "save", "Save Telegram", 'id="save-tg"')}</div>
    ${hint("Turn on Telegram in Settings &gt; Notifications after saving.")}</div>`);

  view.innerHTML = `<div class="max-w-7xl mx-auto px-6 py-8 space-y-6">
    <div><h1 class="text-2xl font-bold font-headline text-slate-900 tracking-tight flex items-center gap-2.5"><span>Credentials</span>
        <span class="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200">${icon("lock", "text-xs")}<span>Write-only</span></span></h1>
      <p class="text-xs text-slate-500 mt-1">Stored only in <span class="${CRED_MONO}">workspace/secrets.json</span> (readable by you only). The browser can set them but never read them back.</p></div>
    <div><h2 class="font-headline font-bold text-lg text-slate-900 mb-3">Connected apps</h2><div class="grid gap-4 lg:grid-cols-2 items-start">${linkedin}${youtube}</div></div>
    <div><h2 class="font-headline font-bold text-lg text-slate-900 mb-3">Voice</h2><div class="grid gap-4 lg:grid-cols-2 items-start">${eleven}</div></div>
    <div class="grid gap-6 lg:grid-cols-2 items-start">${ai}<div class="space-y-6">${gmail}${telegram}</div></div></div>`;

  const save = (body, msg) => api("/api/credentials", { method: "PUT", body }).then(() => { toast(msg); renderCredentials(); }).catch(e => toast(e.message, true));
  $("#check").onclick = async () => { $("#check").disabled = true; try { await post("/api/credentials/check"); toast("Checked"); } catch (e) { toast(e.message, true); } renderCredentials(); refreshOverview(); };
  if ($("#disconnect")) $("#disconnect").onclick = async () => { if (!confirm("Remove the LinkedIn token from this computer?")) return; await post("/api/credentials/disconnect"); renderCredentials(); };
  $("#save-app").onclick = () => { const body = { linkedin_client_id: $("#cid").value.trim() }; if ($("#csecret").value) body.linkedin_client_secret = $("#csecret").value.trim(); save(body, "App details saved"); };
  $("#yt-save").onclick = () => { const body = { youtube_client_id: $("#yt-cid").value.trim() }; if ($("#yt-csecret").value) body.youtube_client_secret = $("#yt-csecret").value.trim(); save(body, "YouTube app details saved"); };
  $("#yt-check").onclick = async () => { $("#yt-check").disabled = true; try { await post("/api/credentials/check"); toast("Checked"); } catch (e) { toast(e.message, true); } renderCredentials(); refreshOverview(); };
  if ($("#yt-disconnect")) $("#yt-disconnect").onclick = async () => { if (!confirm("Disconnect the YouTube channel from this computer?")) return;
    try { await post("/api/credentials/disconnect", { app: "youtube" }); } catch (e) { toast(e.message, true); } renderCredentials(); };
  $("#el-save").onclick = () => { const v = $("#el-key").value.trim(); if (v) save({ elevenlabs_api_key: v }, "ElevenLabs key saved"); else $("#el-key").focus(); };
  if ($("#el-del")) $("#el-del").onclick = () => { if (confirm("Remove the ElevenLabs key from this computer?")) save({ elevenlabs_api_key: "" }, "Key removed"); };
  $("#el-test").onclick = async () => {
    const b = $("#el-test"); b.disabled = true; $("#el-result").textContent = "testing…";
    const r = await post("/api/credentials/test-voice").catch(e => ({ ok: false, message: e.message }));
    $("#el-result").textContent = `${r.ok ? "OK" : "Failed"}: ${r.message || ""}${r.characters_left != null ? ` (${Number(r.characters_left).toLocaleString()} characters left)` : ""}`; b.disabled = false;
  };
  $("#save-gm").onclick = () => { const body = { gmail_address: $("#gm-addr").value.trim(), email_to: $("#gm-to").value.trim() }; if ($("#gm-pass").value) body.gmail_app_password = $("#gm-pass").value.trim(); save(body, "Gmail saved"); };
  $("#test-gm").onclick = async () => {
    const b = $("#test-gm"); b.disabled = true; $("#gm-result").textContent = "sending…";
    const r = await post("/api/notifications/test-email").catch(e => ({ ok: false, error: e.message }));
    $("#gm-result").textContent = r.ok ? `Sent to ${r.to}. Check the inbox (and spam).` : `Failed: ${r.error}`; b.disabled = false;
  };
  $("#save-tg").onclick = () => { const body = { telegram_chat_id: $("#tg-chat").value.trim() }; if ($("#tg-token").value) body.telegram_bot_token = $("#tg-token").value.trim(); save(body, "Telegram saved"); };
  const saveKey = (k, v) => api("/api/credentials", { method: "PUT", body: { [k]: v } }).then(async () => {
    toast(v ? "Key saved" : "Key removed"); await post("/api/credentials/check"); renderCredentials(); refreshOverview(); }).catch(e => toast(e.message, true));
  if ($("#save-ai")) $("#save-ai").onclick = e => { const v = $("#ai-key").value.trim(); if (v) saveKey(e.currentTarget.dataset.k, v); else $("#ai-key").focus(); };
  if ($("#del-ai")) $("#del-ai").onclick = e => { if (confirm("Remove this API key from this computer?")) saveKey(e.currentTarget.dataset.k, ""); };
  $("#test-ai").onclick = async () => {
    const b = $("#test-ai"); b.disabled = true; $("#ai-result").textContent = "calling…";
    const r = await post("/api/credentials/test-ai").catch(e => ({ ok: false, error: e.message }));
    $("#ai-result").textContent = r.ok ? `OK: ${r.model} answered in ${r.seconds}s (${money(r.cost_usd)})` : `Failed: ${r.error}`; b.disabled = false;
  };
}
VIEWS.credentials = renderCredentials;
