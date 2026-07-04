"""Procedural audio: every sound effect is synthesized with numpy at first launch and
cached as .wav files in the system temp dir, then played through Panda's audio manager."""

import math
import os
import tempfile
import wave

import numpy as np

RATE = 22050


def _write(path, data):
    data = np.clip(data, -1, 1)
    pcm = (data * 32000).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def _t(dur):
    return np.arange(int(RATE * dur)) / RATE


def _env(n, attack=0.002, release=0.05):
    e = np.ones(n)
    a = max(1, int(RATE * attack))
    r = max(1, int(RATE * release))
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r)
    return e


def _noise(dur):
    return np.random.default_rng(4).uniform(-1, 1, int(RATE * dur))


def _lowpass(x, alpha):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += alpha * (v - acc)
        y[i] = acc
    return y


def _generate_all(d):
    # engine: exactly periodic saw + rumble so it loops seamlessly
    dur = 1.0
    t = _t(dur)
    f = 65.0
    saw = 2 * ((t * f) % 1.0) - 1
    sub = np.sin(2 * np.pi * f * 0.5 * t)
    eng = 0.5 * saw + 0.45 * sub
    _write(d["engine"], _lowpass(eng, 0.25) * 0.9)

    # police wail: sine sweep up and back down over 2s
    t = _t(2.0)
    sweep = 650 + 450 * np.sin(2 * np.pi * 0.5 * t - np.pi / 2)
    phase = np.cumsum(sweep) / RATE
    _write(d["siren"], np.sin(2 * np.pi * phase) * 0.5)

    # tire squeal
    n = _noise(0.7)
    band = n - _lowpass(n, 0.15)
    _write(d["skid"], band * _env(len(band), 0.01, 0.05) * 0.8)

    for name, dur, punch, tail in (("shot_pistol", 0.16, 1.0, 0.020),
                                   ("shot_smg", 0.10, 0.8, 0.014),
                                   ("shot_shotgun", 0.34, 1.3, 0.06)):
        n = int(RATE * dur)
        noise = np.random.default_rng(7).uniform(-1, 1, n)
        decay = np.exp(-np.arange(n) / (RATE * tail))
        thump = np.sin(2 * np.pi * 110 * _t(dur)) * np.exp(-np.arange(n) / (RATE * 0.03))
        _write(d[name], (_lowpass(noise, 0.5) * decay + 0.7 * thump) * punch * 0.8)

    n = int(RATE * 0.5)
    noise = np.random.default_rng(9).uniform(-1, 1, n)
    decay = np.exp(-np.arange(n) / (RATE * 0.09))
    thud = np.sin(2 * np.pi * 70 * _t(0.5)) * np.exp(-np.arange(n) / (RATE * 0.12))
    _write(d["crash"], _lowpass(noise * decay, 0.3) + 0.9 * thud)

    t = _t(0.5)
    horn = np.sign(np.sin(2 * np.pi * 370 * t)) * 0.35 + np.sign(np.sin(2 * np.pi * 466 * t)) * 0.35
    _write(d["horn"], _lowpass(horn, 0.4) * _env(len(t), 0.01, 0.05))

    parts = []
    for f in (660, 880, 1320):
        t = _t(0.09)
        parts.append(np.sin(2 * np.pi * f * t) * _env(len(t), 0.002, 0.03))
    _write(d["pickup"], np.concatenate(parts) * 0.6)

    t = _t(0.25)
    _write(d["thud"], np.sin(2 * np.pi * 85 * t) * np.exp(-np.arange(len(t)) / (RATE * 0.05)))

    n = _noise(0.5)
    e = np.exp(-np.arange(len(n)) / (RATE * 0.12))
    _write(d["splash"], (n - _lowpass(n, 0.4)) * e * 0.7)

    parts = []
    for f in (392, 311, 262, 196):
        t = _t(0.30)
        tone = np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2 * t)
        parts.append(tone * _env(len(t), 0.01, 0.12))
    _write(d["wasted"], np.concatenate(parts) * 0.45)

    parts = []
    for f in (185, 147):
        t = _t(0.4)
        saw = 2 * ((t * f) % 1.0) - 1
        parts.append(_lowpass(saw, 0.3) * _env(len(t), 0.01, 0.2))
    _write(d["busted"], np.concatenate(parts) * 0.6)

    parts = []
    for f in (523, 659, 784, 1047):
        t = _t(0.12)
        parts.append(np.sin(2 * np.pi * f * t) * _env(len(t), 0.005, 0.05))
    _write(d["chime"], np.concatenate(parts) * 0.5)

    t = _t(0.03)
    _write(d["click"], np.sin(2 * np.pi * 1400 * t) * _env(len(t), 0.001, 0.01) * 0.4)

    # helicopter rotor: low rumble chopped at 12 Hz (integer rate → seamless loop)
    t = _t(1.0)
    n = np.random.default_rng(21).uniform(-1, 1, len(t))
    chop = 0.35 + 0.65 * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 12 * t)))
    _write(d["rotor"], _lowpass(n, 0.12) * chop * 1.6)

    # piston prop: saw + harmonics with a 25 Hz flutter
    f = 88.0
    saw = 2 * ((t * f) % 1.0) - 1
    saw2 = 2 * ((t * f * 2) % 1.0) - 1
    am = 0.8 + 0.2 * np.sin(2 * np.pi * 25 * t)
    _write(d["prop"], _lowpass(0.6 * saw + 0.3 * saw2, 0.3) * am * 0.9)

    # jet: broadband whoosh
    n = np.random.default_rng(23).uniform(-1, 1, len(t))
    body = _lowpass(n, 0.45) - _lowpass(n, 0.06)
    _write(d["jet"], body * 1.1)

    # shoreline waves: 4s slow swell loop
    t4 = _t(4.0)
    n = np.random.default_rng(25).uniform(-1, 1, len(t4))
    swell = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t4 - np.pi / 2))
    _write(d["waves"], _lowpass(n, 0.08) * swell * 0.9)


