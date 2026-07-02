"""Third-person player: on-foot movement, driving, aiming/shooting, character swapping."""

import math
import random
from . import config as C
from .characters import PRESETS, CharacterRig
from .weapons import WEAPONS, WEAPON_ORDER, fire


class Player:
    def __init__(self, game, x, y):
        self.game = game
        self.preset_idx = 0
        self.rig = CharacterRig(game.render, PRESETS[0])
        self.x, self.y = x, y
        self.z = game.ground.surface(x, y, 0)[0]
        self.vz = 0.0
        self.heading = math.pi          # face south initially
        self.phase = 0.0
        self.health = C.PLAYER_MAX_HP
        self.money = C.START_MONEY
        self.dead = False
        self.car = None
        self.weapons = {"fist": None}   # kind -> ammo (None = infinite)
        self.current = "fist"
        self.fire_cd = 0.0
        self.cam_yaw = math.pi
        self.cam_pitch = -0.25
        self.cam_dist = C.CAM_DIST_FOOT
        self.aiming = False
        self.walk_speed = 0.0
        self.swap_cooldown = 0.0

    # ---------------- character / inventory ----------------

    def swap_character(self, delta):
        if self.car is not None or self.swap_cooldown > 0:
            return
        self.preset_idx = (self.preset_idx + delta) % len(PRESETS)
        pos = (self.x, self.y, self.z)
        h = self.rig.root.getH()
        self.rig.destroy()
        self.rig = CharacterRig(self.game.render, PRESETS[self.preset_idx])
        self.rig.root.setPos(*pos)
        self.rig.root.setH(h)
        if self.current != "fist":
            self.rig.show_gun(self.current)
        self.swap_cooldown = 0.15
        self.game.sfx.play("click", 0.8)
        self.game.hud.flash_message("Now playing: %s" % PRESETS[self.preset_idx]["name"])

    @property
    def name(self):
        return PRESETS[self.preset_idx]["name"]

    def give_weapon(self, kind, ammo):
        if kind in self.weapons and self.weapons[kind] is not None:
            self.weapons[kind] += ammo
        else:
            self.weapons[kind] = ammo
        self.select_weapon(kind)

    def give_ammo(self, n):
        for k in self.weapons:
            if self.weapons[k] is not None:
                self.weapons[k] += n

    def select_weapon(self, kind):
        if kind in self.weapons:
            self.current = kind
            self.rig.show_gun(kind if kind != "fist" else None)

    def cycle_weapon(self):
        owned = [w for w in WEAPON_ORDER if w in self.weapons]
        i = owned.index(self.current) if self.current in owned else 0
        self.select_weapon(owned[(i + 1) % len(owned)])

    def speed_estimate(self):
        if self.car:
            return abs(self.car.speed)
        return self.walk_speed

    # ---------------- damage / death ----------------

    def take_damage(self, dmg):
        if self.dead:
            return
        if self.car:
            self.car.damage(dmg * 0.5)
            return
        self.health -= dmg
        self.game.hud.damage_flash()
        if self.health <= 0:
            self.health = 0
            self.game.wasted()

    # ---------------- cars ----------------

    def try_enter_exit(self):
        game = self.game
        if self.car:
            mode = getattr(self.car, "mode", "car")
            airborne = mode == "air" and not self.car.grounded
            if mode == "car" and abs(self.car.speed) > 7:
                return
            fx, fy = self.car.fwd
            lx, ly = -fy, fx     # left of car
            self.x = self.car.x + lx * (self.car.spec["w"] / 2 + 1.1)
            self.y = self.car.y + ly * (self.car.spec["w"] / 2 + 1.1)
            if airborne:
                # bail out mid-air: free-fall from here
                self.z = self.car.z
                self.vz = 0.0
                game.hud.flash_message("Geronimo!")
            else:
                self.z = game.ground.surface(self.x, self.y, self.car.z)[0]
            self.car.driver = None
            if mode == "car":
                self.car.speed *= 0.2
                game.traffic.parked.append(self.car)
            self.car = None
            self.rig.root.show()
            if not airborne and game.ground.is_wet(self.x, self.y, self.z):
                game.fished_out()
            return
        # find nearest enterable vehicle
        best, best_d = None, 4.6
        for car in game.all_world_cars():
            if car.wreck:
                continue
            d = math.hypot(car.x - self.x, car.y - self.y)
            if d < best_d and abs(car.z - self.z) < 3.0:
                best, best_d = car, d
        if best is None:
            return
        if best.driver == "ai":
            # carjack: the driver bails and runs
            game.peds.peds.append(_bailer(game, best))
            game.cops.add_heat(0.35)
        elif best.driver == "cop":
            game.cops.add_heat(1.0)
            game.cops.cruisers = [c for c in game.cops.cruisers if c is not best]
        game.traffic.remove_car(best)
        best.driver = "player"
        self.car = best
        self.rig.root.hide()
        game.hud.flash_message(best.spec["name"])

    # ---------------- per-frame ----------------

    def update(self, dt):
        game = self.game
        keys = game.keys
        self.fire_cd -= dt
        self.swap_cooldown -= dt
        self.aiming = bool(keys.get("mouse3")) and self.car is None

        if self.car:
            self._update_drive(dt, keys)
        else:
            self._update_foot(dt, keys)

        # shooting (on foot only)
        if self.car is None and keys.get("mouse1") and self.fire_cd <= 0 and not self.dead:
            w = WEAPONS[self.current]
            ammo = self.weapons.get(self.current)
            if self.current == "fist":
                self._punch()
                self.fire_cd = w["rof"]
            elif ammo and ammo > 0:
                self.fire_cd = w["rof"]
                self.weapons[self.current] = ammo - w["pellets"] if False else ammo - 1
                ox = self.x - math.sin(self.heading) * 0.4
                oy = self.y + math.cos(self.heading) * 0.4
                oz = self.z + 1.35
                dx, dy, dz = game.camera_aim_dir(ox, oy, oz)
                fire(game, self, ox, oy, oz, dx, dy, dz, self.current)
                if not w["auto"]:
                    keys["mouse1"] = False
            else:
                game.sfx.play("click", 0.5)
                keys["mouse1"] = False

    def _punch(self):
        game = self.game
        fx, fy = -math.sin(self.heading), math.cos(self.heading)
        for ped in game.peds.everyone():
            if ped.down:
                continue
            dx, dy = ped.x - self.x, ped.y - self.y
            if dx * fx + dy * fy > 0 and dx * dx + dy * dy < 1.9 * 1.9:
                ped.hurt(WEAPONS["fist"]["dmg"], (fx, fy), by_player=True)
                game.sfx.play("thud", 0.7)
                game.cops.add_heat(0.15)
                return
        game.sfx.play("click", 0.3)

    def _update_foot(self, dt, keys):
        game = self.game
        mx = (1 if keys.get("d") else 0) - (1 if keys.get("a") else 0)
        my = (1 if keys.get("w") else 0) - (1 if keys.get("s") else 0)
        moving = mx or my
        speed = C.FOOT_RUN if keys.get("shift") else C.FOOT_SPEED
        if self.aiming:
            speed = C.FOOT_SPEED * 0.7
        self.walk_speed = speed if moving else 0.0
        if moving:
            ang = self.cam_yaw + math.atan2(-mx, my)
            if self.aiming:
                self.heading = self.cam_yaw
            else:
                d = (ang - self.heading + math.pi) % math.tau - math.pi
                self.heading += max(-12 * dt, min(12 * dt, d * 10 * dt))
                self.heading = ang if abs(d) < 0.1 else self.heading
            self.x += -math.sin(ang) * speed * dt
            self.y += math.cos(ang) * speed * dt
        elif self.aiming:
            self.heading = self.cam_yaw

        # jump / gravity / fall damage
        gz, _ = game.ground.surface(self.x, self.y, self.z)
        if keys.get("space") and self.z <= gz + 0.05:
            self.vz = 5.2
        if self.z > gz + 0.02 or self.vz > 0:
            self.vz -= 16.0 * dt
            self.z += self.vz * dt
            if self.z <= gz:
                self.z = gz
                if self.vz < -13:
                    if game.ground.is_wet(self.x, self.y, self.z):
                        pass    # splashdown handled below
                    else:
                        self.take_damage((-self.vz - 12) * 7)
                        game.sfx.play("thud", 1.0, rate=0.7)
                self.vz = 0.0
        else:
            self.z = gz

        self._collide_statics()
        self._collide_cars()

        if game.ground.is_wet(self.x, self.y, self.z):
            game.fished_out()
            return

        self.phase += self.walk_speed * dt * 1.9
        self.rig.root.setPos(self.x, self.y, self.z)
        self.rig.root.setH(math.degrees(self.heading))
        pitch_deg = math.degrees(self.cam_pitch)
        self.rig.pose(self.phase, min(1, self.walk_speed / 4),
                      aiming=self.aiming or (self.current != "fist" and keys.get("mouse1")),
                      aim_pitch=pitch_deg if self.aiming else 0)

    def _update_drive(self, dt, keys):
        car = self.car
        mode = getattr(car, "mode", "car")
        if mode == "boat":
            car.update_player(dt, keys)
            car.sync(self.game.t)
            self.x, self.y, self.z = car.x, car.y, car.z
            if car.wreck:
                self.take_damage_direct(50)
            return
        if mode == "air":
            car.update_player(dt, keys, self.cam_yaw, self.cam_pitch)
            # taxiing into pedestrians still counts
            if car.grounded and car.vel_mag > 2.5:
                for ped in self.game.peds.everyone():
                    if not ped.down and (ped.x - car.x) ** 2 + (ped.y - car.y) ** 2 < 3.2 ** 2 \
                            and abs(ped.z - car.z) < 2:
                        ped.hit_by_car(car)
            car.sync(self.game.t)
            self.x, self.y, self.z = car.x, car.y, car.z
            if car.wreck:
                self.take_damage_direct(75)
            return
        throttle = (1 if keys.get("w") else 0) - (1 if keys.get("s") else 0)
        steer = (1 if keys.get("a") else 0) - (1 if keys.get("d") else 0)
        car.control(dt, throttle, steer, bool(keys.get("space")))
        car.integrate(dt)
        hit = car.collide_static()
        for other in self.game.all_world_cars():
            if other is not car and abs(other.x - car.x) < 12 and abs(other.y - car.y) < 12:
                car.collide_car(other)
        # run over peds
        if car.vel_mag > 2.5:
            for ped in self.game.peds.everyone():
                if not ped.down and (ped.x - car.x) ** 2 + (ped.y - car.y) ** 2 < 2.4 ** 2 \
                        and abs(ped.z - car.z) < 2:
                    ped.hit_by_car(car)
        car.set_headlights(self.game.is_night)
        car.sync()
        self.x, self.y, self.z = car.x, car.y, car.z
        if self.game.ground.is_wet(car.x, car.y, car.z):
            self.game.fished_out()
        if car.wreck:
            self.take_damage_direct(65)

    def take_damage_direct(self, dmg):
        """Bypasses the car shield (explosions, drowning)."""
        if self.dead:
            return
        self.health -= dmg
        self.game.hud.damage_flash()
        if self.health <= 0:
            self.health = 0
            self.game.wasted()

    def _collide_statics(self):
        r = 0.38
        for (x0, x1, y0, y1, z0, z1) in self.game.city.query_colliders(self.x, self.y, r + 0.8):
            if self.z > z1 - 0.5 or self.z + 1.7 < z0:
                continue
            nx = max(x0, min(self.x, x1))
            ny = max(y0, min(self.y, y1))
            dx, dy = self.x - nx, self.y - ny
            d2 = dx * dx + dy * dy
            if d2 < r * r:
                if d2 < 1e-9:
                    self.x += r
                    continue
                d = math.sqrt(d2)
                self.x = nx + dx / d * r
                self.y = ny + dy / d * r

    def _collide_cars(self):
        for car in self.game.nearby_cars(self.x, self.y, 6.0):
            fx, fy = car.fwd
            for off in (0.3, -0.3):
                cx = car.x + fx * car.spec["l"] * off
                cy = car.y + fy * car.spec["l"] * off
                if abs(car.z - self.z) > 1.8:
                    continue
                r = car.spec["w"] * 0.55 + 0.35
                dx, dy = self.x - cx, self.y - cy
                d2 = dx * dx + dy * dy
                if 1e-9 < d2 < r * r:
                    d = math.sqrt(d2)
                    self.x = cx + dx / d * r
                    self.y = cy + dy / d * r
                    if car.vel_mag > 6:
                        self.take_damage(car.vel_mag * 1.2)
                        if car.driver == "cop":
                            pass
                        elif car.driver == "ai":
                            self.game.sfx.play("thud", 0.8)

    # ---------------- camera ----------------

    def update_camera(self, dt, mouse_dx, mouse_dy, wheel):
        game = self.game
        cam = game.camera
        self.cam_yaw -= mouse_dx * 0.0032
        self.cam_pitch = max(-1.1, min(0.7, self.cam_pitch - mouse_dy * 0.0032))
        if wheel:
            self.cam_dist = max(4.0, min(20.0, self.cam_dist - wheel * 1.2))

        if self.car:
            # chase cam eases toward behind-the-vehicle
            mode = getattr(self.car, "mode", "car")
            want = self.car.heading
            d = (want - self.cam_yaw + math.pi) % math.tau - math.pi
            chase = 3.0 if mode == "car" else 1.6
            self.cam_yaw += d * min(1, chase * dt)
            if mode == "air":
                dist = C.CAM_DIST_AIR + abs(self.car.speed) * 0.10
                pitch = self.cam_pitch if not self.car.grounded else -0.16
                pitch = max(-0.9, min(0.55, pitch))
            else:
                dist = C.CAM_DIST_CAR + abs(self.car.speed) * 0.12
                pitch = -0.20
            fx, fy = -math.sin(self.cam_yaw), math.cos(self.cam_yaw)
            tx, ty, tz = self.car.x, self.car.y, self.car.z + (1.4 if mode != "air" else 2.2)
        else:
            dist = 2.6 if self.aiming else self.cam_dist
            pitch = self.cam_pitch
            fx, fy = -math.sin(self.cam_yaw), math.cos(self.cam_yaw)
            tx, ty, tz = self.x, self.y, self.z + 1.5
            if self.aiming:
                rx, ry = fy, -fx   # shoulder offset
                tx += rx * 0.5
                ty += ry * 0.5

        cx = tx - fx * dist * math.cos(pitch)
        cy = ty - fy * dist * math.cos(pitch)
        cz = tz - dist * math.sin(pitch)
        # keep camera above terrain
        gz, _ = game.ground.surface(cx, cy, cz + 5)
        cz = max(cz, gz + 0.5)
        cam.setPos(cx, cy, cz)
        cam.lookAt(tx, ty, tz + (0.0 if self.car else 0.1))


def _bailer(game, car):
    """The evicted AI driver, spawned fleeing from a carjacking."""
    from .npc import Ped
    fx, fy = car.fwd
    p = Ped(game, car.x - fy * 2.2, car.y + fx * 2.2)
    p.state = "flee"
    p.flee_from = (car.x, car.y)
    p.state_t = 7.0
    return p
