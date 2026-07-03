"""Pedestrians and the police response (wanted stars, cruisers, officers on foot)."""

import math
import random
from . import config as C
from .characters import CharacterRig, COP_PRESET, random_ped_preset
from .vehicles import Car
from . import weapons


class Ped:
    def __init__(self, game, x, y, preset=None, cop=False):
        self.game = game
        self.cop = cop
        rng = random.Random(random.random())
        beach = x < C.BEACHTOWN_X1
        self.rig = CharacterRig(game.render, preset or random_ped_preset(rng, beach),
                                scale=rng.uniform(0.93, 1.05))
        self.x, self.y = x, y
        self.z = game.ground.surface(x, y, 0)[0]
        self.heading = rng.uniform(0, math.tau)
        self.speed = 0.0
        self.phase = 0.0
        self.hp = 30.0
        self.down = False
        self.flung = False
        self.fvx = self.fvy = self.fvz = 0.0
        self.spin = 0.0
        self.fade = 0.0
        self.state = "walk"
        self.state_t = rng.uniform(2, 8)
        self.flee_from = None
        self.shoot_cd = 0.0
        self.cash_dropped = False

    def hurt(self, dmg, push_dir, by_player=False):
        if self.down:
            return
        self.hp -= dmg
        if by_player:
            self.game.cops.add_heat(0.5 if not self.cop else 0.9)
        if self.hp <= 0:
            self.go_down()
        else:
            self.state = "flee" if not self.cop else self.state
            self.flee_from = (self.x - push_dir[0] * 5, self.y - push_dir[1] * 5)
            self.state_t = 6.0

    def go_down(self):
        if self.down:
            return
        self.down = True
        self.fade = 7.0
        self.rig.lie_down()
        self.game.sfx.play("thud", 0.6)
        if not self.cop and not self.cash_dropped and random.random() < 0.35:
            self.cash_dropped = True
            self.game.spawn_cash(self.x + random.uniform(-1, 1),
                                 self.y + random.uniform(-1, 1),
                                 random.randint(15, 60))

    def hit_by_car(self, car):
        v = car.vel_mag
        if v > 3.5:
            # ballistic fling: inherit the car's velocity plus an upward kick
            self.hp = 0
            self.flung = True
            self.fvx = car.vx * 0.85
            self.fvy = car.vy * 0.85
            self.fvz = min(8.0, 2.0 + v * 0.35)
            self.spin = random.uniform(300, 560) * random.choice((-1, 1))
            self.game.sfx.play("thud", 0.8)
            if car.driver == "player":
                self.game.cops.add_heat(0.75)
        else:
            self.state = "flee"
            self.flee_from = (car.x, car.y)
            self.state_t = 5.0

    def scare(self, x, y):
        if not self.cop and not self.down:
            self.state = "flee"
            self.flee_from = (x, y)
            self.state_t = 6.0

    def update(self, dt):
        game = self.game
        if self.flung:
            self.fvz -= 18.0 * dt
            self.x += self.fvx * dt
            self.y += self.fvy * dt
            self.z += self.fvz * dt
            gz = game.ground.surface(self.x, self.y, self.z)[0]
            self.rig.root.setPos(self.x, self.y, max(self.z, gz))
            self.rig.root.setP(self.rig.root.getP() + self.spin * dt)
            self.fvx *= max(0.0, 1 - 0.4 * dt)
            self.fvy *= max(0.0, 1 - 0.4 * dt)
            if self.z <= gz:
                self.z = gz
                self.flung = False
                self.go_down()
            return True
        if self.down:
            self.fade -= dt
            if self.fade < 1.5:
                self.rig.root.setAlphaScale(max(0.0, self.fade / 1.5))
                self.rig.root.setTransparency(True)
            return self.fade > 0
        self.state_t -= dt
        self.shoot_cd -= dt

        if self.cop:
            self._update_cop(dt)
        elif self.state == "flee":
            fx, fy = self.x - self.flee_from[0], self.y - self.flee_from[1]
            l = math.hypot(fx, fy) or 1
            want = math.atan2(-fx / l, fy / l)
            self._walk_toward(want, 6.5, dt)
            if self.state_t <= 0:
                self.state = "walk"
                self.state_t = random.uniform(3, 9)
        elif self.state == "idle":
            self.speed = 0.0
            if self.state_t <= 0:
                self.state = "walk"
                self.state_t = random.uniform(4, 10)
        else:
            if self.state_t <= 0:
                if random.random() < 0.25:
                    self.state = "idle"
                    self.state_t = random.uniform(2, 5)
                else:
                    self.heading += random.uniform(-1.6, 1.6)
                    self.state_t = random.uniform(4, 10)
            self._walk_toward(self.heading, 1.5, dt)

        # dodge cars
        for car in game.nearby_cars(self.x, self.y, 6.0):
            if car.vel_mag > 3 and not self.cop:
                self.scare(car.x, car.y)
        self._collide(dt)
        self.z = game.ground.surface(self.x, self.y, self.z)[0]
        self.phase += self.speed * dt * 2.2
        self.rig.root.setPos(self.x, self.y, self.z)
        self.rig.root.setH(math.degrees(self.heading))
        aiming = self.cop and self.shoot_cd > -0.4 and self.game.cops.stars >= 2
        self.rig.pose(self.phase, min(1.0, self.speed / 3), aiming=aiming)
        return True

    def _walk_toward(self, want, speed, dt):
        d = (want - self.heading + math.pi) % math.tau - math.pi
        self.heading += max(-3 * dt, min(3 * dt, d * 4 * dt))
        self.speed = speed
        fx, fy = -math.sin(self.heading), math.cos(self.heading)
        self.x += fx * speed * dt
        self.y += fy * speed * dt

    def _update_cop(self, dt):
        game = self.game
        p = game.player
        px, py = game.player_world_pos()
        dx, dy = px - self.x, py - self.y
        dist = math.hypot(dx, dy)
        want = math.atan2(-dx, dy)
        if dist > 2.0:
            self._walk_toward(want, 5.8, dt)
        else:
            self.speed = 0.0
            self.heading = want
        # arrest
        if p.car is None and dist < 1.7 and not p.dead:
            game.busted()
            return
        # shoot at 2+ stars
        if game.cops.stars >= 2 and self.shoot_cd <= 0 and 3 < dist < 45 and p.car is None:
            self.shoot_cd = random.uniform(1.1, 1.8)
            ox, oy, oz = self.x, self.y, self.z + 1.3
            tx, ty, tz = px, py, p.z + 0.9
            l = math.dist((ox, oy, oz), (tx, ty, tz)) or 1
            aim_err = 0.10 if p.speed_estimate() > 3 else 0.045
            weapons.fire(game, self, ox, oy, oz,
                         (tx - ox) / l + random.uniform(-aim_err, aim_err),
                         (ty - oy) / l + random.uniform(-aim_err, aim_err),
                         (tz - oz) / l + random.uniform(-aim_err, aim_err), "pistol")

    def _collide(self, dt):
        for (x0, x1, y0, y1, z0, z1) in self.game.city.query_colliders(self.x, self.y, 1.2):
            if self.z > z1 - 0.4 or self.z + 1.8 < z0:
                continue
            nx = max(x0, min(self.x, x1))
            ny = max(y0, min(self.y, y1))
            dx, dy = self.x - nx, self.y - ny
            d2 = dx * dx + dy * dy
            r = 0.4
            if d2 < r * r:
                if d2 < 1e-6:
                    self.heading += math.pi
                    continue
                d = math.sqrt(d2)
                self.x = nx + dx / d * r
                self.y = ny + dy / d * r
                if self.state == "walk":
                    self.heading += random.uniform(1.2, 2.0)

    def destroy(self):
        self.rig.destroy()


