"""High-end rendering path: per-pixel lighting, real-time sun shadow maps, procedural
textures (ground detail, tower facades, animated water), horizon glow dome, specular
paint, MSAA, and bloom. Everything is generated in code — no image files.

Quality levels:
  high   — shadows 2048, bloom, MSAA, all textures
  medium — shadows 1024, bloom, all textures
  low    — fixed-function pipeline (fast; used by the CI smoke test)
"""

import math
import numpy as np
from panda3d.core import (AntialiasAttrib, CardMaker, ColorBlendAttrib, PNMImage,
                          TexGenAttrib, Texture, TextureStage, TransparencyAttrib)
from .meshgen import MeshBuilder


def _tex_from_array(arr, name):
    """arr: HxWx3 float 0..1 -> Texture"""
    h, w, _ = arr.shape
    img = PNMImage(w, h)
    a8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    for y in range(h):
        for x in range(w):
            img.setXelVal(x, y, int(a8[y, x, 0]), int(a8[y, x, 1]), int(a8[y, x, 2]))
    tex = Texture(name)
    tex.load(img)
    tex.setWrapU(Texture.WMRepeat)
    tex.setWrapV(Texture.WMRepeat)
    tex.setMinfilter(Texture.FTLinearMipmapLinear)
    tex.setMagfilter(Texture.FTLinear)
    return tex


