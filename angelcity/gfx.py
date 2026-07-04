"""High-end rendering path: per-pixel lighting, real-time sun shadow maps, procedural
textures (ground detail, tower facades, animated water), horizon glow dome, specular
paint, MSAA, and bloom. Everything is generated in code — no image files.

Quality levels:
  high   — shadows 2048, bloom, MSAA, all textures
  medium — shadows 1024, bloom, all textures
  low    — fixed-function pipeline (fast; used by the CI smoke test)
"""

import math
import random
import numpy as np
from panda3d.core import (AntialiasAttrib, CardMaker, ColorBlendAttrib, Material,
                          PNMImage, PointLight, Spotlight, TexGenAttrib, Texture,
                          TextureStage, TransparencyAttrib, Vec4)
from .meshgen import MeshBuilder


def _tex_from_array(arr, name, alpha=None):
    """arr: HxWx3 float 0..1 (+ optional HxW alpha) -> Texture, via fast ram upload."""
    h, w, _ = arr.shape
    a8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    tex = Texture(name)
    if alpha is not None:
        al = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)[..., None]
        a8 = np.concatenate([a8, al], axis=-1)
        tex.setup2dTexture(w, h, Texture.TUnsignedByte, Texture.FRgba)
        tex.setRamImageAs(a8[::-1].tobytes(), "RGBA")
    else:
        tex.setup2dTexture(w, h, Texture.TUnsignedByte, Texture.FRgb)
        tex.setRamImageAs(a8[::-1].tobytes(), "RGB")
    tex.setWrapU(Texture.WMRepeat)
    tex.setWrapV(Texture.WMRepeat)
    tex.setMinfilter(Texture.FTLinearMipmapLinear)
    tex.setMagfilter(Texture.FTLinear)
    return tex


