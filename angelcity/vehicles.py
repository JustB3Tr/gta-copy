"""Cars: procedural bodies, arcade physics, AI traffic that follows the road grid,
plus ambient freeway cruisers on the elevated deck."""

import math
import random
from panda3d.core import NodePath
from . import config as C
from .meshgen import MeshBuilder

KINDS = {
    #            length width height  accel  top   grip   hp   name
    "sedan":   dict(l=4.6, w=1.9, h=1.42, accel=9.5,  top=33, grip=6.0, hp=100, name="Cascade"),
    "coupe":   dict(l=4.4, w=1.9, h=1.16, accel=15.0, top=46, grip=7.0, hp=85,  name="Vantura GT"),
    "lowrider": dict(l=5.1, w=2.0, h=1.30, accel=12.0, top=39, grip=5.2, hp=95,  name="Marquee 64"),
    "pickup":  dict(l=5.2, w=2.1, h=1.80, accel=8.5,  top=32, grip=5.5, hp=120, name="Bronco Bay"),
    "van":     dict(l=5.0, w=2.1, h=2.20, accel=7.0,  top=28, grip=4.8, hp=110, name="Cargo Queen"),
    "taxi":    dict(l=4.6, w=1.9, h=1.46, accel=10.0, top=34, grip=6.0, hp=100, name="Angel Cab"),
    "police":  dict(l=4.8, w=1.95, h=1.50, accel=13.5, top=43, grip=6.8, hp=130, name="APD Cruiser"),
    "beater":  dict(l=4.5, w=1.9, h=1.40, accel=7.0,  top=26, grip=5.0, hp=70,  name="Rustbucket"),
}

PALETTES = {
    "sedan": [(0.75, 0.75, 0.78), (0.35, 0.38, 0.45), (0.55, 0.12, 0.12), (0.16, 0.30, 0.50),
              (0.85, 0.83, 0.75), (0.20, 0.20, 0.22), (0.45, 0.55, 0.50)],
    "coupe": [(0.85, 0.10, 0.15), (0.95, 0.60, 0.10), (0.10, 0.60, 0.70), (0.90, 0.88, 0.90),
              (0.25, 0.80, 0.40), (0.15, 0.15, 0.18)],
    "lowrider": [(0.60, 0.10, 0.45), (0.15, 0.35, 0.70), (0.75, 0.55, 0.10), (0.45, 0.05, 0.08)],
    "pickup": [(0.55, 0.25, 0.15), (0.30, 0.35, 0.30), (0.70, 0.70, 0.72), (0.20, 0.25, 0.40)],
    "van": [(0.80, 0.78, 0.72), (0.40, 0.50, 0.60), (0.60, 0.30, 0.20), (0.30, 0.30, 0.32)],
    "taxi": [(0.95, 0.75, 0.10)],
    "police": [(0.10, 0.10, 0.12)],
    "beater": [(0.45, 0.35, 0.25), (0.40, 0.42, 0.38), (0.50, 0.20, 0.15)],
}

GLASS = (0.16, 0.22, 0.28)
TIRE = (0.10, 0.10, 0.11)

_protos = {}