class PedManager:
    def __init__(self, game):
        self.game = game
        self.peds = []

    def everyone(self):
        return self.peds + self.game.cops.officers

    def scare(self, x, y, radius):
        for p in self.peds:
            if (p.x - x) ** 2 + (p.y - y) ** 2 < radius * radius:
                p.scare(x, y)

    def update(self, dt):
        game = self.game
        px, py = game.player_world_pos()
        keep = []
        for p in self.peds:
            alive = p.update(dt)
            d = math.hypot(p.x - px, p.y - py)
            if not alive or d > C.DESPAWN_R:
                p.destroy()
            else:
                keep.append(p)
        self.peds = keep
        if len(self.peds) < C.MAX_PEDS and random.random() < 0.15:
            self._spawn(px, py)

    def _spawn(self, px, py):
        game = self.game
        for _ in range(10):
            ang = random.uniform(0, math.tau)
            d = random.uniform(*C.SPAWN_RING)
            x, y = px - math.sin(ang) * d, py + math.cos(ang) * d
            if not (C.BASIN_X0 - 80 < x < C.BASIN_X1 - 20 and C.BASIN_Y0 + 20 < y < C.BASIN_Y1 - 20):
                continue
            if game.ground.is_wet(x, y):
                continue
            # keep them near sidewalks: snap to the closest road edge sometimes
            self.peds.append(Ped(game, x, y))
            return


