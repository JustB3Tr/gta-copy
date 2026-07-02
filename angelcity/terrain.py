"""Terrain height model + drivable overlay surfaces (bridges, freeway decks, pier,
helipads).

The basin is exactly flat (z=0) except for analytic features: the beach slope on the
west (with the LAX shelf notch), the two sunken river channels, and the northern hills.
Overlay patches sit above/across the terrain; entities snap to whichever surface is
nearest below them, so you can drive UNDER a freeway or ON it, and land a helicopter
on a rooftop pad."""

import math
from . import config as C


def _clamp01(t):
    return 0.0 if t < 0 else (1.0 if t > 1 else t)


def _smooth(t):
    t = _clamp01(t)
    return t * t * (3 - 2 * t)


class Patch:
    """Sloped/flat rectangle surface. z lerps from z0 to z1 along `axis`."""

    __slots__ = ("x0", "x1", "y0", "y1", "z0", "z1", "axis")

    def __init__(self, x0, x1, y0, y1, z0, z1=None, axis="x"):
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.z0, self.z1 = z0, (z0 if z1 is None else z1)
        self.axis = axis

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def height(self, x, y):
        if self.z0 == self.z1:
            return self.z0
        if self.axis == "x":
            t = (x - self.x0) / (self.x1 - self.x0)
        else:
            t = (y - self.y0) / (self.y1 - self.y0)
        return self.z0 + (self.z1 - self.z0) * _clamp01(t)


def coast_sand_x(y):
    """Where the sand begins, as a function of latitude. The LAX shelf juts west."""
    base = C.BEACH_X
    if C.LAX_Y0 - 120 < y < C.LAX_Y1 + 120:
        n = _smooth((y - (C.LAX_Y0 - 120)) / 140.0) * _smooth(((C.LAX_Y1 + 120) - y) / 140.0)
        return base + (C.LAX_COAST_X - base) * min(1.0, n * 1.6)
    return base


class Ground:
    def __init__(self, seed=7):
        self.patches = []
        self.bumps = [(-700, 1240, 460, 95), (-80, 1330, 420, 110), (520, 1300, 430, 88),
                      (1100, 1260, 380, 70), (-1250, 1300, 400, 60), (240, 1120, 260, 40)]
        self.obs_center = C.OBSERVATORY

    def add_patch(self, *a, **kw):
        p = Patch(*a, **kw)
        self.patches.append(p)
        return p

    # ---- analytic terrain ----
    def height(self, x, y):
        h = 0.0
        cx = coast_sand_x(y)
        if x < cx:
            h -= 4.6 * _clamp01((cx - x) / 150.0)
        # channels: Ballona Creek (E-W) and the LA River (N-S); take the deeper of the two
        d_creek = 0.0
        dy = abs(y - C.CREEK_Y)
        if dy < C.RIVER_HALF_TOP and C.BASIN_X0 - 40 < x < C.RIVER_X - 20:
            if dy < C.RIVER_HALF_FLAT:
                d_creek = 1.0
            else:
                d_creek = 1.0 - _smooth((dy - C.RIVER_HALF_FLAT) /
                                        (C.RIVER_HALF_TOP - C.RIVER_HALF_FLAT))
            end = _smooth((x - (C.BASIN_X0 - 40)) / 120.0)
            d_creek *= end
        d_river = 0.0
        dx = abs(x - C.RIVER_X)
        if dx < C.RIVER_HALF_TOP and C.PORT_Y0 - 80 < y < 840:
            if dx < C.RIVER_HALF_FLAT:
                d_river = 1.0
            else:
                d_river = 1.0 - _smooth((dx - C.RIVER_HALF_FLAT) /
                                        (C.RIVER_HALF_TOP - C.RIVER_HALF_FLAT))
            d_river *= _smooth((840 - y) / 120.0)
        d = max(d_creek, d_river)
        if d > 0:
            h -= C.RIVER_DEPTH * d
        # northern hills
        if y > 820:
            base = _smooth((y - 820) / 620.0) * 120.0
            for bx, by, r, bh in self.bumps:
                d2 = (x - bx) ** 2 + (y - by) ** 2
                if d2 < r * r * 4:
                    base += bh * math.exp(-d2 / (r * r * 0.55))
            ox, oy = self.obs_center
            dd = math.hypot(x - ox, y - oy)
            if dd < 130:
                w = _smooth(1.0 - dd / 130.0)
                base = base * (1 - w) + 118.0 * w
            # amphitheater bowl carve
            bxx, byy = C.BOWL_POS
            dd = math.hypot(x - bxx, y - byy)
            if dd < 90:
                base -= 14.0 * _smooth(1.0 - dd / 90.0)
            h += base
        # south harbor strip slopes into the water beyond the docks
        if y < C.PORT_Y0:
            h -= 4.5 * _clamp01((C.PORT_Y0 - y) / 120.0)
        return h

    def normal(self, x, y, eps=1.5):
        hx = self.height(x + eps, y) - self.height(x - eps, y)
        hy = self.height(x, y + eps) - self.height(x, y - eps)
        nx, ny, nz = -hx / (2 * eps), -hy / (2 * eps), 1.0
        l = math.sqrt(nx * nx + ny * ny + nz * nz)
        return (nx / l, ny / l, nz / l)

    # ---- combined surface (terrain + overlays) ----
    def surface(self, x, y, z_ref=0.0):
        """Return (height, on_overlay). Picks the highest surface not more than
        ~2.6m above z_ref, so entities under a deck don't snap up onto it."""
        best = self.height(x, y)
        on = False
        for p in self.patches:
            if p.contains(x, y):
                pz = p.height(x, y)
                if pz <= z_ref + 2.6 and pz > best:
                    best = pz
                    on = True
        return best, on

    def is_wet(self, x, y, z_ref=0.0):
        h, on = self.surface(x, y, z_ref)
        return (not on) and h < C.WATER_Z - 0.3
