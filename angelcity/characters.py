"""Blocky low-poly characters, built procedurally. One rig class serves the player,
pedestrians, and cops; the player can swap between the playable presets at any time."""

import math
import random
from .meshgen import MeshBuilder

SKIN_TONES = [(0.96, 0.80, 0.66), (0.87, 0.67, 0.51), (0.72, 0.51, 0.35),
              (0.55, 0.38, 0.26), (0.42, 0.29, 0.20)]
SHIRTS = [(0.90, 0.30, 0.28), (0.25, 0.55, 0.85), (0.95, 0.80, 0.25), (0.30, 0.70, 0.45),
          (0.85, 0.85, 0.88), (0.55, 0.35, 0.75), (0.95, 0.55, 0.20), (0.20, 0.22, 0.25),
          (0.95, 0.45, 0.65), (0.15, 0.65, 0.65)]
PANTS = [(0.25, 0.30, 0.45), (0.20, 0.20, 0.22), (0.55, 0.45, 0.35), (0.75, 0.72, 0.65),
         (0.35, 0.40, 0.35), (0.60, 0.25, 0.25)]
HAIR = [(0.12, 0.10, 0.08), (0.25, 0.16, 0.08), (0.55, 0.42, 0.20), (0.85, 0.75, 0.45),
        (0.35, 0.35, 0.38), (0.75, 0.30, 0.15)]
HAIR_STYLES = ["flat", "afro", "long", "cap", "beanie", "bald"]

# Playable characters — original Angel City locals.
PRESETS = [
    dict(name="Mira Santos", skin=1, shirt=(0.95, 0.45, 0.35), pants=(0.25, 0.30, 0.45),
         hair=(0.12, 0.10, 0.08), style="long", shorts=False),
    dict(name="Dre Holloway", skin=3, shirt=(0.55, 0.35, 0.75), pants=(0.20, 0.20, 0.22),
         hair=(0.12, 0.10, 0.08), style="flat", shorts=False),
    dict(name="Sofia Reyes", skin=2, shirt=(0.95, 0.80, 0.25), pants=(0.35, 0.40, 0.35),
         hair=(0.25, 0.16, 0.08), style="cap", shorts=True),
    dict(name="Kenji Park", skin=0, shirt=(0.20, 0.22, 0.25), pants=(0.55, 0.45, 0.35),
         hair=(0.12, 0.10, 0.08), style="flat", shorts=False),
    dict(name="Rocket Reed", skin=1, shirt=(0.30, 0.70, 0.45), pants=(0.75, 0.72, 0.65),
         hair=(0.75, 0.30, 0.15), style="afro", shorts=True),
    dict(name="Nova Odum", skin=4, shirt=(0.25, 0.55, 0.85), pants=(0.20, 0.20, 0.22),
         hair=(0.12, 0.10, 0.08), style="beanie", shorts=False),
    dict(name="Sunny Delgado", skin=2, shirt=(0.95, 0.55, 0.20), pants=(0.15, 0.65, 0.65),
         hair=(0.55, 0.42, 0.20), style="bald", shorts=True),
    dict(name="Lex Marlowe", skin=0, shirt=(0.90, 0.30, 0.28), pants=(0.25, 0.30, 0.45),
         hair=(0.85, 0.75, 0.45), style="long", shorts=False),
    dict(name="Marisol Vega", skin=2, shirt=(0.95, 0.95, 0.95), pants=(0.60, 0.25, 0.25),
         hair=(0.25, 0.16, 0.08), style="long", shorts=False),
    dict(name="Tyrese Cole", skin=4, shirt=(0.95, 0.80, 0.25), pants=(0.25, 0.30, 0.45),
         hair=(0.12, 0.10, 0.08), style="bald", shorts=True),
    dict(name="Harper Lane", skin=1, shirt=(0.20, 0.75, 0.75), pants=(0.20, 0.20, 0.22),
         hair=(0.75, 0.30, 0.15), style="beanie", shorts=False),
    dict(name="Diego Ruiz", skin=3, shirt=(0.30, 0.70, 0.45), pants=(0.55, 0.45, 0.35),
         hair=(0.12, 0.10, 0.08), style="cap", shorts=False),
]

COP_PRESET = dict(name="APD Officer", skin=2, shirt=(0.14, 0.17, 0.30),
                  pants=(0.13, 0.15, 0.26), hair=(0.12, 0.10, 0.08), style="cap",
                  shorts=False)

GUN_SPECS = {
    "pistol": [((0, 0.16, 0.02), (0.05, 0.26, 0.06), (0.18, 0.18, 0.20)),
               ((0, 0.04, -0.07), (0.05, 0.07, 0.12), (0.22, 0.20, 0.18))],
    "smg": [((0, 0.20, 0.02), (0.06, 0.40, 0.08), (0.15, 0.15, 0.17)),
            ((0, 0.04, -0.08), (0.05, 0.08, 0.14), (0.18, 0.17, 0.15)),
            ((0, 0.30, -0.06), (0.04, 0.10, 0.08), (0.12, 0.12, 0.14))],
    "shotgun": [((0, 0.26, 0.02), (0.06, 0.60, 0.07), (0.30, 0.22, 0.14)),
                ((0, -0.02, -0.05), (0.06, 0.16, 0.10), (0.35, 0.24, 0.15))],
}