class CopSystem:
    def __init__(self, game):
        self.game = game
        self.heat = 0.0
        self.cooldown = 0.0
        self.cruisers = []     # Car with driver='cop'
        self.officers = []     # Ped(cop=True)
        self.spawn_t = 0.0

    @property
    def stars(self):
        return min(5, int(self.heat))

    def add_heat(self, amount):
        self.heat = min(5.9, self.heat + amount)
        self.cooldown = 9.0

    def witness_gunfire(self):
        px, py = self.game.player_world_pos()
        # gunfire raises heat faster if cops are nearby
        near = any(math.hypot(c.x - px, c.y - py) < 60 for c in self.cruisers)
        self.add_heat(0.30 if near else 0.12)

    def clear(self):
        self.heat = 0.0
        for c in self.cruisers:
            c.destroy()
        for o in self.officers:
            o.destroy()
        self.cruisers = []
        self.officers = []

    def update(self, dt, t):
        game = self.game
        if self.cooldown > 0:
            self.cooldown -= dt
        elif self.heat > 0:
            self.heat = max(0.0, self.heat - C.WANTED_DECAY * dt * (1 + self.heat * 0.2))
        stars = self.stars
        if stars == 0:
            if self.cruisers or self.officers:
                self.clear()
            return

        px, py = game.player_world_pos()
        # maintain cruiser count
        want_cars = stars
        self.spawn_t -= dt
        if len(self.cruisers) < want_cars and self.spawn_t <= 0:
            self.spawn_t = max(2.0, 7.0 - stars)
            ang = random.uniform(0, math.tau)
            d = random.uniform(120, 190)
            x, y = px - math.sin(ang) * d, py + math.cos(ang) * d
            x = max(C.BASIN_X0 + 30, min(C.BASIN_X1 - 30, x))
            y = max(C.BASIN_Y0 + 30, min(C.BASIN_Y1 - 30, y))
            if not game.ground.is_wet(x, y):
                self.cruisers.append(Car(game, "police", x, y,
                                         random.uniform(0, math.tau), driver="cop"))

        keep = []
        for car in self.cruisers:
            if car.wreck:
                if random.random() < 0.02:
                    continue  # eventually despawn wrecks... keep most for chaos
                keep.append(car)
                continue
            self._chase(car, dt, px, py)
            car.integrate(dt)
            car.collide_static()
            car.flash_lightbar(t)
            car.set_headlights(game.is_night)
            car.sync()
            d = math.hypot(car.x - px, car.y - py)
            # deploy an officer when close and slow
            if d < 16 and abs(car.speed) < 2 and len(self.officers) < stars and game.player.car is None:
                self.officers.append(Ped(game, car.x + 1.5, car.y, preset=COP_PRESET, cop=True))
            if d > C.DESPAWN_R + 60:
                car.destroy()
                continue
            keep.append(car)
        self.cruisers = keep

        keep = []
        for o in self.officers:
            if o.update(dt) and math.hypot(o.x - px, o.y - py) < C.DESPAWN_R:
                keep.append(o)
            else:
                o.destroy()
        self.officers = keep

    def _chase(self, car, dt, px, py):
        dx, dy = px - car.x, py - car.y
        dist = math.hypot(dx, dy)
        want = math.atan2(-dx, dy)
        derr = (want - car.heading + math.pi) % math.tau - math.pi
        steer = max(-1, min(1, derr * 2.0))
        # whisker: steer around static stuff dead ahead
        fx, fy = car.fwd
        ax, ay = car.x + fx * 9, car.y + fy * 9
        for (x0, x1, y0, y1, z0, z1) in self.game.city.query_colliders(ax, ay, 3.0):
            if z0 <= car.z + 1 and car.z < z1:
                steer = 1.0 if steer >= 0 else -1.0
                break
        target = 10.0 if dist < 25 else min(car.spec["top"], 12 + dist * 0.35)
        throttle = 0.9 if car.speed < target else -0.4
        if dist < 9 and self.game.player.car is None:
            throttle = -0.8 if car.speed > 1 else 0.0
        # reverse out when stuck
        if abs(car.speed) < 0.7 and not car.airborne:
            car.stuck_t += dt
        else:
            car.stuck_t = max(0, car.stuck_t - dt)
        if car.stuck_t > 1.6:
            throttle = -0.8
            steer = -steer
            if car.stuck_t > 3.2:
                car.stuck_t = 0
        car.control(dt, throttle, steer, False)