def _build_body(kind, color):
    k = KINDS[kind]
    l, w, h = k["l"], k["w"], k["h"]
    root = NodePath("car_proto")
    b = MeshBuilder("body")
    ride = 0.32                      # ground to floor
    body_top = ride + (h - ride) * 0.55
    dark = tuple(c * 0.55 for c in color)

    if kind == "van":
        b.add_box(0, 0, ride, w, l, h - ride - 0.1, color, top_color=tuple(c * 0.9 for c in color))
        b.add_box(0, l * 0.38, ride + 0.25, w - 0.15, l * 0.22, 0.55, GLASS)  # windshield hint
    elif kind == "pickup":
        b.add_box(0, -l * 0.18, ride, w, l * 0.62, body_top - ride, color)
        b.add_box(0, l * 0.28, ride, w, l * 0.42, body_top - ride + 0.05, color)
        b.add_box(0, l * 0.10, body_top, w - 0.30, l * 0.30, h - body_top, GLASS)
        b.add_box(0, l * 0.10, h - 0.06, w - 0.26, l * 0.32, 0.07, color)
        b.add_box(0, -l * 0.20, ride + 0.35, w - 0.24, l * 0.52, 0.06, dark)  # bed
    else:
        b.add_box(0, 0, ride, w, l * 0.96, body_top - ride, color)
        cab_len = l * (0.36 if kind == "coupe" else 0.44)
        cab_off = -l * 0.06
        b.add_box(0, cab_off, body_top, w - 0.26, cab_len, h - body_top, GLASS)
        b.add_box(0, cab_off, h - 0.055, w - 0.20, cab_len + 0.15, 0.06, color)
        if kind == "coupe":
            b.add_box(0, -l * 0.44, body_top, w - 0.3, 0.25, 0.16, color)  # spoiler
        if kind == "lowrider":
            b.add_box(0, 0, ride - 0.05, w + 0.06, l * 0.98, 0.08, (0.9, 0.85, 0.5))  # chrome trim

    # bumpers, lights
    b.add_box(0, l * 0.49, ride, w - 0.1, 0.14, 0.22, dark)
    b.add_box(0, -l * 0.49, ride, w - 0.1, 0.14, 0.22, dark)
    for sx in (-1, 1):
        b.add_box(sx * (w / 2 - 0.24), l * 0.485, ride + 0.22, 0.20, 0.06, 0.12,
                  (0.95, 0.95, 0.75))
    b.build(root)

    # tail lights as separate node so we can brighten on brake
    tb = MeshBuilder("brake")
    for sx in (-1, 1):
        tb.add_box(sx * (w / 2 - 0.24), -l * 0.487, ride + 0.22, 0.22, 0.06, 0.12,
                   (0.6, 0.05, 0.05))
    brake = tb.build(root)
    brake.setName("brakelights")

    if kind == "taxi":
        tb = MeshBuilder("sign")
        tb.add_box(0, -l * 0.06, h + 0.01, 0.5, 0.24, 0.20, (0.95, 0.75, 0.10))
        tb.build(root)
        sb = MeshBuilder("stripe")
        sb.add_box(0, 0, 0.62, w + 0.02, l * 0.9, 0.10, (0.2, 0.2, 0.22))
        sb.build(root)
    if kind == "police":
        pb = MeshBuilder("livery")
        pb.add_box(0, l * 0.30, ride + 0.02, w + 0.02, l * 0.30, 0.30, (0.92, 0.92, 0.92))
        pb.add_box(0, -l * 0.34, ride + 0.02, w + 0.02, l * 0.24, 0.30, (0.92, 0.92, 0.92))
        pb.build(root)
        lb = MeshBuilder("bar_red")
        lb.add_box(-0.28, -l * 0.06, h + 0.02, 0.42, 0.28, 0.14, (0.95, 0.10, 0.10))
        red = lb.build(root)
        red.setName("bar_red")
        lb = MeshBuilder("bar_blue")
        lb.add_box(0.28, -l * 0.06, h + 0.02, 0.42, 0.28, 0.14, (0.15, 0.25, 0.95))
        blue = lb.build(root)
        blue.setName("bar_blue")

    # headlight ground cones (shown at night)
    hb = MeshBuilder("headlights")
    for sx in (-0.55, 0.55):
        x0 = sx * w / 2
        hb.add_quad((x0 - 0.35, l * 0.5, 0.06), (x0 + 0.35, l * 0.5, 0.06),
                    (x0 + 1.1, l * 0.5 + 9.0, 0.06), (x0 - 1.1, l * 0.5 + 9.0, 0.06),
                    (0.95, 0.9, 0.6, 0.30), (0, 0, 1))
    hl = hb.build(root)
    hl.setName("headlights")
    hl.setTransparency(True)
    hl.setLightOff()
    hl.hide()

    # blob shadow
    sb = MeshBuilder("shadow")
    sb.add_rect(-w / 2 - 0.15, -l / 2 - 0.1, w / 2 + 0.15, l / 2 + 0.1, 0.03,
                (0.05, 0.05, 0.07, 0.35))
    sh = sb.build(root)
    sh.setTransparency(True)

    # wheels
    r = 0.34
    wb = MeshBuilder("wheel")
    wb.add_cylinder(0, 0, -0.125, r, 0.25, TIRE, sides=10)
    wb.add_cylinder(0, 0, -0.13, r * 0.5, 0.26, (0.55, 0.55, 0.58), sides=8)
    wheel_proto = NodePath("wp")
    wnp = wb.build(wheel_proto)
    wnp.setP(90)
    for name, (sx, sy) in {"wheel_fl": (-1, 0.32), "wheel_fr": (1, 0.32),
                           "wheel_rl": (-1, -0.34), "wheel_rr": (1, -0.34)}.items():
        piv = root.attachNewNode(name)
        piv.setPos(sx * (w / 2 - 0.08), sy * l, r)
        wheel_proto.getChild(0).copyTo(piv)
    return root


def get_car_proto(kind, color):
    key = (kind, color)
    if key not in _protos:
        _protos[key] = _build_body(kind, color)
    return _protos[key]


