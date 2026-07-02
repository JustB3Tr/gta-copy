"""On-screen UI: health, money, wanted stars, weapon, minimap with blips, prompts,
banners (WASTED/BUSTED), pause menu, and the full-city map overlay."""

import math
from panda3d.core import CardMaker, TextNode, TextureStage, TransparencyAttrib

FONT_COL = (0.95, 0.95, 0.92, 1)
GOLD = (0.95, 0.80, 0.25, 1)
DARKCHIP = (0.25, 0.25, 0.28, 0.55)

CONTROLS_TEXT = """WASD — move / drive        MOUSE — look    (RMB aim, LMB fire/punch)
SHIFT — sprint             SPACE — jump / handbrake
E — enter or exit car, buy, respray       C — swap character
1-4 / X — weapons          H — horn        M — city map
SCROLL — camera zoom       F5 — screenshot        ESC — pause"""


def _card(parent, color, l=-1, r=1, b=-1, t=1):
    cm = CardMaker("card")
    cm.setFrame(l, r, b, t)
    np = parent.attachNewNode(cm.generate())
    np.setColor(*color)
    np.setTransparency(TransparencyAttrib.MAlpha)
    return np


def _text(parent, msg, x, y, scale=0.05, color=FONT_COL, align=TextNode.ALeft,
          shadow=True):
    tn = TextNode("t")
    tn.setText(msg)
    tn.setTextColor(*color)
    tn.setAlign(align)
    if shadow:
        tn.setShadow(0.06, 0.06)
        tn.setShadowColor(0, 0, 0, 0.8)
    np = parent.attachNewNode(tn)
    np.setPos(x, 0, y)
    np.setScale(scale)
    return np, tn


