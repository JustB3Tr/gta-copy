"""Hitscan weapons, tracers, and world pickups."""

import math
import random
from panda3d.core import LineSegs, NodePath
from .meshgen import MeshBuilder

WEAPONS = {
    "fist":    dict(label="Fists",   dmg=10, rof=0.45, spread=0.0,   rng=1.9,  auto=False, pellets=1),
    "pistol":  dict(label="9mm",     dmg=17, rof=0.36, spread=0.014, rng=130,  auto=False, pellets=1),
    "smg":     dict(label="SMG",     dmg=9,  rof=0.10, spread=0.038, rng=100,  auto=True,  pellets=1),
    "shotgun": dict(label="Shotgun", dmg=8,  rof=0.85, spread=0.075, rng=42,   auto=False, pellets=7),
}
WEAPON_ORDER = ["fist", "pistol", "smg", "shotgun"]


def raycast(game, ox, oy, oz, dx, dy, dz, max_range, ignore=None):
    """March a ray against terrain, static colliders, cars, peds/cops, and the player.
    Returns (dist, kind, target, point) with kind in {none, ground, static, car, ped, player}."""
    best = (max_range, "none", None, (ox + dx * max_range, oy + dy * max_range, oz + dz * max_range))

    # dynamic targets as spheres
    def test_sphere(cx, cy, cz, r, kind, target):
        nonlocal best
        lx, ly, lz = cx - ox, cy - oy, cz - oz
        t = lx * dx + ly * dy + lz * dz
        if t < 0 or t > best[0]:
            return
        px, py, pz = ox + dx * t, oy + dy * t, oz + dz * t
        d2 = (px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2
        if d2 < r * r:
            best = (t, kind, target, (px, py, pz))

    for ped in game.peds.everyone():
        if ped is ignore or ped.down:
            continue
        test_sphere(ped.x, ped.y, ped.z + 0.95, 0.55, "ped", ped)
    for car in game.all_world_cars():
        if car is ignore:
            continue
        fx, fy = car.fwd
        for off in (0.28, -0.28):
            test_sphere(car.x + fx * car.spec["l"] * off, car.y + fy * car.spec["l"] * off,
                        car.z + 0.7, car.spec["w"] * 0.62, "car", car)
    p = game.player
    if ignore is not p and p.car is None and not p.dead:
        test_sphere(p.x, p.y, p.z + 0.95, 0.55, "player", p)

    # statics + ground, marched in steps
    steps = max(4, int(best[0] / 3.0))
    seen = set()
    for i in range(steps + 1):
        t = best[0] * i / steps
        px, py, pz = ox + dx * t, oy + dy * t, oz + dz * t
        gz = game.ground.height(px, py)
        if pz < gz:
            best = (t, "ground", None, (px, py, max(gz, pz)))
            break
        hit_static = False
        for col in game.city.query_colliders(px, py, 3.5):
            if col in seen:
                continue
            seen.add(col)
            x0, x1, y0, y1, z0, z1 = col
            ts = _ray_aabb(ox, oy, oz, dx, dy, dz, x0, x1, y0, y1, z0, z1)
            if ts is not None and ts < best[0]:
                best = (ts, "static", None, (ox + dx * ts, oy + dy * ts, oz + dz * ts))
                hit_static = True
        if hit_static:
            break
    return best


def _ray_aabb(ox, oy, oz, dx, dy, dz, x0, x1, y0, y1, z0, z1):
    tmin, tmax = 0.0, 1e9
    for o, d, lo, hi in ((ox, dx, x0, x1), (oy, dy, y0, y1), (oz, dz, z0, z1)):
        if abs(d) < 1e-8:
            if o < lo or o > hi:
                return None
        else:
            t1, t2 = (lo - o) / d, (hi - o) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return None
    return tmin if tmin > 0.001 else None


def fire(game, shooter, ox, oy, oz, dx, dy, dz, weapon):
    """Fire one shot (all pellets). Returns list of (kind, target)."""
    w = WEAPONS[weapon]
    hits = []
    for _ in range(w["pellets"]):
        s = w["spread"]
        ddx = dx + random.uniform(-s, s)
        ddy = dy + random.uniform(-s, s)
        ddz = dz + random.uniform(-s, s)
        l = math.sqrt(ddx * ddx + ddy * ddy + ddz * ddz) or 1
        ddx, ddy, ddz = ddx / l, ddy / l, ddz / l
        dist, kind, target, point = raycast(game, ox, oy, oz, ddx, ddy, ddz,
                                            w["rng"], ignore=shooter)
        game.fx.tracer((ox, oy, oz), point)
        game.fx.impact(point, kind)
        if kind == "ped":
            target.hurt(w["dmg"], (ddx, ddy), by_player=(shooter is game.player))
            hits.append((kind, target))
        elif kind == "car":
            target.damage(w["dmg"] * 0.6)
            if shooter is game.player:
                game.cops.add_heat(0.08)
            hits.append((kind, target))
        elif kind == "player":
            game.player.take_damage(w["dmg"])
            hits.append((kind, target))
    snd = {"pistol": "shot_pistol", "smg": "shot_smg", "shotgun": "shot_shotgun"}.get(weapon)
    if snd:
        d = game.dist_to_player(ox, oy)
        game.sfx.play(snd, vol=max(0.15, 1.0 - d / 120.0), rate=random.uniform(0.94, 1.06))
    if shooter is game.player and weapon != "fist":
        game.peds.scare(ox, oy, 40.0)
        game.cops.witness_gunfire()
    return hits


# ---------------------------------------------------------------- pickups

PICKUP_COLORS = {"pistol": (0.9, 0.9, 0.95), "smg": (0.9, 0.9, 0.95),
                 "shotgun": (0.9, 0.9, 0.95), "ammo": (0.95, 0.7, 0.15),
                 "cash": (0.35, 0.9, 0.45), "health": (0.95, 0.3, 0.3)}


class Pickup:
    def __init__(self, game, kind, x, y, amount=0, respawn=90.0):
        self.game = game
        self.kind = kind
        self.x, self.y = x, y
        self.z = game.ground.surface(x, y, 0)[0]
        self.amount = amount
        self.respawn = respawn
        self.cooldown = 0.0
        self.np = NodePath("pickup")
        b = MeshBuilder("icon")
        c = PICKUP_COLORS[kind]
        if kind in ("pistol", "smg", "shotgun"):
            b.add_box(0, 0.1, 0.55, 0.10, 0.7 if kind != "pistol" else 0.45, 0.12,
                      (0.25, 0.25, 0.30))
            b.add_box(0, -0.12, 0.38, 0.09, 0.14, 0.22, (0.3, 0.28, 0.25))
        elif kind == "ammo":
            b.add_box(0, 0, 0.35, 0.5, 0.35, 0.3, (0.35, 0.45, 0.25), top_color=c)
        elif kind == "cash":
            b.add_box(0, 0, 0.35, 0.45, 0.3, 0.16, c)
        elif kind == "health":
            b.add_box(0, 0, 0.3, 0.5, 0.5, 0.4, (0.95, 0.95, 0.95))
            b.add_box(0, 0, 0.72, 0.36, 0.12, 0.1, c)
            b.add_box(0, 0, 0.72, 0.12, 0.36, 0.1, c)
        # glow disc
        b.add_rect(-0.6, -0.6, 0.6, 0.6, 0.06, (c[0], c[1], c[2], 0.35))
        self.np = b.build(game.render)
        self.np.setTransparency(True)
        self.np.setPos(x, y, self.z)

    def update(self, dt, t):
        if self.cooldown > 0:
            self.cooldown -= dt
            if self.cooldown <= 0:
                self.np.show()
            return
        self.np.setH(t * 90 % 360)
        self.np.setZ(self.z + 0.15 + 0.12 * math.sin(t * 3))
        p = self.game.player
        if p.car is None and not p.dead:
            d2 = (p.x - self.x) ** 2 + (p.y - self.y) ** 2
            if d2 < 1.8 * 1.8 and abs(p.z - self.z) < 2.5:
                if self.collect(p):
                    self.game.sfx.play("pickup", 0.7)
                    if self.respawn > 0:
                        self.cooldown = self.respawn
                        self.np.hide()
                    else:
                        self.np.removeNode()
                        self.game.pickups.remove(self)

    def collect(self, p):
        if self.kind in ("pistol", "smg", "shotgun"):
            p.give_weapon(self.kind, 40 if self.kind != "shotgun" else 16)
            self.game.hud.flash_message("Picked up %s" % WEAPONS[self.kind]["label"])
        elif self.kind == "ammo":
            p.give_ammo(60)
            self.game.hud.flash_message("Ammo +60")
        elif self.kind == "cash":
            p.money += self.amount or 40
            self.game.hud.flash_message("+$%d" % (self.amount or 40))
        elif self.kind == "health":
            if p.health >= 100:
                return False
            p.health = min(100.0, p.health + 50)
            self.game.hud.flash_message("Patched up")
        return True


# ---------------------------------------------------------------- visual fx

class FXPool:
    """Short-lived tracers / impact puffs / explosion flashes, plus persistent
    fading skid marks and water effects."""

    SKID_TTL = 16.0
    MAX_SKIDS = 260

    def __init__(self, game):
        self.game = game
        self.items = []   # (np, ttl, grow)
        self.skids = []   # (np, ttl)
        self._skid_gap = 0.0

    def skid_mark(self, x, y, z, heading):
        # distance-gate so marks form a dashed trail rather than a solid smear
        if self.skids:
            last = self.skids[-1][0]
            if (last.getX() - x) ** 2 + (last.getY() - y) ** 2 < 0.55:
                return
        b = MeshBuilder("skid")
        b.add_rect(-0.14, -0.65, 0.14, 0.65, 0.0, (0.05, 0.05, 0.06, 0.55))
        np = b.build(self.game.render)
        np.setPos(x, y, z + 0.06)
        np.setH(math.degrees(heading))
        np.setTransparency(True)
        np.setDepthWrite(False)
        self.skids.append([np, self.SKID_TTL])
        if len(self.skids) > self.MAX_SKIDS:
            old = self.skids.pop(0)
            old[0].removeNode()

    def dust(self, x, y, z, color):
        b = MeshBuilder("dust")
        b.add_box(0, 0, 0, 0.5, 0.5, 0.4, color)
        np = b.build(self.game.render)
        np.setPos(x, y, z)
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 0.7, 2.6])

    def wake(self, x, y, small=False):
        b = MeshBuilder("wake")
        s = 0.6 if small else 1.1
        b.add_rect(-s, -s * 0.7, s, s * 0.7, 0.0, (0.95, 0.98, 0.97, 0.5))
        np = b.build(self.game.render)
        from . import config as _C
        np.setPos(x, y, _C.WATER_Z + 0.08)
        np.setLightOff()
        np.setTransparency(True)
        np.setDepthWrite(False)
        self.items.append([np, 1.1, 1.8])

    def ripple(self, x, y):
        b = MeshBuilder("ripple")
        for k in range(8):
            a0 = math.tau * k / 8
            a1 = math.tau * (k + 1) / 8
            r0, r1 = 0.85, 1.0
            b.add_quad((math.cos(a0) * r0, math.sin(a0) * r0, 0),
                       (math.cos(a0) * r1, math.sin(a0) * r1, 0),
                       (math.cos(a1) * r1, math.sin(a1) * r1, 0),
                       (math.cos(a1) * r0, math.sin(a1) * r0, 0),
                       (0.95, 0.98, 0.97, 0.55), (0, 0, 1))
        np = b.build(self.game.render)
        from . import config as _C
        np.setPos(x, y, _C.WATER_Z + 0.1)
        np.setLightOff()
        np.setTransparency(True)
        np.setDepthWrite(False)
        self.items.append([np, 1.0, 3.2])

    def splash(self, x, y):
        b = MeshBuilder("splash")
        b.add_dome(0, 0, 0, 1.0, (0.92, 0.96, 0.97, 0.75), sides=8, rings=2)
        np = b.build(self.game.render)
        from . import config as _C
        np.setPos(x, y, _C.WATER_Z)
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 0.5, 5.0])
        self.ripple(x, y)

    def tracer(self, a, b):
        segs = LineSegs()
        segs.setThickness(2.0)
        segs.setColor(1.0, 0.95, 0.6, 0.9)
        segs.moveTo(*a)
        segs.drawTo(*b)
        np = self.game.render.attachNewNode(segs.create())
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 0.07, 0.0])

    def impact(self, point, kind):
        b = MeshBuilder("puff")
        col = (1.0, 0.9, 0.5, 0.9) if kind in ("static", "ground", "none") else (1, 0.5, 0.2, 0.9)
        s = 0.16
        x, y, z = point
        b.add_box(x, y, z - s / 2, s, s, s, col)
        np = b.build(self.game.render)
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 0.12, 3.0])

    def explosion(self, x, y, z):
        b = MeshBuilder("boom")
        b.add_dome(0, 0, -1.2, 1.6, (1.0, 0.75, 0.25, 0.85), sides=10, rings=3)
        np = b.build(self.game.render)
        np.setPos(x, y, z + 1.0)
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 0.5, 16.0])
        b = MeshBuilder("smoke")
        b.add_dome(0, 0, 0, 1.2, (0.2, 0.2, 0.22, 0.6), sides=8, rings=2)
        np = b.build(self.game.render)
        np.setPos(x, y, z + 1.2)
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 1.2, 6.0])

    def smoke_puff(self, x, y, z):
        b = MeshBuilder("s")
        b.add_box(0, 0, 0, 0.3, 0.3, 0.3, (0.25, 0.25, 0.28, 0.5))
        np = b.build(self.game.render)
        np.setPos(x, y, z)
        np.setLightOff()
        np.setTransparency(True)
        self.items.append([np, 0.9, 2.0])

    def update(self, dt):
        keep_s = []
        for sk in self.skids:
            sk[1] -= dt
            if sk[1] <= 0:
                sk[0].removeNode()
                continue
            sk[0].setAlphaScale(min(1.0, sk[1] / (self.SKID_TTL * 0.5)))
            keep_s.append(sk)
        self.skids = keep_s
        keep = []
        for it in self.items:
            it[1] -= dt
            if it[1] <= 0:
                it[0].removeNode()
                continue
            if it[2]:
                s = 1.0 + it[2] * dt
                it[0].setScale(it[0].getScale() * s)
                it[0].setZ(it[0].getZ() + dt * 1.2)
            it[0].setAlphaScale(max(0.1, min(1.0, it[1] * 8)))
            keep.append(it)
        self.items = keep