def detail_texture(size=256, seed=3):
    """Neutral grain + large soft blotches; modulated over the whole static city."""
    rng = np.random.default_rng(seed)
    fine = rng.uniform(-1, 1, (size, size))
    # soft blotches from a coarse grid blown up and blurred hard
    coarse = rng.uniform(-1, 1, (size // 16, size // 16))
    blotch = np.kron(coarse, np.ones((16, 16)))
    for _ in range(10):   # cheap box blur, repeated until the blocks melt away
        blotch = (np.roll(blotch, 1, 0) + np.roll(blotch, -1, 0) +
                  np.roll(blotch, 1, 1) + np.roll(blotch, -1, 1) + blotch) / 5
    v = 1.0 + fine * 0.05 + blotch * 0.08
    warm = 1.0 + blotch * 0.03
    arr = np.stack([v * warm, v, v / warm], axis=-1) * 0.95
    return _tex_from_array(arr, "detail")


def facade_texture(size=128, cell=16, seed=7):
    """Window grid for tower walls: glass panes with mullions and per-pane variance."""
    rng = np.random.default_rng(seed)
    arr = np.zeros((size, size, 3))
    for cy in range(size // cell):
        for cx in range(size // cell):
            shade = 0.75 + rng.uniform(-0.22, 0.22)
            cool = rng.uniform(-0.06, 0.10)
            col = np.array([shade * (1 - cool * 0.5), shade, shade * (1 + cool)])
            arr[cy * cell:(cy + 1) * cell, cx * cell:(cx + 1) * cell] = col
            # sky reflection gradient inside each pane
            for row in range(cell):
                arr[cy * cell + row, cx * cell:(cx + 1) * cell] *= (1.06 - 0.10 * row / cell)
    # mullions
    for k in range(0, size, cell):
        arr[k:k + 2, :] *= 0.35
        arr[:, k:k + 2] *= 0.35
    return _tex_from_array(arr, "facade")


def water_texture(size=256, seed=5):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size
    waves = (np.sin((x * 6 + y * 2) * math.tau) * 0.5 +
             np.sin((x * 1.7 - y * 4.3) * math.tau + 1.7) * 0.35 +
             np.sin((y * 9.1 + x * 0.6) * math.tau + 0.6) * 0.25)
    noise = rng.uniform(-1, 1, (size, size)) * 0.15
    v = 0.86 + (waves + noise) * 0.12
    arr = np.stack([v * 0.92, v, v * 1.05], axis=-1)
    return _tex_from_array(arr, "water")


def glow_texture(size=128):
    y, x = np.mgrid[0:size, 0:size]
    r = np.sqrt((x - size / 2) ** 2 + (y - size / 2) ** 2) / (size / 2)
    a = np.clip(1 - r, 0, 1) ** 2.2
    img = PNMImage(size, size)
    img.addAlpha()
    for yy in range(size):
        for xx in range(size):
            img.setXelVal(xx, yy, 255, 255, 255)
            img.setAlphaVal(xx, yy, int(a[yy, xx] * 255))
    tex = Texture("glow")
    tex.load(img)
    tex.setMinfilter(Texture.FTLinear)
    return tex


class Gfx:
    def __init__(self, game, quality="high"):
        self.game = game
        self.quality = quality
        self.filters = None
        self.water_stages = []
        self.belt = None
        self.sun_glow = None
        if quality == "low":
            self._horizon_belt()   # cheap and pretty even on low
            return

        render = game.render
        render.setShaderAuto()
        render.setAntialias(AntialiasAttrib.MMultisample)

        # real-time sun shadows, frustum follows the player
        size = 2048 if quality == "high" else 1024
        try:
            game.sun.setShadowCaster(True, size, size)
            lens = game.sun.getLens()
            lens.setFilmSize(420, 420)
            lens.setNearFar(-700, 1200)
        except Exception:
            pass

        # ground-detail grain over the whole static city (world-projected, no UVs needed)
        ts = TextureStage("detail")
        ts.setMode(TextureStage.MModulate)
        city_np = game.city.root
        city_np.setTexGen(ts, TexGenAttrib.MWorldPosition)
        city_np.setTexScale(ts, 1 / 9.0, 1 / 9.0)
        city_np.setTexture(ts, detail_texture())

        # tower facades get the window-grid texture via their baked UVs
        if game.city.facade_np is not None and not game.city.facade_np.isEmpty():
            game.city.facade_np.setTexture(facade_texture())

        # animated water: two world-projected layers drifting against each other
        wnp = game.city.water_np
        if wnp is not None and not wnp.isEmpty():
            for i, scale in enumerate((1 / 26.0, 1 / 7.0)):
                ws = TextureStage("water%d" % i)
                ws.setMode(TextureStage.MModulate)
                wnp.setTexGen(ws, TexGenAttrib.MWorldPosition)
                wnp.setTexScale(ws, scale, scale)
                wnp.setTexture(ws, water_texture(seed=5 + i))
                self.water_stages.append(ws)

        self._horizon_belt()
        self._sun_glow()

        # bloom (graceful fallback if the driver can't do offscreen buffers)
        try:
            from direct.filter.CommonFilters import CommonFilters
            f = CommonFilters(game.win, game.cam)
            ok = f.setBloom(blend=(0.30, 0.40, 0.30, 0.0), mintrigger=0.72,
                            maxtrigger=1.0, desat=0.2, intensity=1.0, size="medium")
            self.filters = f if ok else None
        except Exception:
            self.filters = None

    # ---------------- sky extras ----------------

    def _horizon_belt(self):
        """Ring of vertex-alpha gradient around the horizon; tinted per time of day."""
        b = MeshBuilder("belt")
        R = 2250
        segs = 24
        for i in range(segs):
            a0 = math.tau * i / segs
            a1 = math.tau * (i + 1) / segs
            x0, y0 = math.cos(a0) * R, math.sin(a0) * R
            x1, y1 = math.cos(a1) * R, math.sin(a1) * R
            b.add_quad((x0, y0, -80), (x1, y1, -80), (x1, y1, 260), (x0, y0, 260),
                       (1, 1, 1, 0.0), None)
            # overwrite alphas: bottom opaque, top transparent
            n = len(b.verts)
            v = list(b.verts[n - 4])
            v[9] = 0.85
            b.verts[n - 4] = tuple(v)
            v = list(b.verts[n - 3])
            v[9] = 0.85
            b.verts[n - 3] = tuple(v)
        self.belt = b.build(self.game.sky, "horizon")
        self.belt.setTwoSided(True)
        self.belt.setTransparency(TransparencyAttrib.MAlpha)
        self.belt.setLightOff()
        self.belt.setShaderOff()
        self.belt.setBin("background", 4)
        self.belt.setDepthWrite(False)

    def _sun_glow(self):
        cm = CardMaker("sunglow")
        cm.setFrame(-260, 260, -260, 260)
        np_ = self.game.sky.attachNewNode(cm.generate())
        np_.setTexture(glow_texture())
        np_.setTransparency(TransparencyAttrib.MAlpha)
        np_.setBillboardPointEye()
        np_.setLightOff()
        np_.setShaderOff()
        np_.setBin("background", 3)
        np_.setDepthWrite(False)
        np_.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd))
        self.sun_glow = np_

    # ---------------- per-frame ----------------

    def update(self, t, sun_dir, sun_col, horizon_col, el):
        game = self.game
        # keep the shadow frustum centered on the action
        px, py = game.player_world_pos()
        game.sun_np.setPos(px, py, 0)
        for i, ws in enumerate(self.water_stages):
            sp = 0.006 + i * 0.004
            game.city.water_np.setTexOffset(ws, (t * sp) % 1.0, (t * sp * 0.7) % 1.0)
        if self.belt:
            self.belt.setColorScale(horizon_col[0], horizon_col[1], horizon_col[2], 1.0)
        if self.sun_glow:
            self.sun_glow.setPos(-sun_dir.x * 1900, -sun_dir.y * 1900, -sun_dir.z * 1900)
            warm = max(0.0, min(1.0, 1.2 - abs(el) * 1.5))
            alpha = max(0.0, min(0.9, el * 3 + 0.35))
            self.sun_glow.setColorScale(1.0, 0.75 + 0.2 * (1 - warm), 0.45 + 0.4 * (1 - warm),
                                        alpha)