def _fbm(size, seed, octaves=4):
    """Cheap value-noise fBm in [-1,1], vectorized."""
    rng = np.random.default_rng(seed)
    out = np.zeros((size, size))
    amp, total = 1.0, 0.0
    cell = size // 4
    for _ in range(octaves):
        g = rng.uniform(-1, 1, (max(2, size // cell), max(2, size // cell)))
        big = np.kron(g, np.ones((cell, cell)))[:size, :size]
        for _ in range(2):
            big = (np.roll(big, 1, 0) + np.roll(big, -1, 0) +
                   np.roll(big, 1, 1) + np.roll(big, -1, 1) + big) / 5
        out += big * amp
        total += amp
        amp *= 0.55
        cell = max(1, cell // 2)
    return out / total


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


def asphalt_texture(size=512, seed=11):
    """Dark asphalt: fine aggregate, faint wear bands, occasional crack + patch."""
    rng = np.random.default_rng(seed)
    grain = rng.uniform(-1, 1, (size, size))
    wear = _fbm(size, seed + 1, 3)
    v = 0.93 + grain * 0.055 + wear * 0.06
    # a couple of meandering cracks
    y = np.arange(size)
    for k in range(2):
        x0 = rng.uniform(0, size)
        path = (x0 + np.cumsum(rng.uniform(-1.4, 1.4, size))).astype(int) % size
        for w_ in (-1, 0, 1):
            v[y, (path + w_) % size] *= 0.82 if w_ == 0 else 0.92
    # patch rectangle
    px, py = rng.integers(20, size - 84, 2)
    v[py:py + 64, px:px + 64] *= 1.07
    arr = np.stack([v, v, v * 1.03], axis=-1)
    return _tex_from_array(arr, "asphalt")


def concrete_texture(size=512, seed=13):
    """Sidewalk slabs: expansion joints every half-texture + mottling + edge wear."""
    rng = np.random.default_rng(seed)
    v = 0.94 + rng.uniform(-1, 1, (size, size)) * 0.035 + _fbm(size, seed, 3) * 0.05
    for k in (0, size // 2):
        v[k:k + 2, :] *= 0.72
        v[:, k:k + 2] *= 0.72
        v[(k + 2) % size, :] *= 0.9
        v[:, (k + 2) % size] *= 0.9
    # sparse stains
    st = _fbm(size, seed + 5, 2)
    v *= 1.0 - np.clip(st - 0.55, 0, 1) * 0.35
    arr = np.stack([v, v * 0.995, v * 0.97], axis=-1)
    return _tex_from_array(arr, "concrete")


def rooftile_texture(size=128, seed=17):
    """Terracotta: overlapping horizontal courses with per-tile hue shifts."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size
    course = 8
    row = (y * course) % 1.0
    shade = 0.82 + 0.30 * np.clip(np.sin(row * math.pi), 0, 1)   # curved tile profile
    shade[(row < 0.10)] *= 0.62                                  # course shadow line
    tile_w = 4
    col_id = (x * tile_w).astype(int) + (y * course).astype(int) * 13
    jitter = (np.vectorize(lambda i: rng.uniform(0.9, 1.1) if False else 0)(0))  # noop
    per_tile = 0.92 + ((col_id * 2654435761) % 97) / 97.0 * 0.18
    v = shade * per_tile
    arr = np.stack([v, v * 0.62, v * 0.48], axis=-1)
    return _tex_from_array(arr, "rooftile")


def stucco_texture(size=128, seed=19):
    rng = np.random.default_rng(seed)
    v = 0.97 + rng.uniform(-1, 1, (size, size)) * 0.03 + _fbm(size, seed, 3) * 0.035
    arr = np.stack([v, v * 0.995, v * 0.985], axis=-1)
    return _tex_from_array(arr, "stucco")


def grass_texture(size=128, seed=23):
    rng = np.random.default_rng(seed)
    v = 0.92 + rng.uniform(-1, 1, (size, size)) * 0.07 + _fbm(size, seed, 3) * 0.10
    g = v * (1.0 + _fbm(size, seed + 2, 2) * 0.10)
    arr = np.stack([v * 0.88, g, v * 0.80], axis=-1)
    return _tex_from_array(arr, "grass")


def sand_texture(size=128, seed=29):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size
    ripple = np.sin((x * 7 + _fbm(size, seed, 2) * 1.6) * math.tau) * 0.05
    v = 0.95 + rng.uniform(-1, 1, (size, size)) * 0.03 + ripple
    arr = np.stack([v, v * 0.97, v * 0.90], axis=-1)
    return _tex_from_array(arr, "sand")


def metal_texture(size=128, seed=31):
    """Corrugated panels: vertical ribs + rust streaks."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size
    rib = 0.88 + 0.14 * np.abs(np.sin(x * 12 * math.tau))
    rust = np.clip(_fbm(size, seed, 3) - 0.35, 0, 1)
    streak = np.clip(np.cumsum(rng.uniform(-0.02, 0.025, (size, size)), axis=0), 0, 0.5)
    v = rib - rust * 0.25 - streak * 0.2
    arr = np.stack([v, v * (1 - rust * 0.25), v * (1 - rust * 0.4)], axis=-1)
    return _tex_from_array(arr, "metal")


def cloud_texture(size=256, seed=37):
    n = _fbm(size, seed, 4)
    y, x = np.mgrid[0:size, 0:size]
    r = np.sqrt((x - size / 2) ** 2 + (y - size / 2) ** 2) / (size / 2)
    body = np.clip(n * 0.9 + 0.55 - r * 0.9, 0, 1)
    alpha = np.clip(body * 1.6, 0, 1) ** 1.4
    col = 0.97 - np.clip(0.4 - body, 0, 1) * 0.25
    arr = np.stack([col, col, col * 1.02], axis=-1)
    return _tex_from_array(arr, "cloud", alpha=alpha)


def ring_texture(size=128):
    y, x = np.mgrid[0:size, 0:size]
    r = np.sqrt((x - size / 2) ** 2 + (y - size / 2) ** 2) / (size / 2)
    alpha = np.clip(1 - np.abs(r - 0.72) * 7, 0, 1) ** 1.5
    arr = np.ones((size, size, 3))
    return _tex_from_array(arr, "ring", alpha=alpha)


# world-projection tiling scale per material class (meters per repeat)
MAT_SCALE = {"asphalt": 7.0, "concrete": 4.0, "roof": 3.2, "stucco": 5.0,
             "grass": 6.5, "sand": 8.0, "metal": 3.0}

_MAT_TEX_FNS = {"asphalt": asphalt_texture, "concrete": concrete_texture,
                "roof": rooftile_texture, "stucco": stucco_texture,
                "grass": grass_texture, "sand": sand_texture, "metal": metal_texture}

# physically-motivated surface response per class (specular color scale, shininess)
MAT_SURFACE = {"asphalt": (0.18, 14), "concrete": (0.10, 8), "roof": (0.22, 12),
               "stucco": (0.06, 6), "grass": (0.04, 4), "sand": (0.07, 5),
               "metal": (0.65, 30)}


def _encode_normal(h, strength):
    dx = np.roll(h, -1, 1) - np.roll(h, 1, 1)
    dy = np.roll(h, -1, 0) - np.roll(h, 1, 0)
    nx, ny, nz = -dx * strength, -dy * strength, np.ones_like(h)
    l = np.sqrt(nx * nx + ny * ny + nz * nz)
    arr = np.stack([nx / l, ny / l, nz / l], axis=-1) * 0.5 + 0.5
    return arr


def normal_texture(mat, size=256):
    """Tangent-space normal map per material, from analytic height fields that line
    up with the diffuse patterns (joints, tile courses, ribs, ripples, grain)."""
    y, x = np.mgrid[0:size, 0:size] / size
    rng = np.random.default_rng(101)
    if mat == "concrete":
        h = _fbm(size, 13, 3) * 0.25
        for k in (0, size // 2):
            h[k:k + 2, :] -= 1.2
            h[:, k:k + 2] -= 1.2
        strength = 2.2
    elif mat == "roof":
        course = 8
        row = (y * course) % 1.0
        h = np.clip(np.sin(row * math.pi), 0, 1) * 1.6
        h[row < 0.10] -= 1.2
        strength = 2.8
    elif mat == "metal":
        h = np.abs(np.sin(x * 12 * math.tau)) * 1.4 + _fbm(size, 31, 2) * 0.3
        strength = 2.6
    elif mat == "sand":
        h = np.sin((x * 7 + _fbm(size, 29, 2) * 1.6) * math.tau) * 0.9
        strength = 1.8
    elif mat == "asphalt":
        h = rng.uniform(-1, 1, (size, size)) * 0.35 + _fbm(size, 11, 3) * 0.5
        strength = 1.6
    elif mat == "facade":
        cell = 16
        h = np.ones((size, size)) * 0.5
        for k in range(0, size, cell):
            h[k:k + 2, :] -= 1.4
            h[:, k:k + 2] -= 1.4
        strength = 2.0
    elif mat == "grass":
        h = rng.uniform(-1, 1, (size, size)) * 0.3 + _fbm(size, 19, 3) * 0.4
        strength = 0.6
    else:   # stucco
        h = rng.uniform(-1, 1, (size, size)) * 0.5 + _fbm(size, 19, 3) * 0.4
        strength = 1.0
    return _tex_from_array(_encode_normal(h, strength), "n_" + mat)


def facade_texture(size=256, cell=32, seed=7):
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
        self.clouds = []
        self.headlights = []
        self.strobe = None
        self.strobe_np = None
        if quality == "low":
            self._horizon_belt()   # cheap and pretty even on low
            return

        render = game.render
        render.setShaderAuto()
        render.setAntialias(AntialiasAttrib.MMultisample)

        # real-time sun shadows, frustum follows the player
        size = 4096 if quality == "high" else 1024
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

        # per-material textures + normal maps + surface response: horizontal classes
        # are world-projected; wall/roof classes carry baked UVs from the mesh builder
        projected = {"asphalt", "concrete", "grass", "sand"}
        for mat, nodes in game.city.mat_nodes.items():
            fn = _MAT_TEX_FNS.get(mat)
            if fn is None:
                continue
            tex = fn()
            ntex = normal_texture(mat)
            base = TextureStage("mat_" + mat)
            base.setMode(TextureStage.MModulate)
            norm = TextureStage("nrm_" + mat)
            norm.setMode(TextureStage.MNormal)
            spec, shin = MAT_SURFACE.get(mat, (0.1, 8))
            m = Material("m_" + mat)
            m.setSpecular((spec, spec, spec, 1))
            m.setShininess(shin)
            for np_ in nodes:
                np_.setTexture(base, tex)
                np_.setTexture(norm, ntex)
                np_.setMaterial(m)
                if mat in projected:
                    for st in (base, norm):
                        np_.setTexGen(st, TexGenAttrib.MWorldPosition)
                        np_.setTexScale(st, 1 / MAT_SCALE[mat], 1 / MAT_SCALE[mat])

        # tower facades: three window-grid variants, glassy response + mullion relief
        variants = [facade_texture(seed=7), facade_texture(seed=15), facade_texture(seed=23)]
        fnorm = normal_texture("facade", 128)
        fstage = TextureStage("nrm_facade")
        fstage.setMode(TextureStage.MNormal)
        glass_m = Material("m_glass")
        glass_m.setSpecular((0.9, 0.92, 0.95, 1))
        glass_m.setShininess(90.0)
        for i, np_ in enumerate(game.city.facade_nps):
            np_.setTexture(variants[i % len(variants)])
            np_.setTexture(fstage, fnorm)
            np_.setMaterial(glass_m)

        # animated water: drifting layers + specular sun glint
        wnp = game.city.water_np
        if wnp is not None and not wnp.isEmpty():
            for i, scale in enumerate((1 / 26.0, 1 / 7.0)):
                ws = TextureStage("water%d" % i)
                ws.setMode(TextureStage.MModulate)
                wnp.setTexGen(ws, TexGenAttrib.MWorldPosition)
                wnp.setTexScale(ws, scale, scale)
                wnp.setTexture(ws, water_texture(seed=5 + i))
                self.water_stages.append(ws)
            m = Material("watermat")
            m.setSpecular((1.0, 0.95, 0.8, 1))
            m.setShininess(140.0)
            wnp.setMaterial(m)

        self._horizon_belt()
        self._sun_glow()
        self._clouds()
        self._dynamic_lights()

        # bloom + SSAO (graceful fallback if the driver can't do offscreen buffers)
        try:
            from direct.filter.CommonFilters import CommonFilters
            f = CommonFilters(game.win, game.cam)
            ok = f.setBloom(blend=(0.30, 0.40, 0.30, 0.0), mintrigger=0.72,
                            maxtrigger=1.0, desat=0.2, intensity=1.0, size="medium")
            if ok and quality == "high":
                f.setAmbientOcclusion(numsamples=16, radius=0.028, amount=1.6,
                                      strength=0.014, falloff=0.000004)
            self.filters = f if ok else None
        except Exception:
            self.filters = None

    def _clouds(self):
        """Soft drifting cumulus billboards high over the basin."""
        tex = cloud_texture()
        rng = random.Random(6)
        for _ in range(14):
            cm = CardMaker("cloud")
            s = rng.uniform(160, 420)
            cm.setFrame(-s, s, -s * 0.42, s * 0.42)
            np_ = self.game.render.attachNewNode(cm.generate())
            np_.setTexture(tex)
            np_.setTransparency(TransparencyAttrib.MAlpha)
            np_.setBillboardPointEye()
            np_.setLightOff()
            np_.setShaderOff()
            np_.setDepthWrite(False)
            np_.setPos(rng.uniform(-2300, 1500), rng.uniform(-1500, 1400),
                       rng.uniform(380, 560))
            np_.setColorScale(1, 1, 1, rng.uniform(0.5, 0.8))
            self.clouds.append((np_, rng.uniform(2.5, 6.0)))

    def _dynamic_lights(self):
        """Real spotlights for the player's headlights + a police strobe point light.
        Enabled only at night; per-pixel via the shader pipeline."""
        for i in (-1, 1):
            sl = Spotlight("headlight%d" % i)
            sl.setColor(Vec4(1.0, 0.95, 0.8, 1))
            lens = sl.getLens()
            lens.setFov(38)
            lens.setNearFar(0.5, 90)
            sl.setAttenuation((1.0, 0.0, 0.00012))
            np_ = self.game.render.attachNewNode(sl)
            self.headlights.append(np_)
        pl = PointLight("strobe")
        pl.setColor(Vec4(0, 0, 0, 1))
        pl.setAttenuation((1.0, 0.0, 0.0018))
        self.strobe_np = self.game.render.attachNewNode(pl)
        self.strobe = pl
        self._lights_on = False

    def _set_dynamic_lights(self, on):
        if on == getattr(self, "_lights_on", False):
            return
        self._lights_on = on
        for np_ in self.headlights:
            if on:
                self.game.render.setLight(np_)
            else:
                self.game.render.clearLight(np_)
        if self.strobe_np:
            if on:
                self.game.render.setLight(self.strobe_np)
            else:
                self.game.render.clearLight(self.strobe_np)

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

    def update(self, t, sun_dir, sun_col, horizon_col, el, sky_col=None):
        game = self.game
        # keep the shadow frustum centered on the action
        px, py = game.player_world_pos()
        game.sun_np.setPos(px, py, 0)
        # the post-process scene buffer keeps its own clear color — track the sky
        if self.filters is not None and sky_col is not None:
            try:
                for buf in self.filters.manager.buffers:
                    buf.setClearColor(Vec4(sky_col[0], sky_col[1], sky_col[2], 1.0))
            except Exception:
                pass
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
        # clouds drift east and dim toward dusk
        day = max(0.15, min(1.0, el * 2.2 + 0.5))
        for np_, speed in self.clouds:
            x = np_.getX() + speed * (t - getattr(self, "_last_t", t))
            if x > 1700:
                x = -2450
            np_.setX(x)
            np_.setColorScale(day, day, day * 1.02, 0.65)
        self._last_t = t
        self._update_dynamic_lights(t)

    def _update_dynamic_lights(self, t):
        game = self.game
        if not self.headlights:
            return
        p = game.player
        driving = (p.car is not None and getattr(p.car, "mode", "car") == "car"
                   and not p.car.wreck)
        want = bool(game.is_night and (driving or game.cops.cruisers))
        self._set_dynamic_lights(want)
        if not want:
            return
        if driving:
            car = p.car
            fx, fy = car.fwd
            for i, np_ in enumerate(self.headlights):
                side = -1 if i == 0 else 1
                rx, ry = fy, -fx
                np_.setPos(car.x + fx * car.spec["l"] * 0.45 + rx * side * 0.6,
                           car.y + fy * car.spec["l"] * 0.45 + ry * side * 0.6,
                           car.z + 0.7)
                np_.setHpr(math.degrees(car.heading), -6, 0)
                np_.node().setColor(Vec4(1.0, 0.95, 0.8, 1))
        else:
            for np_ in self.headlights:
                np_.node().setColor(Vec4(0, 0, 0, 1))
        # police strobe on the nearest active cruiser
        if game.cops.cruisers and self.strobe_np:
            px, py = game.player_world_pos()
            car = min(game.cops.cruisers, key=lambda c: (c.x - px) ** 2 + (c.y - py) ** 2)
            self.strobe_np.setPos(car.x, car.y, car.z + 2.4)
            phase = int(t * 6) % 2
            self.strobe.setColor(Vec4(2.2, 0.1, 0.1, 1) if phase else Vec4(0.1, 0.2, 2.2, 1))
        elif self.strobe:
            self.strobe.setColor(Vec4(0, 0, 0, 1))
