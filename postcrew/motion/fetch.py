"""Fetching a reference video from a URL, with yt-dlp (https://github.com/yt-dlp/yt-dlp), only after you declared your right to use it.

    pip install yt-dlp          # in Postcrew's environment; or any yt-dlp on the PATH

What is fetched depends on what you asked to analyse: the screens need the video (at most 720p, enough to judge layout and motion);
the script needs only the words, which come from the video's subtitles (its own, else automatic captions) when it has them, so a
script-only analysis downloads no video at all. Nothing is fetched for a video longer than library.MAX_SECONDS.
"""
import re
import shutil
import subprocess
from pathlib import Path

from .library import MAX_SECONDS


class FetchError(RuntimeError):
    pass


def available():
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return bool(shutil.which("yt-dlp"))


def _opts(dest, video, subs):
    o = {"outtmpl": str(Path(dest) / "source.%(ext)s"), "quiet": True, "no_warnings": True, "noplaylist": True,
         "restrictfilenames": True, "socket_timeout": 30}
    if video:
        o.update(format="bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b[height<=720]/b",
                 merge_output_format="mp4")
    else:
        o["skip_download"] = True
    if subs:
        o.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=["en", "en-US", "en-GB", "en.*"], subtitlesformat="vtt")
    return o


def fetch(url, dest, video=True, subs=True, log=print):
    """Download into `dest`. Returns {"title", "creator", "seconds", "video": path or None, "transcript": text or ""}."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        import yt_dlp
    except ImportError:
        yt_dlp = None
    if yt_dlp is None and not shutil.which("yt-dlp"):
        raise FetchError("fetching a URL needs yt-dlp: run `pip install yt-dlp` in Postcrew's environment, or upload the file instead")
    if yt_dlp:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as y:
                info = y.extract_info(url, download=False)
        except Exception as e:
            raise FetchError(f"could not read {url}: {str(e)[-300:]}")
        seconds = float(info.get("duration") or 0)
        if seconds > MAX_SECONDS:
            raise FetchError(f"the video is {seconds:.0f}s long: references are at most {MAX_SECONDS}s (a Short or one explainer)")
        log(f"downloading {'the video and ' if video else ''}its subtitles")
        try:
            with yt_dlp.YoutubeDL(_opts(dest, video, subs)) as y:
                y.download([url])
        except Exception as e:
            raise FetchError(f"download failed: {str(e)[-300:]}")
    else:
        r = subprocess.run(["yt-dlp", "--dump-single-json", "--no-playlist", url], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise FetchError(f"could not read {url}: {r.stderr.strip()[-300:]}")
        import json
        info = json.loads(r.stdout)
        seconds = float(info.get("duration") or 0)
        if seconds > MAX_SECONDS:
            raise FetchError(f"the video is {seconds:.0f}s long: references are at most {MAX_SECONDS}s")
        cmd = ["yt-dlp", "--no-playlist", "-o", str(dest / "source.%(ext)s")]
        cmd += (["-f", _opts(dest, True, False)["format"], "--merge-output-format", "mp4"] if video else ["--skip-download"])
        if subs:
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "en,en-US,en-GB,en.*", "--sub-format", "vtt"]
        log(f"downloading {'the video and ' if video else ''}its subtitles")
        r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise FetchError(f"download failed: {r.stderr.strip()[-300:]}")
    vids = [p for p in dest.glob("source.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".m4v")]
    if video and not vids:
        raise FetchError("the download finished but left no video file")
    subs_files = sorted(dest.glob("source*.vtt"), key=lambda p: (".en." not in p.name, len(p.name)))
    text = vtt_text(subs_files[0].read_text(errors="replace")) if subs_files else ""
    for f in subs_files:
        f.unlink()
    return {"title": info.get("title") or "", "creator": info.get("channel") or info.get("uploader") or "", "seconds": seconds,
            "video": str(vids[0]) if vids else None, "transcript": text}


def vtt_text(vtt):
    """Plain text from a WebVTT file. Automatic captions repeat each line as it scrolls: the repeats are dropped."""
    out = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and (not out or line != out[-1]) and not (out and out[-1].endswith(line)):
            out.append(line)
    return " ".join(out)