class Car:
    def __init__(self, game, kind, x, y, heading, color=None, driver=None):
        self.game = game
        self.kind = kind
        self.spec = KINDS[kind]
        self.color = color or random.choice(PALETTES[kind])
        self.np = NodePath("car")
        get_car_proto(kind, self.color).copyTo(self.np)
        self.np.reparentTo(game.render)
        self.wheels = {n: self.np.find("**/" + n) for n in
                       ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr")}
        self.brake_np = self.np.find("**/brakelights")
        self.head_np = self.np.find("**/headlights")
        self.bar_red = self.np.find("**/bar_red")
        self.bar_blue = self.np.find("**/bar_blue")
        self.x, self.y = x, y
        self.z, _ = game.ground.surface(x, y, 0)
        self.heading = heading          # radians; forward = (-sin h, cos h)
        self.speed = 0.0
        self.vx = self.vy = 0.0
        self.vz = 0.0
        self.airborne = False
        self.hp = float(self.spec["hp"])
        self.driver = driver            # None | "player" | "ai" | "cop"
        self.wheel_spin = 0.0
        self.steer_vis = 0.0
        self.stuck_t = 0.0
        self.smoke_t = 0.0
        self.wreck = False
        self.flash_t = 0.0
        # traffic AI state
        self.route = None
        self.cruise = 12.0
        self.sync()

    @property
    def fwd(self):
        return (-math.sin(self.heading), math.cos(self.heading))

    @property
    def vel_mag(self):
        return math.hypot(self.vx, self.vy)

    def control(self, dt, throttle, steer, handbrake):
        """Arcade bicycle model with drift; works on slopes and overlay decks."""
        if self.wreck:
            throttle = 0.0
        fx, fy = self.fwd
        # slope force along forward
        g = self.game.ground
        half = self.spec["l"] * 0.4
        zf, _ = g.surface(self.x + fx * half, self.y + fy * half, self.z)
        zb, _ = g.surface(self.x - fx * half, self.y - fy * half, self.z)
        pitch = math.atan2(zf - zb, 2 * half)

        self.speed = self.vx * fx + self.vy * fy
        top = self.spec["top"]
        if throttle > 0:
            acc = self.spec["accel"] * (1.0 - max(0.0, self.speed) / top)
        elif throttle < 0:
            acc = self.spec["accel"] * (0.8 if self.speed > 0.5 else 0.45)
        else:
            acc = 0.0
        a = throttle * abs(acc) - math.sin(pitch) * 6.5
        if handbrake:
            a -= math.copysign(min(abs(self.speed) * 2, 10), self.speed)
        self.speed += a * dt
        self.speed -= self.speed * 0.25 * dt          # drag
        self.speed = max(-top * 0.4, min(top, self.speed))

        turn_authority = min(1.0, abs(self.speed) / 7.0)
        yaw = steer * 2.3 * turn_authority * (1.0 if self.speed >= 0 else -1.0)
        if handbrake:
            yaw *= 1.5
        if not self.airborne:
            self.heading += yaw * dt
        fx, fy = self.fwd

        grip = self.spec["grip"] * (0.28 if handbrake else 1.0)
        k = min(1.0, grip * dt)
        self.vx += (fx * self.speed - self.vx) * k
        self.vy += (fy * self.speed - self.vy) * k

        self.steer_vis += (steer * 30 - self.steer_vis) * min(1, 10 * dt)
        self.wheel_spin += self.speed * dt / 0.34 * 57.3
        if not self.brake_np.isEmpty():
            braking = throttle < 0 or handbrake
            self.brake_np.setColorScale((3, 0.6, 0.6, 1) if braking else (1, 1, 1, 1))

    def integrate(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        g = self.game.ground
        zg, on = g.surface(self.x, self.y, self.z)
        if self.z > zg + 0.25:
            self.airborne = True
            self.vz -= 22.0 * dt
            self.z += self.vz * dt
            if self.z <= zg:
                self.z = zg
                if self.vz < -8:
                    self.damage(min(30, -self.vz * 1.5), silent=False)
                self.vz = 0.0
                self.airborne = False
        else:
            self.z += (zg - self.z) * min(1, 12 * dt)
            self.vz = 0.0
            self.airborne = False

    def collide_static(self):
        game = self.game
        fx, fy = self.fwd
        hit = 0.0
        for off in (0.30, -0.30):
            cx = self.x + fx * self.spec["l"] * off
            cy = self.y + fy * self.spec["l"] * off
            r = self.spec["w"] * 0.55
            for (x0, x1, y0, y1, z0, z1) in game.city.query_colliders(cx, cy, r + 1):
                if self.z > z1 - 0.3 or self.z + 1.4 < z0:
                    continue
                nx = max(x0, min(cx, x1))
                ny = max(y0, min(cy, y1))
                dx, dy = cx - nx, cy - ny
                d2 = dx * dx + dy * dy
                if d2 < r * r:
                    d = math.sqrt(d2) or 0.001
                    push = (r - d)
                    ux, uy = dx / d, dy / d
                    self.x += ux * push
                    self.y += uy * push
                    vn = self.vx * ux + self.vy * uy
                    if vn < 0:
                        hit = max(hit, -vn)
                        self.vx -= ux * vn * 1.4
                        self.vy -= uy * vn * 1.4
                        self.speed *= 0.4
        if hit > 4.0:
            self.damage(hit * 1.6)
            game.on_crash(self, hit)
        return hit

    def collide_car(self, other):
        fx, fy = self.fwd
        ofx, ofy = other.fwd
        for a_off in (0.3, -0.3):
            ax = self.x + fx * self.spec["l"] * a_off
            ay = self.y + fy * self.spec["l"] * a_off
            for b_off in (0.3, -0.3):
                bx = other.x + ofx * other.spec["l"] * b_off
                by = other.y + ofy * other.spec["l"] * b_off
                if abs(self.z - other.z) > 2.0:
                    continue
                r = (self.spec["w"] + other.spec["w"]) * 0.55
                dx, dy = ax - bx, ay - by
                d2 = dx * dx + dy * dy
                if d2 < r * r and d2 > 0.0001:
                    d = math.sqrt(d2)
                    ux, uy = dx / d, dy / d
                    push = (r - d) * 0.5
                    self.x += ux * push
                    self.y += uy * push
                    other.x -= ux * push
                    other.y -= uy * push
                    rvx, rvy = self.vx - other.vx, self.vy - other.vy
                    vn = rvx * ux + rvy * uy
                    if vn < 0:
                        imp = -vn * 0.6
                        self.vx += ux * imp
                        self.vy += uy * imp
                        other.vx -= ux * imp
                        other.vy -= uy * imp
                        if -vn > 4:
                            self.damage(-vn * 1.2)
                            other.damage(-vn * 1.2)
                            self.game.on_car_hit_car(self, other, -vn)
                    return True
        return False

    def damage(self, amount, silent=True):
        if self.wreck:
            return
        self.hp -= amount
        self.flash_t = 0.1
        if self.hp <= 0:
            self.hp = 0
            self.become_wreck()

    def become_wreck(self):
        if self.wreck:
            return
        self.wreck = True
        self.np.setColorScale(0.25, 0.22, 0.20, 1)
        self.head_np.hide()
        self.game.on_explosion(self)

    def sync(self):
        self.np.setPos(self.x, self.y, self.z)
        self.np.setH(math.degrees(self.heading))
        # pitch/roll from ground normal (only when grounded)
        if not self.airborne:
            g = self.game.ground
            fx, fy = self.fwd
            rx, ry = fy, -fx
            hl = self.spec["l"] * 0.4
            hw = self.spec["w"] * 0.5
            zf, _ = g.surface(self.x + fx * hl, self.y + fy * hl, self.z)
            zb, _ = g.surface(self.x - fx * hl, self.y - fy * hl, self.z)
            zr, _ = g.surface(self.x + rx * hw, self.y + ry * hw, self.z)
            zl, _ = g.surface(self.x - rx * hw, self.y - ry * hw, self.z)
            self.np.setP(math.degrees(math.atan2(zf - zb, 2 * hl)))
            self.np.setR(math.degrees(math.atan2(zl - zr, 2 * hw)))
        for n, w in self.wheels.items():
            if w and not w.isEmpty():
                w.setP(-self.wheel_spin % 360)
                if n in ("wheel_fl", "wheel_fr"):
                    w.setH(self.steer_vis)

    def set_headlights(self, on):
        if self.head_np.isEmpty():
            return
        if on and not self.wreck:
            self.head_np.show()
        else:
            self.head_np.hide()

    def flash_lightbar(self, t):
        if self.bar_red.isEmpty():
            return
        phase = int(t * 5) % 2
        self.bar_red.setColorScale((3, 0.3, 0.3, 1) if phase else (0.7, 0.2, 0.2, 1))
        self.bar_blue.setColorScale((0.3, 0.3, 3, 1) if not phase else (0.2, 0.2, 0.7, 1))

    def destroy(self):
        self.np.removeNode()


# ---------------------------------------------------------------- traffic AI

def _lane_pos(road_axis, road_coord, direction):
    """Right-hand traffic lane offset for a road. Returns offset perpendicular."""
    return road_coord + C.LANE_OFFSET * (-direction if road_axis == "h" else direction)


class TrafficCar:
    """Wraps a Car with grid-following behaviour."""

    def __init__(self, car, axis, road_coord, direction):
        self.car = car
        self.axis = axis          # 'v' drives along y on a vertical avenue, 'h' along x
        self.road = road_coord
        self.dir = direction      # +1/-1 along the travel axis
        self.turn_target = None
        self.decided_at = None
        car.driver = "ai"
        car.cruise = random.uniform(10.5, 15.0)

    def lane_coord(self):
        if self.axis == "v":
            return self.road + C.LANE_OFFSET * self.dir
        return self.road - C.LANE_OFFSET * self.dir

    def desired_heading(self):
        if self.axis == "v":
            return 0.0 if self.dir > 0 else math.pi
        return -math.pi / 2 if self.dir > 0 else math.pi / 2

    def _plan_turn(self, nxt, new_dir):
        """Set a waypoint ~14m past the intersection on the new road's proper lane."""
        if self.axis == "v":
            # turning onto horizontal road y=nxt
            tx = self.road + 14 * new_dir
            ty = nxt - C.LANE_OFFSET * new_dir
            self.turn_target = (tx, ty, "h", nxt, new_dir)
        else:
            # turning onto vertical avenue x=nxt
            tx = nxt + C.LANE_OFFSET * new_dir
            ty = self.road + 14 * new_dir
            self.turn_target = (tx, ty, "v", nxt, new_dir)

    def update(self, game, dt):
        car = self.car
        if car.wreck:
            return
        along = car.y if self.axis == "v" else car.x
        cross = car.x if self.axis == "v" else car.y
        lane = self.lane_coord()

        # next crossing road in the travel direction
        lines = game.city.roads_h if self.axis == "v" else game.city.roads_v
        ahead = [L for L in lines if (L - along) * self.dir > 6]
        nxt = min(ahead, key=lambda L: (L - along) * self.dir) if ahead else None

        if self.turn_target is None and nxt is not None and abs(nxt - along) < 26 \
                and self.decided_at != nxt:
            self.decided_at = nxt
            last_chance = len(ahead) == 1   # road is about to end — must turn
            if last_chance or random.random() < 0.30:
                self._plan_turn(nxt, random.choice((-1, 1)))
        elif self.turn_target is None and nxt is None:
            # ran out of road (shouldn't normally happen): U-turn onto opposite lane
            self.dir = -self.dir
            self.decided_at = None

        target_speed = car.cruise
        # obey traffic signals at major×major intersections
        if self.turn_target is None and nxt is not None:
            own_major = self.road in (game.city.major_vs if self.axis == "v"
                                      else game.city.major_hs)
            cross_major = nxt in (game.city.major_hs if self.axis == "v"
                                  else game.city.major_vs)
            if own_major and cross_major and not C.light_green(self.axis, game.t):
                gap = (nxt - along) * self.dir
                if 9 < gap < 26:
                    target_speed = 0.0
        if self.turn_target:
            tx, ty, na, nr, nd = self.turn_target
            dx, dy = tx - car.x, ty - car.y
            target_speed = 7.0
            want = math.atan2(-dx, dy)
            if math.hypot(dx, dy) < 3.5:
                self.axis, self.road, self.dir = na, nr, nd
                self.turn_target = None
                self.decided_at = None
        else:
            # steer toward a lookahead point on the lane centerline
            err = lane - cross
            look = 14.0
            if self.axis == "v":
                want = math.atan2(-err, look * self.dir)
            else:
                want = math.atan2(-look * self.dir, err)

        # obstacle ahead → brake
        fx, fy = car.fwd
        obs = False
        for ox, oy, oz in game.traffic_obstacles(car):
            rx, ry = ox - car.x, oy - car.y
            ahead = rx * fx + ry * fy
            side = abs(-rx * fy + ry * fx)
            if 2 < ahead < 13 and side < 2.4 and abs(oz - car.z) < 2.5:
                obs = True
                break
        if obs:
            target_speed = 0.0

        derr = (want - car.heading + math.pi) % (2 * math.pi) - math.pi
        steer = max(-1.0, min(1.0, derr * 2.2))
        if car.speed < target_speed - 0.5:
            throttle = 0.75
        elif car.speed > target_speed + 1.0:
            throttle = -0.8 if target_speed < 1 else -0.3
        else:
            throttle = 0.1
        car.control(dt, throttle, steer, False)


class Traffic:
    def __init__(self, game):
        self.game = game
        self.cars = []          # TrafficCar list
        self.freeway = []       # simple deck cruisers (Car)
        self.parked = []        # plain Cars, enterable
        rng = random.Random(11)
        for (x, y, h, kind) in game.city.parked_spots[:C.MAX_PARKED]:
            color = rng.choice(PALETTES[kind])
            self.parked.append(Car(game, kind, x, y, h, color=color))

    def _spawn_one(self, rng):
        game = self.game
        px, py = game.player_world_pos()
        for _ in range(14):
            axis = rng.choice(("v", "h"))
            if axis == "v":
                road = rng.choice(game.city.roads_v)
                along = rng.uniform(C.BASIN_Y0 + 40, C.BASIN_Y1 - 40)
                d = rng.choice((-1, 1))
                x, y = road + C.LANE_OFFSET * d, along
            else:
                road = rng.choice(game.city.roads_h)
                along = rng.uniform(C.BASIN_X0 + 40, C.BASIN_X1 - 40)
                d = rng.choice((-1, 1))
                x, y = along, road - C.LANE_OFFSET * d
            dist = math.hypot(x - px, y - py)
            if C.SPAWN_RING[0] < dist < C.SPAWN_RING[1]:
                kind = rng.choices(("sedan", "coupe", "lowrider", "pickup", "van", "taxi", "beater"),
                                   weights=(30, 12, 8, 14, 12, 14, 10))[0]
                car = Car(game, kind, x, y, 0, driver="ai")
                tc = TrafficCar(car, axis, road, d)
                car.heading = tc.desired_heading()
                car.sync()
                self.cars.append(tc)
                return

    def update(self, dt, t):
        game = self.game
        rng = random.Random(int(t * 997) ^ 12345)
        px, py = game.player_world_pos()
        # cull & top up
        keep = []
        for tc in self.cars:
            d = math.hypot(tc.car.x - px, tc.car.y - py)
            if d > C.DESPAWN_R or (tc.car.wreck and d > 80):
                tc.car.destroy()
            else:
                keep.append(tc)
        self.cars = keep
        if len(self.cars) < C.MAX_TRAFFIC and int(t * 10) % 3 == 0:
            self._spawn_one(rng)
        for tc in self.cars:
            tc.update(game, dt)

        # freeway ambience on the elevated 10 (E-W) and 110 (N-S)
        if len(self.freeway) < C.MAX_FREEWAY_CARS and rng.random() < 0.05:
            kind = rng.choice(("sedan", "coupe", "van", "pickup"))
            if rng.random() < 0.6:
                lane_y = C.FREEWAY_Y + rng.choice((-7.5, -3.5, 3.5, 7.5))
                east = lane_y < C.FREEWAY_Y
                x = C.FREEWAY_X0 + 5 if east else C.FREEWAY_X1 - 5
                car = Car(self.game, kind, x, lane_y,
                          -math.pi / 2 if east else math.pi / 2, driver="ai")
                car.z = C.FREEWAY_Z + 0.8
            else:
                lane_x = C.FWY110_X + rng.choice((-6.5, -3.0, 3.0, 6.5))
                north = lane_x > C.FWY110_X
                y = C.FWY110_Y0 + 8 if north else C.FWY110_Y1 - 8
                car = Car(self.game, kind, lane_x, y, 0.0 if north else math.pi,
                          driver="ai")
                car.z = C.FWY110_Z + 0.8
            car.cruise = rng.uniform(20, 26)
            self.freeway.append(car)
        keep = []
        for car in self.freeway:
            fx, fy = car.fwd
            car.speed = car.cruise
            car.vx, car.vy = fx * car.speed, fy * car.speed
            car.x += car.vx * dt
            car.y += car.vy * dt
            car.z, _ = self.game.ground.surface(car.x, car.y, car.z)
            car.wheel_spin += car.speed * dt / 0.34 * 57.3
            car.sync()
            if (C.FREEWAY_X0 - 20 < car.x < C.FREEWAY_X1 + 20 and
                    C.FWY110_Y0 - 20 < car.y < C.FWY110_Y1 + 20):
                keep.append(car)
            else:
                car.destroy()
        self.freeway = keep

    def all_cars(self):
        for tc in self.cars:
            yield tc.car
        for c in self.parked:
            yield c
        for c in self.freeway:
            yield c

    def remove_car(self, car):
        """Player took this car — promote it out of traffic management."""
        self.cars = [tc for tc in self.cars if tc.car is not car]
        if car in self.parked:
            self.parked.remove(car)
        if car in self.freeway:
            self.freeway.remove(car)


# ---------------------------------------------------------------- boats & aircraft

BOAT_SPEC = dict(l=6.5, w=2.4, h=1.8, accel=8.0, top=26, grip=2.2, hp=80, name="Marlin 500")

AIR_SPECS = {
    "prop": dict(l=8.5, w=2.2, h=2.6, accel=9.0, top=52, hp=70, stall=16,
                 name="Duster 150"),
    "jet":  dict(l=13.0, w=2.6, h=3.4, accel=16.0, top=95, hp=90, stall=26,
                 name="Sunjet 700"),
    "heli": dict(l=9.0, w=2.4, h=3.0, accel=11.0, top=42, hp=80, stall=0,
                 name="Hummingbird H2"),
}


def _build_boat(color):
    root = NodePath("boat_proto")
    b = MeshBuilder("hull")
    white = (0.92, 0.92, 0.90)
    b.add_box(0, -0.6, 0.15, 2.3, 4.6, 1.0, white)
    b.add_box(0, 2.2, 0.15, 1.5, 1.6, 0.9, white)          # bow
    b.add_box(0, 0.4, 1.05, 2.1, 2.6, 0.35, color)          # deck trim
    b.add_box(0, 1.15, 1.15, 1.7, 0.15, 0.7, GLASS)         # windshield
    b.add_box(0, -2.6, 0.5, 0.8, 0.5, 1.0, (0.25, 0.25, 0.28))  # outboard
    b.add_box(0, -0.9, 1.05, 1.4, 1.6, 0.4, (0.75, 0.55, 0.35))  # seats
    b.build(root)
    return root


def _build_plane(sub, color):
    root = NodePath("plane_proto")
    b = MeshBuilder("body")
    k = AIR_SPECS[sub]
    l = k["l"]
    white = color
    if sub == "prop":
        b.add_box(0, 0, 0.9, 1.4, l * 0.72, 1.5, white)
        b.add_box(0, l * 0.42, 1.0, 1.0, l * 0.22, 1.1, white)          # nose
        b.add_box(0, 0.6, 2.0, 1.2, 1.8, 0.7, GLASS)                    # canopy
        b.add_box(0, 0.4, 2.1, 11.0, 1.9, 0.25, (0.85, 0.25, 0.2))      # high wing
        b.add_box(0, -l * 0.42, 1.4, 4.2, 1.1, 0.22, (0.85, 0.25, 0.2))  # stabilizer
        b.add_box(0, -l * 0.44, 1.5, 0.2, 1.2, 1.6, white)              # fin
        for sx in (-1.1, 1.1):
            b.add_box(sx, 0.8, 0.15, 0.25, 0.25, 0.8, (0.3, 0.3, 0.32))
            b.add_cylinder(sx, 0.8, 0.0, 0.3, 0.28, TIRE, sides=8)
        b.add_box(0, l * 0.40, 0.15, 0.25, 0.25, 0.9, (0.3, 0.3, 0.32))
    else:  # jet
        b.add_box(0, 0, 1.2, 1.9, l * 0.78, 1.9, white)
        b.add_box(0, l * 0.44, 1.4, 1.3, l * 0.16, 1.3, white)
        b.add_box(0, l * 0.30, 2.5, 1.5, 2.2, 0.6, GLASS)
        # swept wings
        for s in (-1, 1):
            b.add_box(s * 4.4, -0.8, 1.25, 8.0, 2.6, 0.28, white, heading=s * 0.5)
            b.add_cylinder(s * 2.6, -1.6, 0.7, 0.55, 2.6, (0.35, 0.35, 0.4), sides=8)
        b.add_box(0, -l * 0.42, 2.2, 4.6, 1.4, 0.25, white)
        b.add_box(0, -l * 0.44, 2.2, 0.25, 1.6, 2.4, (0.85, 0.55, 0.15))
        for sx in (-1.4, 1.4):
            b.add_box(sx, 0.4, 0.3, 0.25, 0.25, 1.0, (0.3, 0.3, 0.32))
        b.add_box(0, l * 0.40, 0.3, 0.25, 0.25, 1.1, (0.3, 0.3, 0.32))
    b.build(root)
    # spinner
    pb = MeshBuilder("prop")
    if sub == "prop":
        pb.add_box(0, 0, -1.6, 0.25, 0.18, 3.2, (0.2, 0.2, 0.22))
        pb.add_box(-1.6, 0, -0.09, 3.2, 0.18, 0.25, (0.2, 0.2, 0.22))
        pnp = pb.build(root)
        pnp.setName("prop")
        pnp.setPos(0, l * 0.53, 1.0)
    # shadow
    sb = MeshBuilder("shadow")
    sb.add_rect(-2.5, -l / 2, 2.5, l / 2, 0.04, (0.05, 0.05, 0.07, 0.3))
    sh = sb.build(root)
    sh.setTransparency(True)
    return root


def _build_heli(color):
    root = NodePath("heli_proto")
    b = MeshBuilder("body")
    b.add_box(0, 0.8, 0.7, 2.2, 3.6, 2.0, color)
    b.add_box(0, 2.2, 1.0, 1.8, 1.2, 1.4, GLASS)
    b.add_box(0, -2.6, 1.5, 0.5, 4.4, 0.6, color)            # tail boom
    b.add_box(0, -4.6, 1.9, 0.2, 0.9, 1.3, color)            # fin
    for sx in (-1.0, 1.0):
        b.add_box(sx, 0.6, 0.0, 0.22, 3.4, 0.2, (0.35, 0.35, 0.4))
        b.add_box(sx, 0.6, 0.2, 0.15, 0.15, 0.6, (0.35, 0.35, 0.4))
    b.add_box(0, 0.6, 2.7, 0.5, 0.5, 0.45, (0.3, 0.3, 0.33))  # rotor mast
    b.build(root)
    rb = MeshBuilder("rotor")
    rb.add_box(0, 0, -0.05, 0.4, 10.0, 0.12, (0.18, 0.18, 0.2))
    rb.add_box(0, 0, -0.05, 10.0, 0.4, 0.12, (0.18, 0.18, 0.2))
    rnp = rb.build(root)
    rnp.setName("rotor")
    rnp.setPos(0, 0.6, 3.25)
    tb = MeshBuilder("rotor2")
    tb.add_box(0.15, 0, -0.9, 0.1, 0.25, 1.8, (0.18, 0.18, 0.2))
    tnp = tb.build(root)
    tnp.setName("rotor2")
    tnp.setPos(0, -4.6, 2.2)
    sb = MeshBuilder("shadow")
    sb.add_rect(-1.4, -4.5, 1.4, 3.2, 0.04, (0.05, 0.05, 0.07, 0.3))
    sh = sb.build(root)
    sh.setTransparency(True)
    return root


class Boat:
    mode = "boat"

    def __init__(self, game, x, y, heading):
        self.game = game
        self.spec = BOAT_SPEC
        self.np = NodePath("boat")
        _build_boat(random.choice([(0.85, 0.25, 0.2), (0.2, 0.5, 0.8), (0.9, 0.7, 0.2)])).copyTo(self.np)
        self.np.reparentTo(game.render)
        self.x, self.y, self.z = x, y, C.WATER_Z + 0.3
        self.heading = heading
        self.speed = 0.0
        self.vx = self.vy = 0.0
        self.hp = float(self.spec["hp"])
        self.driver = None
        self.wreck = False
        self.phase = random.uniform(0, 6)
        self.steer_vis = 0.0
        self.sync(0)

    @property
    def fwd(self):
        return (-math.sin(self.heading), math.cos(self.heading))

    @property
    def vel_mag(self):
        return math.hypot(self.vx, self.vy)

    def update_player(self, dt, keys):
        if self.wreck:
            return
        throttle = (1 if keys.get("w") else 0) - (1 if keys.get("s") else 0)
        steer = (1 if keys.get("a") else 0) - (1 if keys.get("d") else 0)
        self.speed += throttle * self.spec["accel"] * dt
        self.speed -= self.speed * 0.30 * dt
        self.speed = max(-6, min(self.spec["top"], self.speed))
        self.heading += steer * 1.6 * min(1, abs(self.speed) / 6) * dt * \
            (1 if self.speed >= 0 else -1)
        fx, fy = self.fwd
        k = min(1.0, self.spec["grip"] * dt)
        self.vx += (fx * self.speed - self.vx) * k
        self.vy += (fy * self.speed - self.vy) * k
        nx, ny = self.x + self.vx * dt, self.y + self.vy * dt
        # run aground on shallows
        if self.game.ground.height(nx, ny) > C.WATER_Z - 0.35:
            self.speed *= -0.25
            self.vx *= -0.3
            self.vy *= -0.3
        else:
            self.x, self.y = nx, ny
        # bounce off docks / ships / bounds
        for (x0, x1, y0, y1, z0, z1) in self.game.city.query_colliders(self.x, self.y, 3):
            if z0 > self.z + 2 or z1 < self.z - 2:
                continue
            cx = max(x0, min(self.x, x1))
            cy = max(y0, min(self.y, y1))
            dx, dy = self.x - cx, self.y - cy
            d2 = dx * dx + dy * dy
            r = 1.6
            if d2 < r * r and d2 > 1e-9:
                d = math.sqrt(d2)
                self.x = cx + dx / d * r
                self.y = cy + dy / d * r
                self.speed *= 0.3
        self.steer_vis += (steer * 10 - self.steer_vis) * min(1, 8 * dt)

    def update_idle(self, dt):
        self.speed *= max(0.0, 1 - 0.5 * dt)

    def damage(self, amount, silent=True):
        if self.wreck:
            return
        self.hp -= amount
        if self.hp <= 0:
            self.hp = 0
            self.wreck = True
            self.np.setColorScale(0.3, 0.3, 0.32, 1)

    def become_wreck(self):
        self.damage(9999)

    def set_headlights(self, on):
        pass

    def sync(self, t):
        bob = 0.10 * math.sin(t * 2.1 + self.phase)
        self.z = C.WATER_Z + 0.3 + (0 if self.wreck else bob)
        self.np.setPos(self.x, self.y, self.z)
        self.np.setH(math.degrees(self.heading))
        self.np.setP(2.5 * math.sin(t * 1.7 + self.phase) - min(8, self.speed * 0.4))
        self.np.setR(self.steer_vis)

    def destroy(self):
        self.np.removeNode()


class Aircraft:
    mode = "air"

    def __init__(self, game, sub, x, y, z, heading):
        self.game = game
        self.sub = sub
        self.spec = AIR_SPECS[sub]
        self.np = NodePath("aircraft")
        color = {"prop": (0.92, 0.90, 0.85), "jet": (0.88, 0.90, 0.94),
                 "heli": (0.75, 0.20, 0.18)}[sub]
        proto = _build_heli(color) if sub == "heli" else _build_plane(sub, color)
        proto.copyTo(self.np)
        self.np.reparentTo(game.render)
        self.rotor = self.np.find("**/rotor")
        self.rotor2 = self.np.find("**/rotor2")
        self.prop = self.np.find("**/prop")
        self.x, self.y = x, y
        gz, _ = game.ground.surface(x, y, z if z is not None else 0)
        self.z = gz if z is None else z
        self.heading = heading
        self.pitch = 0.0
        self.roll = 0.0
        self.speed = 0.0
        self.vx = self.vy = 0.0     # for collision interop with cars
        self.vz = 0.0
        self.grounded = True
        self.hp = float(self.spec["hp"])
        self.driver = None
        self.wreck = False
        self.rotor_spin = 0.0
        self._last_sync_t = None
        self.sync(0)

    @property
    def fwd(self):
        return (-math.sin(self.heading), math.cos(self.heading))

    @property
    def vel_mag(self):
        return math.hypot(self.vx, self.vy)

    def _chase(self, current, target, rate, dt):
        d = (target - current + math.pi) % math.tau - math.pi
        return current + max(-rate * dt, min(rate * dt, d))

    def update_player(self, dt, keys, cam_yaw, cam_pitch):
        if self.wreck:
            self.update_idle(dt)
            return
        if self.sub == "heli":
            self._fly_heli(dt, keys, cam_yaw)
        else:
            self._fly_plane(dt, keys, cam_yaw, cam_pitch)

    def _fly_heli(self, dt, keys, cam_yaw):
        g = self.game.ground
        gz, _ = g.surface(self.x, self.y, self.z)
        up = 1 if keys.get("space") else 0
        down = 1 if keys.get("shift") else 0
        if self.grounded:
            self.rotor_spin *= 1
            if up:
                self.grounded = False
                self.vz = 2.5
            else:
                self.z = gz
                return
        self.heading = self._chase(self.heading, cam_yaw, 1.7, dt)
        fx, fy = self.fwd
        acc_f = ((1 if keys.get("w") else 0) - (1 if keys.get("s") else 0)) * 9.0
        acc_s = ((1 if keys.get("d") else 0) - (1 if keys.get("a") else 0)) * 6.0
        rx, ry = fy, -fx
        self.vx += (fx * acc_f + rx * acc_s) * dt
        self.vy += (fy * acc_f + ry * acc_s) * dt
        self.vx -= self.vx * 0.8 * dt
        self.vy -= self.vy * 0.8 * dt
        sp = math.hypot(self.vx, self.vy)
        if sp > self.spec["top"]:
            self.vx *= self.spec["top"] / sp
            self.vy *= self.spec["top"] / sp
        self.vz += (up * 8.0 - down * 8.0) * dt
        self.vz -= self.vz * (1.6 if not (up or down) else 0.3) * dt
        if self.z > 400:
            self.vz = min(self.vz, 0)
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        self.speed = sp
        self.pitch = -acc_f * 0.012 - sp * 0.004
        self.roll = acc_s * 0.015
        gz, _ = g.surface(self.x, self.y, self.z)
        if self.z <= gz:
            self.z = gz
            if self.vz < -9:
                self.damage(40, silent=False)
            if self.vz < -16:
                self.become_wreck()
            self.vz = 0
            if abs(self.vx) + abs(self.vy) < 2:
                self.grounded = True
                self.vx = self.vy = 0.0
        self._hit_statics()

    def _fly_plane(self, dt, keys, cam_yaw, cam_pitch):
        g = self.game.ground
        spec = self.spec
        throttle = (1 if keys.get("w") else 0) - (1 if keys.get("s") else 0)
        gz, _ = g.surface(self.x, self.y, self.z)
        if self.grounded:
            self.speed += throttle * spec["accel"] * dt
            self.speed -= self.speed * 0.15 * dt
            self.speed = max(0, min(spec["top"], self.speed))
            steer = (1 if keys.get("a") else 0) - (1 if keys.get("d") else 0)
            self.heading += steer * 1.0 * min(1, self.speed / 14) * dt
            fx, fy = self.fwd
            self.x += fx * self.speed * dt
            self.y += fy * self.speed * dt
            self.vx, self.vy = fx * self.speed, fy * self.speed
            self.z = gz
            self.pitch = self.roll = 0.0
            if self.speed > spec["stall"] * 1.25 and cam_pitch > 0.04:
                self.grounded = False
                self.vz = 3.0
            self._hit_statics()
            return
        self.speed += throttle * spec["accel"] * dt
        self.speed -= self.speed * 0.045 * dt
        self.speed = max(0.0, min(spec["top"], self.speed))
        old = self.heading
        self.heading = self._chase(self.heading, cam_yaw,
                                   0.55 if self.sub == "prop" else 0.42, dt)
        derr = (cam_yaw - self.heading + math.pi) % math.tau - math.pi
        self.roll = max(-1.0, min(1.0, derr * 1.6))
        want_pitch = max(-0.5, min(0.6, cam_pitch))
        self.pitch += max(-0.9 * dt, min(0.9 * dt, want_pitch - self.pitch))
        sink = max(0.0, (spec["stall"] - self.speed)) * 0.55
        if self.z > 420:
            self.pitch = min(self.pitch, -0.05)
        fx, fy = self.fwd
        horiz = self.speed * math.cos(self.pitch)
        self.vx, self.vy = fx * horiz, fy * horiz
        self.vz = self.speed * math.sin(self.pitch) - sink
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        gz, _ = g.surface(self.x, self.y, self.z)
        if self.z <= gz:
            self.z = gz
            hard = self.vz < -7 or abs(self.roll) > 0.75
            if hard:
                self.damage(70, silent=False)
                self.speed *= 0.4
            if self.vz < -14:
                self.become_wreck()
            self.pitch = 0.0
            self.vz = 0.0
            self.grounded = True
        self._hit_statics()

    def _hit_statics(self):
        if self.wreck:
            return
        v = math.hypot(self.vx, self.vy)
        for (x0, x1, y0, y1, z0, z1) in self.game.city.query_colliders(self.x, self.y, 3):
            if z0 <= self.z + 1.2 and self.z + 0.4 >= z0 and self.z <= z1:
                if x0 - 2 < self.x < x1 + 2 and y0 - 2 < self.y < y1 + 2:
                    if v > 12 or abs(self.vz) > 8:
                        self.become_wreck()
                    else:
                        cx = max(x0, min(self.x, x1))
                        cy = max(y0, min(self.y, y1))
                        dx, dy = self.x - cx, self.y - cy
                        d = math.hypot(dx, dy) or 1
                        self.x = cx + dx / d * 2.2
                        self.y = cy + dy / d * 2.2
                        self.speed *= 0.2
                        self.vx *= 0.2
                        self.vy *= 0.2
                    return

    def update_idle(self, dt):
        """Unmanned or wrecked aircraft: glide down / fall and go boom."""
        g = self.game.ground
        gz, _ = g.surface(self.x, self.y, self.z)
        if self.grounded and not self.wreck:
            self.speed = max(0.0, self.speed - 6 * dt)
            return
        if self.z > gz + 0.2:
            self.vz -= 14.0 * dt
            self.pitch = max(-0.7, self.pitch - 0.4 * dt)
            self.speed = max(0.0, self.speed - 2 * dt)
            fx, fy = self.fwd
            self.x += fx * self.speed * dt
            self.y += fy * self.speed * dt
            self.z += self.vz * dt
            if self.z <= gz:
                self.z = gz
                if self.vz < -8 or self.wreck:
                    if not self.wreck:
                        self.become_wreck()
                    self.game.fx.explosion(self.x, self.y, self.z)
                self.vz = 0
                self.grounded = True
                self.speed = 0

    def damage(self, amount, silent=True):
        if self.wreck:
            return
        self.hp -= amount
        if self.hp <= 0:
            self.hp = 0
            self.become_wreck()

    def become_wreck(self):
        if self.wreck:
            return
        self.wreck = True
        self.np.setColorScale(0.28, 0.26, 0.25, 1)
        self.game.on_explosion(self)

    def set_headlights(self, on):
        pass

    def sync(self, t):
        self.np.setPos(self.x, self.y, self.z)
        self.np.setH(math.degrees(self.heading))
        self.np.setP(math.degrees(self.pitch))
        self.np.setR(math.degrees(-self.roll * 0.7))
        active = (self.driver == "player" or not self.grounded) and not self.wreck
        rpm = 1200 if active else 0
        dt = 0.0 if self._last_sync_t is None else max(0.0, min(0.1, t - self._last_sync_t))
        self._last_sync_t = t
        self.rotor_spin += rpm * dt
        if self.rotor and not self.rotor.isEmpty():
            self.rotor.setH(self.rotor_spin % 360)
        if self.rotor2 and not self.rotor2.isEmpty():
            self.rotor2.setP(self.rotor_spin * 1.7 % 360)
        if self.prop and not self.prop.isEmpty():
            self.prop.setR(self.rotor_spin * 2.0 % 360)

    def destroy(self):
        self.np.removeNode()
