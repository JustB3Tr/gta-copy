"""Generates the whole miniature-Los-Angeles world.

Geography follows the real city at a compressed scale: real freeway topology
(10 / 110 / 101 / 405), real street names on the arterial grid, real neighborhoods in
their right relative positions, and original low-poly stand-ins for famous landmarks.

Rendering detail pass: geometry is emitted into per-chunk builders *per material
class* (asphalt / concrete / roof tile / stucco / corrugated metal / grass / sand /
plain), so each class can carry its own procedurally generated texture. Buildings are
fully dressed — houses have porches, framed windows, chimneys, garages, fences and
driveways; storefronts have glass, awnings and signs; towers have lobbies and rooftop
plant. Streets have curbs, crosswalks, stop lines, lane arrows, manholes, hydrants,
parking meters, bus benches, power poles with sagging lines, and freeway billboards."""

import math
import random
from panda3d.core import NodePath, PNMImage, TextNode, Texture
from . import config as C
from .meshgen import MeshBuilder
from .terrain import coast_sand_x

ASPHALT = (0.24, 0.24, 0.26)
ASPHALT_V = (0.245, 0.245, 0.265)
SIDEWALK = (0.58, 0.56, 0.53)
CURB = (0.66, 0.64, 0.61)
YELLOW = (0.85, 0.70, 0.15)
WHITE_PAINT = (0.82, 0.82, 0.80)
SAND = (0.86, 0.78, 0.58)
DRYGRASS = (0.62, 0.58, 0.34)
GRASS = (0.38, 0.55, 0.28)
CONCRETE = (0.60, 0.58, 0.54)
DIRT = (0.52, 0.46, 0.36)
OCEAN = (0.15, 0.38, 0.48)
FWY_GRAY = (0.55, 0.53, 0.50)
DECK_TOP = (0.33, 0.33, 0.35)
SIGN_GREEN = (0.10, 0.35, 0.18)
GLASS_DARK = (0.14, 0.17, 0.21)
FRAME_WHITE = (0.90, 0.89, 0.86)
STUCCO = [(0.91, 0.87, 0.78), (0.89, 0.80, 0.66), (0.85, 0.72, 0.60), (0.93, 0.90, 0.85),
          (0.80, 0.72, 0.62), (0.87, 0.83, 0.70)]
PASTEL = [(0.95, 0.65, 0.60), (0.55, 0.80, 0.78), (0.95, 0.85, 0.55), (0.70, 0.82, 0.60),
          (0.80, 0.66, 0.85), (0.98, 0.92, 0.80), (0.60, 0.72, 0.90)]
GLASS_TOWER = [(0.45, 0.55, 0.65), (0.55, 0.60, 0.68), (0.40, 0.48, 0.55), (0.60, 0.65, 0.72),
               (0.50, 0.58, 0.60)]
ROOF_TILE = (0.63, 0.32, 0.22)
TREE_GREEN = [(0.25, 0.42, 0.18), (0.30, 0.48, 0.22), (0.22, 0.38, 0.20)]
PALM_GREEN = [(0.28, 0.50, 0.24), (0.33, 0.55, 0.26)]
JACARANDA = (0.55, 0.45, 0.80)
WINDOW_WARM = (1.0, 0.85, 0.5, 0.8)
WINDOW_COOL = (0.75, 0.85, 1.0, 0.8)

# meters-per-repeat, kept in sync with gfx.MAT_SCALE for the baked-UV materials
UVS_STUCCO = 5.0
UVS_METAL = 3.0
UVS_ROOF = 3.2

SHOP_NAMES = ["MARLIN DINER", "SUNSET LIQUOR", "LA BREA TACOS", "VERMONT BOOKS",
              "PACIFIC GYM", "CENTURY DONUTS", "VISTA VIDEO", "PALM CLEANERS",
              "BAYSIDE PAWN", "ECHO RECORDS", "GOLDEN DRAGON", "CRENSHAW CUTS"]

BILLBOARD_ADS = [("ANGEL COLA", "ice cold since 1962"),
                 ("PALM AIR", "nonstop to the bay"),
                 ("MARLIN DINER", "open all nite"),
                 ("AUTO SPA", "lose the heat"),
                 ("KAPD 7 NEWS", "live at dawn"),
                 ("SUNSET SOUNDS", "FM 101.5")]


def _vary(rng, c, amt=0.05):
    return tuple(max(0, min(1, v + rng.uniform(-amt, amt))) for v in c)