class HUD:
    def __init__(self, game):
        self.game = game
        base = game
        self.aspect = base.getAspectRatio()
        A = self.aspect
        root = base.aspect2d
        self.root = root

        # health bar
        self.hp_bg = _card(root, (0.08, 0.08, 0.1, 0.65), -A + 0.06, -A + 0.66, 0.895, 0.945)
        self.hp_fg = _card(root, (0.85, 0.25, 0.25, 0.95), 0, 0.58, 0.0, 0.04)
        self.hp_fg.setPos(-A + 0.07, 0, 0.9)
        self.money_np, self.money_tn = _text(root, "$0", -A + 0.06, 0.82, 0.055,
                                             (0.55, 0.9, 0.55, 1))
        self.name_np, self.name_tn = _text(root, "", -A + 0.06, 0.755, 0.042,
                                           (0.9, 0.9, 0.85, 1))

        # wanted stars
        self.stars = []
        for i in range(5):
            chip = _card(root, DARKCHIP, -0.028, 0.028, -0.028, 0.028)
            chip.setPos(A - 0.42 + i * 0.085, 0, 0.905)
            chip.setR(45)
            self.stars.append(chip)

        # weapon + ammo
        self.wpn_np, self.wpn_tn = _text(root, "", A - 0.06, -0.90, 0.055, FONT_COL,
                                         TextNode.ARight)

        # minimap
        self.mm_size = 0.30
        cx, cy = -A + 0.40, -0.62
        self.mm_frame = _card(root, (0.05, 0.05, 0.08, 0.8),
                              cx - self.mm_size - 0.012, cx + self.mm_size + 0.012,
                              cy - self.mm_size - 0.012, cy + self.mm_size + 0.012)
        self.mm = _card(root, (1, 1, 1, 1), cx - self.mm_size, cx + self.mm_size,
                        cy - self.mm_size, cy + self.mm_size)
        self.mm.setTexture(game.city.map_tex)
        self.mm_center = (cx, cy)
        self.mm_zoom = 560.0     # meters shown across the minimap
        self.player_arrow = _card(root, (1, 1, 1, 1), -0.016, 0.016, -0.022, 0.022)
        self.player_arrow.setPos(cx, 0, cy)
        self.blips = []
        for _ in range(28):
            bp = _card(root, (1, 1, 1, 1), -0.010, 0.010, -0.010, 0.010)
            bp.hide()
            self.blips.append(bp)

        # prompt + flash message + banner + location
        self.prompt_np, self.prompt_tn = _text(root, "", 0, -0.72, 0.055, FONT_COL,
                                               TextNode.ACenter)
        self.msg_np, self.msg_tn = _text(root, "", 0, 0.62, 0.06, GOLD, TextNode.ACenter)
        self.msg_t = 0.0
        self.loc_np, self.loc_tn = _text(root, "", A - 0.06, 0.90, 0.048,
                                         (0.85, 0.88, 0.95, 1), TextNode.ARight)
        self.loc_np.setPos(A - 0.06, 0, 0.80)
        self.card_np, self.card_tn = _text(root, "", -A + 0.10, -0.16, 0.10,
                                           (0.95, 0.85, 0.4, 1), TextNode.ALeft)
        self.card_t = 0.0
        self.banner_np, self.banner_tn = _text(root, "", 0, 0.1, 0.24,
                                               (0.9, 0.15, 0.15, 1), TextNode.ACenter)
        self.banner_np.hide()
        self.fade = _card(root, (0, 0, 0, 0), -A - 0.1, A + 0.1, -1.1, 1.1)
        self.fade.setColor(0, 0, 0, 0)
        self.dmg = _card(root, (0.7, 0, 0, 0), -A - 0.1, A + 0.1, -1.1, 1.1)
        self.dmg_t = 0.0

        # crosshair
        self.cross_v = _card(root, (1, 1, 1, 0.85), -0.002, 0.002, -0.018, 0.018)
        self.cross_h = _card(root, (1, 1, 1, 0.85), -0.018, 0.018, -0.002, 0.002)
        self.cross_v.hide()
        self.cross_h.hide()

        # pause overlay
        self.pause_np = root.attachNewNode("pause")
        _card(self.pause_np, (0.02, 0.02, 0.05, 0.82), -A - 0.1, A + 0.1, -1.1, 1.1)
        _text(self.pause_np, "ANGEL CITY", 0, 0.52, 0.16, GOLD, TextNode.ACenter)
        _text(self.pause_np, "an original open-world sandbox — paused", 0, 0.40, 0.05,
              FONT_COL, TextNode.ACenter)
        _text(self.pause_np, CONTROLS_TEXT, 0, 0.16, 0.045, (0.8, 0.85, 0.9, 1),
              TextNode.ACenter)
        _text(self.pause_np, "ESC — resume", 0, -0.55, 0.055, GOLD, TextNode.ACenter)
        self.pause_np.hide()

        # big map overlay
        self.map_np = root.attachNewNode("bigmap")
        _card(self.map_np, (0.02, 0.02, 0.05, 0.88), -A - 0.1, A + 0.1, -1.1, 1.1)
        big = _card(self.map_np, (1, 1, 1, 1), -0.92, 0.92, -0.92, 0.92)
        big.setTexture(game.city.map_tex)
        self.map_player = _card(self.map_np, (0.2, 1, 0.3, 1), -0.014, 0.014, -0.014, 0.014)
        _text(self.map_np, "M — close map", 1.0, -0.98, 0.05, GOLD, TextNode.ACenter)
        for (name, wx, wy) in game.city.map_labels:
            u, v = game.city.world_to_uv(wx, wy)
            _text(self.map_np, name, -0.92 + u * 1.84, -0.92 + v * 1.84 + 0.02, 0.035,
                  (0.95, 0.92, 0.8, 0.95), TextNode.ACenter)
        self.map_np.hide()
        self._map_poi_dots()

    def _map_poi_dots(self):
        colors = {"hospital": (1, 0.4, 0.4, 1), "police": (0.4, 0.55, 1, 1),
                  "ammo": (0.95, 0.85, 0.3, 1), "spray1": (0.9, 0.5, 0.95, 1),
                  "spray2": (0.9, 0.5, 0.95, 1), "home": (0.4, 0.95, 0.5, 1),
                  "pier": (0.95, 0.7, 0.4, 1), "observatory": (0.8, 0.8, 0.9, 1)}
        for key, col in colors.items():
            if key not in self.game.city.poi:
                continue
            x, y = self.game.city.poi[key]
            u, v = self.game.city.world_to_uv(x, y)
            d = _card(self.map_np, col, -0.011, 0.011, -0.011, 0.011)
            d.setPos(-0.92 + u * 1.84, 0, -0.92 + v * 1.84)
            d.setR(45)

    # ---------------- per-frame ----------------

    def update(self, dt):
        game = self.game
        p = game.player
        self.hp_fg.setScale(max(0.001, p.health / 100.0), 1, 1)
        self.money_tn.setText("$%d" % p.money)
        self.name_tn.setText(p.name)
        stars = game.cops.stars
        blink = (game.t * 3) % 1 > 0.5
        for i, chip in enumerate(self.stars):
            if i < stars:
                chip.setColor(*(GOLD if (i < stars - 1 or blink) else (0.6, 0.5, 0.2, 0.9)))
            else:
                chip.setColor(*DARKCHIP)
        w = p.current
        if p.car:
            mode = getattr(p.car, "mode", "car")
            if mode == "air":
                self.wpn_tn.setText("%s  |  ALT %dm  |  %d mph" % (
                    p.car.spec["name"], int(max(0, p.car.z)),
                    int(abs(p.car.speed) * 2.24)))
            elif mode == "boat":
                self.wpn_tn.setText("%s  |  %d kn" % (p.car.spec["name"],
                                                      int(abs(p.car.speed) * 1.94)))
            else:
                self.wpn_tn.setText("%s  |  %d mph" % (p.car.spec["name"],
                                                       int(abs(p.car.speed) * 2.24)))
        elif w == "fist":
            self.wpn_tn.setText("Fists")
        else:
            from .weapons import WEAPONS
            self.wpn_tn.setText("%s  %d" % (WEAPONS[w]["label"], p.weapons.get(w) or 0))

        show_cross = p.car is None and w != "fist" and not game.paused
        for c in (self.cross_v, self.cross_h):
            c.show() if show_cross else c.hide()

        if self.msg_t > 0:
            self.msg_t -= dt
            if self.msg_t <= 0:
                self.msg_tn.setText("")
            else:
                self.msg_np.setColorScale(1, 1, 1, min(1, self.msg_t))
        if self.card_t > 0:
            self.card_t -= dt
            if self.card_t <= 0:
                self.card_tn.setText("")
            else:
                self.card_np.setColorScale(1, 1, 1, min(1, self.card_t))
        if self.dmg_t > 0:
            self.dmg_t -= dt * 2.2
            self.dmg.setColor(0.7, 0, 0, max(0, min(0.45, self.dmg_t)))

        self._update_minimap()
        if not self.map_np.isHidden():
            px, py = game.player_world_pos()
            u, v = game.city.world_to_uv(px, py)
            self.map_player.setPos(-0.92 + u * 1.84, 0, -0.92 + v * 1.84)
            self.map_player.setR(45 if (game.t * 2) % 1 > 0.5 else 0)

    def _update_minimap(self):
        game = self.game
        px, py = game.player_world_pos()
        u, v = game.city.world_to_uv(px, py)
        span_u = self.mm_zoom / (game.city.map_x1 - game.city.map_x0)
        span_v = self.mm_zoom / (game.city.map_y1 - game.city.map_y0)
        ts = TextureStage.getDefault()
        self.mm.setTexScale(ts, span_u * 2, span_v * 2)
        self.mm.setTexOffset(ts, u - span_u, v - span_v)
        heading = game.player.car.heading if game.player.car else game.player.heading
        self.player_arrow.setR(-math.degrees(heading))

        cx, cy = self.mm_center
        scale = self.mm_size / (self.mm_zoom / 2)   # aspect2d units per meter

        def place(blip, wx, wy, color):
            dx, dy = (wx - px) * scale, (wy - py) * scale
            r = math.hypot(dx, dy)
            lim = self.mm_size * 0.94
            if r > lim:
                dx, dy = dx / r * lim, dy / r * lim
            blip.setPos(cx + dx, 0, cy + dy)
            blip.setColor(*color)
            blip.show()

        i = 0
        blips = self.blips

        def take():
            nonlocal i
            b = blips[i] if i < len(blips) else None
            i += 1
            return b

        poi_cols = (("hospital", (1, 0.4, 0.4, 1)), ("police", (0.4, 0.55, 1, 1)),
                    ("ammo", (0.95, 0.85, 0.3, 1)), ("spray1", (0.9, 0.5, 0.95, 1)),
                    ("spray2", (0.9, 0.5, 0.95, 1)), ("home", (0.4, 0.95, 0.5, 1)))
        for key, col in poi_cols:
            if key in game.city.poi:
                b = take()
                if b:
                    place(b, *game.city.poi[key], col)
        for car in game.cops.cruisers:
            if not car.wreck:
                b = take()
                if b:
                    place(b, car.x, car.y, (0.3, 0.5, 1, 1))
        for b_rest in blips[i:]:
            b_rest.hide()

    # ---------------- events ----------------

    def flash_message(self, msg, t=2.8):
        self.msg_tn.setText(msg)
        self.msg_t = t
        self.msg_np.setColorScale(1, 1, 1, 1)

    def set_location(self, district, road):
        self.loc_tn.setText("%s%s" % (district, ("  —  " + road) if road else ""))

    def location_card(self, district):
        self.card_tn.setText(district.upper())
        self.card_t = 3.5
        self.card_np.setColorScale(1, 1, 1, 1)

    def set_prompt(self, msg):
        self.prompt_tn.setText(msg or "")

    def damage_flash(self):
        self.dmg_t = 0.5

    def banner(self, msg, color=(0.9, 0.15, 0.15, 1)):
        self.banner_tn.setText(msg)
        self.banner_tn.setTextColor(*color)
        self.banner_np.show()

    def banner_off(self):
        self.banner_np.hide()

    def set_fade(self, alpha):
        self.fade.setColor(0, 0, 0, max(0.0, min(1.0, alpha)))

    def show_pause(self, on):
        self.pause_np.show() if on else self.pause_np.hide()

    def toggle_map(self):
        if self.map_np.isHidden():
            self.map_np.show()
        else:
            self.map_np.hide()
