"""Assemble a video from scenes: Pillow frames + ffmpeg (30 fps, H.264, AAC, faststart)."""
import json
import shutil
import subprocess
from pathlib import Path

from .scenes import FORMATS, draw_frame, split_captions

FPS = 30
TAIL_S = 0.6        # calm: a pause after every scene
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100"   # YouTube's usual level: a voice recording alone is far quieter
OPEN_S = 0.7        # the first scene's picture is on screen this long before the voice starts: the video never opens on a talking blank page
LEAD_S = 1.0        # the pause before the closing scene: one second of silence after the content ends
WPS = 2.5
ZOOM = 0.05
ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "veryfast", "-r", str(FPS)]


class VideoError(RuntimeError):
    pass


def _run(cmd, what):
    exe = shutil.which(cmd[0])
    if not exe:
        raise VideoError(f"{cmd[0]} is not installed or not on PATH")
    try:
        r = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, errors="replace")
    except OSError as e:
        raise VideoError(f"{what}: could not run {cmd[0]}: {e}")
    if r.returncode != 0:
        tail = " | ".join([l for l in (r.stderr or "").strip().splitlines() if l.strip()][-4:])
        raise VideoError(f"{what} failed: {tail[:600]}")
    return r.stdout


def probe(path):
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
               "ffprobe")
    try:
        info = json.loads(out)
    except ValueError:
        raise VideoError("ffprobe returned unreadable output")
    streams = info.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    secs = (info.get("format") or {}).get("duration") or v.get("duration") or 0
    try:
        secs = float(secs)
    except (TypeError, ValueError):
        secs = 0.0
    return {"seconds": secs, "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def _words(sc):
    return len(str(sc.get("narration", "")).split())


def _scene_lengths(scenes, audio):
    if isinstance(audio, (list, tuple)):
        if len(audio) != len(scenes):
            raise VideoError(f"{len(audio)} audio files for {len(scenes)} scenes")
        return [max(0.5, probe(a)["seconds"]) + TAIL_S + float(s.get("lead_s") or 0) for a, s in zip(audio, scenes)]
    if audio:
        total = probe(audio)["seconds"]
        wts = [max(1, _words(s)) for s in scenes]
        return [max(0.3, total * w / sum(wts)) for w in wts]
    out = []
    for s in scenes:
        sec = s.get("seconds")
        out.append((float(sec) if sec else max(1.0, _words(s) / WPS)) + float(s.get("lead_s") or 0))
    return out


def _frames(scene, length, fmt, wd, n, count, handle, kicker, captions):
    """Write the PNGs for one scene; return [(path, seconds)]."""
    chunks = split_captions(scene.get("narration", "")) if captions else []
    if not chunks:
        chunks = [""]
    wts = [max(1, len(c.split())) for c in chunks]
    out = []
    for k, (c, w) in enumerate(zip(chunks, wts)):
        png = Path(wd) / f"frame-{n:02d}-{k:03d}.png"
        draw_frame(scene, fmt, c, kicker, handle, n, count, reveal=(k + 1) / len(chunks)).save(png)
        out.append((png, length * w / sum(wts)))
    return out


def _segment(frames, length, fmt, out):
    w, h = FORMATS[fmt]
    lst = Path(out).with_suffix(".txt")
    lines = []
    for p, d in frames:
        lines += [f"file '{p}'", f"duration {d:.4f}"]
    lines.append(f"file '{frames[-1][0]}'")
    lst.write_text("\n".join(lines) + "\n")
    n = max(1, int(round(length * FPS)))
    vf = (f"fps={FPS},zoompan=z='1+{ZOOM}*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d=1:s={w}x{h}:fps={FPS},format=yuv420p")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", vf,
          "-frames:v", str(n), "-an"] + ENC + [str(out)], "Encoding a scene")


def _clip_segment(clip, length, fmt, out):
    w, h = FORMATS[fmt]
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0c2035,"
          f"setsar=1,fps={FPS},format=yuv420p")
    _run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(clip), "-t", f"{length:.3f}",
          "-vf", vf, "-an"] + ENC + [str(out)], "Fitting a clip")


