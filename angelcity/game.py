"""The game application: world assembly, main loop, day/night, input, and game rules."""

import math
import os
import random
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (AmbientLight, CardMaker, ClockObject, DirectionalLight, Fog,
                          TransparencyAttrib, Vec3, Vec4, WindowProperties)
from . import config as C
from .city import City
from .gfx import Gfx
from .hud import HUD
from .meshgen import build_points
from .npc import CopSystem, PedManager
from .player import Player
from .sfx import SFX
from .terrain import Ground, coast_sand_x
from .vehicles import Aircraft, Boat, Traffic
from .weapons import FXPool, Pickup


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class AngelCityGame(ShowBase):
    def __init__(self, opts):
        super().__init__()
        self.opts = opts
        self.disableMouse()
        self.setBackgroundColor(0.55, 0.72, 0.9, 1.0)
        self.camLens.setFar(2600)
        self.camLens.setFov(70)

        self.ground = Ground()
        self.city = City(self.render, self.ground, seed=opts.get("seed", 42))
        self.city.build()

        # lights
        self.amb = AmbientLight("amb")
        self.amb.setColor(Vec4(0.42, 0.42, 0.46, 1))
        self.amb_np = self.render.attachNewNode(self.amb)
        self.render.setLight(self.amb_np)
        self.sun = DirectionalLight("sun")
        self.sun.setColor(Vec4(0.95, 0.9, 0.8, 1))
        self.sun_np = self.render.attachNewNode(self.sun)
        self.render.setLight(self.sun_np)

        self.fog = Fog("smog")
        self.fog.setColor(0.78, 0.74, 0.68)
        self.fog.setLinearRange(400, 2300)
        self.render.setFog(self.fog)

        # sky: stars + sun/moon discs on a node that follows the camera
        self.sky = self.render.attachNewNode("sky")
        rng = random.Random(3)
        pts = []
        for _ in range(260):
            a = rng.uniform(0, math.tau)
            e = rng.uniform(0.08, 1.35)
            r = 2100
            pts.append((r * math.cos(e) * math.cos(a), r * math.cos(e) * math.sin(a),
                        r * math.sin(e)))
        self.stars = build_points(self.sky, pts, (1, 1, 0.95, 1), size=2.0)
        self.stars.setLightOff()
        self.stars.setBin("background", 1)
        self.sun_disc = self._disc((1.0, 0.92, 0.7, 1), 90)
        self.moon_disc = self._disc((0.92, 0.94, 1.0, 1), 55)

        # systems
        self.sfx = SFX(self, enabled=not opts.get("no_audio"))
        self.fx = FXPool(self)
        self.player = Player(self, *self.city.poi["home"])
        self.traffic = Traffic(self)
        self.peds = PedManager(self)
        self.cops = CopSystem(self)
        self.pickups = [Pickup(self, k, x, y, amount=a) for (k, x, y, a) in
                        self.city.pickup_specs]
        # aircraft & boats parked around the map
        self.extra = []
        for (kind, x, y, z, h) in self.city.aircraft_specs:
            self.extra.append(Aircraft(self, kind, x, y, z, h))
        for (x, y, h) in self.city.boat_specs:
            self.extra.append(Boat(self, x, y, h))
        self.gfx = Gfx(self, opts.get("quality", "high"))
        self.hud = HUD(self)

        self.t = 0.0
        self.tod = opts.get("tod", C.START_TOD)
        self.paused = False
        self.dead_timer = 0.0
        self.respawn_to = None
        self.was_night = None
        self.keys = {}
        self.wheel = 0.0
        self._shot_idx = 0
        self._district = None
        self._bind_keys()
        self._apply_scenario(opts.get("scenario") or "home")

        self.taskMgr.add(self._update, "update")

    # ---------------- setup ----------------

    def _disc(self, color, size):
        cm = CardMaker("disc")
        cm.setFrame(-size, size, -size, size)
        np = self.sky.attachNewNode(cm.generate())
        np.setColor(*color)
        np.setTransparency(TransparencyAttrib.MAlpha)
        np.setBillboardPointEye()
        np.setLightOff()
        np.setBin("background", 2)
        return np

    def _bind_keys(self):
        for k in ("w", "a", "s", "d", "space", "shift", "h"):
            self.accept(k, self.keys.__setitem__, [k, True])
            self.accept(k + "-up", self.keys.__setitem__, [k, False])
        self.accept("mouse1", self.keys.__setitem__, ["mouse1", True])
        self.accept("mouse1-up", self.keys.__setitem__, ["mouse1", False])
        self.accept("mouse3", self.keys.__setitem__, ["mouse3", True])
        self.accept("mouse3-up", self.keys.__setitem__, ["mouse3", False])
        self.accept("wheel_up", self._on_wheel, [1])
        self.accept("wheel_down", self._on_wheel, [-1])
        self.accept("e", self._on_e)
        self.accept("c", lambda: self.player.swap_character(1))
        self.accept("x", lambda: self.player.cycle_weapon())
        for i, w in enumerate(("fist", "pistol", "smg", "shotgun")):
            self.accept(str(i + 1), self.player.select_weapon, [w])
        self.accept("m", self.hud.toggle_map)
        self.accept("escape", self._toggle_pause)
        self.accept("f5", self._screenshot)
        if not self.opts.get("headless"):
            props = WindowProperties()
            props.setCursorHidden(True)
            props.setTitle("Angel City")
            self.win.requestProperties(props)

    def _apply_scenario(self, name):
        from .vehicles import Car
        p = self.player

        def put_in(vehicle):
            vehicle.driver = "player"
            p.car = vehicle
            p.rig.root.hide()

        if name == "drive":
            self.tod = 0.455
            car = Car(self, "coupe", -1377, -350, 0, color=(0.85, 0.10, 0.15))
            put_in(car)
            car.speed = 16
            p.x, p.y = car.x, car.y
        elif name == "downtown":
            self.tod = 0.30
            p.x, p.y = 590, 240
            p.give_weapon("pistol", 60)
            p.cam_yaw = math.pi * 0.85
        elif name == "night":
            self.tod = 0.80
            car = Car(self, "lowrider", 423, 30, math.pi, None)
            put_in(car)
            p.x, p.y = car.x, car.y
        elif name == "wanted":
            self.tod = 0.38
            p.x, p.y = 600, 300
            p.give_weapon("smg", 120)
            self.cops.heat = 3.2
        elif name == "hills":
            self.tod = 0.42
            p.x, p.y = -330, 1160
            p.cam_yaw = math.pi
            p.cam_pitch = -0.05
        elif name == "hollywood":
            self.tod = 0.40
            p.x, p.y = -330, 1035
            p.cam_yaw = 0.0
            p.cam_pitch = 0.10
        elif name == "pier":
            self.tod = 0.47
            p.x, p.y = -1520, -300
            p.cam_yaw = math.pi / 2
        elif name == "freeway":
            self.tod = 0.34
            car = Car(self, "sedan", -600, C.FREEWAY_Y - 4, -math.pi / 2)
            car.z = C.FREEWAY_Z + 0.8
            put_in(car)
            car.speed = 20
            p.x, p.y = car.x, car.y
        elif name == "lax":
            self.tod = 0.36
            p.x, p.y = -1585, -930
            p.cam_yaw = math.pi * 0.5
        elif name == "flight":
            self.tod = 0.44
            plane = Aircraft(self, "prop", -1250, -300, 160.0, -math.pi / 2)
            plane.grounded = False
            plane.speed = 38
            self.extra.append(plane)
            put_in(plane)
            p.cam_yaw = -math.pi / 2
            p.cam_pitch = -0.06
            p.x, p.y = plane.x, plane.y
        elif name == "heli":
            self.tod = 0.42
            heli = Aircraft(self, "heli", 510, 380, 320.0, math.pi * 0.75)
            heli.grounded = False
            self.extra.append(heli)
            put_in(heli)
            p.cam_yaw = math.pi * 0.75
            p.cam_pitch = -0.25
            p.x, p.y = heli.x, heli.y
        elif name == "marina":
            self.tod = 0.47
            boat = Boat(self, -1560, C.MARINA_Y, math.pi / 2)
            self.extra.append(boat)
            put_in(boat)
            boat.speed = 10
            p.cam_yaw = math.pi / 2
            p.x, p.y = boat.x, boat.y
        elif name == "harbor":
            self.tod = 0.40
            car = Car(self, "pickup", 1230, C.BRIDGE_Y, -math.pi / 2)
            car.z = 14.8
            put_in(car)
            car.speed = 10
            p.x, p.y = car.x, car.y
        else:  # home
            hx, hy = self.city.poi["home"]
            p.x, p.y = hx - 4, hy - 4
            p.cam_yaw = math.pi * 0.7
        if not p.car:
            p.z = self.ground.surface(p.x, p.y, 0)[0]
        if p.car and getattr(p.car, "mode", "car") == "car":
            p.car.sync()

    # ---------------- accessors used by subsystems ----------------

    def player_world_pos(self):
        if self.player.car:
            return self.player.car.x, self.player.car.y
        return self.player.x, self.player.y

    def dist_to_player(self, x, y):
        px, py = self.player_world_pos()
        return math.hypot(x - px, y - py)

    def all_world_cars(self):
        out = list(self.traffic.all_cars())
        out.extend(self.cops.cruisers)
        out.extend(self.extra)
        if self.player.car:
            out.append(self.player.car)
        return out

    def nearby_cars(self, x, y, r):
        return [c for c in self.all_world_cars()
                if abs(c.x - x) < r + 6 and abs(c.y - y) < r + 6]

    def traffic_obstacles(self, me):
        out = []
        for c in self.all_world_cars():
            if c is not me:
                out.append((c.x, c.y, c.z))
        if self.player.car is None:
            out.append((self.player.x, self.player.y, self.player.z))
        for ped in self.peds.peds:
            if not ped.down:
                out.append((ped.x, ped.y, ped.z))
        return out

    def camera_aim_dir(self, ox, oy, oz):
        q = self.camera.getQuat(self.render)
        f = q.getForward()
        cx, cy, cz = self.camera.getPos(self.render)
        tx, ty, tz = cx + f.x * 160, cy + f.y * 160, cz + f.z * 160
        dx, dy, dz = tx - ox, ty - oy, tz - oz
        l = math.sqrt(dx * dx + dy * dy + dz * dz) or 1
        return dx / l, dy / l, dz / l

    @property
    def is_night(self):
        return math.sin(self.tod * math.tau) < -0.04

    # ---------------- game events ----------------

    def spawn_cash(self, x, y, amount):
        self.pickups.append(Pickup(self, "cash", x, y, amount=amount, respawn=0))

    def on_crash(self, car, impact):
        if car.driver == "player":
            vol = min(1.0, impact / 14)
            self.sfx.play("crash", vol, rate=random.uniform(0.9, 1.1))

    def on_car_hit_car(self, a, b, impact):
        if "player" in (a.driver, b.driver):
            self.sfx.play("crash", min(1.0, impact / 12), rate=random.uniform(0.9, 1.1))
            self.cops.add_heat(0.06)
        else:
            d = self.dist_to_player(a.x, a.y)
            if d < 90:
                self.sfx.play("crash", max(0.1, 0.7 - d / 120))

    def on_explosion(self, car):
        self.fx.explosion(car.x, car.y, car.z)
        self.sfx.play("crash", 1.0, rate=0.6)
        for ped in self.peds.everyone():
            if (ped.x - car.x) ** 2 + (ped.y - car.y) ** 2 < 36:
                ped.hp = 0
                ped.go_down()
        for other in self.nearby_cars(car.x, car.y, 7):
            if other is not car and not other.wreck:
                other.damage(45)
        p = self.player
        if p.car is not car and (p.x - car.x) ** 2 + (p.y - car.y) ** 2 < 49:
            p.take_damage_direct(60)

    def wasted(self):
        if self.player.dead:
            return
        self.player.dead = True
        self.dead_timer = 2.6
        self.respawn_to = "hospital"
        self.hud.banner("WASTED", (0.85, 0.1, 0.1, 1))
        self.sfx.play("wasted", 0.9)
        self.sfx.stop_loops()

    def busted(self):
        if self.player.dead:
            return
        self.player.dead = True
        self.dead_timer = 2.6
        self.respawn_to = "police"
        self.hud.banner("BUSTED", (0.25, 0.45, 0.95, 1))
        self.sfx.play("busted", 0.9)
        self.sfx.stop_loops()

    def fished_out(self):
        p = self.player
        if p.dead:
            return
        self.hud.flash_message("Fished out of the bay. Soggy but alive.")
        self.sfx.play("splash", 0.9)
        if p.car:
            car = p.car
            p.car = None
            car.driver = None
            if getattr(car, "mode", "car") == "car":
                car.become_wreck()
            p.rig.root.show()
        p.x = max(coast_sand_x(p.y) + 20, min(p.x, C.BASIN_X1 - 30))
        p.y = max(C.PORT_Y0 + 30, min(p.y, C.BASIN_Y1 - 30))
        p.z = self.ground.surface(p.x, p.y, 5)[0]
        p.vz = 0.0
        p.take_damage_direct(10)

    def _respawn(self):
        p = self.player
        where = self.city.poi.get(self.respawn_to or "hospital", self.city.poi["home"])
        if p.car:
            car = p.car
            car.driver = None
            self.traffic.parked.append(car)
            p.car = None
            p.rig.root.show()
        p.x, p.y = where[0] + random.uniform(-2, 2), where[1]
        p.z = self.ground.surface(p.x, p.y, 0)[0]
        p.health = C.PLAYER_MAX_HP
        fee = C.HOSPITAL_FEE if self.respawn_to == "hospital" else C.BUSTED_FEE
        p.money = max(0, p.money - fee)
        self.cops.clear()
        p.dead = False
        self.hud.banner_off()
        self.hud.flash_message("-$%d" % fee)

    # ---------------- input events ----------------

    def _on_wheel(self, d):
        self.wheel += d

    def _toggle_pause(self):
        self.paused = not self.paused
        self.hud.show_pause(self.paused)

    def _screenshot(self):
        from panda3d.core import Filename, PNMImage
        self._shot_idx += 1
        path = "angelcity_%02d.png" % self._shot_idx
        img = PNMImage()
        self.win.getScreenshot(img)
        img.removeAlpha()
        img.write(Filename.fromOsSpecific(os.path.abspath(path)))
        self.hud.flash_message("Saved %s" % path)

    def _on_e(self):
        p = self.player
        if p.dead or self.paused:
            return
        # ammo shop
        if p.car is None and "ammo" in self.city.poi:
            ax, ay = self.city.poi["ammo"]
            if math.hypot(p.x - ax, p.y - ay) < 5:
                if p.money >= 50:
                    p.money -= 50
                    p.give_ammo(60)
                    if "pistol" not in p.weapons:
                        p.give_weapon("pistol", 24)
                    self.sfx.play("chime", 0.8)
                    self.hud.flash_message("Bought ammo (+60)")
                else:
                    self.hud.flash_message("Not enough cash ($50)")
                return
        # respray
        if p.car and not p.car.wreck:
            for key in ("spray1", "spray2"):
                sx, sy = self.city.poi[key]
                if math.hypot(p.car.x - sx, p.car.y - sy) < 9 and abs(p.car.speed) < 3:
                    if p.money >= 100:
                        p.money -= 100
                        p.car.hp = float(p.car.spec["hp"])
                        self.cops.heat = 0.0
                        self.cops.clear()
                        self.sfx.play("chime", 0.9)
                        self.hud.flash_message("Resprayed — heat's off")
                    else:
                        self.hud.flash_message("Not enough cash ($100)")
                    return
        p.try_enter_exit()

    # ---------------- mouse ----------------

    def _mouse_delta(self):
        if self.opts.get("headless") or not self.win:
            return 0.0, 0.0
        if not self.win.getProperties().getForeground():
            return 0.0, 0.0
        md = self.win.getPointer(0)
        cx, cy = self.win.getXSize() // 2, self.win.getYSize() // 2
        dx, dy = md.getX() - cx, md.getY() - cy
        self.win.movePointer(0, cx, cy)
        return float(dx), float(dy)

    # ---------------- day/night ----------------

    def _sky_update(self):
        el = math.sin(self.tod * math.tau)          # sun elevation -1..1
        az = self.tod * 360.0 + 90
        self.sun_np.setHpr(az, -max(-30, el * 80), 0)
        warm = max(0.0, min(1.0, 1.0 - abs(el - 0.12) * 3)) if el > -0.1 else 0.0
        if el > 0:
            sun_col = _lerp((0.95, 0.9, 0.82), (0.95, 0.55, 0.30), warm)
            sky = _lerp((0.55, 0.74, 0.92), (0.93, 0.62, 0.42), warm)
            fogc = _lerp((0.80, 0.76, 0.70), (0.9, 0.66, 0.5), warm)
            amb = _lerp((0.40, 0.40, 0.45), (0.45, 0.38, 0.36), warm)
        else:
            k = min(1.0, -el * 5)
            sun_col = _lerp((0.55, 0.45, 0.40), (0.14, 0.16, 0.26), k)
            sky = _lerp((0.45, 0.45, 0.55), (0.035, 0.045, 0.09), k)
            fogc = _lerp((0.55, 0.5, 0.5), (0.05, 0.06, 0.10), k)
            amb = _lerp((0.32, 0.32, 0.38), (0.15, 0.17, 0.24), k)
        self.sun.setColor(Vec4(*sun_col, 1))
        self.amb.setColor(Vec4(*amb, 1))
        self.setBackgroundColor(sky[0], sky[1], sky[2], 1.0)
        self.fog.setColor(*fogc)
        self.fog.setLinearRange(300 if not self.is_night else 200, 2300)
        px, py = self.player_world_pos()
        self.sky.setPos(px, py, 0)
        sd = self.sun_np.getQuat().getForward()
        self.sun_disc.setPos(-sd.x * 2000, -sd.y * 2000, -sd.z * 2000)
        self.moon_disc.setPos(sd.x * 2000, sd.y * 2000, max(200, sd.z * 2000))
        alpha = max(0.0, min(1.0, -el * 4))
        self.gfx.update(self.t, sd, sun_col, fogc, el)
        self.stars.setColorScale(1, 1, 1, alpha)
        self.moon_disc.setColorScale(1, 1, 1, alpha)
        self.sun_disc.setColorScale(1, 1, 1, max(0.0, min(1.0, el * 6 + 0.4)))

        night = self.is_night
        if night != self.was_night:
            self.was_night = night
            if night:
                self.city.night_np.show()
            else:
                self.city.night_np.hide()
            for car in self.all_world_cars():
                car.set_headlights(night)

    # ---------------- prompts ----------------

    def _prompt(self):
        p = self.player
        if p.dead:
            return None
        if p.car is None:
            ax, ay = self.city.poi["ammo"]
            if math.hypot(p.x - ax, p.y - ay) < 5:
                return "E — buy ammo  $50"
            best_d = 3.4
            found = None
            for car in self.all_world_cars():
                if car.wreck:
                    continue
                d = math.hypot(car.x - p.x, car.y - p.y)
                if d < best_d and abs(car.z - p.z) < 2.5:
                    best_d, found = d, car
            if found:
                return "E — enter %s" % found.spec["name"]
        else:
            for key in ("spray1", "spray2"):
                sx, sy = self.city.poi[key]
                if math.hypot(p.car.x - sx, p.car.y - sy) < 9:
                    return "E — respray & repair  $100"
            if abs(p.car.speed) < 7:
                return None
        return None

    # ---------------- main loop ----------------

    def _update(self, task):
        clock = ClockObject.getGlobalClock()
        dt = min(clock.getDt(), 1 / 20)
        mdx, mdy = self._mouse_delta()
        if self.paused:
            return task.cont
        self.t += dt
        self.tod = (self.tod + dt / C.DAY_LENGTH) % 1.0

        p = self.player
        if p.dead:
            self.dead_timer -= dt
            self.hud.set_fade(1.0 - max(0, self.dead_timer - 0.6) / 2.0)
            if self.dead_timer <= 0:
                self._respawn()
                self.hud.set_fade(0)
        else:
            p.update(dt)
            if self.keys.get("h") and p.car:
                self.sfx.play("horn", 0.8)
                self.keys["h"] = False

        self.traffic.update(dt, self.t)
        self.peds.update(dt)
        self.cops.update(dt, self.t)
        for pk in list(self.pickups):
            pk.update(dt, self.t)
        for v in self.extra:
            if v.driver != "player":
                v.update_idle(dt)
                v.sync(self.t)
        self.fx.update(dt)
        self._sky_update()
        self.city.set_light_phase(C.light_green("v", self.t))

        # animated landmarks: ferris wheel spins, pumpjacks nod
        for (np, cabins, speed, mode) in self.city.anims:
            if mode == "spin":
                ang = self.t * speed
                np.setP(ang)
                for c in cabins:
                    c.setP(-ang)
            else:
                np.setP(math.sin(self.t * speed) * 16)

        self._audio_loops(p)
        self._location_update()

        self.hud.set_prompt(self._prompt())
        self.hud.update(dt)
        p.update_camera(dt, mdx, mdy, self.wheel)
        self.wheel = 0.0
        return task.cont

    def _audio_loops(self, p):
        mode = getattr(p.car, "mode", "car") if p.car else None
        sub = getattr(p.car, "sub", None) if p.car else None
        eng_vol = eng_rate = 0.0
        rotor_vol = prop_vol = jet_vol = 0.0
        if p.car and not p.dead:
            sp = abs(p.car.speed) / p.car.spec["top"]
            if mode == "car":
                eng_vol, eng_rate = 0.25 + sp * 0.5, 0.7 + sp * 1.1
            elif mode == "boat":
                eng_vol, eng_rate = 0.30 + sp * 0.5, 0.5 + sp * 0.7
            elif sub == "heli":
                rotor_vol = 0.55 + min(0.4, abs(p.car.vz) * 0.05)
            elif sub == "prop":
                prop_vol = 0.35 + sp * 0.5
            elif sub == "jet":
                jet_vol = 0.30 + sp * 0.6
        self.sfx.loop("engine", "engine", eng_vol, eng_rate or 1.0)
        self.sfx.loop("rotor", "rotor", rotor_vol,
                      1.0 + (abs(p.car.vz) * 0.02 if rotor_vol else 0))
        self.sfx.loop("prop", "prop", prop_vol,
                      0.8 + (abs(p.car.speed) / 60 if prop_vol else 0))
        self.sfx.loop("jet", "jet", jet_vol,
                      0.8 + (abs(p.car.speed) / 90 if jet_vol else 0))
        skid = mode == "car" and bool(self.keys.get("space")) and abs(p.car.speed) > 6 \
            and not p.dead
        self.sfx.loop("skid", "skid", 0.7 if skid else 0.0, 1.0)
        if self.cops.cruisers:
            d = min(self.dist_to_player(c.x, c.y) for c in self.cops.cruisers)
            self.sfx.loop("siren", "siren", max(0.0, 0.8 - d / 180))
        else:
            self.sfx.loop("siren", "siren", 0.0)
        # shoreline ambience + nearby traffic hum
        px, py = self.player_world_pos()
        shore = abs(px - coast_sand_x(py))
        self.sfx.loop("waves", "waves", max(0.0, 0.45 - shore / 300.0))
        moving = sum(1 for tc in self.traffic.cars
                     if abs(tc.car.speed) > 3 and self.dist_to_player(tc.car.x, tc.car.y) < 60)
        self.sfx.loop("amb", "engine", min(0.14, 0.03 * moving), 0.75)

    def _location_update(self):
        px, py = self.player_world_pos()
        district = C.district_name(px, py)
        road = self.city.road_name_at(px, py, self.player.car.z if self.player.car
                                      else self.player.z)
        self.hud.set_location(district, road)
        if district != self._district:
            self._district = district
            self.hud.location_card(district)
