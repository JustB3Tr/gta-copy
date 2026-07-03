"""Procedural mesh building. Everything in the game is generated from these primitives —
there are no asset files. Meshes use flat shading via per-face normals and vertex colors."""

import math
from panda3d.core import (Geom, GeomNode, GeomPoints, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, NodePath)


def rot2(x, y, ang):
    c, s = math.cos(ang), math.sin(ang)
    return x * c - y * s, x * s + y * c


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / l, v[1] / l, v[2] / l)


class MeshBuilder:
    """Accumulates colored (optionally UV-mapped) triangles into a single GeomNode."""

    def __init__(self, name="mesh"):
        self.name = name
        self.verts = []   # (x,y,z, nx,ny,nz, r,g,b,a, u,v)
        self.tris = []

    @property
    def empty(self):
        return not self.tris

    def _v(self, p, n, c, uv=(0.0, 0.0)):
        a = c[3] if len(c) > 3 else 1.0
        self.verts.append((p[0], p[1], p[2], n[0], n[1], n[2], c[0], c[1], c[2], a,
                           uv[0], uv[1]))
        return len(self.verts) - 1

    def add_tri(self, p0, p1, p2, color, normal=None):
        n = normal or _norm(_cross(_sub(p1, p0), _sub(p2, p0)))
        i = self._v(p0, n, color)
        self._v(p1, n, color)
        self._v(p2, n, color)
        self.tris.append((i, i + 1, i + 2))

    def add_quad(self, p0, p1, p2, p3, color, normal=None, uvs=None, colors=None):
        """Counter-clockwise winding as seen from the normal side. `colors` overrides
        the flat color per-vertex (used for baked AO gradients)."""
        n = normal or _norm(_cross(_sub(p1, p0), _sub(p3, p0)))
        uvs = uvs or ((0, 0), (0, 0), (0, 0), (0, 0))
        cs = colors or (color, color, color, color)
        i = self._v(p0, n, cs[0], uvs[0])
        self._v(p1, n, cs[1], uvs[1])
        self._v(p2, n, cs[2], uvs[2])
        self._v(p3, n, cs[3], uvs[3])
        self.tris.append((i, i + 1, i + 2))
        self.tris.append((i, i + 2, i + 3))

    def add_facade_box(self, cx, cy, z0, sx, sy, sz, color, uv_scale=0.25,
                       top_color=None):
        """Box whose four walls carry window-grid UVs (u along the wall, v up)."""
        hx, hy = sx * 0.5, sy * 0.5
        z1 = z0 + sz
        corners = [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy),
                   (cx - hx, cy + hy)]
        u = 0.0
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            w = math.hypot(b[0] - a[0], b[1] - a[1])
            self.add_quad((a[0], a[1], z0), (b[0], b[1], z0),
                          (b[0], b[1], z1), (a[0], a[1], z1), color,
                          uvs=((u, z0 * uv_scale), (u + w * uv_scale, z0 * uv_scale),
                               (u + w * uv_scale, z1 * uv_scale), (u, z1 * uv_scale)))
            u += w * uv_scale
        tc = top_color or tuple(v * 0.6 for v in color[:3])
        self.add_quad((corners[0][0], corners[0][1], z1), (corners[1][0], corners[1][1], z1),
                      (corners[2][0], corners[2][1], z1), (corners[3][0], corners[3][1], z1),
                      tc, (0, 0, 1))

    def add_rect(self, x0, y0, x1, y1, z, color):
        """Horizontal upward-facing rectangle."""
        self.add_quad((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), color, (0, 0, 1))

    def add_box(self, cx, cy, z0, sx, sy, sz, color, heading=0.0, top_color=None,
                bottom=False, wall_uv=0.0, ao=0.0):
        """Axis box centered at (cx,cy), resting on z0, optionally rotated about Z.
        wall_uv > 0 bakes wall UVs (u along the face, v up) at that meters-per-repeat.
        ao > 0 darkens the wall bases by that fraction (cheap contact occlusion)."""
        hx, hy = sx * 0.5, sy * 0.5
        z1 = z0 + sz
        corners = []
        for dx, dy in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
            rx, ry = rot2(dx, dy, heading)
            corners.append((cx + rx, cy + ry))
        c = corners
        tc = top_color or color
        self.add_quad((c[0][0], c[0][1], z1), (c[1][0], c[1][1], z1),
                      (c[2][0], c[2][1], z1), (c[3][0], c[3][1], z1), tc)
        base = tuple(v * (1.0 - ao) for v in color[:3]) + ((color[3],) if len(color) > 3 else ())
        for i in range(4):
            a, b = c[i], c[(i + 1) % 4]
            uvs = None
            if wall_uv > 0:
                w = math.hypot(b[0] - a[0], b[1] - a[1]) / wall_uv
                uvs = ((0, z0 / wall_uv), (w, z0 / wall_uv), (w, z1 / wall_uv),
                       (0, z1 / wall_uv))
            colors = (base, base, color, color) if ao > 0 else None
            self.add_quad((a[0], a[1], z0), (b[0], b[1], z0),
                          (b[0], b[1], z1), (a[0], a[1], z1), color,
                          uvs=uvs, colors=colors)
        if bottom:
            self.add_quad((c[3][0], c[3][1], z0), (c[2][0], c[2][1], z0),
                          (c[1][0], c[1][1], z0), (c[0][0], c[0][1], z0), color)

    def add_gable(self, cx, cy, z0, sx, sy, roof_h, color, heading=0.0, uv=0.0,
                  end_color=None):
        """Triangular prism roof sitting on z0, ridge along local X. uv > 0 bakes
        slope UVs so tile courses run parallel to the ridge."""
        hx, hy = sx * 0.5, sy * 0.5

        def w(dx, dy, z):
            rx, ry = rot2(dx, dy, heading)
            return (cx + rx, cy + ry, z)

        ridge0, ridge1 = w(-hx, 0, z0 + roof_h), w(hx, 0, z0 + roof_h)
        a0, a1 = w(-hx, -hy, z0), w(hx, -hy, z0)
        b0, b1 = w(-hx, hy, z0), w(hx, hy, z0)
        uvs = None
        if uv > 0:
            slope = math.hypot(hy, roof_h) / uv
            L = sx / uv
            uvs = ((0, 0), (0, L), (slope, L), (slope, 0))
            self.add_quad(a0, a1, ridge1, ridge0, color,
                          uvs=((0, 0), (L, 0), (L, slope), (0, slope)))
            self.add_quad(ridge0, ridge1, b1, b0, color,
                          uvs=((0, slope), (L, slope), (L, 0), (0, 0)))
        else:
            self.add_quad(a0, a1, ridge1, ridge0, color)
            self.add_quad(ridge0, ridge1, b1, b0, color)
        ec = end_color or color
        self.add_tri(a0, ridge0, b0, ec)
        self.add_tri(a1, b1, ridge1, ec)

    def add_cylinder(self, cx, cy, z0, radius, height, color, sides=10, top=True,
                     top_color=None, r_top=None):
        r0, r1 = radius, radius if r_top is None else r_top
        z1 = z0 + height
        pts = []
        for i in range(sides):
            a = 2 * math.pi * i / sides
            pts.append((math.cos(a), math.sin(a)))
        for i in range(sides):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % sides]
            na = _norm((ax, ay, 0))
            nb = _norm((bx, by, 0))
            i0 = self._v((cx + ax * r0, cy + ay * r0, z0), na, color)
            self._v((cx + bx * r0, cy + by * r0, z0), nb, color)
            self._v((cx + bx * r1, cy + by * r1, z1), nb, color)
            self._v((cx + ax * r1, cy + ay * r1, z1), na, color)
            self.tris.append((i0, i0 + 1, i0 + 2))
            self.tris.append((i0, i0 + 2, i0 + 3))
        if top:
            tc = top_color or color
            for i in range(1, sides - 1):
                self.add_tri((cx + pts[0][0] * r1, cy + pts[0][1] * r1, z1),
                             (cx + pts[i][0] * r1, cy + pts[i][1] * r1, z1),
                             (cx + pts[i + 1][0] * r1, cy + pts[i + 1][1] * r1, z1),
                             tc, (0, 0, 1))

    def add_dome(self, cx, cy, z0, radius, color, sides=12, rings=4, squash=1.0):
        for j in range(rings):
            a0 = math.pi * 0.5 * j / rings
            a1 = math.pi * 0.5 * (j + 1) / rings
            r0, z0r = radius * math.cos(a0), z0 + radius * math.sin(a0) * squash
            r1, z1r = radius * math.cos(a1), z0 + radius * math.sin(a1) * squash
            for i in range(sides):
                b0 = 2 * math.pi * i / sides
                b1 = 2 * math.pi * (i + 1) / sides
                p00 = (cx + r0 * math.cos(b0), cy + r0 * math.sin(b0), z0r)
                p10 = (cx + r0 * math.cos(b1), cy + r0 * math.sin(b1), z0r)
                p11 = (cx + r1 * math.cos(b1), cy + r1 * math.sin(b1), z1r)
                p01 = (cx + r1 * math.cos(b0), cy + r1 * math.sin(b0), z1r)
                if j == rings - 1:
                    self.add_tri(p00, p10, (cx, cy, z0 + radius * squash), color)
                else:
                    self.add_quad(p00, p10, p11, p01, color)

    def add_strip(self, points, half_width, color, z_off=0.05):
        """Flat ribbon following a 3D polyline (used for hill roads, paths)."""
        if len(points) < 2:
            return
        lefts, rights = [], []
        for i, p in enumerate(points):
            a = points[max(0, i - 1)]
            b = points[min(len(points) - 1, i + 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            l = math.hypot(dx, dy) or 1.0
            px, py = -dy / l * half_width, dx / l * half_width
            lefts.append((p[0] + px, p[1] + py, p[2] + z_off))
            rights.append((p[0] - px, p[1] - py, p[2] + z_off))
        for i in range(len(points) - 1):
            self.add_quad(rights[i], rights[i + 1], lefts[i + 1], lefts[i], color)

    def build(self, parent, name=None):
        fmt = GeomVertexFormat.getV3n3c4t2()
        vdata = GeomVertexData(name or self.name, fmt, Geom.UHStatic)
        vdata.setNumRows(len(self.verts))
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        cw = GeomVertexWriter(vdata, "color")
        tw = GeomVertexWriter(vdata, "texcoord")
        for x, y, z, nx, ny, nz, r, g, b, a, u, v in self.verts:
            vw.addData3(x, y, z)
            nw.addData3(nx, ny, nz)
            cw.addData4(r, g, b, a)
            tw.addData2(u, v)
        prim = GeomTriangles(Geom.UHStatic)
        for t in self.tris:
            prim.addVertices(*t)
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode(name or self.name)
        node.addGeom(geom)
        return parent.attachNewNode(node)


def build_points(parent, pts, color, size=2.0, name="points"):
    """Point cloud (used for the night-sky stars)."""
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(len(pts))
    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")
    for p in pts:
        vw.addData3(*p)
        cw.addData4(*color)
    prim = GeomPoints(Geom.UHStatic)
    for i in range(len(pts)):
        prim.addVertex(i)
    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    np = parent.attachNewNode(node)
    np.setRenderModeThickness(size)
    return np