def assemble(segs, lengths, audio, out_path, leads=None):
    """Join the scene videos and lay the voice under them: one audio file per scene, one for the whole video, or silence."""
    total = sum(lengths)
    vlist = Path(out_path).with_name(Path(out_path).stem + "-segments.txt")
    vlist.write_text("".join(f"file '{s}'\n" for s in segs))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(vlist)]
    if isinstance(audio, (list, tuple)):
        for a in audio:
            cmd += ["-i", str(a)]
        leads = leads or [0] * len(lengths)   # a scene's voice can start after a silence (the closing line)
        parts = [f"[{i + 1}:a]" + (f"adelay={int(lead * 1000)}:all=1," if lead else "") +
                 f"aformat=sample_rates=44100:channel_layouts=stereo,apad=whole_dur={ln:.3f},"
                 f"atrim=0:{ln:.3f},asetpts=N/SR/TB[a{i}]" for i, (ln, lead) in enumerate(zip(lengths, leads))]
        parts.append("".join(f"[a{i}]" for i in range(len(lengths))) + f"concat=n={len(lengths)}:v=0:a=1,{LOUDNESS}[aout]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]"]
    elif audio:
        cmd += ["-i", str(audio), "-filter_complex",
                f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,apad=whole_dur={total:.3f},{LOUDNESS}[aout]",
                "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", "-movflags", "+faststart",
            str(out_path)]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    _run(cmd, "Assembling the video")


def compose(scenes, out_path, fmt, workdir, audio=None, handle="", kicker="", captions=True, clips=None,
            progress=None):
    if fmt not in FORMATS:
        raise VideoError(f"unknown format '{fmt}'")
    scenes = list(scenes or [])
    if not scenes:
        raise VideoError("no scenes to render")
    if clips is not None and len(clips) != len(scenes):
        raise VideoError(f"{len(clips)} clips for {len(scenes)} scenes")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    w, h = FORMATS[fmt]
    lengths = _scene_lengths(scenes, audio)
    total = sum(lengths)
    segs = []
    for i, (sc, ln) in enumerate(zip(scenes, lengths)):
        seg = wd / f"seg-{i:02d}.mp4"
        if clips:
            _clip_segment(clips[i], ln, fmt, seg)
        else:
            fr = _frames(sc, ln, fmt, wd, i, len(scenes), handle, kicker, captions)
            _segment(fr, ln, fmt, seg)
        segs.append(seg)
        if progress:
            progress(i + 1, len(scenes))
    assemble(segs, lengths, audio, out_path)
    info = probe(out_path)
    return {"path": str(out_path), "seconds": info["seconds"], "width": info["width"], "height": info["height"]}


def check_video(path, fmt):
    out = []
    try:
        info = probe(path)
    except (VideoError, OSError) as e:
        return [{"label": "Readable video", "ok": False, "detail": str(e)}]
    w, h, secs = info["width"], info["height"], info["seconds"]
    out.append({"label": "Readable video", "ok": bool(w and h and secs > 0),
                "detail": f"{w}x{h}, {secs:.1f} s"})
    tw, th = FORMATS.get(fmt, FORMATS["short"])
    want = tw / th
    ratio = (w / h) if h else 0
    ok = bool(h) and abs(ratio - want) / want <= 0.03
    out.append({"label": "Aspect ratio", "ok": ok,
                "detail": f"{w}x{h}" + ("" if ok else f"; a {fmt} video should be {'vertical 9:16' if th > tw else '16:9'}")})
    if fmt == "short":
        ok = 0 < secs <= 180
        det = f"{secs:.1f} s" + ("" if ok else "; Shorts must be 3 minutes or less")
    else:
        ok = 0 < secs <= 12 * 3600
        det = f"{secs:.1f} s" + ("; under a minute, fine but not a long video" if ok and secs < 60 else "")
    out.append({"label": "Duration", "ok": ok, "detail": det})
    out.append({"label": "Audio track", "ok": info["has_audio"],
                "detail": "present" if info["has_audio"] else "no audio track"})
    try:
        size = Path(path).stat().st_size
    except OSError:
        size = 0
    out.append({"label": "File size", "ok": 0 < size < 256 * 1024 ** 3, "detail": f"{size / 1e6:.1f} MB"})
    return out