class City:
    def __init__(self, render, ground, seed=42):
        self.render = render
        self.ground = ground
        self.seed = seed
        self.roads_v = list(C.ROADS_V)
        self.roads_h = [y for y in C.ROADS_H if abs(y - C.CREEK_Y) > 1]
        self.major_vs = {x for i, x in enumerate(C.ROADS_V) if i % C.MAJOR_EVERY == 0}
        self.major_hs = {y for i, y in enumerate(C.ROADS_H)
                         if i % C.MAJOR_EVERY == 0 and abs(y - C.CREEK_Y) > 1}
        self.colliders = []
        self.cells = {}
        self.chunks = {}                 # (cx, cy, material) -> MeshBuilder
        self.mat_nodes = {}              # material -> [NodePath]
        self.water_b = MeshBuilder("water")
        self.night_b = MeshBuilder("night")
        self.decal_b = MeshBuilder("decals")     # soft AO pads / stains (alpha)
        self.facade_bs = [MeshBuilder("facade%d" % i) for i in range(3)]
        self.facade_nps = []
        self.lights_g_b = MeshBuilder("lights_green")
        self.lights_r_b = MeshBuilder("lights_red")
        self.anims = []                  # (nodepath, cabins, speed, mode)
        self.parked_spots = []
        self.aircraft_specs = []
        self.boat_specs = []
        self.pickup_specs = []
        self.poi = {}
        self.map_labels = []
        self.root = None
        self.night_np = None
        self.water_np = None
        self.reserved = {"hospital": (8, 6), "police": (9, 6), "ammo": (5, 4),
                         "spray1": (4, 1), "spray2": (12, 1), "home": (0, 5),
                         "stadium": (13, 10), "coliseum": (9, 5), "capitol": (6, 10),
                         "donut": (3, 1), "watts": (11, 0)}
        self.reserved_blocks = set(self.reserved.values())

    # ---------------- builders / helpers ----------------

    def _mb(self, x, y, mat="plain"):
        key = (int(x // 260), int(y // 260), mat)
        if key not in self.chunks:
            self.chunks[key] = MeshBuilder("chunk%s" % (key,))
        return self.chunks[key]

    def _b(self, x, y):
        return self._mb(x, y, "plain")

    def add_collider(self, x0, x1, y0, y1, z0, z1):
        col = (min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1), z0, z1)
        self.colliders.append(col)
        c0, c1 = int(col[0] // 24), int(col[1] // 24)
        r0, r1 = int(col[2] // 24), int(col[3] // 24)
        for i in range(c0, c1 + 1):
            for j in range(r0, r1 + 1):
                self.cells.setdefault((i, j), []).append(col)

    def query_colliders(self, x, y, r):
        out = []
        c0, c1 = int((x - r) // 24), int((x + r) // 24)
        r0, r1 = int((y - r) // 24), int((y + r) // 24)
        seen = set()
        for i in range(c0, c1 + 1):
            for j in range(r0, r1 + 1):
                for col in self.cells.get((i, j), ()):
                    if id(col) not in seen:
                        seen.add(id(col))
                        out.append(col)
        return out

    def _ao_pad(self, cx, cy, rx, ry, alpha=0.16):
        """Soft octagonal contact-shadow decal under a structure."""
        b = self.decal_b
        z = self.ground.height(cx, cy) + 0.045
        pts = []
        for k in range(8):
            a = math.tau * (k + 0.5) / 8
            pts.append((cx + math.cos(a) * rx * 1.35, cy + math.sin(a) * ry * 1.35))
        for k in range(1, 7):
            b.add_tri((pts[0][0], pts[0][1], z), (pts[k][0], pts[k][1], z),
                      (pts[k + 1][0], pts[k + 1][1], z), (0, 0, 0, alpha), (0, 0, 1))

    def road_half(self, axis, idx):
        return C.ROAD_HALF_MAJOR if idx % C.MAJOR_EVERY == 0 else C.ROAD_HALF_MINOR

    def district(self, x, y):
        dx0, dx1, dy0, dy1 = C.DOWNTOWN
        if dx0 <= x <= dx1 and dy0 <= y <= dy1:
            return "downtown"
        px0, px1, py0, py1 = C.PARK
        if px0 <= x <= px1 and py0 <= y <= py1:
            return "park"
        if y < C.INDUSTRIAL_Y1:
            return "industrial"
        if x < C.BEACHTOWN_X1:
            return "beach"
        return "residential"

    def road_name_at(self, x, y, z):
        if z > 5:
            if abs(y - C.FREEWAY_Y) < C.FREEWAY_HALF + 10 and C.FREEWAY_X0 < x < C.FREEWAY_X1:
                return "Santa Monica Fwy (10)"
            if abs(x - C.FWY110_X) < C.FWY110_HALF + 10 and C.FWY110_Y0 < y < C.FWY110_Y1:
                return "Harbor Fwy (110)"
            if abs(y - C.BRIDGE_Y) < 14:
                return "Harbor Gate Bridge"
        if abs(x - C.FWY405_X) < 14 and C.BASIN_Y0 < y < C.BASIN_Y1:
            return "San Diego Fwy (405)"
        best, name = 10.0, None
        for idx, X in enumerate(self.roads_v):
            d = abs(x - X)
            if d < self.road_half("v", idx) + 3 and d < best:
                best, name = d, C.NAMES_V[idx]
        for idx, Y in enumerate(C.ROADS_H):
            if abs(Y - C.CREEK_Y) < 1:
                continue
            d = abs(y - Y)
            if d < self.road_half("h", idx) + 3 and d < best:
                best, name = d, C.NAMES_H[idx]
        return name

    # ---------------- build ----------------

    def build(self):
        rng = random.Random(self.seed)
        self.root = self.render.attachNewNode("city")
        self._terrain()
        self._water()
        self._roads()
        self._blocks(rng)
        self._freeway10()
        self._freeway110()
        self._fwy405()
        self._fwy101()
        self._bridges()
        self._traffic_lights()
        self._power_lines()
        self._billboards()
        self._pier(rng)
        self._marina(rng)
        self._lifeguards(rng)
        self._beach_props(rng)
        self._lax(rng)
        self._sign()
        self._observatory()
        self._bowl()
        self._hill_road()
        self._port(rng)
        self._vt_bridge()
        self._civics()
        self._bounds()
        for (ci, cj, mat), b in self.chunks.items():
            if b.empty:
                continue
            np = b.build(self.root)
            self.mat_nodes.setdefault(mat, []).append(np)
        for fb in self.facade_bs:
            if not fb.empty:
                np = fb.build(self.root)
                self.facade_nps.append(np)
        self.water_np = self.water_b.build(self.root)
        self.water_np.setTransparency(True)
        if not self.decal_b.empty:
            dn = self.decal_b.build(self.root)
            dn.setTransparency(True)
            dn.setDepthWrite(False)
        self.night_np = self.night_b.build(self.root)
        self.night_np.setTransparency(True)
        self.night_np.setLightOff()
        self.night_np.hide()
        self.lights_g = self.lights_g_b.build(self.root)
        self.lights_r = self.lights_r_b.build(self.root)
        for np in (self.lights_g, self.lights_r):
            np.setLightOff()
        self._minimap()
        return self.root

    # ---------------- terrain & water ----------------

    def ground_color(self, x, y):
        if self.ground.is_wet(x, y, 5):
            return OCEAN
        if x < coast_sand_x(y) + 12:
            if C.LAX_Y0 < y < C.LAX_Y1 and x < -1430:
                return (0.55, 0.55, 0.52)
            return SAND
        if abs(y - C.CREEK_Y) < C.RIVER_HALF_TOP + 4 and x < C.RIVER_X:
            return CONCRETE
        if abs(x - C.RIVER_X) < C.RIVER_HALF_TOP + 4:
            return CONCRETE
        if y > 830:
            h = math.sin(x * 0.013) * math.cos(y * 0.017)
            return DRYGRASS if h > -0.3 else (0.45, 0.48, 0.30)
        if y < C.BASIN_Y0 + 6:
            return CONCRETE
        d = self.district(x, y)
        if d == "park":
            return GRASS
        if d == "beach":
            return (0.62, 0.58, 0.52)
        if d == "industrial":
            return DIRT
        return (0.50, 0.47, 0.40)

    def _terrain_mat(self, x, y):
        if self.ground.is_wet(x, y, 5):
            return "plain"
        if x < coast_sand_x(y) + 12:
            if C.LAX_Y0 < y < C.LAX_Y1 and x < -1430:
                return "concrete"
            return "sand"
        if abs(y - C.CREEK_Y) < C.RIVER_HALF_TOP + 4 and x < C.RIVER_X:
            return "concrete"
        if abs(x - C.RIVER_X) < C.RIVER_HALF_TOP + 4:
            return "concrete"
        if y > 830:
            return "grass"
        if y < C.BASIN_Y0 + 6:
            return "concrete"
        return "plain"

    def _grid(self, x0, x1, y0, y1, step):
        g = self.ground
        nx = max(1, int((x1 - x0) / step))
        ny = max(1, int((y1 - y0) / step))
        for i in range(nx):
            for j in range(ny):
                ax, ay = x0 + i * (x1 - x0) / nx, y0 + j * (y1 - y0) / ny
                bx, by = x0 + (i + 1) * (x1 - x0) / nx, y0 + (j + 1) * (y1 - y0) / ny
                mx, my = (ax + bx) / 2, (ay + by) / 2
                b = self._mb(mx, my, self._terrain_mat(mx, my))
                c = self.ground_color(mx, my)
                b.add_quad((ax, ay, g.height(ax, ay)), (bx, ay, g.height(bx, ay)),
                           (bx, by, g.height(bx, by)), (ax, by, g.height(ax, by)), c)

    def _terrain(self):
        self._grid(-1750, 1560, 820, 1545, 24)
        self._grid(-2450, -1390, -1650, 820, 22)
        self._grid(-1390, C.RIVER_X - 44, C.CREEK_Y - 44, C.CREEK_Y + 44, 11)
        self._grid(C.RIVER_X - 46, C.RIVER_X + 46, -1560, 830, 12)
        self._grid(-1390, 1560, -1650, C.BASIN_Y0 + 10, 26)
        self._grid(-1390, C.RIVER_X - 44, C.BASIN_Y0 + 10, C.CREEK_Y - 44, 90)
        self._grid(-1390, C.RIVER_X - 44, C.CREEK_Y + 44, 820, 90)
        self._grid(C.RIVER_X + 44, 1560, C.BASIN_Y0 + 10, 820, 90)

    def _water(self):
        w = self.water_b
        wc = (*OCEAN, 0.88)
        w.add_rect(-2600, C.LAX_Y1 + 60, C.OCEAN_X + 14, 1560, C.WATER_Z, wc)
        w.add_rect(-2600, -1650, C.OCEAN_X + 14, C.LAX_Y0 - 60, C.WATER_Z, wc)
        w.add_rect(-2600, C.LAX_Y0 - 60, -2210, C.LAX_Y1 + 60, C.WATER_Z, wc)
        w.add_rect(-1700, C.PORT_Y0 - 260, 1600, C.PORT_Y0 - 6, C.WATER_Z, wc)
        # layered surf: three foam bands, animated by alpha pulsing in gfx
        for k, (off, al) in enumerate(((8, 0.65), (16, 0.38), (26, 0.22))):
            w.add_rect(C.OCEAN_X + off - 3, -640, C.OCEAN_X + off + 1, 1540,
                       C.WATER_Z + 0.05 + k * 0.01, (0.95, 0.97, 0.95, al))
        w.add_rect(C.BASIN_X0 - 30, C.CREEK_Y - 8, C.RIVER_X, C.CREEK_Y + 8,
                   -C.RIVER_DEPTH + 0.45, (0.30, 0.45, 0.42, 0.85))
        w.add_rect(C.RIVER_X - 8, -1450, C.RIVER_X + 8, 820, -C.RIVER_DEPTH + 0.45,
                   (0.30, 0.45, 0.42, 0.85))

    # ---------------- roads & streetscape ----------------

    def _roads(self):
        g = self.ground
        y_lo, y_hi = C.ROADS_H[0] - 40, C.ROADS_H[-1] + 40
        x_lo, x_hi = C.ROADS_V[0] - 40, C.ROADS_V[-1] + 40
        rngm = random.Random(8)
        for idx, X in enumerate(self.roads_v):
            half = self.road_half("v", idx)
            y = y_lo
            while y < y_hi:
                y2 = min(y_hi, y + 130)
                self._mb(X, (y + y2) / 2, "asphalt").add_rect(X - half, y, X + half, y2,
                                                              0.030, ASPHALT_V)
                y = y2
            self._road_marks("v", idx, X, half, y_lo, y_hi)
            self._manholes("v", X, y_lo, y_hi, rngm)
        for idx, Y in enumerate(C.ROADS_H):
            if abs(Y - C.CREEK_Y) < 1:
                continue
            half = self.road_half("h", idx)
            x = x_lo
            while x < x_hi:
                x2 = min(x_hi, x + 130)
                self._mb((x + x2) / 2, Y, "asphalt").add_rect(x, Y - half, x2, Y + half,
                                                              0.020, ASPHALT)
                x = x2
            self._road_marks("h", idx, Y, half, x_lo, x_hi)
            self._manholes("h", Y, x_lo, x_hi, rngm)
        # street lamps + palms + bus benches along majors
        rngl = random.Random(5)
        for idx, X in enumerate(self.roads_v):
            if idx % C.MAJOR_EVERY:
                continue
            half = self.road_half("v", idx)
            y = y_lo + 30
            n = 0
            while y < y_hi - 30:
                if abs(y - C.CREEK_Y) > 42:
                    for side in (-1, 1):
                        self._lamp(X + side * (half + 1.0), y)
                    if rngl.random() < 0.75:
                        for side in (-1, 1):
                            self._palm(self._b(X, y + 20), X + side * (half + 1.8), y + 20,
                                       g.height(X, y + 20), rngl)
                    if n % 3 == 2:
                        self._bus_stop(X + half + 2.6, y + 8, math.pi / 2)
                n += 1
                y += 62

    def _manholes(self, axis, L, lo, hi, rng):
        t = lo + rng.uniform(30, 80)
        while t < hi - 30:
            off = rng.choice((-2.2, 2.2))
            x, y = (L + off, t) if axis == "v" else (t, L + off)
            self._b(x, y).add_cylinder(x, y, 0.055, 0.55, 0.012, (0.16, 0.16, 0.17),
                                       sides=10)
            t += rng.uniform(70, 130)

    def _road_marks(self, axis, idx, L, half, lo, hi):
        major = idx % C.MAJOR_EVERY == 0
        crossings = self.roads_h if axis == "v" else self.roads_v
        z = 0.05 if axis == "v" else 0.045
        t = lo
        dash, gap = (5.0, 7.0) if not major else (60.0, 0.0)
        while t < hi:
            t2 = min(hi, t + dash)
            blocked = any(abs((t + t2) / 2 - cL) < 11 for cL in crossings)
            if not blocked:
                b = self._b(L, (t + t2) / 2) if axis == "v" else self._b((t + t2) / 2, L)
                if axis == "v":
                    if major:
                        b.add_rect(L - 0.35, t, L - 0.12, t2, z, YELLOW)
                        b.add_rect(L + 0.12, t, L + 0.35, t2, z, YELLOW)
                        b.add_rect(L - 3.6, t, L - 3.35, t2 - 3, z, WHITE_PAINT)
                        b.add_rect(L + 3.35, t, L + 3.6, t2 - 3, z, WHITE_PAINT)
                    else:
                        b.add_rect(L - 0.12, t, L + 0.12, t2, z, YELLOW)
                else:
                    if major:
                        b.add_rect(t, L - 0.35, t2, L - 0.12, z, YELLOW)
                        b.add_rect(t, L + 0.12, t2, L + 0.35, z, YELLOW)
                        b.add_rect(t, L - 3.6, t2 - 3, L - 3.35, z, WHITE_PAINT)
                        b.add_rect(t, L + 3.35, t2 - 3, L + 3.6, z, WHITE_PAINT)
                    else:
                        b.add_rect(t, L - 0.12, t2, L + 0.12, z, YELLOW)
            t = t2 + gap

    def _lamp(self, x, y):
        z = self.ground.height(x, y)
        b = self._b(x, y)
        b.add_box(x, y, z, 0.22, 0.22, 6.0, (0.30, 0.30, 0.33))
        b.add_box(x, y, z + 5.9, 0.18, 2.2, 0.16, (0.30, 0.30, 0.33))
        b.add_box(x, y + 1.0, z + 5.75, 0.35, 0.8, 0.18, (0.9, 0.85, 0.6))
        self.night_b.add_rect(x - 3.2, y - 2.4, x + 3.2, y + 4.4, z + 0.11,
                              (0.95, 0.80, 0.45, 0.28))

    def _bus_stop(self, x, y, heading):
        b = self._b(x, y)
        z = self.ground.height(x, y)
        b.add_box(x, y, z + 0.45, 0.5, 3.0, 0.12, (0.55, 0.35, 0.20))       # seat
        b.add_box(x + 0.25, y, z + 0.45, 0.10, 3.0, 0.75, (0.55, 0.35, 0.20))
        for sy in (-1.2, 1.2):
            b.add_box(x, y + sy, z, 0.12, 0.12, 0.45, (0.25, 0.25, 0.28))
        b.add_box(x + 0.8, y - 1.8, z, 0.12, 0.12, 2.8, (0.3, 0.3, 0.33))
        b.add_box(x + 0.8, y - 1.8, z + 2.5, 0.06, 0.7, 0.5, (0.20, 0.35, 0.75))

    def _hydrant(self, x, y):
        b = self._b(x, y)
        z = self.ground.height(x, y)
        red = (0.80, 0.15, 0.12)
        b.add_cylinder(x, y, z, 0.16, 0.55, red, sides=8)
        b.add_dome(x, y, z + 0.55, 0.16, red, sides=8, rings=2)
        b.add_box(x, y, z + 0.32, 0.5, 0.14, 0.12, red)
        self.add_collider(x - 0.18, x + 0.18, y - 0.18, y + 0.18, z, z + 0.7)

    def _parking_meter(self, x, y):
        b = self._b(x, y)
        z = self.ground.height(x, y)
        b.add_box(x, y, z, 0.07, 0.07, 1.1, (0.4, 0.4, 0.43))
        b.add_box(x, y, z + 1.1, 0.22, 0.10, 0.28, (0.55, 0.55, 0.58))

    def _power_lines(self):
        """Wood poles with sagging lines along the minor avenues — very LA."""
        dark = (0.16, 0.15, 0.14)
        for idx, X in enumerate(self.roads_v):
            if idx % C.MAJOR_EVERY == 0 or idx % 2 == 0:
                continue
            half = self.road_half("v", idx)
            px = X + half + 1.9
            tops = []
            y = C.ROADS_H[0] - 10
            while y < C.ROADS_H[-1] + 10:
                near_cross = any(abs(y - Y) < 18 for Y in C.ROADS_H)
                if not near_cross and abs(y - C.CREEK_Y) > 45:
                    z = self.ground.height(px, y)
                    b = self._b(px, y)
                    b.add_cylinder(px, y, z, 0.15, 8.6, (0.42, 0.33, 0.24), sides=6)
                    b.add_box(px, y, z + 8.0, 1.9, 0.14, 0.14, (0.42, 0.33, 0.24))
                    tops.append((y, z + 8.05))
                else:
                    if tops and len(tops) >= 2:
                        self._string_wires(px, tops, dark)
                    tops = []
                y += 55
            if len(tops) >= 2:
                self._string_wires(px, tops, dark)

    def _string_wires(self, px, tops, color):
        b = self._b(px, tops[0][0])
        for k in range(len(tops) - 1):
            (y0, z0), (y1, z1) = tops[k], tops[k + 1]
            for off in (-0.8, 0.0, 0.8):
                pts = []
                for s in range(4):
                    tt = s / 3
                    sag = math.sin(tt * math.pi) * 0.9
                    pts.append((y0 + (y1 - y0) * tt, z0 + (z1 - z0) * tt - sag))
                for s in range(3):
                    (ya, za), (yb, zb) = pts[s], pts[s + 1]
                    b.add_quad((px + off, ya, za - 0.035), (px + off, yb, zb - 0.035),
                               (px + off, yb, zb + 0.035), (px + off, ya, za + 0.035),
                               color, (1, 0, 0))

    def _billboards(self):
        rng = random.Random(21)
        spots = [(-700, C.FREEWAY_Y - C.FREEWAY_HALF - 16, 180),
                 (-80, C.FREEWAY_Y + C.FREEWAY_HALF + 16, 0),
                 (420 - 60, C.FREEWAY_Y - C.FREEWAY_HALF - 16, 180),
                 (980, C.FREEWAY_Y + C.FREEWAY_HALF + 16, 0),
                 (C.FWY405_X + 17, -260, 90),
                 (C.FWY405_X - 17, 320, 270)]
        for i, (x, y, hdg) in enumerate(spots):
            title, tag = BILLBOARD_ADS[i % len(BILLBOARD_ADS)]
            bg = rng.choice([(0.85, 0.30, 0.20), (0.16, 0.35, 0.55), (0.90, 0.75, 0.20),
                             (0.20, 0.20, 0.24), (0.55, 0.25, 0.55)])
            b = self._b(x, y)
            z = self.ground.height(x, y)
            for sx in (-2.6, 2.6):
                ox, oy = sx * math.cos(math.radians(hdg)), sx * math.sin(math.radians(hdg))
                b.add_box(x + ox, y + oy, z, 0.35, 0.35, 9.0, (0.35, 0.35, 0.38))
            b.add_box(x, y, z + 9.0, 9.6, 0.5, 4.6, (0.9, 0.88, 0.84), heading=math.radians(hdg))
            b.add_box(x, y, z + 9.2, 8.8, 0.62, 4.0, bg, heading=math.radians(hdg))
            fx = math.sin(math.radians(hdg)) * 0.45
            fy = -math.cos(math.radians(hdg)) * 0.45
            self._text(title, x + fx, y + fy, z + 11.6, 1.5, hpr=(hdg, 0, 0))
            self._text(tag, x + fx, y + fy, z + 10.2, 0.85, hpr=(hdg, 0, 0),
                       color=(0.95, 0.93, 0.85, 1))
            self.add_collider(x - 1, x + 1, y - 1, y + 1, z, z + 9)

    # ---------------- city blocks ----------------

    def _block_rect(self, i, j):
        xs, ys = self.roads_v, C.ROADS_H
        x0 = xs[i] + self.road_half("v", i) + C.SIDEWALK_W
        x1 = xs[i + 1] - self.road_half("v", i + 1) - C.SIDEWALK_W
        y0 = ys[j] + self.road_half("h", j) + C.SIDEWALK_W
        y1 = ys[j + 1] - self.road_half("h", j + 1) - C.SIDEWALK_W
        return x0, x1, y0, y1

    def _block_center(self, tag):
        i, j = self.reserved[tag]
        x0, x1, y0, y1 = self._block_rect(i, j)
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _sidewalk_and_curb(self, x0, x1, y0, y1):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        sw = C.SIDEWALK_W
        b = self._mb(cx, cy, "concrete")
        b.add_rect(x0 - sw, y0 - sw, x1 + sw, y1 + sw, 0.075, SIDEWALK)
        pb = self._b(cx, cy)
        for (ax0, ay0, ax1, ay1) in ((x0 - sw, y0 - sw, x1 + sw, y0 - sw + 0.28),
                                     (x0 - sw, y1 + sw - 0.28, x1 + sw, y1 + sw),
                                     (x0 - sw, y0 - sw, x0 - sw + 0.28, y1 + sw),
                                     (x1 + sw - 0.28, y0 - sw, x1 + sw, y1 + sw)):
            pb.add_box((ax0 + ax1) / 2, (ay0 + ay1) / 2, 0.0,
                       ax1 - ax0, ay1 - ay0, 0.14, CURB)

    def _blocks(self, rng):
        xs, ys = self.roads_v, C.ROADS_H
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                x0, x1, y0, y1 = self._block_rect(i, j)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if abs(cy - C.CREEK_Y) < 100 or abs(cx - C.RIVER_X) < 110:
                    self._channel_block(rng, x0, x1, y0, y1, cx, cy)
                    continue
                brng = random.Random(self.seed * 1000 + i * 57 + j)
                d = self.district(cx, cy)
                self._sidewalk_and_curb(x0, x1, y0, y1)
                b = self._b(cx, cy)
                if (i, j) in self.reserved_blocks:
                    self._mb(cx, cy, "concrete").add_rect(x0, y0, x1, y1, 0.09,
                                                          (0.48, 0.47, 0.44))
                    continue
                if d == "downtown":
                    self._mb(cx, cy, "concrete").add_rect(x0, y0, x1, y1, 0.09,
                                                          (0.45, 0.44, 0.42))
                    self._downtown_block(b, brng, i, j, x0, x1, y0, y1)
                elif d == "park":
                    self._park_block(b, brng, x0, x1, y0, y1)
                elif d == "industrial":
                    b.add_rect(x0, y0, x1, y1, 0.09, _vary(brng, DIRT, 0.03))
                    self._industrial_block(b, brng, x0, x1, y0, y1)
                elif d == "beach":
                    self._mb(cx, cy, "concrete").add_rect(x0, y0, x1, y1, 0.09,
                                                          (0.60, 0.56, 0.50))
                    self._beach_block(b, brng, i, j, x0, x1, y0, y1)
                else:
                    if brng.random() < 0.30:
                        self._mb(cx, cy, "concrete").add_rect(x0, y0, x1, y1, 0.09,
                                                              (0.52, 0.50, 0.45))
                        self._commercial_block(b, brng, x0, x1, y0, y1)
                    else:
                        self._mb(cx, cy, "grass").add_rect(x0, y0, x1, y1, 0.09,
                                                           _vary(brng, (0.42, 0.50, 0.30), 0.04))
                        self._residential_block(b, brng, x0, x1, y0, y1)

    def _channel_block(self, rng, x0, x1, y0, y1, cx, cy):
        b = self._b(cx, cy)
        for _ in range(2):
            col = rng.choice([(0.9, 0.3, 0.5), (0.3, 0.8, 0.9), (0.95, 0.8, 0.2),
                              (0.5, 0.9, 0.4)])
            z0 = -C.RIVER_DEPTH + 1.2
            if abs(cy - C.CREEK_Y) < 100 and x1 < C.RIVER_X:
                gx = rng.uniform(x0 + 8, x1 - 8)
                side = 1 if cy > C.CREEK_Y else -1
                wy = C.CREEK_Y + side * (C.RIVER_HALF_FLAT + 6)
                b.add_quad((gx - 4, wy, z0), (gx + 4, wy, z0), (gx + 4, wy, z0 + 2.2),
                           (gx - 4, wy, z0 + 2.2), (*col, 0.9), (0, -side, 0))
            elif abs(cx - C.RIVER_X) < 110:
                gy = rng.uniform(y0 + 8, y1 - 8)
                side = 1 if cx > C.RIVER_X else -1
                wx = C.RIVER_X + side * (C.RIVER_HALF_FLAT + 6)
                b.add_quad((wx, gy - 4, z0), (wx, gy + 4, z0), (wx, gy + 4, z0 + 2.2),
                           (wx, gy - 4, z0 + 2.2), (*col, 0.9), (-side, 0, 0))

    # ---------------- residential detail ----------------

    def _window(self, b, x, y, z, w, h, face):
        """Framed window on a wall; face is the outward normal axis ('n','s','e','w')."""
        d = 0.09
        if face in ("n", "s"):
            sy = 1 if face == "n" else -1
            b.add_box(x, y + sy * d / 2, z - 0.08, w + 0.24, d, 0.10, FRAME_WHITE)
            b.add_box(x, y + sy * d / 2, z + h, w + 0.24, d, 0.10, FRAME_WHITE)
            b.add_box(x - w / 2 - 0.07, y + sy * d / 2, z, 0.14, d, h, FRAME_WHITE)
            b.add_box(x + w / 2 + 0.07, y + sy * d / 2, z, 0.14, d, h, FRAME_WHITE)
            b.add_quad((x - w / 2, y + sy * 0.02, z), (x + w / 2, y + sy * 0.02, z),
                       (x + w / 2, y + sy * 0.02, z + h), (x - w / 2, y + sy * 0.02, z + h),
                       GLASS_DARK, (0, sy, 0))
        else:
            sx = 1 if face == "e" else -1
            b.add_box(x + sx * d / 2, y, z - 0.08, d, w + 0.24, 0.10, FRAME_WHITE)
            b.add_box(x + sx * d / 2, y, z + h, d, w + 0.24, 0.10, FRAME_WHITE)
            b.add_box(x + sx * d / 2, y - w / 2 - 0.07, z, d, 0.14, h, FRAME_WHITE)
            b.add_box(x + sx * d / 2, y + w / 2 + 0.07, z, d, 0.14, h, FRAME_WHITE)
            b.add_quad((x + sx * 0.02, y - w / 2, z), (x + sx * 0.02, y + w / 2, z),
                       (x + sx * 0.02, y + w / 2, z + h), (x + sx * 0.02, y - w / 2, z + h),
                       GLASS_DARK, (sx, 0, 0))

    def _house(self, rng, hx, hy, lot_w, lot_d, front_y):
        """A fully dressed single-family house. Front faces -y (the street side)."""
        b = self._b(hx, hy)
        stucco = self._mb(hx, hy, "stucco")
        roofb = self._mb(hx, hy, "roof")
        grass = self._mb(hx, hy, "grass")
        col = _vary(rng, rng.choice(STUCCO), 0.04)
        w, d = rng.uniform(9.5, 12), rng.uniform(7.5, 9.5)
        hh = rng.uniform(3.0, 3.8)
        # yard
        grass.add_rect(hx - lot_w / 2 + 0.6, hy - lot_d / 2 + 0.6,
                       hx + lot_w / 2 - 0.6, hy + lot_d / 2 - 0.6, 0.1,
                       _vary(rng, (0.40, 0.50, 0.28), 0.05))
        # foundation + walls (AO-darkened base) + tiled roof with eaves
        b.add_box(hx, hy, 0.0, w + 0.3, d + 0.3, 0.28, (0.62, 0.60, 0.57))
        stucco.add_box(hx, hy, 0.28, w, d, hh - 0.28, col, wall_uv=UVS_STUCCO, ao=0.18)
        roof_col = _vary(rng, ROOF_TILE, 0.05)
        roofb.add_gable(hx, hy, hh, w + 1.4, d + 1.4, rng.uniform(1.5, 2.0), roof_col,
                        uv=UVS_ROOF, end_color=tuple(v * 0.92 for v in col))
        b.add_box(hx, hy, hh - 0.14, w + 1.5, d + 1.5, 0.14,
                  tuple(v * 0.8 for v in col))     # eave fascia
        self.add_collider(hx - w / 2, hx + w / 2, hy - d / 2, hy + d / 2, 0, hh + 2.0)
        self._ao_pad(hx, hy, w / 2 + 0.8, d / 2 + 0.8)
        # chimney
        if rng.random() < 0.55:
            cxx = hx + rng.uniform(-w / 3, w / 3)
            b.add_box(cxx, hy + d / 4, hh + 0.6, 0.8, 0.8, 1.6, (0.55, 0.35, 0.28))
            b.add_box(cxx, hy + d / 4, hh + 2.2, 1.0, 1.0, 0.18, (0.45, 0.44, 0.42))
        # front: door + steps + windows; canopy or full porch
        door_x = hx + rng.choice((-1, 1)) * w * 0.22
        fy = hy - d / 2
        b.add_box(door_x, fy - 0.05, 0.28, 1.3, 0.16, 2.2, FRAME_WHITE)
        b.add_quad((door_x - 0.5, fy - 0.14, 0.3), (door_x + 0.5, fy - 0.14, 0.3),
                   (door_x + 0.5, fy - 0.14, 2.3), (door_x - 0.5, fy - 0.14, 2.3),
                   rng.choice([(0.45, 0.25, 0.15), (0.25, 0.30, 0.40), (0.55, 0.15, 0.12)]),
                   (0, -1, 0))
        b.add_box(door_x, fy - 0.6, 0.0, 1.8, 1.0, 0.16, (0.62, 0.60, 0.57))
        b.add_box(door_x, fy - 1.0, 0.0, 1.8, 0.6, 0.08, (0.62, 0.60, 0.57))
        if rng.random() < 0.4:   # porch
            b.add_box(door_x, fy - 1.1, 2.5, 3.6, 2.4, 0.18, tuple(v * 0.85 for v in col))
            for sx in (-1.5, 1.5):
                b.add_box(door_x + sx, fy - 2.0, 0, 0.16, 0.16, 2.5, FRAME_WHITE)
        wz = 1.0
        for wx in (hx - w * 0.30, hx + w * 0.30):
            if abs(wx - door_x) > 1.6:
                self._window(b, wx, fy, wz, 1.4, 1.2, "s")
        self._window(b, hx - w / 2, hy + rng.uniform(-1, 1), wz, 1.2, 1.1, "w")
        self._window(b, hx + w / 2, hy + rng.uniform(-1, 1), wz, 1.2, 1.1, "e")
        self._window(b, hx + rng.uniform(-2, 2), hy + d / 2, wz, 1.4, 1.2, "n")
        # garage + concrete driveway to the street edge
        if rng.random() < 0.5 and lot_w > w + 7:
            gx = hx + (w / 2 + 2.8) * rng.choice((-1, 1))
            gw = 4.6
            stucco.add_box(gx, hy - d / 2 + 2.4, 0, gw, 5.0, 2.7, col,
                           wall_uv=UVS_STUCCO, ao=0.18)
            roofb.add_gable(gx, hy - d / 2 + 2.4, 2.7, gw + 1.0, 5.8, 1.0, roof_col,
                            uv=UVS_ROOF, end_color=tuple(v * 0.92 for v in col))
            gdy = hy - d / 2 - 0.11
            self._mb(hx, hy, "metal").add_quad(
                (gx - gw / 2 + 0.4, gdy, 0.15), (gx + gw / 2 - 0.4, gdy, 0.15),
                (gx + gw / 2 - 0.4, gdy, 2.2), (gx - gw / 2 + 0.4, gdy, 2.2),
                (0.88, 0.87, 0.84), (0, -1, 0),
                uvs=((0, 0), (gw / UVS_METAL, 0), (gw / UVS_METAL, 2 / UVS_METAL),
                     (0, 2 / UVS_METAL)))
            self.add_collider(gx - gw / 2, gx + gw / 2, hy - d / 2, hy + 2.4, 0, 3.7)
            self._mb(hx, hy, "concrete").add_rect(gx - 1.6, front_y, gx + 1.6,
                                                  hy - d / 2 - 0.1, 0.11, (0.66, 0.64, 0.60))
        else:
            self._mb(hx, hy, "concrete").add_rect(door_x - 0.8, front_y, door_x + 0.8,
                                                  fy - 0.9, 0.11, (0.68, 0.66, 0.62))
        # yard fence (picket or block wall) on three sides
        if rng.random() < 0.55:
            fence_col = FRAME_WHITE if rng.random() < 0.6 else (0.72, 0.68, 0.60)
            fz, fh = 0.0, rng.uniform(0.8, 1.1)
            ex0, ex1 = hx - lot_w / 2 + 0.7, hx + lot_w / 2 - 0.7
            ey1 = hy + lot_d / 2 - 0.7
            b.add_box((ex0 + ex1) / 2, ey1, fz, ex1 - ex0, 0.12, fh, fence_col)
            b.add_box(ex0, hy + 1, fz, 0.12, lot_d / 2 - 2, fh, fence_col)
            b.add_box(ex1, hy + 1, fz, 0.12, lot_d / 2 - 2, fh, fence_col)
        # pool
        if rng.random() < 0.30:
            px, py = hx + rng.uniform(-2, 2), hy + d / 2 + 2.6
            self._mb(hx, hy, "concrete").add_rect(px - 2.7, py - 2.0, px + 2.7, py + 2.0,
                                                  0.12, (0.75, 0.73, 0.70))
            self.water_b.add_rect(px - 2.2, py - 1.6, px + 2.2, py + 1.6, 0.14,
                                  (0.30, 0.68, 0.80, 0.85))
        if rng.random() < 0.5:
            self._tree(self._b(hx, hy), hx + rng.uniform(-lot_w / 3, lot_w / 3),
                       hy + lot_d / 2 - 2.5, 0.1, rng, purple=rng.random() < 0.3)

    def _residential_block(self, b, rng, x0, x1, y0, y1):
        cols = max(2, int((x1 - x0) / 27))
        rows = max(2, int((y1 - y0) / 32))
        lot_w, lot_d = (x1 - x0) / cols, (y1 - y0) / rows
        for ii in range(cols):
            for jj in range(rows):
                hx = x0 + (ii + 0.5) * lot_w
                hy = y0 + (jj + 0.5) * lot_d
                if rng.random() < 0.10:
                    self._palm(b, hx, hy, 0.1, rng)
                    continue
                self._house(rng, hx, hy, lot_w, lot_d, hy - lot_d / 2)

    # ---------------- commercial detail ----------------

    def _commercial_block(self, b, rng, x0, x1, y0, y1):
        n = max(3, int((x1 - x0) / 15))
        stucco = self._mb((x0 + x1) / 2, (y0 + y1) / 2, "stucco")
        metal = self._mb((x0 + x1) / 2, (y0 + y1) / 2, "metal")
        for k in range(n):
            sx0 = x0 + k * (x1 - x0) / n
            sx1 = x0 + (k + 1) * (x1 - x0) / n
            cxx = (sx0 + sx1) / 2
            col = _vary(rng, rng.choice(STUCCO + PASTEL), 0.04)
            hh = rng.uniform(4.5, 8.5)
            d = rng.uniform(14, 20)
            stucco.add_box(cxx, y0 + d / 2, 0, sx1 - sx0 - 1.5, d, hh, col,
                           wall_uv=UVS_STUCCO, ao=0.15)
            b.add_box(cxx, y0 + d / 2, hh, sx1 - sx0 - 1.0, d + 0.5, 0.5,
                      tuple(v * 0.7 for v in col))
            self._ao_pad(cxx, y0 + d / 2, (sx1 - sx0) / 2, d / 2, 0.13)
            # storefront: glass + mullions + recessed door
            gw = sx1 - sx0 - 3
            b.add_quad((cxx - gw / 2, y0 - 0.01, 0.4), (cxx + gw / 2, y0 - 0.01, 0.4),
                       (cxx + gw / 2, y0 - 0.01, 2.7), (cxx - gw / 2, y0 - 0.01, 2.7),
                       (0.16, 0.20, 0.24), (0, -1, 0))
            for mx in (-gw / 4, 0, gw / 4):
                b.add_box(cxx + mx, y0 - 0.02, 0.4, 0.10, 0.08, 2.3, (0.25, 0.25, 0.28))
            b.add_box(cxx - gw / 2 - 0.3, y0 - 0.02, 0.0, 0.35, 0.10, 3.0, col)
            b.add_box(cxx + gw / 2 + 0.3, y0 - 0.02, 0.0, 0.35, 0.10, 3.0, col)
            # striped awning
            aw_c1 = rng.choice([(0.8, 0.3, 0.3), (0.3, 0.5, 0.8), (0.9, 0.7, 0.2),
                                (0.3, 0.6, 0.45)])
            aw_c2 = (0.93, 0.92, 0.88)
            seg = gw / 6
            for m in range(6):
                ax = cxx - gw / 2 + seg * (m + 0.5)
                cc = aw_c1 if m % 2 == 0 else aw_c2
                b.add_quad((ax - seg / 2, y0 - 1.3, 2.75), (ax + seg / 2, y0 - 1.3, 2.75),
                           (ax + seg / 2, y0 + 0.05, 3.35), (ax - seg / 2, y0 + 0.05, 3.35),
                           cc)
            # sign board over the awning
            sign_bg = rng.choice([(0.85, 0.25, 0.20), (0.15, 0.30, 0.55), (0.90, 0.72, 0.15),
                                  (0.20, 0.45, 0.35), (0.30, 0.20, 0.40)])
            b.add_box(cxx, y0 + 0.15, 3.5, gw * 0.9, 0.35, 1.0, sign_bg)
            if rng.random() < 0.45:
                self._text(rng.choice(SHOP_NAMES), cxx, y0 - 0.08, 3.75, 0.55,
                           color=(0.97, 0.95, 0.90, 1))
            # roof plant
            for _ in range(rng.randint(1, 2)):
                metal.add_box(cxx + rng.uniform(-gw / 3, gw / 3),
                              y0 + d / 2 + rng.uniform(-3, 3), hh + 0.5,
                              2.2, 2.6, 1.1, (0.62, 0.62, 0.64), wall_uv=UVS_METAL)
            self.add_collider(sx0 + 0.7, sx1 - 0.7, y0, y0 + d, 0, hh)
        # rear parking lot + dumpster
        ly0 = y0 + 24
        self._mb((x0 + x1) / 2, (ly0 + y1) / 2, "concrete").add_rect(
            x0, ly0, x1, y1, 0.11, (0.36, 0.36, 0.38))
        px = x0 + 6
        while px < x1 - 6:
            b.add_rect(px, ly0 + 4, px + 0.3, ly0 + 9.5, 0.13, WHITE_PAINT)
            if random.Random(int(px)).random() < 0.4:
                self.parked_spots.append((px + 1.6, ly0 + 6.8, math.pi / 2,
                                          rng.choice(("sedan", "coupe", "van", "pickup",
                                                      "lowrider"))))
            px += 3.2
        dx = rng.uniform(x0 + 4, x1 - 4)
        b.add_box(dx, y1 - 2.5, 0, 2.6, 1.5, 1.4, (0.20, 0.40, 0.25), ao=0.2)
        b.add_box(dx, y1 - 2.5, 1.4, 2.7, 1.6, 0.14, (0.16, 0.32, 0.20))
        self.add_collider(dx - 1.3, dx + 1.3, y1 - 3.25, y1 - 1.75, 0, 1.55)

    # ---------------- downtown detail ----------------

    def _downtown_block(self, b, rng, i, j, x0, x1, y0, y1):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if (i, j) == (11, 8):
            self._city_hall(b, cx, cy)
            return
        if (i, j) == (10, 8):
            self._crown_tower(b, cx, cy)
            return
        if (i, j) == (10, 7):
            self._bonaventure(b, cx, cy)
            return
        if (i, j) == (11, 7):
            self._wilshire_grand(b, cx, cy)
            return
        style = rng.choice(["glass", "glass", "stepped", "slab"])
        w = min(x1 - x0, 92) * rng.uniform(0.55, 0.8)
        d = min(y1 - y0, 92) * rng.uniform(0.55, 0.8)
        hmax = 170 - (abs(cx - 620) + abs(cy - 380)) * 0.14
        h = max(35.0, hmax * rng.uniform(0.55, 1.0))
        col = _vary(rng, rng.choice(GLASS_TOWER), 0.03)
        fb = self.facade_bs[rng.randrange(3)]
        lobby_h = 5.5
        # lobby: dark glass base with entrance canopy + columns
        b.add_box(cx, cy, 0, w + 1.2, d + 1.2, lobby_h, (0.18, 0.22, 0.26),
                  top_color=(0.3, 0.3, 0.33))
        b.add_box(cx, cy - d / 2 - 2.4, 4.2, 12, 4.4, 0.35, (0.85, 0.85, 0.88))
        for sx in (-5, 5):
            b.add_box(cx + sx, cy - d / 2 - 3.8, 0, 0.4, 0.4, 4.2, (0.75, 0.75, 0.78))
        if style == "glass":
            fb.add_facade_box(cx, cy, lobby_h, w, d, h - lobby_h, col,
                              top_color=(0.35, 0.35, 0.38))
            b.add_box(cx, cy, h, w * 0.3, d * 0.3, 4, (0.3, 0.3, 0.33))
        elif style == "stepped":
            fb.add_facade_box(cx, cy, lobby_h, w, d, h * 0.55 - lobby_h, col)
            fb.add_facade_box(cx, cy, h * 0.55, w * 0.72, d * 0.72, h * 0.30, col)
            fb.add_facade_box(cx, cy, h * 0.85, w * 0.45, d * 0.45, h * 0.15, col)
            b.add_box(cx, cy, h, 1.2, 1.2, 12, (0.5, 0.5, 0.55))
        else:
            col = (0.30, 0.32, 0.36)
            fb.add_facade_box(cx, cy, lobby_h, w * 0.7, d * 0.7, h * 1.05 - lobby_h, col,
                              top_color=(0.30, 0.30, 0.33))
        # rooftop plant: penthouse, water tank, antenna cluster
        top = h if style != "slab" else h * 1.05
        b.add_box(cx + w * 0.18, cy + d * 0.15, top, w * 0.22, d * 0.22, 3.2,
                  (0.42, 0.42, 0.46))
        b.add_cylinder(cx - w * 0.2, cy - d * 0.15, top, 1.6, 2.6, (0.55, 0.42, 0.32),
                       sides=8)
        for sx in (-0.9, 0.9):
            b.add_box(cx - w * 0.2 + sx, cy - d * 0.15, top - 0.6, 0.14, 0.14, 0.8,
                      (0.35, 0.35, 0.4))
        self.add_collider(cx - w / 2 - 0.6, cx + w / 2 + 0.6, cy - d / 2 - 0.6,
                          cy + d / 2 + 0.6, 0, h)
        self._ao_pad(cx, cy, w / 2 + 1.4, d / 2 + 1.4, 0.18)
        self._windows(cx, cy, w, d, h, rng)
        # streetside parking meters + trees
        for m in range(5):
            self._parking_meter(x0 + 4 + m * 5.5, y0 - C.SIDEWALK_W * 0.5)
        for _ in range(3):
            tx = rng.uniform(x0 + 4, x1 - 4)
            ty = rng.uniform(y0 + 4, y1 - 4)
            if abs(tx - cx) > w / 2 + 3 or abs(ty - cy) > d / 2 + 3:
                self._palm(b, tx, ty, 0.1, rng)

    def _windows(self, cx, cy, w, d, h, rng):
        z = 5.0
        while z < h - 3:
            for face, (fx, fy, ox, oy) in enumerate(((0, -1, 1, 0), (0, 1, 1, 0),
                                                     (-1, 0, 0, 1), (1, 0, 0, 1))):
                span = w if ox else d
                n = max(1, int(span / 5))
                for k in range(n):
                    if rng.random() > 0.24:
                        continue
                    off = -span / 2 + (k + 0.5) * span / n
                    if ox:
                        px, py = cx + ox * off, cy + fy * (d / 2 + 0.06)
                        self.night_b.add_quad((px - 0.8, py, z), (px + 0.8, py, z),
                                              (px + 0.8, py, z + 1.6), (px - 0.8, py, z + 1.6),
                                              WINDOW_WARM if rng.random() < 0.7 else WINDOW_COOL,
                                              (0, fy, 0))
                    else:
                        px, py = cx + fx * (w / 2 + 0.06), cy + oy * off
                        self.night_b.add_quad((px, py - 0.8, z), (px, py + 0.8, z),
                                              (px, py + 0.8, z + 1.6), (px, py - 0.8, z + 1.6),
                                              WINDOW_WARM if rng.random() < 0.7 else WINDOW_COOL,
                                              (fx, 0, 0))
            z += 6.0

    def _city_hall(self, b, cx, cy):
        white = (0.92, 0.90, 0.84)
        b.add_box(cx, cy, 0, 74, 46, 14, white, ao=0.12)
        b.add_box(cx, cy, 14, 40, 34, 12, white)
        self.facade_bs[2].add_facade_box(cx, cy, 26, 22, 22, 42, white)
        b.add_box(cx, cy, 68, 15, 15, 8, white)
        b.add_cylinder(cx, cy, 76, 7.0, 7, white, sides=10, r_top=1.2)
        for k in range(8):
            a = k * math.tau / 8
            b.add_box(cx + math.cos(a) * 9.5, cy + math.sin(a) * 9.5, 68, 1.4, 1.4, 8, white)
        for k in range(9):
            b.add_box(cx - 32 + k * 8, cy - 21.5, 0, 1.6, 1.6, 12, white)
        self.add_collider(cx - 37, cx + 37, cy - 23, cy + 23, 0, 84)
        self._ao_pad(cx, cy, 39, 25, 0.16)
        self.poi["cityhall"] = (cx, cy)
        self.map_labels.append(("City Hall", cx, cy))

    def _crown_tower(self, b, cx, cy):
        col = (0.55, 0.62, 0.70)
        b.add_cylinder(cx, cy, 0, 17, 178, col, sides=16, top_color=(0.4, 0.4, 0.45))
        b.add_cylinder(cx, cy, 178, 13, 8, (0.85, 0.88, 0.92), sides=16)
        zz = 8.0
        while zz < 172:
            b.add_cylinder(cx, cy, zz, 17.25, 1.2, (0.32, 0.36, 0.42), sides=16)
            zz += 8.0
        self.add_collider(cx - 15, cx + 15, cy - 15, cy + 15, 0, 186)
        self._ao_pad(cx, cy, 19, 19, 0.18)
        self.ground.add_patch(cx - 9, cx + 9, cy - 9, cy + 9, 186.4)
        b.add_cylinder(cx, cy, 186.0, 10, 0.4, (0.30, 0.30, 0.33), sides=12)
        b.add_box(cx, cy, 186.45, 4.5, 0.9, 0.05, WHITE_PAINT)
        b.add_box(cx - 1.8, cy, 186.45, 0.9, 4.5, 0.05, WHITE_PAINT)
        b.add_box(cx + 1.8, cy, 186.45, 0.9, 4.5, 0.05, WHITE_PAINT)
        self.night_b.add_cylinder(cx, cy, 178.2, 13.4, 7.6, (1.0, 0.9, 0.55, 0.5), sides=16,
                                  top=False)
        self.aircraft_specs.append(("heli", cx, cy + 3, 186.4, 0.0))
        self.poi["crown"] = (cx, cy)
        self.map_labels.append(("The Crown", cx, cy))

    def _bonaventure(self, b, cx, cy):
        col = (0.60, 0.66, 0.72)
        b.add_cylinder(cx, cy, 0, 13, 92, col, sides=14, top_color=(0.4, 0.4, 0.44))
        for k in range(4):
            a = k * math.tau / 4 + math.pi / 4
            b.add_cylinder(cx + math.cos(a) * 15, cy + math.sin(a) * 15, 0, 8, 72, col,
                           sides=12, top_color=(0.4, 0.4, 0.44))
        self.add_collider(cx - 23, cx + 23, cy - 23, cy + 23, 0, 92)
        self._ao_pad(cx, cy, 25, 25, 0.16)

    def _wilshire_grand(self, b, cx, cy):
        col = (0.42, 0.52, 0.64)
        self.facade_bs[0].add_facade_box(cx, cy, 0, 34, 22, 160, col,
                                         top_color=(0.5, 0.55, 0.6))
        b.add_quad((cx - 17, cy - 8, 160), (cx + 17, cy - 8, 160), (cx + 17, cy + 4, 174),
                   (cx - 17, cy + 4, 174), (0.85, 0.90, 0.95))
        b.add_quad((cx - 17, cy + 11, 160), (cx + 17, cy + 11, 160), (cx + 17, cy + 4, 174),
                   (cx - 17, cy + 4, 174), (0.75, 0.82, 0.9))
        b.add_cylinder(cx, cy + 4, 174, 0.8, 22, (0.8, 0.82, 0.88), sides=6, r_top=0.2)
        self.add_collider(cx - 17, cx + 17, cy - 11, cy + 11, 0, 174)
        self._ao_pad(cx, cy, 19, 13, 0.16)
        self._windows(cx, cy, 34, 22, 160, random.Random(9))

    # ---------------- industrial / beach / park ----------------

    def _industrial_block(self, b, rng, x0, x1, y0, y1):
        metal = self._mb((x0 + x1) / 2, (y0 + y1) / 2, "metal")
        n = rng.randint(1, 2)
        for k in range(n):
            wx = x0 + (k + 0.5) * (x1 - x0) / n
            w = (x1 - x0) / n * rng.uniform(0.6, 0.8)
            d = (y1 - y0) * rng.uniform(0.45, 0.65)
            wy = rng.uniform(y0 + d / 2 + 2, y1 - d / 2 - 2)
            hh = rng.uniform(7, 11)
            col = _vary(rng, (0.62, 0.60, 0.55), 0.06)
            metal.add_box(wx, wy, 0, w, d, hh, col, top_color=tuple(v * 0.8 for v in col),
                          wall_uv=UVS_METAL, ao=0.15)
            for v in range(3):
                b.add_box(wx - w / 4 + v * w / 4, wy, hh, 2.5, 3, 1.2, (0.5, 0.5, 0.52))
            # roll-up doors + loading dock on the south face
            fy = wy - d / 2
            for m in range(2):
                dx = wx - w / 4 + m * w / 2
                b.add_quad((dx - 2.4, fy - 0.03, 0.9), (dx + 2.4, fy - 0.03, 0.9),
                           (dx + 2.4, fy - 0.03, 4.4), (dx - 2.4, fy - 0.03, 4.4),
                           (0.72, 0.71, 0.68), (0, -1, 0))
                b.add_box(dx, fy - 0.4, 0.7, 5.2, 0.7, 0.25, (0.30, 0.30, 0.32))
            # wall pipes
            px = wx + w / 2 - 0.4
            b.add_cylinder(px, wy - d / 4, 0, 0.14, hh - 0.5, (0.5, 0.52, 0.55), sides=6)
            b.add_cylinder(px, wy + d / 4, 0, 0.14, hh - 0.5, (0.5, 0.52, 0.55), sides=6)
            self.add_collider(wx - w / 2, wx + w / 2, wy - d / 2, wy + d / 2, 0, hh)
            self._ao_pad(wx, wy, w / 2 + 1, d / 2 + 1, 0.14)
        if rng.random() < 0.5:
            tx, ty = rng.uniform(x0 + 8, x1 - 8), y0 + 8
            for s in (-1, 1):
                metal.add_cylinder(tx + s * 5, ty, 0, 3.4, rng.uniform(6, 9),
                                   (0.75, 0.73, 0.68), sides=10)
                self.add_collider(tx + s * 5 - 3.4, tx + s * 5 + 3.4, ty - 3.4, ty + 3.4, 0, 9)
        if rng.random() < 0.30:
            self._pumpjack(rng.uniform(x0 + 12, x1 - 12), y1 - 10)
        self._containers(metal, rng, x0 + 6, y1 - 16, rng.randint(2, 5))

    def _pumpjack(self, x, y):
        b = self._b(x, y)
        b.add_rect(x - 5, y - 4, x + 5, y + 4, 0.1, (0.4, 0.38, 0.34))
        b.add_box(x, y, 0, 1.0, 3.0, 4.2, (0.55, 0.20, 0.15))
        self.add_collider(x - 1, x + 1, y - 2, y + 2, 0, 5)
        pivot = self.root.attachNewNode("pumpjack")
        pivot.setPos(x, y, 4.2)
        mb = MeshBuilder("beam")
        mb.add_box(0, 0, -0.4, 0.8, 7.0, 0.8, (0.55, 0.20, 0.15))
        mb.add_box(0, 3.6, -0.9, 1.2, 1.2, 1.4, (0.3, 0.3, 0.32))
        mb.build(pivot)
        self.anims.append((pivot, [], 0.9, "rock"))

    def _containers(self, b, rng, x, y, count, heading=0.0):
        cols = [(0.62, 0.28, 0.20), (0.25, 0.42, 0.55), (0.30, 0.52, 0.30), (0.72, 0.48, 0.16),
                (0.55, 0.55, 0.58)]
        for k in range(count):
            cx = x + k * 13.0
            col = _vary(rng, rng.choice(cols), 0.03)
            stack = 1 + (rng.random() < 0.45)
            for s in range(stack):
                b.add_box(cx, y, s * 2.7, 12.2, 2.5, 2.6, col if s == 0 else
                          _vary(rng, rng.choice(cols), 0.03), wall_uv=UVS_METAL)
            self.add_collider(cx - 6.1, cx + 6.1, y - 1.25, y + 1.25, 0, 2.7 * stack)

    def _beach_block(self, b, rng, i, j, x0, x1, y0, y1):
        if (i, j) == (0, 4):
            self._mb(x0 + 20, y0 + 13, "concrete").add_rect(x0 + 6, y0 + 6, x0 + 34,
                                                            y0 + 21, 0.12, (0.75, 0.45, 0.28))
            for lx in (x0 + 6, x0 + 34):
                b.add_box(lx, y0 + 13.5, 0, 0.3, 0.3, 3.2, (0.4, 0.4, 0.42))
                b.add_box(lx, y0 + 13.5, 3.2, 1.4, 0.2, 1.0, (0.9, 0.9, 0.9))
            self.poi["courts"] = ((x0 + 20), (y0 + 13))
        stucco = self._mb((x0 + x1) / 2, (y0 + y1) / 2, "stucco")
        n = max(3, int((x1 - x0) / 13))
        for k in range(n):
            sx0 = x0 + k * (x1 - x0) / n
            sx1 = x0 + (k + 1) * (x1 - x0) / n
            col = _vary(rng, rng.choice(PASTEL), 0.05)
            hh = rng.uniform(5, 9)
            d = rng.uniform(12, (y1 - y0) * 0.55)
            cxx, cyy = (sx0 + sx1) / 2, y1 - d / 2
            stucco.add_box(cxx, cyy, 0, sx1 - sx0 - 1.2, d, hh, col,
                           wall_uv=UVS_STUCCO, ao=0.15)
            self.add_collider(sx0 + 0.6, sx1 - 0.6, cyy - d / 2, cyy + d / 2, 0, hh)
            self._ao_pad(cxx, cyy, (sx1 - sx0) / 2, d / 2, 0.13)
            # west-facing balconies with railings
            if hh > 6:
                bz = hh * 0.55
                fy2 = cyy + d / 2
                b.add_box(cxx, fy2 + 0.7, bz, sx1 - sx0 - 3, 1.4, 0.15, (0.85, 0.83, 0.80))
                for m in range(5):
                    bx = cxx - (sx1 - sx0 - 3.4) / 2 + m * (sx1 - sx0 - 3.4) / 4
                    b.add_box(bx, fy2 + 1.35, bz, 0.08, 0.08, 0.9, FRAME_WHITE)
                b.add_box(cxx, fy2 + 1.35, bz + 0.9, sx1 - sx0 - 3, 0.10, 0.08, FRAME_WHITE)
                self._window(b, cxx, fy2, bz + 1.0, 1.6, 1.4, "n")
            if rng.random() < 0.4:
                m = rng.choice([(0.95, 0.4, 0.6), (0.4, 0.8, 0.9), (0.98, 0.8, 0.3)])
                b.add_quad((sx0 + 0.5, cyy + d / 2 + 0.01, 0.5),
                           (sx1 - 0.5, cyy + d / 2 + 0.01, 0.5),
                           (sx1 - 0.5, cyy + d / 2 + 0.01, hh - 1),
                           (sx0 + 0.5, cyy + d / 2 + 0.01, hh - 1), (*m, 0.95), (0, 1, 0))
        for _ in range(3):
            self._palm(b, rng.uniform(x0, x1), rng.uniform(y0, y0 + 14), 0.1, rng)

    def _beach_props(self, rng):
        """Umbrellas, towels, surfboards scattered on the sand."""
        y = -1100
        while y < 780:
            if abs(y - C.PIER_Y) > 55 and abs(y - C.MARINA_Y) > 70:
                for _ in range(rng.randint(0, 3)):
                    x = coast_sand_x(y) - rng.uniform(10, 44)
                    z = self.ground.height(x, y)
                    b = self._b(x, y)
                    r = rng.random()
                    if r < 0.4:
                        pole_c = (0.75, 0.73, 0.70)
                        um_c = rng.choice([(0.9, 0.3, 0.3), (0.25, 0.55, 0.85),
                                           (0.95, 0.75, 0.2), (0.3, 0.7, 0.5)])
                        b.add_cylinder(x, y, z, 0.06, 2.0, pole_c, sides=5)
                        b.add_cylinder(x, y, z + 1.5, 1.6, 0.7, um_c, sides=8, r_top=0.1)
                    elif r < 0.8:
                        tw = rng.choice([(0.9, 0.4, 0.4), (0.4, 0.6, 0.9), (0.95, 0.85, 0.4),
                                         (0.5, 0.85, 0.75)])
                        b.add_rect(x - 0.8, y - 1.4, x + 0.8, y + 1.4, z + 0.03, tw)
                    else:
                        sb_c = rng.choice([(0.95, 0.6, 0.2), (0.3, 0.8, 0.85), (0.9, 0.9, 0.9)])
                        b.add_box(x, y, z, 0.5, 0.16, 2.2, sb_c)
            y += rng.uniform(50, 110)

    def _park_block(self, b, rng, x0, x1, y0, y1):
        self._mb((x0 + x1) / 2, (y0 + y1) / 2, "grass").add_rect(
            x0, y0, x1, y1, 0.06, _vary(rng, GRASS, 0.02))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if rng.random() < 0.4:
            self.water_b.add_rect(cx - 22, cy - 14, cx + 22, cy + 14, 0.12,
                                  (0.25, 0.50, 0.55, 0.9))
            self._mb(cx, cy, "concrete").add_rect(cx - 24, cy - 16, cx + 24, cy + 16,
                                                  0.09, (0.5, 0.48, 0.42))
        self._mb(cx, cy, "concrete").add_rect(x0, cy - 1.5, x1, cy + 1.5, 0.10,
                                              (0.72, 0.68, 0.60))
        self._mb(cx, cy, "concrete").add_rect(cx - 1.5, y0, cx + 1.5, y1, 0.10,
                                              (0.72, 0.68, 0.60))
        for _ in range(3):   # park benches along the path
            bx = rng.uniform(x0 + 8, x1 - 8)
            b.add_box(bx, cy + 2.4, 0.4, 1.8, 0.4, 0.1, (0.5, 0.32, 0.2))
            b.add_box(bx, cy + 2.6, 0.4, 1.8, 0.1, 0.6, (0.5, 0.32, 0.2))
        for _ in range(14):
            tx, ty = rng.uniform(x0 + 3, x1 - 3), rng.uniform(y0 + 3, y1 - 3)
            if abs(tx - cx) < 26 and abs(ty - cy) < 18:
                continue
            if rng.random() < 0.5:
                self._palm(b, tx, ty, 0.1, rng)
            else:
                self._tree(b, tx, ty, 0.1, rng, purple=rng.random() < 0.4)

    def _palm(self, b, x, y, z, rng, h=None):
        h = h or rng.uniform(6.5, 11.0)
        lean = rng.uniform(-0.06, 0.06)
        segs = 4
        px = x
        for i in range(segs):
            px = x + lean * h * (i / segs) ** 1.5 * 3
            b.add_box(px, y, z + h * i / segs, 0.42 - i * 0.06, 0.42 - i * 0.06,
                      h / segs + 0.1, (0.45, 0.36, 0.24))
        topx, topz = px + lean * h * 0.5, z + h
        green = rng.choice(PALM_GREEN)
        for k in range(6):
            a = k * math.tau / 6 + rng.uniform(-0.2, 0.2)
            fx, fy = math.cos(a) * 3.4, math.sin(a) * 3.4
            b.add_tri((topx, y, topz + 0.4),
                      (topx + fx * 0.55 - fy * 0.16, y + fy * 0.55 + fx * 0.16, topz + 0.9),
                      (topx + fx, y + fy, topz - 0.7), green)
            b.add_tri((topx, y, topz + 0.4),
                      (topx + fx, y + fy, topz - 0.7),
                      (topx + fx * 0.55 + fy * 0.16, y + fy * 0.55 - fx * 0.16, topz + 0.9),
                      tuple(v * 0.85 for v in green))
        self.add_collider(x - 0.35, x + 0.35, y - 0.35, y + 0.35, z, z + h * 0.8)

    def _tree(self, b, x, y, z, rng, purple=False):
        h = rng.uniform(3.5, 5.5)
        b.add_box(x, y, z, 0.5, 0.5, h * 0.45, (0.38, 0.30, 0.22))
        green = JACARANDA if purple else rng.choice(TREE_GREEN)
        b.add_dome(x, y, z + h * 0.35, h * 0.5, green, sides=8, rings=3, squash=1.1)
        self.add_collider(x - 0.4, x + 0.4, y - 0.4, y + 0.4, z, z + h * 0.5)

    # ---------------- freeways ----------------

    def _gantry(self, b, x, y, z0, txt, vertical=False):
        if vertical:
            for side in (-1, 1):
                b.add_box(x + side * (C.FWY110_HALF - 0.8), y, z0, 0.5, 0.5, 7.0,
                          (0.45, 0.47, 0.45))
            b.add_box(x, y, z0 + 7.0, 2 * C.FWY110_HALF - 1, 1.0, 0.6, (0.45, 0.47, 0.45))
            b.add_box(x, y, z0 + 4.6, 14, 0.4, 2.4, SIGN_GREEN)
            self._text(txt, x, y - 0.4, z0 + 5.0, scale=1.1, hpr=(0, 0, 0))
        else:
            for side in (-1, 1):
                b.add_box(x, y + side * (C.FREEWAY_HALF - 0.8), z0, 0.5, 0.5, 7.0,
                          (0.45, 0.47, 0.45))
            b.add_box(x, y, z0 + 7.0, 1.0, 2 * C.FREEWAY_HALF - 1, 0.6, (0.45, 0.47, 0.45))
            b.add_box(x, y, z0 + 4.6, 0.4, 14, 2.4, SIGN_GREEN)
            self._text(txt, x - 0.4, y, z0 + 5.0, scale=1.1, hpr=(90, 0, 0))

    def _elevated(self, axis, L, half, z, lo, hi, ramps, name_signs):
        g = self.ground
        deck_top = z + 0.8
        if axis == "h":
            g.add_patch(lo, hi, L - half, L + half, deck_top)
        else:
            g.add_patch(L - half, L + half, lo, hi, deck_top)
        for r in ramps:
            g.add_patch(*r[:6], axis=r[6])
        t = lo
        while t < hi:
            t2 = min(hi, t + 130)
            mid = (t + t2) / 2
            b = self._b(mid, L) if axis == "h" else self._b(L, mid)
            if axis == "h":
                b.add_box(mid, L, z, t2 - t, 2 * half, 0.8, FWY_GRAY, top_color=DECK_TOP,
                          bottom=True)
            else:
                b.add_box(L, mid, z, 2 * half, t2 - t, 0.8, FWY_GRAY, top_color=DECK_TOP,
                          bottom=True)
            for off in (-half / 2, 0, half / 2):
                dd = t
                while dd < t2:
                    if axis == "h":
                        b.add_rect(dd, L + off - 0.12, min(t2, dd + 4), L + off + 0.12,
                                   deck_top + 0.02, WHITE_PAINT)
                    else:
                        b.add_rect(L + off - 0.12, dd, L + off + 0.12, min(t2, dd + 4),
                                   deck_top + 0.02, WHITE_PAINT)
                    dd += 12
            t = t2
        t = lo + 20
        while t < hi - 20:
            if all(not (r[7] - 25 < t < r[8] + 25) for r in ramps):
                if axis == "h":
                    b = self._b(t, L)
                    b.add_cylinder(t, L, 0, 1.1, z, (0.58, 0.56, 0.52), sides=10)
                    self.add_collider(t - 1.1, t + 1.1, L - 1.1, L + 1.1, 0, z)
                else:
                    b = self._b(L, t)
                    b.add_cylinder(L, t, 0, 1.1, z, (0.58, 0.56, 0.52), sides=10)
                    self.add_collider(L - 1.1, L + 1.1, t - 1.1, t + 1.1, 0, z)
            t += 40
        for side in (-1, 1):
            edge = L + side * (half - 0.4)
            t = lo
            while t < hi:
                t2 = min(hi, t + 20)
                in_gap = any(r[7] - 4 < t < r[8] + 4 and r[9] == side for r in ramps)
                if not in_gap:
                    if axis == "h":
                        b = self._b((t + t2) / 2, L)
                        b.add_box((t + t2) / 2, edge, deck_top, t2 - t, 0.5, 1.0,
                                  (0.62, 0.60, 0.56))
                        self.add_collider(t, t2, edge - 0.25, edge + 0.25, deck_top,
                                          deck_top + 1.0)
                    else:
                        b = self._b(L, (t + t2) / 2)
                        b.add_box(edge, (t + t2) / 2, deck_top, 0.5, t2 - t, 1.0,
                                  (0.62, 0.60, 0.56))
                        self.add_collider(edge - 0.25, edge + 0.25, t, t2, deck_top,
                                          deck_top + 1.0)
                t = t2
        for r in ramps:
            x0, x1, y0, y1, z0, z1 = r[:6]
            b = self._b((x0 + x1) / 2, (y0 + y1) / 2)
            if r[6] == "x":
                b.add_quad((x0, y0, z0), (x1, y0, z1), (x1, y1, z1), (x0, y1, z0),
                           (0.35, 0.35, 0.37))
                outer = y0 if abs(y0 - L) > abs(y1 - L) else y1
                b.add_quad((x0, outer, 0), (x1, outer, 0), (x1, outer, z1), (x0, outer, z0),
                           (0.5, 0.48, 0.46))
            else:
                b.add_quad((x0, y0, z0), (x1, y0, z0), (x1, y1, z1), (x0, y1, z1),
                           (0.35, 0.35, 0.37))
                outer = x0 if abs(x0 - L) > abs(x1 - L) else x1
                b.add_quad((outer, y0, 0), (outer, y1, 0), (outer, y1, z1), (outer, y0, z0),
                           (0.5, 0.48, 0.46))
        for (pos, txt) in name_signs:
            if axis == "h":
                self._gantry(self._b(pos, L), pos, L, deck_top, txt)
            else:
                self._gantry(self._b(L, pos), L, pos, deck_top, txt, vertical=True)

    def _freeway10(self):
        Y, Z, H = C.FREEWAY_Y, C.FREEWAY_Z, C.FREEWAY_HALF
        deck = Z + 0.8
        ramps = [
            (-980, -840, Y - H - 8, Y - H, 0.0, deck, "x", -980, -840, -1),
            (800, 950, Y - H - 8, Y - H, deck, 0.0, "x", 800, 950, -1),
            (840, 980, Y + H, Y + H + 8, 0.0, deck, "x", 840, 980, 1),
            (-950, -800, Y + H, Y + H + 8, deck, 0.0, "x", -950, -800, 1),
        ]
        self._elevated("h", Y, H, Z, C.FREEWAY_X0, C.FREEWAY_X1, ramps,
                       [(-420, "OCEAN AVE   NEXT EXIT"), (520, "10 EAST   DOWNTOWN")])

    def _freeway110(self):
        X, Z, H = C.FWY110_X, C.FWY110_Z, C.FWY110_HALF
        deck = Z + 0.8
        ramps = [
            (X - H - 8, X - H, -1040, -900, 0.0, deck, "y", -1040, -900, -1),
            (X - H - 8, X - H, 300, 440, deck, 0.0, "y", 300, 440, -1),
            (X + H, X + H + 8, 340, 480, 0.0, deck, "y", 340, 480, 1),
            (X + H, X + H + 8, -900, -760, deck, 0.0, "y", -900, -760, 1),
            (X - H, X + H, C.FWY110_Y0 - 130, C.FWY110_Y0, 0.0, deck, "y",
             C.FWY110_Y0 - 130, C.FWY110_Y0, 0),
        ]
        self._elevated("v", X, H, Z, C.FWY110_Y0, C.FWY110_Y1, ramps,
                       [(200, "110 NORTH   DOWNTOWN"), (-700, "110 SOUTH   SAN PEDRO")])

    def _fwy405(self):
        X = C.FWY405_X
        y = C.BASIN_Y0 + 10
        while y < C.BASIN_Y1 - 10:
            y2 = min(C.BASIN_Y1 - 10, y + 130)
            b = self._mb(X, (y + y2) / 2, "asphalt")
            b.add_rect(X - 13, y, X + 13, y2, 0.035, (0.28, 0.28, 0.30))
            pb = self._b(X, (y + y2) / 2)
            if abs((y + y2) / 2 - C.CREEK_Y) > 40:
                pb.add_box(X, (y + y2) / 2, 0.05, 1.0, y2 - y, 0.9, (0.62, 0.60, 0.56))
                self.add_collider(X - 0.5, X + 0.5, y, y2, 0, 1.0)
            dd = y
            while dd < y2:
                for off in (-9, -4.5, 4.5, 9):
                    pb.add_rect(X + off - 0.12, dd, X + off + 0.12, dd + 4, 0.06, WHITE_PAINT)
                dd += 12
            y = y2
        self._gantry(self._b(X, 600), X, 600, 0.1, "405 NORTH", vertical=True)
        self._gantry(self._b(X, -900), X, -900, 0.1, "405 SOUTH   LAX", vertical=True)

    def _fwy101(self):
        g = self.ground
        pts = [(x, y, g.height(x, y)) for (x, y) in C.FWY101_PTS]
        b = self._mb(0, 800, "asphalt")
        b.add_strip(pts, 11.0, (0.28, 0.28, 0.30), z_off=0.12)
        self._b(0, 800).add_strip(pts, 0.3, YELLOW, z_off=0.16)
        self._text("101  HOLLYWOOD FWY", 300, 726, 6.5, 1.3, hpr=(35, 0, 0))

    # ---------------- traffic signals + crosswalks ----------------

    def _traffic_lights(self):
        for X in sorted(self.major_vs):
            for Y in sorted(self.major_hs):
                hv = C.ROAD_HALF_MAJOR
                b = self._b(X, Y)
                # zebra crosswalks + stop lines on all four approaches
                for k in range(6):
                    off = -hv + 1.2 + k * (2 * hv - 2.4) / 5
                    b.add_rect(X + off - 0.30, Y - hv - 2.6, X + off + 0.30, Y - hv - 0.6,
                               0.06, WHITE_PAINT)
                    b.add_rect(X + off - 0.30, Y + hv + 0.6, X + off + 0.30, Y + hv + 2.6,
                               0.06, WHITE_PAINT)
                    b.add_rect(X - hv - 2.6, Y + off - 0.30, X - hv - 0.6, Y + off + 0.30,
                               0.06, WHITE_PAINT)
                    b.add_rect(X + hv + 0.6, Y + off - 0.30, X + hv + 2.6, Y + off + 0.30,
                               0.06, WHITE_PAINT)
                b.add_rect(X + 0.6, Y - hv - 3.6, X + hv - 0.6, Y - hv - 3.1, 0.06, WHITE_PAINT)
                b.add_rect(X - hv + 0.6, Y + hv + 3.1, X - 0.6, Y + hv + 3.6, 0.06, WHITE_PAINT)
                b.add_rect(X - hv - 3.6, Y + 0.6, X - hv - 3.1, Y + hv - 0.6, 0.06, WHITE_PAINT)
                b.add_rect(X + hv + 3.1, Y - hv + 0.6, X + hv + 3.6, Y - 0.6, 0.06, WHITE_PAINT)
                # lane arrows
                for (ax, ay, ang) in ((X + 3.4, Y - hv - 7, 0), (X - 3.4, Y + hv + 7, math.pi),
                                      (X - hv - 7, Y - 3.4, math.pi / 2),
                                      (X + hv + 7, Y + 3.4, -math.pi / 2)):
                    fx, fy = -math.sin(ang), math.cos(ang)
                    b.add_box(ax, ay, 0.055, 0.32, 2.0, 0.012, WHITE_PAINT, heading=ang)
                    b.add_tri((ax - 0.7 * math.cos(ang), ay - 0.7 * math.sin(ang), 0.075),
                              (ax + 0.7 * math.cos(ang), ay + 0.7 * math.sin(ang), 0.075),
                              (ax + fx * 1.7, ay + fy * 1.7, 0.075), WHITE_PAINT, (0, 0, 1))
                # signal poles + hydrant on one corner
                for cx, cy in ((X - hv - 1.2, Y - hv - 1.2), (X + hv + 1.2, Y + hv + 1.2)):
                    b2 = self._b(cx, cy)
                    b2.add_box(cx, cy, 0, 0.25, 0.25, 5.4, (0.25, 0.25, 0.28))
                    b2.add_box(cx, cy, 5.4, 0.7, 0.7, 1.6, (0.20, 0.20, 0.22))
                    self.lights_g_b.add_quad((cx - 0.2, cy - 0.36, 5.6), (cx + 0.2, cy - 0.36, 5.6),
                                             (cx + 0.2, cy - 0.36, 6.0), (cx - 0.2, cy - 0.36, 6.0),
                                             (0.1, 0.95, 0.2, 1), (0, -1, 0))
                    self.lights_g_b.add_quad((cx + 0.2, cy + 0.36, 5.6), (cx - 0.2, cy + 0.36, 5.6),
                                             (cx - 0.2, cy + 0.36, 6.0), (cx + 0.2, cy + 0.36, 6.0),
                                             (0.1, 0.95, 0.2, 1), (0, 1, 0))
                    self.lights_r_b.add_quad((cx - 0.36, cy + 0.2, 5.6), (cx - 0.36, cy - 0.2, 5.6),
                                             (cx - 0.36, cy - 0.2, 6.0), (cx - 0.36, cy + 0.2, 6.0),
                                             (0.95, 0.15, 0.1, 1), (-1, 0, 0))
                    self.lights_r_b.add_quad((cx + 0.36, cy - 0.2, 5.6), (cx + 0.36, cy + 0.2, 5.6),
                                             (cx + 0.36, cy + 0.2, 6.0), (cx + 0.36, cy - 0.2, 6.0),
                                             (0.95, 0.15, 0.1, 1), (1, 0, 0))
                self._hydrant(X - hv - 1.6, Y + hv + 1.6)

    def set_light_phase(self, v_green):
        if v_green:
            self.lights_g.setColorScale(1, 1, 1, 1)
            self.lights_r.setColorScale(1, 1, 1, 1)
        else:
            self.lights_g.setColorScale(0.25, 0.3, 0.25, 1)
            self.lights_r.setColorScale(1.6, 0.6, 0.5, 1)

    # ---------------- text helper ----------------

    def _text(self, txt, x, y, z, scale=1.0, hpr=(0, 0, 0), color=(1, 1, 1, 1),
              backing=None):
        tn = TextNode("t")
        tn.setText(txt)
        tn.setTextColor(*color)
        tn.setShadow(0.06, 0.06)
        tn.setShadowColor(0.1, 0.1, 0.12, 0.9)
        tn.setAlign(TextNode.ACenter)
        np = self.root.attachNewNode(tn)
        np.setPos(x, y, z)
        np.setHpr(*hpr)
        np.setScale(scale)
        np.setLightOff()
        np.setTwoSided(True)
        return np

    # ---------------- bridges ----------------

    def _bridge(self, axis, road_half, cross_L, road_L):
        g = self.ground
        half = road_half + 1.5
        lo = cross_L - C.RIVER_HALF_TOP - 4
        hi = cross_L + C.RIVER_HALF_TOP + 4
        if axis == "v":
            g.add_patch(road_L - half, road_L + half, lo, hi, 0.1)
            b = self._b(road_L, cross_L)
            b.add_box(road_L, cross_L, -0.9, half * 2, hi - lo, 1.0, (0.52, 0.50, 0.47),
                      top_color=(0.30, 0.30, 0.32), bottom=True)
            for side in (-1, 1):
                e = road_L + side * (half - 0.3)
                b.add_box(e, cross_L, 0.1, 0.4, hi - lo, 1.0, (0.58, 0.56, 0.52))
                self.add_collider(e - 0.2, e + 0.2, lo, hi, 0.1, 1.4)
        else:
            g.add_patch(lo, hi, road_L - half, road_L + half, 0.1)
            b = self._b(cross_L, road_L)
            b.add_box(cross_L, road_L, -0.9, hi - lo, half * 2, 1.0, (0.52, 0.50, 0.47),
                      top_color=(0.30, 0.30, 0.32), bottom=True)
            for side in (-1, 1):
                e = road_L + side * (half - 0.3)
                b.add_box(cross_L, e, 0.1, hi - lo, 0.4, 1.0, (0.58, 0.56, 0.52))
                self.add_collider(lo, hi, e - 0.2, e + 0.2, 0.1, 1.4)

    def _bridges(self):
        for idx, X in enumerate(self.roads_v):
            self._bridge("v", self.road_half("v", idx), C.CREEK_Y, X)
        for idx, Y in enumerate(C.ROADS_H):
            if abs(Y - C.CREEK_Y) < 1:
                continue
            self._bridge("h", self.road_half("h", idx), C.RIVER_X, Y)

    # ---------------- coast: pier, marina, lifeguards ----------------

    def _pier(self, rng):
        g = self.ground
        py = C.PIER_Y
        deck = 3.2
        gz = g.height(-1406, py)
        g.add_patch(-1450, -1406, py - 15, py + 15, deck, gz, axis="x")
        g.add_patch(-1700, -1450, py - 15, py + 15, deck)
        b = self._b(-1500, py)
        b.add_quad((-1450, py - 15, deck), (-1406, py - 15, gz), (-1406, py + 15, gz),
                   (-1450, py + 15, deck), (0.55, 0.42, 0.30))
        x = -1700
        while x < -1450:
            b.add_box(x + 12.5, py, deck - 0.4, 25, 30, 0.4, (0.58, 0.45, 0.32),
                      top_color=(0.62, 0.48, 0.34), bottom=True)
            x += 25
        x = -1690
        while x < -1410:
            for side in (-1, 1):
                b.add_box(x, py + side * 13.5, C.WATER_Z - 3, 0.8, 0.8,
                          deck - C.WATER_Z + 2.6, (0.35, 0.28, 0.22))
            x += 22
        for side in (-1, 1):
            b.add_box(-1575, py + side * 14.6, deck, 250, 0.3, 1.0, (0.75, 0.72, 0.68))
            self.add_collider(-1700, -1450, py + side * 14.6 - 0.15, py + side * 14.6 + 0.15,
                              deck, deck + 1.0)
        b.add_box(-1698, py, deck, 0.3, 30, 1.0, (0.75, 0.72, 0.68))
        self.add_collider(-1698.2, -1697.8, py - 15, py + 15, deck, deck + 1.0)
        for bx, col in ((-1480, (0.9, 0.4, 0.4)), (-1520, (0.4, 0.6, 0.9)),
                        (-1560, (0.95, 0.8, 0.3))):
            b.add_box(bx, py - 9, deck, 6, 5, 3.4, (0.92, 0.90, 0.85))
            b.add_gable(bx, py - 9, deck + 3.4, 6.5, 5.5, 1.4, col)
            self.add_collider(bx - 3, bx + 3, py - 11.5, py - 6.5, deck, deck + 4.8)
        wx, wy = -1640.0, py + 6.0
        base = self._b(wx, wy)
        hub_z = deck + 14.0
        for side in (-1, 1):
            base.add_quad((wx - 0.6, wy + side * 4.5, deck), (wx + 0.6, wy + side * 4.5, deck),
                          (wx + 0.3, wy + side * 0.6, hub_z), (wx - 0.3, wy + side * 0.6, hub_z),
                          (0.85, 0.30, 0.25))
        self.add_collider(wx - 1, wx + 1, wy - 5, wy + 5, deck, deck + 2)
        wheel_root = self.root.attachNewNode("ferris")
        wheel_root.setPos(wx, wy, hub_z)
        wb = MeshBuilder("wheel")
        R = 12.0
        wb.add_cylinder(0, 0, -0.8, 0.9, 1.6, (0.9, 0.85, 0.4), sides=8)
        for k in range(10):
            a = k * math.tau / 10
            wb.add_quad((-0.15, 0, 0), (0.15, 0, 0),
                        (0.15, math.cos(a) * R, math.sin(a) * R),
                        (-0.15, math.cos(a) * R, math.sin(a) * R), (0.85, 0.30, 0.25))
        for k in range(20):
            a0, a1 = k * math.tau / 20, (k + 1) * math.tau / 20
            wb.add_quad((-0.2, math.cos(a0) * R, math.sin(a0) * R),
                        (0.2, math.cos(a0) * R, math.sin(a0) * R),
                        (0.2, math.cos(a1) * R, math.sin(a1) * R),
                        (-0.2, math.cos(a1) * R, math.sin(a1) * R), (0.95, 0.75, 0.20))
        wheel_np = wb.build(wheel_root)
        cabins = []
        cabcols = [(0.9, 0.3, 0.3), (0.3, 0.6, 0.9), (0.95, 0.8, 0.25), (0.4, 0.8, 0.45),
                   (0.8, 0.5, 0.85)]
        for k in range(10):
            a = k * math.tau / 10
            piv = wheel_np.attachNewNode("cab")
            piv.setPos(0, math.cos(a) * R, math.sin(a) * R)
            cb = MeshBuilder("cabin")
            cb.add_box(0, 0, -2.0, 1.6, 1.6, 1.7, cabcols[k % len(cabcols)])
            cb.build(piv)
            cabins.append(piv)
        self.anims.append((wheel_np, cabins, 12.0, "spin"))
        self.poi["pier"] = (-1600, py)
        self.map_labels.append(("Santa Monica Pier", -1600, py))
        self.pickup_specs += [("smg", -1688, py + 8, 0), ("cash", -1620, py - 8, 60),
                              ("health", -1470, py + 10, 0)]
        bw = self._b(-1395, 0)
        y = -1130
        while y < 830:
            bw.add_rect(-1402, y, -1388, y + 60, 0.06, (0.60, 0.47, 0.33))
            y += 60
        rngb = random.Random(9)
        y = -1120
        while y < 820:
            self._palm(self._b(-1395, y), -1395 + rngb.uniform(-2, 2), y, 0.05, rngb)
            y += rngb.uniform(28, 48)

    def _marina(self, rng):
        my = C.MARINA_Y
        b = self._b(-1460, my)
        for k, dy in enumerate((-40, 0, 40)):
            b.add_box(-1490, my + dy, C.WATER_Z + 0.5, 80, 3.0, 0.4, (0.55, 0.42, 0.30),
                      top_color=(0.62, 0.48, 0.34))
            self.ground.add_patch(-1530, -1450, my + dy - 1.5, my + dy + 1.5, C.WATER_Z + 0.9)
            x = -1525
            while x < -1455:
                b.add_box(x, my + dy, C.WATER_Z - 2.5, 0.6, 0.6, 3.4, (0.35, 0.28, 0.22))
                x += 14
        for dy in (-20, 20):
            self.boat_specs.append((-1545, my + dy, math.pi / 2))
        self.boat_specs.append((-1545, my, math.pi / 2))
        self.poi["marina"] = (-1470, my)
        self.map_labels.append(("Marina", -1500, my))
        self.pickup_specs.append(("cash", -1466, my - 38, 50))

    def _lifeguards(self, rng):
        y = -1050
        while y < 700:
            if abs(y - C.PIER_Y) > 70 and abs(y - C.MARINA_Y) > 80:
                x = coast_sand_x(y) - 26
                z = self.ground.height(x, y)
                b = self._b(x, y)
                col = (0.35, 0.65, 0.85)
                for sx in (-1.6, 1.6):
                    for sy in (-1.4, 1.4):
                        b.add_box(x + sx, y + sy, z, 0.3, 0.3, 2.6, (0.75, 0.70, 0.60))
                b.add_box(x, y, z + 2.6, 4.6, 4.0, 2.4, col, top_color=(0.85, 0.80, 0.70))
                b.add_gable(x, y, z + 5.0, 5.0, 4.4, 1.0, (0.9, 0.88, 0.8))
                self.add_collider(x - 2.3, x + 2.3, y - 2, y + 2, z, z + 6)
            y += 260

    # ---------------- LAX ----------------

    def _lax(self, rng):
        b = self._b(-1800, -1000)
        self._mb(-1800, -1000, "concrete").add_rect(-2120, -1240 + 60, -1450, -800, 0.04,
                                                    (0.55, 0.55, 0.52))
        for ry, tag in ((-1010.0, "25R"), (-1130.0, "25L")):
            rb = self._mb(-1800, ry, "asphalt")
            rb.add_rect(-2090, ry - 22, -1470, ry + 22, 0.055, (0.17, 0.17, 0.19))
            pb = self._b(-1800, ry)
            x = -2080
            while x < -1490:
                pb.add_rect(x, ry - 0.4, x + 14, ry + 0.4, 0.07, WHITE_PAINT)
                x += 28
            for ex in (-2086, -1486):
                pb.add_rect(ex - 2, ry - 18, ex + 2, ry + 18, 0.07, WHITE_PAINT)
            self._text(tag, -1520, ry, 0.4, scale=9, hpr=(0, -90, 0),
                       color=(0.9, 0.9, 0.88, 1))
            x = -2080
            while x < -1480:
                for side in (-1, 1):
                    self.night_b.add_rect(x - 0.5, ry + side * 23 - 0.5, x + 0.5,
                                          ry + side * 23 + 0.5, 0.1, (0.95, 0.9, 0.5, 0.9))
                x += 40
            self.night_b.add_rect(-2090, ry - 18, -2086, ry + 18, 0.1, (0.2, 1, 0.3, 0.9))
            self.night_b.add_rect(-1474, ry - 18, -1470, ry + 18, 0.1, (1, 0.25, 0.2, 0.9))
        self._mb(-1800, -1070, "asphalt").add_rect(-2060, -1085, -1500, -1055, 0.06,
                                                   (0.30, 0.30, 0.32))
        x = -2050
        while x < -1510:
            self.night_b.add_rect(x - 0.4, -1071, x + 0.4, -1069, 0.1, (0.3, 0.5, 1, 0.9))
            x += 36
        for k in range(3):
            tx = -1980 + k * 150
            b.add_box(tx, -850, 0, 90, 26, 9, (0.80, 0.80, 0.82),
                      top_color=(0.55, 0.55, 0.58), ao=0.12)
            b.add_box(tx, -866, 0, 60, 8, 6, (0.6, 0.62, 0.66))
            # jet bridges
            for m in (-30, 0, 30):
                b.add_box(tx + m, -838, 2.2, 2.2, 9, 2.4, (0.70, 0.72, 0.75))
            self.add_collider(tx - 45, tx + 45, -863, -837, 0, 9)
            self._ao_pad(tx, -850, 46, 14, 0.14)
        b.add_cylinder(-1755, -880, 0, 2.2, 26, (0.85, 0.85, 0.88), sides=10)
        b.add_cylinder(-1755, -880, 26, 5.0, 4.5, (0.3, 0.4, 0.5), sides=10)
        self.add_collider(-1758, -1752, -883, -877, 0, 31)
        cx, cy = -1560, -880
        for rot in (0, math.pi / 2):
            for i in range(9):
                a0 = math.pi * i / 9
                a1 = math.pi * (i + 1) / 9
                r = 26.0
                p0 = (cx + math.cos(rot) * math.cos(a0) * r, cy + math.sin(rot) * math.cos(a0) * r,
                      math.sin(a0) * 18)
                p1 = (cx + math.cos(rot) * math.cos(a1) * r, cy + math.sin(rot) * math.cos(a1) * r,
                      math.sin(a1) * 18)
                mx, my_, mz = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2
                seg = math.dist(p0, p1)
                hdg = math.atan2(p1[0] - p0[0], p1[1] - p0[1])
                b.add_box(mx, my_, mz - 0.5, 1.0, seg + 0.3, 1.0, (0.92, 0.92, 0.9),
                          heading=-hdg)
        b.add_cylinder(cx, cy, 0, 1.8, 9, (0.85, 0.85, 0.85), sides=8)
        b.add_cylinder(cx, cy, 9, 8.5, 2.8, (0.90, 0.90, 0.92), sides=12,
                       top_color=(0.4, 0.42, 0.46))
        self.add_collider(cx - 3, cx + 3, cy - 3, cy + 3, 0, 12)
        self.aircraft_specs += [("jet", -1620, -950, None, math.pi / 2),
                                ("prop", -1530, -965, None, math.pi / 2),
                                ("heli", -1470, -905, None, 0.0)]
        self.parked_spots.append((-1445, -860, 0.0, "van"))
        self.poi["lax"] = (-1560, -905)
        self.map_labels.append(("LAX", -1780, -960))
        self.pickup_specs.append(("ammo", -1585, -905, 0))

    # ---------------- hills landmarks ----------------

    def _sign(self):
        g = self.ground
        x, y = C.SIGN_POS
        z = g.height(x, y)
        self._text("HOLLYWOOD", x, y, z + 1.5, scale=15, hpr=(0, 10, 0),
                   color=(0.96, 0.96, 0.93, 1))
        self.poi["sign"] = (x, y)
        self.map_labels.append(("Hollywood Sign", x, y))

    def _observatory(self):
        ox, oy = self.ground.obs_center
        z = 118.0
        b = self._b(ox, oy)
        b.add_cylinder(ox, oy, z - 2, 46, 2.2, (0.72, 0.70, 0.66), sides=18)
        white = (0.93, 0.92, 0.88)
        copper = (0.35, 0.42, 0.38)
        b.add_box(ox, oy, z, 34, 15, 7, white, ao=0.1)
        b.add_dome(ox, oy + 2, z + 7, 7.5, copper, sides=14, rings=5)
        for sx in (-1, 1):
            b.add_cylinder(ox + sx * 15, oy, z, 5.5, 6, white, sides=12)
            b.add_dome(ox + sx * 15, oy, z + 6, 5.5, copper, sides=12, rings=4)
        self.add_collider(ox - 18, ox + 18, oy - 8, oy + 8, z, z + 15)
        self._mb(ox, oy, "grass").add_rect(ox - 40, oy - 42, ox + 40, oy - 12, z + 0.06,
                                           (0.42, 0.55, 0.30))
        self._mb(ox, oy, "concrete").add_rect(ox - 30, oy - 42, ox + 30, oy - 26, z + 0.08,
                                              (0.32, 0.32, 0.34))
        self.poi["observatory"] = (ox, oy - 30)
        self.map_labels.append(("Observatory", ox, oy))
        self.pickup_specs.append(("cash", ox + 20, oy - 20, 80))
        self.parked_spots.append((ox - 12, oy - 34, math.pi / 2, "coupe"))

    def _bowl(self):
        bx, by = C.BOWL_POS
        g = self.ground
        z = g.height(bx, by)
        b = self._b(bx, by)
        for k, r in enumerate((10.0, 13.5, 17.0, 20.5)):
            for i in range(8):
                a0 = math.pi * i / 8
                a1 = math.pi * (i + 1) / 8
                p0 = (bx + math.cos(a0) * r, by + 2 + k * 2.5, z + math.sin(a0) * r * 0.8)
                p1 = (bx + math.cos(a1) * r, by + 2 + k * 2.5, z + math.sin(a1) * r * 0.8)
                mx, mz = (p0[0] + p1[0]) / 2, (p0[2] + p1[2]) / 2
                b.add_box(mx, by + 2 + k * 2.5, mz - 0.5, max(1.0, abs(p1[0] - p0[0]) + 0.4),
                          0.8, max(1.0, abs(p1[2] - p0[2]) + 0.4), (0.94, 0.94, 0.90))
        self._mb(bx, by, "concrete").add_rect(bx - 9, by - 4, bx + 9, by + 6, z + 0.1,
                                              (0.45, 0.40, 0.36))
        for row in range(6):
            self._mb(bx, by, "concrete").add_rect(bx - 14 - row, by - 14 - row * 4,
                                                  bx + 14 + row, by - 11 - row * 4,
                                                  z + 0.1 + row * 0.5, (0.75, 0.72, 0.66))
        self.poi["bowl"] = (bx, by - 30)
        self.map_labels.append(("The Bowl", bx, by))

    def _hill_road(self):
        g = self.ground
        pts = [(x, y, g.height(x, y)) for (x, y) in
               [(60, 850), (95, 940), (20, 1010), (105, 1090), (240, 1140),
                (330, 1152), (350, 1150)]]
        self._mb(100, 1000, "asphalt").add_strip(pts, 5.0, (0.30, 0.30, 0.32), z_off=0.15)

    # ---------------- stadiums & oddball landmarks ----------------

    def _oval_stadium(self, cx, cy, rx, ry, tiers, col, field_col, label):
        b = self._b(cx, cy)
        sides = 22
        for tier in range(tiers):
            r0x, r0y = rx - tier * 4, ry - tier * 4
            z0, z1 = tier * 3.2, tier * 3.2 + 4.0
            for i in range(sides):
                a0 = math.tau * i / sides
                a1 = math.tau * (i + 1) / sides
                p0 = (cx + math.cos(a0) * r0x, cy + math.sin(a0) * r0y, z0)
                p1 = (cx + math.cos(a1) * r0x, cy + math.sin(a1) * r0y, z0)
                p2 = (cx + math.cos(a1) * (r0x - 3), cy + math.sin(a1) * (r0y - 3), z1)
                p3 = (cx + math.cos(a0) * (r0x - 3), cy + math.sin(a0) * (r0y - 3), z1)
                b.add_quad(p0, p1, p2, p3, col)
        self._mb(cx, cy, "grass").add_rect(cx - rx + 14, cy - ry + 14, cx + rx - 14,
                                           cy + ry - 14, 0.15, field_col)
        self.add_collider(cx - rx, cx - rx + 6, cy - ry, cy + ry, 0, tiers * 3.2 + 2)
        self.add_collider(cx + rx - 6, cx + rx, cy - ry, cy + ry, 0, tiers * 3.2 + 2)
        self.add_collider(cx - rx, cx + rx, cy - ry, cy - ry + 6, 0, tiers * 3.2 + 2)
        self.add_collider(cx - rx, cx + rx, cy + ry - 6, cy + ry, 0, tiers * 3.2 + 2)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            lx, ly = cx + sx * (rx - 8), cy + sy * (ry - 8)
            b.add_box(lx, ly, 0, 0.8, 0.8, 22, (0.4, 0.4, 0.44))
            b.add_box(lx, ly, 22, 4.5, 0.6, 2.4, (0.85, 0.85, 0.8))
        self.map_labels.append((label, cx, cy))

    def _stadiums(self):
        sx, sy = self._block_center("stadium")
        self._oval_stadium(sx, sy, 62, 56, 4, (0.35, 0.45, 0.75), (0.36, 0.52, 0.28),
                           "The Ravine")
        b = self._b(sx, sy)
        b.add_rect(sx - 16, sy - 16, sx + 16, sy + 4, 0.18, (0.55, 0.42, 0.30))
        self.poi["stadium"] = (sx, sy - 70)
        cx, cy = self._block_center("coliseum")
        self._oval_stadium(cx, cy, 66, 48, 3, (0.72, 0.68, 0.60), (0.36, 0.52, 0.28),
                           "The Coliseum")
        b = self._b(cx, cy)
        for k in range(5):
            b.add_box(cx + 52, cy - 16 + k * 8, 0, 2.0, 2.0, 10, (0.75, 0.70, 0.62))
        b.add_box(cx + 52, cy, 10, 3.0, 36, 2.0, (0.75, 0.70, 0.62))
        b.add_cylinder(cx + 52, cy, 12, 2.2, 6, (0.75, 0.70, 0.62), sides=8, r_top=1.4)
        self.night_b.add_dome(cx + 52, cy, 18.2, 1.6, (1.0, 0.6, 0.15, 0.9), sides=6, rings=2)
        self.poi["coliseum"] = (cx, cy - 60)

    def _capitol(self):
        cx, cy = self._block_center("capitol")
        b = self._b(cx, cy)
        for k in range(7):
            b.add_cylinder(cx, cy, 4 + k * 5.2, 12.0 if k % 2 == 0 else 12.8, 4.6,
                           (0.90, 0.89, 0.86) if k % 2 == 0 else (0.75, 0.76, 0.78),
                           sides=14, top_color=(0.6, 0.6, 0.62))
        b.add_box(cx, cy, 0, 26, 26, 4, (0.85, 0.84, 0.80), ao=0.12)
        b.add_cylinder(cx, cy, 40.4, 0.6, 14, (0.8, 0.8, 0.84), sides=6, r_top=0.1)
        self.night_b.add_dome(cx, cy, 54.0, 0.9, (0.95, 0.2, 0.2, 0.95), sides=6, rings=2)
        self.add_collider(cx - 13, cx + 13, cy - 13, cy + 13, 0, 44)
        self._ao_pad(cx, cy, 14, 14, 0.15)
        self._windows(cx, cy, 24, 24, 38, random.Random(12))
        self.map_labels.append(("The Record Tower", cx, cy))

    def _donut(self):
        cx, cy = self._block_center("donut")
        b = self._b(cx, cy)
        b.add_box(cx, cy, 0, 18, 12, 5, (0.95, 0.80, 0.70), ao=0.14)
        b.add_quad((cx - 8, cy - 6.01, 0.5), (cx + 8, cy - 6.01, 0.5),
                   (cx + 8, cy - 6.01, 3.5), (cx - 8, cy - 6.01, 3.5),
                   (0.25, 0.20, 0.18), (0, -1, 0))
        self.add_collider(cx - 9, cx + 9, cy - 6, cy + 6, 0, 5)
        R = 7.5
        for i in range(14):
            a = math.tau * i / 14
            px = cx + math.cos(a) * R
            pz = 5 + R * 0.9 + math.sin(a) * R * 0.9
            b.add_box(px, cy, pz - 1.3, 2.6, 2.3, 2.6, (0.82, 0.62, 0.38))
        self._text("DONUT DEN", cx, cy - 6.2, 4.2, 1.4, color=(0.95, 0.4, 0.5, 1))
        self.map_labels.append(("Donut Den", cx, cy))

    def _watts(self):
        cx, cy = self._block_center("watts")
        b = self._b(cx, cy)
        for (dx, dy, h) in ((-6, 0, 30), (2, 4, 24), (7, -3, 18)):
            x, y = cx + dx, cy + dy
            for k in range(6):
                z0 = k * h / 6
                rr = 3.0 * (1 - k / 6.5)
                b.add_cylinder(x, y, z0, rr, h / 6 + 0.2, (0.60, 0.55, 0.48), sides=7,
                               r_top=rr * 0.82, top=False)
            b.add_cylinder(x, y, h, 0.3, 2.5, (0.60, 0.55, 0.48), sides=5, r_top=0.05)
            self.add_collider(x - 1, x + 1, y - 1, y + 1, 0, h)
        self._mb(cx, cy, "concrete").add_rect(cx - 14, cy - 10, cx + 14, cy + 10, 0.12,
                                              (0.55, 0.50, 0.44))
        self.map_labels.append(("The Spires", cx, cy))

    # ---------------- harbor ----------------

    def _port(self, rng):
        self._mb(0, -1300, "concrete").add_rect(-900, -1390, 700, C.BASIN_Y0, 0.05, CONCRETE)
        metal = self._mb(0, -1300, "metal")
        for row in range(4):
            self._containers(self._mb(-400 + row * 5, -1260 - row * 30, "metal"),
                             rng, -650 + rng.uniform(0, 30), -1245 - row * 28, 8)
        for cx in (-500, -150, 200):
            cb = self._b(cx, -1360)
            for sx in (-9, 9):
                cb.add_box(cx + sx, -1355, 0, 2.2, 2.2, 26, (0.85, 0.45, 0.15))
            cb.add_box(cx, -1355, 26, 24, 3.0, 3.0, (0.85, 0.45, 0.15))
            cb.add_box(cx, -1338, 26.5, 2.4, 36, 2.4, (0.85, 0.45, 0.15))
            cb.add_box(cx, -1352, 22, 3.5, 4, 4, (0.3, 0.3, 0.33))
            for sx in (-9, 9):
                self.add_collider(cx + sx - 1.1, cx + sx + 1.1, -1356.1, -1353.9, 0, 26)
        sb = self._b(400, -1420)
        sb.add_box(420, -1428, C.WATER_Z - 2, 150, 26, 9, (0.45, 0.16, 0.14),
                   top_color=(0.55, 0.52, 0.48))
        sb.add_box(475, -1428, C.WATER_Z + 7, 18, 22, 12, (0.90, 0.88, 0.84))
        self._containers(metal, rng, 370, -1430, 6)
        self._containers(metal, rng, 375, -1425, 5)
        self.add_collider(345, 495, -1441, -1415, -3, 8)
        self.poi["port"] = (0, -1300)
        self.map_labels.append(("Port", -150, -1330))
        self.pickup_specs += [("shotgun", -420, -1252, 0), ("ammo", -415, -1252, 0)]
        self.boat_specs.append((520, -1445, math.pi / 2))

    def _vt_bridge(self):
        g = self.ground
        Y = C.BRIDGE_Y
        green = (0.25, 0.48, 0.38)
        deck_z = 14.0
        x0, x1 = 1130, 1330
        g.add_patch(1010, x0, Y - 8, Y + 8, 0.1, deck_z, axis="x")
        g.add_patch(x0, x1, Y - 8, Y + 8, deck_z)
        g.add_patch(x1, 1450, Y - 8, Y + 8, deck_z, 0.1, axis="x")
        b = self._b(1230, Y)
        b.add_quad((1010, Y - 8, 0.1), (x0, Y - 8, deck_z), (x0, Y + 8, deck_z),
                   (1010, Y + 8, 0.1), (0.4, 0.42, 0.40))
        b.add_box(1230, Y, deck_z - 1.0, x1 - x0, 16, 1.1, green,
                  top_color=(0.35, 0.35, 0.37), bottom=True)
        b.add_quad((x1, Y - 8, deck_z), (1450, Y - 8, 0.1), (1450, Y + 8, 0.1),
                   (x1, Y + 8, deck_z), (0.4, 0.42, 0.40))
        for side in (-1, 1):
            e = Y + side * 7.6
            b.add_box(1230, e, deck_z, x1 - x0, 0.4, 1.0, green)
            self.add_collider(x0, x1, e - 0.2, e + 0.2, deck_z, deck_z + 1)
        for tx in (1165, 1295):
            for side in (-1, 1):
                b.add_box(tx, Y + side * 7, -4, 2.2, 2.2, 46, green)
                self.add_collider(tx - 1.1, tx + 1.1, Y + side * 7 - 1.1, Y + side * 7 + 1.1,
                                  deck_z, 42)
            b.add_box(tx, Y, 38, 2.0, 16, 2.0, green)
        for side in (-1, 1):
            cy = Y + side * 7
            pts = []
            for k in range(13):
                x = 1130 + (1330 - 1130) * k / 12
                sag = 40 - 24 * (1 - ((x - 1230) / 100) ** 2)
                pts.append((x, cy, sag + 2))
            for k in range(12):
                p0, p1 = pts[k], pts[k + 1]
                seg = math.dist(p0, p1)
                b.add_box((p0[0] + p1[0]) / 2, cy, (p0[2] + p1[2]) / 2 - 0.2, seg + 0.2,
                          0.35, 0.35, green)
            for k in range(1, 12):
                x, _, cz = pts[k]
                b.add_box(x, cy, deck_z, 0.12, 0.12, max(0.3, cz - deck_z), green)
        self.poi["bridge"] = (1230, Y)
        self.map_labels.append(("Harbor Gate", 1230, Y))

    def _bounds(self):
        for (x0, x1, y0, y1) in ((C.WORLD_X0, C.WORLD_X0 + 4, C.WORLD_Y0, C.WORLD_Y1),
                                 (C.WORLD_X1 - 4, C.WORLD_X1, C.WORLD_Y0, C.WORLD_Y1),
                                 (C.WORLD_X0, C.WORLD_X1, C.WORLD_Y0, C.WORLD_Y0 + 4),
                                 (C.WORLD_X0, C.WORLD_X1, C.WORLD_Y1 - 4, C.WORLD_Y1)):
            self.add_collider(x0, x1, y0, y1, -10, 400)

    # ---------------- civic buildings ----------------

    def _civics(self):
        rng = random.Random(77)
        self._stadiums()
        self._capitol()
        self._donut()
        self._watts()
        hx, hy = self._block_center("hospital")
        b = self._b(hx, hy)
        b.add_box(hx, hy, 0, 44, 22, 20, (0.93, 0.93, 0.95), top_color=(0.7, 0.7, 0.72),
                  ao=0.12)
        b.add_box(hx, hy - 12.5, 0, 16, 4, 4.5, (0.85, 0.85, 0.88))
        b.add_box(hx, hy, 20, 10, 6, 2.5, (0.95, 0.3, 0.3))
        self.add_collider(hx - 22, hx + 22, hy - 11, hy + 11, 0, 20)
        self._ao_pad(hx, hy, 24, 13, 0.15)
        self._text("ANGEL MERCY HOSPITAL", hx, hy - 12.7, 6.5, 1.6,
                   color=(0.85, 0.2, 0.2, 1))
        self.ground.add_patch(hx + 6, hx + 20, hy - 7, hy + 7, 20.05)
        b.add_cylinder(hx + 13, hy, 20.0, 6.5, 0.1, (0.35, 0.35, 0.38), sides=12)
        b.add_box(hx + 13, hy, 20.12, 3.2, 0.7, 0.05, WHITE_PAINT)
        b.add_box(hx + 11.7, hy, 20.12, 0.7, 3.2, 0.05, WHITE_PAINT)
        b.add_box(hx + 14.3, hy, 20.12, 0.7, 3.2, 0.05, WHITE_PAINT)
        self.aircraft_specs.append(("heli", hx + 13, hy, 20.1, math.pi / 2))
        self.poi["hospital"] = (hx, hy - 18)
        self.pickup_specs.append(("health", hx - 10, hy - 16, 0))
        px, py = self._block_center("police")
        b = self._b(px, py)
        b.add_box(px, py, 0, 40, 24, 14, (0.35, 0.40, 0.55), top_color=(0.3, 0.32, 0.4),
                  ao=0.12)
        b.add_box(px, py + 13, 0, 20, 3, 5, (0.85, 0.85, 0.9))
        self.add_collider(px - 20, px + 20, py - 12, py + 12, 0, 14)
        self._ao_pad(px, py, 22, 14, 0.15)
        self._text("APD CENTRAL", px, py + 14.6, 6.0, 1.6, color=(0.8, 0.85, 1, 1))
        self.poi["police"] = (px, py + 18)
        self.parked_spots += [(px - 10, py + 17, 0, "police"), (px + 12, py + 17, 0, "police")]
        ax, ay = self._block_center("ammo")
        b = self._b(ax, ay)
        b.add_box(ax, ay, 0, 14, 12, 5.5, (0.25, 0.35, 0.25), ao=0.15)
        self.add_collider(ax - 7, ax + 7, ay - 6, ay + 6, 0, 5.5)
        self._text("ANGEL ARMS", ax, ay - 6.2, 4.2, 1.3, color=(0.95, 0.85, 0.3, 1))
        self.poi["ammo"] = (ax, ay - 9)
        for key in ("spray1", "spray2"):
            sx, sy = self._block_center(key)
            b = self._b(sx, sy)
            b.add_box(sx, sy + 4, 0, 16, 8, 6, (0.55, 0.35, 0.55), ao=0.15)
            b.add_box(sx - 7, sy - 2, 0, 2, 6, 6, (0.55, 0.35, 0.55))
            b.add_box(sx + 7, sy - 2, 0, 2, 6, 6, (0.55, 0.35, 0.55))
            b.add_box(sx, sy - 2, 5.0, 16, 6, 1.0, (0.55, 0.35, 0.55))
            self.add_collider(sx - 8, sx + 8, sy, sy + 8, 0, 6)
            self._text("AUTO SPA", sx, sy - 5.2, 4.6, 1.2, color=(0.95, 0.6, 0.95, 1))
            self.poi[key] = (sx, sy - 2)
            self.night_b.add_rect(sx - 5, sy - 6, sx + 5, sy - 4, 0.12, (0.9, 0.4, 0.9, 0.3))
        hx2, hy2 = self._block_center("home")
        b = self._b(hx2, hy2)
        b.add_box(hx2, hy2, 0, 16, 12, 9, (0.55, 0.70, 0.85), ao=0.14)
        b.add_box(hx2, hy2 - 6.5, 0, 6, 1.5, 3, (0.9, 0.9, 0.92))
        self._window(b, hx2 - 4, hy2 - 6, 4.5, 1.6, 1.4, "s")
        self._window(b, hx2 + 4, hy2 - 6, 4.5, 1.6, 1.4, "s")
        self.add_collider(hx2 - 8, hx2 + 8, hy2 - 6, hy2 + 6, 0, 9)
        self._ao_pad(hx2, hy2, 9, 7, 0.14)
        self.poi["home"] = (hx2, hy2 - 14)
        self.pickup_specs.append(("pistol", hx2 - 7, hy2 - 12, 0))
        self.parked_spots.insert(0, (hx2 + 13, hy2 - 12, 0.15, "beater"))
        self.pickup_specs += [
            ("cash", -600, 300, 45), ("cash", 900, -200, 45), ("cash", 200, 700, 45),
            ("ammo", 620, 380, 0), ("health", -700, -500, 0),
            ("smg", 1180, -890, 0), ("pistol", -160, 480, 0),
        ]
        rngp = random.Random(31)
        kinds = ("sedan", "coupe", "lowrider", "pickup", "van", "taxi", "beater")
        weights = (28, 10, 12, 14, 10, 8, 14)
        for _ in range(60):
            if rngp.random() < 0.5:
                idx = rngp.randrange(len(self.roads_v))
                X = self.roads_v[idx]
                half = self.road_half("v", idx)
                y = rngp.uniform(C.ROADS_H[0], C.ROADS_H[-1])
                if abs(y - C.CREEK_Y) < 50 or any(abs(y - Y) < 16 for Y in C.ROADS_H):
                    continue
                side = rngp.choice((-1, 1))
                self.parked_spots.append((X + side * (half - 1.3), y,
                                          0 if side < 0 else math.pi,
                                          rngp.choices(kinds, weights=weights)[0]))
            else:
                idx = rngp.randrange(len(C.ROADS_H))
                Y = C.ROADS_H[idx]
                if abs(Y - C.CREEK_Y) < 1:
                    continue
                half = self.road_half("h", idx)
                x = rngp.uniform(self.roads_v[0], self.roads_v[-1])
                if any(abs(x - X) < 16 for X in self.roads_v) or abs(x - C.RIVER_X) < 50:
                    continue
                side = rngp.choice((-1, 1))
                self.parked_spots.append((x, Y + side * (half - 1.3),
                                          math.pi / 2 if side < 0 else -math.pi / 2,
                                          rngp.choices(kinds, weights=weights)[0]))

    # ---------------- minimap ----------------

    def _minimap(self):
        S = 768
        self.map_x0, self.map_x1 = -2280.0, 1560.0
        self.map_y0, self.map_y1 = -1660.0, 1560.0
        img = PNMImage(S, S)
        img.fill(0.55, 0.52, 0.44)

        def px(wx):
            return int((wx - self.map_x0) / (self.map_x1 - self.map_x0) * (S - 1))

        def py(wy):
            return int((1 - (wy - self.map_y0) / (self.map_y1 - self.map_y0)) * (S - 1))

        def rect(x0, x1, y0, y1, c):
            for ix in range(max(0, px(x0)), min(S - 1, px(x1)) + 1):
                for iy in range(max(0, py(y1)), min(S - 1, py(y0)) + 1):
                    img.setXel(ix, iy, *c)

        for iy in range(S):
            wy = self.map_y0 + (1 - iy / (S - 1)) * (self.map_y1 - self.map_y0)
            sand = coast_sand_x(wy)
            water_edge = sand - 55
            for ix in range(0, px(sand + 10)):
                wx = self.map_x0 + ix / (S - 1) * (self.map_x1 - self.map_x0)
                if wx < water_edge:
                    img.setXel(ix, iy, 0.16, 0.35, 0.45)
                else:
                    img.setXel(ix, iy, 0.85, 0.77, 0.56)
        rect(self.map_x0, self.map_x1, self.map_y0, C.PORT_Y0, (0.16, 0.35, 0.45))
        rect(C.BEACH_X, self.map_x1, 860, self.map_y1, (0.48, 0.44, 0.28))
        rect(C.PARK[0], C.PARK[1], C.PARK[2], C.PARK[3], (0.30, 0.45, 0.24))
        rect(C.DOWNTOWN[0], C.DOWNTOWN[1], C.DOWNTOWN[2], C.DOWNTOWN[3], (0.48, 0.46, 0.42))
        rect(-900, 700, C.PORT_Y0 + 10, C.BASIN_Y0, (0.5, 0.48, 0.44))
        rect(-2120, -1450, C.LAX_Y0 + 60, -800, (0.62, 0.62, 0.60))
        rect(-2090, -1470, -1032, -988, (0.25, 0.25, 0.28))
        rect(-2090, -1470, -1152, -1108, (0.25, 0.25, 0.28))
        rect(C.BASIN_X0, C.RIVER_X, C.CREEK_Y - 26, C.CREEK_Y + 26, (0.42, 0.48, 0.47))
        rect(C.BASIN_X0, C.RIVER_X, C.CREEK_Y - 8, C.CREEK_Y + 8, (0.25, 0.42, 0.45))
        rect(C.RIVER_X - 26, C.RIVER_X + 26, -1450, 820, (0.42, 0.48, 0.47))
        rect(C.RIVER_X - 8, C.RIVER_X + 8, -1450, 820, (0.25, 0.42, 0.45))
        for idx, X in enumerate(self.roads_v):
            wpx = 2 if idx % C.MAJOR_EVERY else 3
            for ix in range(px(X) - wpx // 2, px(X) + wpx // 2 + 1):
                for iy in range(py(C.ROADS_H[-1] + 40), py(C.ROADS_H[0] - 40)):
                    if 0 <= ix < S and 0 <= iy < S:
                        img.setXel(ix, iy, 0.75, 0.73, 0.68)
        for idx, Y in enumerate(C.ROADS_H):
            if abs(Y - C.CREEK_Y) < 1:
                continue
            wpx = 2 if idx % C.MAJOR_EVERY else 3
            for iy in range(py(Y) - wpx // 2, py(Y) + wpx // 2 + 1):
                for ix in range(px(self.roads_v[0] - 40), px(self.roads_v[-1] + 40)):
                    if 0 <= ix < S and 0 <= iy < S:
                        img.setXel(ix, iy, 0.75, 0.73, 0.68)
        for iy in range(py(C.FREEWAY_Y) - 2, py(C.FREEWAY_Y) + 3):
            for ix in range(px(C.FREEWAY_X0), px(C.FREEWAY_X1)):
                if 0 <= ix < S and 0 <= iy < S:
                    img.setXel(ix, iy, 0.85, 0.60, 0.25)
        for ix in range(px(C.FWY110_X) - 2, px(C.FWY110_X) + 3):
            for iy in range(py(C.FWY110_Y1), py(C.FWY110_Y0)):
                if 0 <= ix < S and 0 <= iy < S:
                    img.setXel(ix, iy, 0.85, 0.60, 0.25)
        for ix in range(px(C.FWY405_X) - 2, px(C.FWY405_X) + 3):
            for iy in range(py(C.BASIN_Y1), py(C.BASIN_Y0)):
                if 0 <= ix < S and 0 <= iy < S:
                    img.setXel(ix, iy, 0.85, 0.60, 0.25)
        for k in range(len(C.FWY101_PTS) - 1):
            (ax, ay), (bx, by) = C.FWY101_PTS[k], C.FWY101_PTS[k + 1]
            for s in range(30):
                wx = ax + (bx - ax) * s / 30
                wy = ay + (by - ay) * s / 30
                ix, iy = px(wx), py(wy)
                for ddx in (-1, 0, 1):
                    for ddy in (-1, 0, 1):
                        if 0 <= ix + ddx < S and 0 <= iy + ddy < S:
                            img.setXel(ix + ddx, iy + ddy, 0.85, 0.60, 0.25)
        rect(-1700, -1406, C.PIER_Y - 16, C.PIER_Y + 16, (0.62, 0.48, 0.34))
        self.map_tex = Texture("minimap")
        self.map_tex.load(img)
        self.map_tex.setWrapU(Texture.WMClamp)
        self.map_tex.setWrapV(Texture.WMClamp)

    def world_to_uv(self, x, y):
        u = (x - self.map_x0) / (self.map_x1 - self.map_x0)
        v = (y - self.map_y0) / (self.map_y1 - self.map_y0)
        return u, v
