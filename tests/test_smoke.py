"""Headless smoke test: boots the whole game world and runs 60 frames offscreen.
Run directly: python tests/test_smoke.py (no extra dependencies; also discoverable
by pytest if you happen to have it installed)."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_smoke():
    cmd = [sys.executable, os.path.join(ROOT, "main.py"),
           "--headless", "--no-audio", "--quality", "low", "--frames", "60"]
    if os.environ.get("DISPLAY") is None and os.name != "nt":
        xvfb = "/usr/bin/xvfb-run"
        if os.path.exists(xvfb):
            cmd = [xvfb, "-a"] + cmd
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, "game crashed:\n%s\n%s" % (proc.stdout[-2000:],
                                                            proc.stderr[-2000:])


if __name__ == "__main__":
    test_smoke()
    print("smoke test passed")
