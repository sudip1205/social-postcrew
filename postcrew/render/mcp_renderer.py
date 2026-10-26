"""Minimal MCP client over stdio (newline-delimited JSON-RPC 2.0) and a per-scene clip renderer."""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL = "2024-11-05"


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, command, args=None, timeout_s=600, env=None):
        self.command, self.args = command, list(args or [])
        self.timeout_s = float(timeout_s or 600)
        self.env = env
        self.proc = None
        self._q = queue.Queue()
        self._id = 0
        self._stderr = []

    def __enter__(self):
        if not self.command:
            raise McpError("MCP renderer: no command configured")
        env = dict(os.environ)
        env.update(self.env or {})
        try:
            self.proc = subprocess.Popen([self.command] + self.args, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                         text=True, encoding="utf-8", bufsize=1)
        except (OSError, ValueError) as e:
            raise McpError(f"MCP renderer: cannot start '{self.command}': {e}")
        threading.Thread(target=self._read, args=(self.proc.stdout, True), daemon=True).start()
        threading.Thread(target=self._read, args=(self.proc.stderr, False), daemon=True).start()
        try:
            self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                         "clientInfo": {"name": "postcrew", "version": "1.0"}})
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        p, self.proc = self.proc, None
        if p is None:
            return
        try:
            p.stdin.close()
        except Exception:
            pass
        if p.poll() is None:
            p.kill()
        try:
            p.wait(timeout=5)
        except Exception:
            pass

    def _read(self, stream, is_out):
        try:
            for line in stream:
                if is_out:
                    self._q.put(line)
                else:
                    self._stderr.append(line.rstrip())
        except Exception:
            pass
        if is_out:
            self._q.put(None)

    def _send(self, msg):
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            raise McpError("MCP renderer: the process closed its input" + self._tail())

    def _tail(self):
        t = " | ".join(self._stderr[-3:])
        return f" ({t[:300]})" if t else ""

    def _request(self, method, params=None):
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout_s
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.close()
                raise McpError(f"MCP renderer: '{method}' timed out after {self.timeout_s:g}s")
            try:
                line = self._q.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                raise McpError("MCP renderer: the process exited" + self._tail())
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # stray non-JSON output
            if not isinstance(msg, dict) or msg.get("id") != rid or "method" in msg:
                continue
            if "error" in msg:
                err = msg["error"] or {}
                raise McpError(f"MCP renderer: {method} failed: {err.get('message', err)}")
            return msg.get("result") or {}

    def list_tools(self):
        return self._request("tools/list").get("tools", [])

    def call_tool(self, name, arguments=None):
        res = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        content = res.get("content") or []
        text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if res.get("isError"):
            raise McpError(f"MCP renderer: tool '{name}' returned an error: {text[:400] or 'no details'}")
        return {"text": text, "content": content}


def render_clips(cfg_mcp, scenes, fmt, workdir, progress=None):
    from .scenes import FORMATS
    cfg = cfg_mcp or {}
    tool = cfg.get("tool")
    if not cfg.get("command") or not tool:
        raise McpError("MCP renderer: set both a command and a tool name in the video settings")
    w, h = FORMATS.get(fmt, FORMATS["short"])
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    clips = []
    with McpClient(cfg["command"], cfg.get("args") or [], cfg.get("timeout_s") or 600) as c:
        for i, sc in enumerate(scenes, 1):
            out = wd / f"clip-{i:02d}.mp4"
            words = len(str(sc.get("narration", "")).split())
            secs = float(sc.get("seconds") or max(2.0, words / 2.5))
            res = c.call_tool(tool, {"scene": sc, "format": fmt, "width": w, "height": h,
                                     "seconds": secs, "output_path": str(out)})
            path = out
            if not out.exists():
                for tok in res["text"].replace("\n", " ").split():
                    tok = tok.strip("\"'`,;()")
                    if tok.lower().endswith(".mp4") and Path(tok).exists():
                        path = Path(tok)
                        break
            if not path.exists() or path.stat().st_size == 0:
                raise McpError(f"MCP renderer: scene {i} produced no video file (expected {out})")
            clips.append(str(path))
            if progress:
                progress(i, len(scenes))
    return clips