def random_ped_preset(rng, beach=False):
    if beach and rng.random() < 0.6:
        shirt = random.choice([(0.95, 0.55, 0.20), (0.20, 0.75, 0.75), (0.95, 0.45, 0.65),
                               (0.95, 0.90, 0.80)])
        shorts = True
    else:
        shirt = rng.choice(SHIRTS)
        shorts = rng.random() < 0.3
    return dict(name="ped", skin=rng.randrange(len(SKIN_TONES)), shirt=shirt,
                pants=rng.choice(PANTS), hair=rng.choice(HAIR),
                style=rng.choice(HAIR_STYLES), shorts=shorts)


class CharacterRig:
    """Articulated blocky human. Origin at the feet, faces +Y at heading 0."""

    def __init__(self, parent, preset, scale=1.0):
        self.preset = preset
        self.root = parent.attachNewNode("char")
        self.root.setScale(scale)
        skin = SKIN_TONES[preset["skin"]]
        shirt, pants, hair = preset["shirt"], preset["pants"], preset["hair"]
        shoe = (0.15, 0.13, 0.12)

        b = MeshBuilder("torso")
        b.add_box(0, 0, 0.74, 0.42, 0.26, 0.60, shirt)
        b.add_box(0, 0, 0.66, 0.40, 0.25, 0.10, pants)
        b.build(self.root)

        b = MeshBuilder("head")
        b.add_box(0, 0, 1.40, 0.27, 0.25, 0.27, skin)
        # eyes on the +Y (front) face
        ec = (0.08, 0.08, 0.10)
        b.add_quad((-0.085, 0.128, 1.52), (-0.035, 0.128, 1.52),
                   (-0.035, 0.128, 1.575), (-0.085, 0.128, 1.575), ec, (0, 1, 0))
        b.add_quad((0.035, 0.128, 1.52), (0.085, 0.128, 1.52),
                   (0.085, 0.128, 1.575), (0.035, 0.128, 1.575), ec, (0, 1, 0))
        style = preset["style"]
        if style == "flat":
            b.add_box(0, -0.01, 1.66, 0.29, 0.27, 0.07, hair)
        elif style == "afro":
            b.add_dome(0, 0, 1.60, 0.21, hair, sides=8, rings=3)
        elif style == "long":
            b.add_box(0, -0.01, 1.66, 0.29, 0.27, 0.07, hair)
            b.add_box(0, -0.11, 1.22, 0.30, 0.09, 0.46, hair)
        elif style == "cap":
            b.add_box(0, 0.0, 1.65, 0.30, 0.28, 0.08, hair)
            b.add_box(0, 0.19, 1.64, 0.26, 0.12, 0.03, hair)
        elif style == "beanie":
            b.add_box(0, 0, 1.62, 0.30, 0.28, 0.12, hair)
        b.build(self.root)

        def limb(px, shoulder_z, w, upper_len, lower_len, upper_c, lower_c, foot=None):
            pivot = self.root.attachNewNode("pivot")
            pivot.setPos(px, 0, shoulder_z)
            mb = MeshBuilder("limb")
            mb.add_box(0, 0, -upper_len, w, w, upper_len, upper_c)
            mb.add_box(0, 0, -upper_len - lower_len, w * 0.92, w * 0.92, lower_len, lower_c)
            if foot:
                mb.add_box(0, 0.05, -upper_len - lower_len - 0.06, w, w + 0.12, 0.09, foot)
            mb.build(pivot)
            return pivot

        sleeve = shirt
        self.arm_l = limb(-0.28, 1.28, 0.13, 0.26, 0.26, sleeve, skin)
        self.arm_r = limb(0.28, 1.28, 0.13, 0.26, 0.26, sleeve, skin)
        leg_upper = skin if preset.get("shorts") else pants
        leg_c = pants if not preset.get("shorts") else pants
        self.leg_l = limb(-0.11, 0.70, 0.15, 0.34, 0.30, leg_c, leg_upper if preset.get("shorts") else pants, foot=shoe)
        self.leg_r = limb(0.11, 0.70, 0.15, 0.34, 0.30, leg_c, leg_upper if preset.get("shorts") else pants, foot=shoe)

        # blob shadow
        sb = MeshBuilder("shadow")
        sb.add_rect(-0.34, -0.3, 0.34, 0.34, 0.02, (0.05, 0.05, 0.07, 0.35))
        self.shadow = sb.build(self.root)
        self.shadow.setTransparency(True)

        # gun models attach to the right hand; hidden until wielded
        self.hand = self.arm_r.attachNewNode("hand")
        self.hand.setPos(0, 0.06, -0.52)
        self.guns = {}
        for kind, parts in GUN_SPECS.items():
            g = MeshBuilder("gun")
            for (cx, cy, cz), (sx, sy, sz), col in parts:
                g.add_box(cx, cy, cz - sz / 2, sx, sy, sz, col)
            np = g.build(self.hand)
            np.hide()
            self.guns[kind] = np
        self.current_gun = None

    def show_gun(self, kind):
        if self.current_gun == kind:
            return
        for k, np in self.guns.items():
            np.hide()
        if kind in self.guns:
            self.guns[kind].show()
        self.current_gun = kind if kind in self.guns else None

    def pose(self, phase, amp, aiming=False, aim_pitch=0.0):
        """phase advances with distance walked; amp 0..1; aim_pitch in degrees."""
        swing = math.sin(phase) * 38.0 * amp
        self.leg_l.setP(swing)
        self.leg_r.setP(-swing)
        self.arm_l.setP(-swing * 0.8)
        if aiming:
            self.arm_r.setP(-90.0 - aim_pitch)
        else:
            self.arm_r.setP(swing * 0.8)

    def lie_down(self):
        self.root.setP(88)
        self.root.setZ(self.root.getZ() + 0.25)

    def destroy(self):
        self.root.removeNode()
