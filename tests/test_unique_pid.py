import tempfile
import unittest
from pathlib import Path

from postcrew.agents.yt_publish import _unique_pid
from postcrew.workspace import Workspace


class UniquePostId(unittest.TestCase):
    """Two posts for the same day/platform/plan slot must not share an id: the second one overwrote the first one's video."""

    def test_a_taken_id_gets_a_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            media = ws.root / "media"
            media.mkdir()
            pid = "2026-11-11-youtube-assigned-short-052fc498"
            self.assertEqual(_unique_pid(ws, media, pid), pid)
            ws.add_history({"id": pid})
            self.assertEqual(_unique_pid(ws, media, pid), pid + "-2")
            (media / f"{pid}-2.mp4").write_bytes(b"x")
            self.assertEqual(_unique_pid(ws, media, pid), pid + "-3")


if __name__ == "__main__":
    unittest.main()