NAMES = ["engine", "siren", "skid", "shot_pistol", "shot_smg", "shot_shotgun", "crash",
         "horn", "pickup", "thud", "splash", "wasted", "busted", "chime", "click",
         "rotor", "prop", "jet", "waves"]


class SFX:
    def __init__(self, base, enabled=True):
        self.base = base
        mgr = base.sfxManagerList[0] if base.sfxManagerList else None
        self.ok = bool(enabled and mgr and mgr.isValid())
        self.sounds = {}
        self.loops = {}
        if not self.ok:
            return
        cache = os.path.join(tempfile.gettempdir(), "angelcity_sfx")
        os.makedirs(cache, exist_ok=True)
        paths = {n: os.path.join(cache, n + ".wav") for n in NAMES}
        if not all(os.path.exists(p) for p in paths.values()):
            _generate_all(paths)
        for n, p in paths.items():
            snd = base.loader.loadSfx(p)
            if snd:
                self.sounds[n] = snd
        self.ok = bool(self.sounds)

    def play(self, name, vol=1.0, rate=1.0):
        if not self.ok or name not in self.sounds:
            return
        s = self.sounds[name]
        s.setVolume(min(1.0, vol))
        s.setPlayRate(rate)
        s.play()

    def loop(self, key, name, vol, rate=1.0):
        """Start/adjust a persistent looping sound (engine, siren, skid)."""
        if not self.ok:
            return
        s = self.loops.get(key)
        if s is None:
            if name not in self.sounds:
                return
            base_snd = self.sounds[name]
            s = self.base.loader.loadSfx(base_snd.getName())
            if not s:
                return
            s.setLoop(True)
            self.loops[key] = s
        if vol <= 0.01:
            if s.status() == s.PLAYING:
                s.stop()
            return
        s.setVolume(min(1.0, vol))
        s.setPlayRate(max(0.3, rate))
        if s.status() != s.PLAYING:
            s.play()

    def stop_loops(self):
        for s in self.loops.values():
            s.stop()
