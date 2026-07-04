#!/usr/bin/env python3
"""Angel City — an original open-world driving/action sandbox set in a stylized
Los Angeles. Run `python main.py`. See README.md for controls and build steps."""

import argparse
import os
import sys


def parse_args():
    ap = argparse.ArgumentParser(description="Angel City")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fps", action="store_true", help="show frame-rate meter")
    ap.add_argument("--quality", choices=("high", "medium", "low"), default="high",
                    help="high: shadows+bloom+MSAA; low: fast fixed-function")
    # headless / capture (used by tests and CI)
    ap.add_argument("--headless", action="store_true", help="render offscreen")
    ap.add_argument("--frames", type=int, default=0, help="run N frames then exit")
    ap.add_argument("--screenshot", default="", help="save a screenshot before exiting")
    ap.add_argument("--scenario", default="",
                    help="start state: home drive downtown night wanted hills pier freeway")
    return ap.parse_args()


def main():
    args = parse_args()
    from panda3d.core import loadPrcFileData

    prc = [
        "window-title Angel City",
        "win-size %d %d" % (args.width, args.height),
        "sync-video 0",
        "notify-level-glgsg error",
        "notify-level-x11display error",
        "default-antialias-enable 1",
    ]
    if args.quality != "low":
        prc += ["framebuffer-multisample 1", "multisamples 4"]
    if args.fullscreen:
        prc.append("fullscreen 1")
    if args.headless:
        prc.append("window-type offscreen")
    if args.no_audio or args.headless:
        prc.append("audio-library-name null")
    if args.fps:
        prc.append("show-frame-rate-meter 1")
    loadPrcFileData("", "\n".join(prc))

    if args.frames:
        from panda3d.core import ClockObject
        clock = ClockObject.getGlobalClock()
        clock.setMode(ClockObject.MNonRealTime)
        clock.setFrameRate(60)

    from angelcity.game import AngelCityGame

    game = AngelCityGame(dict(
        headless=args.headless,
        no_audio=args.no_audio or args.headless,
        seed=args.seed,
        scenario=args.scenario,
        quality=args.quality,
    ))

    if args.frames:
        for _ in range(args.frames):
            game.taskMgr.step()
        if args.screenshot:
            os.makedirs(os.path.dirname(os.path.abspath(args.screenshot)), exist_ok=True)
            # save RGB only: post-process passes can leave partial alpha in the window
            from panda3d.core import Filename, PNMImage
            img = PNMImage()
            game.win.getScreenshot(img)
            img.removeAlpha()
            img.write(Filename.fromOsSpecific(os.path.abspath(args.screenshot)))
            print("saved", args.screenshot)
        game.destroy()
        return 0
    game.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
