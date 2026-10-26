# YouTube automation: shared contract

Everyone building a piece of the YouTube feature codes against this file. Change it only with the lead.

## Config (config.json)

```
platforms.youtube = {
  "enabled": false,
  "schedule": {...same keys as LinkedIn's schedule...},
  "planning": {...}, "categories": {...},
  "publishing": {"approval": "manual|auto_with_veto|immediate", "dry_run": true,
                 "visibility": "public|unlisted|private", "category_id": "28", "made_for_kids": false},
  "video": {
    "format": "short" | "long",          # default for every topic; a topic may override with its own "format"
    "target_seconds": 45,                # short: 15-60, long: 60-1800; a topic may override
    "voice": {"provider": "elevenlabs", "voice_id": "", "model": "eleven_multilingual_v2", "speed": 1.0},
    "renderer": "ffmpeg" | "mcp",
    "mcp": {"command": "", "args": [], "tool": "", "timeout_s": 600},
    "captions": true
  }
}
```
A YouTube topic (category) has: label, brief, media "video", research ("required|optional|off"), fact_check, ideas[], and optional
`format`, `target_seconds`. Plan entries may also carry `format` and `target_seconds` for one day.

## Secrets (secrets.json, write-only from the browser)
`youtube_client_id`, `youtube_client_secret`, `youtube_refresh_token`, `youtube_channel_title`, `elevenlabs_api_key`.
Visible to the browser (not secret): `youtube_client_id`, `youtube_channel_title`. Everything else: true/false "is set".

## Script (the writer's output, `ctx.outputs["writer"]`)
```
{"title": str (<=100), "description": str (<=5000), "tags": [str] (total <=500 chars), "thumbnail_text": str (<=30 chars),
 "text": str,                       # the whole voice-over, scenes' narration joined by blank lines
 "scenes": [{"layout": "title|statement|points|code", "narration": str, "on_screen": str, "items": [str], "code": str,
             "language": str, "seconds": float}]}
```
Words per second for timing: 2.5. A short is <=60 s and vertical (1080x1920); a long video is 16:9 (1920x1080).

## Queue / history post for YouTube
```
{"id": "2026-11-03-youtube-explainer", "platform": "youtube", "topic": <title>, "text": <description>,
 "media": "media/<id>.mp4", "media_kind": "video", "poster_image": "media/<id>.png" (thumbnail),
 "youtube": {"title", "description", "tags", "format", "seconds", "voice": "<voice name or 'none'>", "thumbnail_text",
             "scenes": [{"narration", "on_screen", "seconds"}], "source": {"script": "crew|own", "voice": "crew|own|none",
             "video": "crew|own"}, "video_id": null, "url": null},
 "status": queued|awaiting_approval|approved|published|failed|dry_run|vetoed, "scheduled_at", "review": {"overall", "scores"}}
```
Files under the workspace are served at `/media/<path after media/>`.

## HTTP API additions (all JSON; mutations need header X-Postcrew: 1)
- `GET /api/credentials` -> also `secrets.youtube_*`, `secrets.elevenlabs_api_key` (masked) and
  `status.youtube = {state, message, name}`, `status.elevenlabs = {state, message, characters_left}`; states as for LinkedIn
  (ok, not_connected, error, expiring...).
- `PUT /api/credentials` accepts the new secret keys (empty string removes one).
- `GET /oauth/youtube/start` (redirect to Google), `GET /oauth/youtube/callback`.
- `POST /api/credentials/disconnect` body `{"app": "linkedin"|"youtube"}`.
- `POST /api/credentials/test-voice` -> `{ok, message, characters_left}`.
- `GET /api/voices` -> `{"voices": [{"id", "name", "category", "preview_url"}]}` (400 with a message if no key).
- `POST /api/voices/sample` body `{"voice_id", "text"?}` -> `{"url": "/media/sample-<hash>.mp3"}`.
- Assets the user supplies for one video (keyed by app + date, used by the next crew run for that date):
  - `GET /api/assets/youtube/<YYYY-MM-DD>` -> `{"assets": {"script"?: A, "voice"?: A, "video"?: A}}`
  - `POST /api/assets/youtube/<date>?kind=script|voice|video&name=<file name>`: the raw file as the request body
    (Content-Type application/octet-stream). Limits: script 200 KB (.txt/.md), voice 100 MB (.mp3/.wav/.m4a), video 1 GB (.mp4/.mov).
    Returns the listing above, or 400 `{"error"}`.
  - `POST /api/assets/youtube/<date>/remove` body `{"kind": "..."}` -> the listing.
  - A = `{"name", "bytes", "checks": [{"label", "ok": bool, "detail"}], ...}` plus, for script: `"scenes": [{"narration",
    "seconds"}]`, `"words"`, `"seconds"`; for voice: `"seconds"`; for video: `"seconds"`, `"width"`, `"height"`, `"thumbnail"` (a /media/ url).
- `POST /api/runs` body may add `"format"` and `"target_seconds"` (one-off override) and `"platform": "youtube"`.
- `POST /api/queue/<id>/<action>` works for YouTube posts too (approve, veto, restore, publish_now, edit, delete).
  `edit` for YouTube takes `{"title", "description", "tags": [..], "date"}`.

## Python interfaces
```
postcrew/voice.py
  class VoiceError(RuntimeError): .kind in auth|quota|invalid|network|failed
  list_voices(api_key, opener=None) -> [{"id","name","category","preview_url"}]
  check_key(api_key, opener=None) -> {"ok": bool, "message": str, "characters_left": int|None}
  synthesize(text, voice_id, api_key, out_path, model="eleven_multilingual_v2", speed=1.0, opener=None)
      -> {"path": str, "seconds": float, "characters": int}
  cached_synthesize(root, text, voice_cfg, api_key, opener=None) -> same dict; mp3s cached in <root>/cache/voice/<sha1>.mp3
  audio_seconds(path) -> float   (ffprobe; falls back to a size-based estimate for mp3)
postcrew/youtube.py
  class YouTubeError(RuntimeError): .kind in auth|quota|invalid|network|failed, .status
  auth_url(client_id, redirect_uri, state) -> str ; exchange_code(client_id, client_secret, code, redirect_uri, opener=None)
      -> {"refresh_token", "access_token", "expires_in"}
  class YouTube(client_id, client_secret, refresh_token, opener=None):
      channel() -> {"id", "title"} ; upload(path, title, description, tags, category_id="28", privacy="private",
      publish_at=None, made_for_kids=False, progress=None) -> {"id", "url"} ; set_thumbnail(video_id, image_path)
postcrew/render/scenes.py
  FORMATS = {"short": (1080, 1920), "long": (1920, 1080)}
  draw_frame(scene, fmt, caption="", kicker="", handle="", index=0, total=1) -> PIL.Image
  split_captions(text, max_words=9) -> [str]
postcrew/render/video.py
  probe(path) -> {"seconds", "width", "height", "has_audio"}
  compose(scenes, out_path, fmt, workdir, audio=None, handle="", kicker="", captions=True, clips=None, progress=None)
      -> {"path", "seconds", "width", "height"}   # audio: list of per-scene audio files, one file for the whole video, or None
  check_video(path, fmt) -> [{"label", "ok", "detail"}]
postcrew/render/mcp_renderer.py
  class McpError(RuntimeError); class McpClient(command, args, timeout_s, env=None) (context manager)
      .list_tools() ; .call_tool(name, arguments) -> {"text": str, "content": [...]}
  render_clips(cfg_mcp, scenes, fmt, workdir) -> [clip path per scene]   # raises McpError
```
