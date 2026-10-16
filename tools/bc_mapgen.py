#!/usr/bin/env python3
"""Boat Crew random custom-level generator.

Writes a level folder in the format the game's level editor reads. Put it under
<Boat Crew>/Boat Crew_Data/GameData/LevelEditor/<name>/ and it appears in the editor's list:

    SOURCE_<n>_Terrain.BCT   4096x4096 little-endian uint16, 0 = sea, >0 = land height
    SOURCE_<n>.BCD           gzip'd JSON node graph (spawners, waypoints, mission nodes)
    PreviewData.BCI          Title / Author / Description
    PreviewImage.png         thumbnail

Also writes <name>.BCP (a zip of the same files at its root, the Steam Workshop layout).

World <-> pixel mapping used for node placement, measured by opening generated maps in the editor:
    px = 2048 + X / UNITS_PER_PX      py = 2048 + Y / UNITS_PER_PX      (UNITS_PER_PX = 32, good to a few percent)
The editor's grid labels are world units / 250 and its grid shows roughly +-50 labels (+-12,500 world, +-390 px),
so everything is kept inside +-375 px of the centre.
Use --calibrate to add four marker waypoints (+-10 grid units around the player start) to check the scale in-game.

Usage: python bc_mapgen.py --seed 7 --style landmass --out ./generated
Needs: numpy, Pillow.
"""
import argparse, gzip, json, math, os, random, re, zipfile
import numpy as np
from PIL import Image

N = 4096
UNITS_PER_PX = 32.0      # world units per terrain pixel (about; measured, not read from the game)
GRID_UNIT = 250.0        # world units per editor grid label
PLAY_RADIUS_PX = 375     # keep land and nodes inside this radius of the map centre


# ---------- terrain ----------
def fractal_noise(size, beta, rng):
    """Spectral-synthesis noise, roughly 1/f^beta, normalised to 0..1."""
    f = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(f, f)
    r = np.sqrt(fx ** 2 + fy ** 2)
    r[0, 0] = 1.0
    amp = 1.0 / r ** (beta / 2.0)
    amp[0, 0] = 0.0
    phase = rng.uniform(0, 2 * np.pi, (size, size))
    field = np.fft.ifft2(amp * np.exp(1j * phase)).real
    field -= field.min()
    field /= field.max()
    return field.astype(np.float32)


def upscale(a, size):
    a = np.where(np.abs(a) < 1e-6, 0.0, a).astype(np.float32)   # PIL's float resize returns NaN on denormals
    im = Image.fromarray(a, mode='F').resize((size, size), Image.BILINEAR)
    return np.nan_to_num(np.asarray(im, dtype=np.float32))


def make_terrain(seed, islands, spread, size_px, ruggedness, peak, style="landmass"):
    """style: 'landmass' (long chained bodies with bays and islets), 'archipelago' (many small ones),
    'islands' (one warped ellipse each). Mirrors mapgen.js."""
    rng = np.random.default_rng(seed)
    py_rng = random.Random(seed)
    S = 1024                                       # work resolution, upscaled to 4096
    k = N // S
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    LIM = (PLAY_RADIUS_PX - 25) / k                # keep every lobe inside the editor grid (in 1024-grid cells)
    lobes, masses = [], []

    def clash(cx, cy, r):
        return any(math.hypot(cx - l["cx"], cy - l["cy"]) < (r + l["rad"]) * 0.75 for l in lobes)

    if style == "islands":
        for _ in range(islands):
            for _try in range(200):
                ang = py_rng.uniform(0, 2 * math.pi)
                dist = py_rng.uniform(0.15, 1.0) * spread / k
                cx, cy = S / 2 + dist * math.cos(ang), S / 2 + dist * math.sin(ang)
                rad = py_rng.uniform(0.5, 1.0) * size_px / k
                if all(math.hypot(cx - c["cx"], cy - c["cy"]) > (rad + c["rad"]) * 0.9 for c in lobes):
                    lobes.append(dict(cx=cx, cy=cy, rad=rad, a=py_rng.uniform(0, math.pi), stretch=py_rng.uniform(1.0, 2.4)))
                    masses.append([lobes[-1]])
                    break
    else:
        big = style == "landmass"
        rad0 = size_px / k * (1.25 if big else 0.6)
        for _m in range(islands):
            placed = None
            for _attempt in range(80):
                ang = py_rng.uniform(0, 2 * math.pi)
                dist = py_rng.uniform(0, 1) * spread / k
                x, y = S / 2 + dist * math.cos(ang), S / 2 + dist * math.sin(ang)
                d = py_rng.uniform(0, 2 * math.pi)
                n = py_rng.randint(4, 7) if big else py_rng.randint(2, 4)
                chain = []
                for j in range(n):
                    r = rad0 * py_rng.uniform(0.55, 1.0)
                    if j > 0:
                        d += py_rng.uniform(-0.8, 0.8)
                        step = (chain[j - 1]["rad"] + r) * py_rng.uniform(0.45, 0.7)
                        x += math.cos(d) * step
                        y += math.sin(d) * step
                    dd = math.hypot(x - S / 2, y - S / 2)
                    maxd = max(4, LIM - r * 1.35)
                    if dd > maxd:
                        f = maxd / dd
                        x, y = S / 2 + (x - S / 2) * f, S / 2 + (y - S / 2) * f
                        d += math.pi / 2                       # turn away from the edge
                    chain.append(dict(cx=x, cy=y, rad=r, a=py_rng.uniform(0, math.pi), stretch=py_rng.uniform(1.0, 1.7)))
                if all(not clash(l["cx"], l["cy"], l["rad"]) for l in chain):
                    placed = chain
                    break
            if placed:
                lobes.extend(placed)
                masses.append(placed)
        for _k in range(max(3, len(masses) * 3) if big else 0):          # small islets just off the coasts
            if not lobes:
                break
            l = lobes[py_rng.randrange(len(lobes))]
            ang = py_rng.uniform(0, 2 * math.pi)
            d = l["rad"] * py_rng.uniform(1.5, 2.4)
            r = rad0 * py_rng.uniform(0.12, 0.28)
            cx, cy = l["cx"] + d * math.cos(ang), l["cy"] + d * math.sin(ang)
            if math.hypot(cx - S / 2, cy - S / 2) + r * 1.35 <= LIM and not clash(cx, cy, r):
                lobes.append(dict(cx=cx, cy=cy, rad=r, a=py_rng.uniform(0, math.pi), stretch=py_rng.uniform(1.0, 1.5)))

    wxn = fractal_noise(S, 2.4, rng)
    wyn = fractal_noise(S, 2.4, rng)
    base = np.zeros((S, S), np.float32)
    for l in lobes:
        # elongated, rotated lobe with a domain-warped outline so coasts are irregular
        ca, sa, amp = math.cos(l["a"]), math.sin(l["a"]), l["rad"] * 0.9
        R = int(math.ceil(l["rad"] * max(1.0, l["stretch"]) + amp * 0.5)) + 2
        y0, y1 = max(0, int(math.floor(l["cy"] - R))), min(S - 1, int(math.ceil(l["cy"] + R)))
        x0, x1 = max(0, int(math.floor(l["cx"] - R))), min(S - 1, int(math.ceil(l["cx"] + R)))
        sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        dx = xx[sl] - l["cx"] + (wxn[sl] - 0.5) * amp
        dy = yy[sl] - l["cy"] + (wyn[sl] - 0.5) * amp
        u = (dx * ca + dy * sa) / l["stretch"]
        v = -dx * sa + dy * ca
        d = np.sqrt(u * u + v * v) / l["rad"]
        val = np.where(d < 1, np.clip(1.0 - d, 0, 1) ** 0.7, 0)
        base[sl] = np.maximum(base[sl], val)

    detail = fractal_noise(S, 2.6, rng)
    ridge = 1.0 - np.abs(fractal_noise(S, 2.2, rng) * 2 - 1)           # ridged noise for mountain spines
    fine = upscale(fractal_noise(S, 2.2, rng), N)
    inland = np.clip(base * 1.6, 0, 1)                                    # roughness only where there is land
    if style == "islands":
        f = base * (0.55 + 0.9 * ruggedness * (detail - 0.2) + 0.5 * ruggedness * (ridge - 0.5) * inland) - 0.05
        land_s = np.where(base > 0.04, np.clip(f, 0, None), 0).astype(np.float32)
    else:
        coast = fractal_noise(S, 2.0, rng)                                # carves bays and peninsulas
        z = (coast - coast.mean()) / max(1e-9, coast.std())
        e = base + z * (0.16 * (0.6 + 0.8 * ruggedness)) - 0.22
        mult = np.maximum(0.2, 0.55 + 0.9 * ruggedness * (detail - 0.2) + 0.5 * ruggedness * (ridge - 0.5) * inland)
        # signed field (positive land, negative sea) so the 4x upscale places the coast between cells
        land_s = np.where(base > 0.02, np.where(e > 0, e * mult, np.maximum(e, -0.3)), -0.3).astype(np.float32)
    land = upscale(land_s, N)
    land = np.where(land > 0, np.clip(land + (fine - 0.5) * 0.03, 0, None), 0).astype(np.float32)
    h = land / max(float(land.max()), 1e-6)
    h = (h ** 0.9 * peak).astype(np.uint16)
    h[(h == 0) & (land > 0)] = 1                  # keep a thin beach at the very edge
    return h, masses


# ---------- node graph ----------
class Graph:
    def __init__(self, name):
        self.name = name
        self.blocks = []
        self.used = set()
        self.node_codes = []

    def _code(self, rng):
        while True:
            c = rng.randint(1_000_000, 2_100_000_000)
            if c not in self.used:
                self.used.add(c)
                return str(c)

    @staticmethod
    def _params(d):
        return {"parameters": [{"name": k, "value": str(v), "_color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}} for k, v in d.items()]}

    def node(self, rng, ntype, px, py, rot=0.0, **props):
        """px, py in terrain pixels. Returns the node code."""
        X = (px - N / 2) * UNITS_PER_PX
        Y = (py - N / 2) * UNITS_PER_PX
        code = self._code(rng)
        self.node_codes.append(code)
        d = {"Type": "Node", "NodeType": ntype, "Code": code, "Orientation": f"X{X:.2f} Y{Y:.2f} R{rot:.2f}"}
        d.update(props)
        self.blocks.append(self._params(d))
        return code

    def link(self, a, b, kind):
        self.blocks.append(self._params({"Type": "Link", "From": a, "To": b, "Link": kind}))

    GROUP_SLOTS = 64   # the game writes every group as 4 header params + 64 "Node" slots, unused ones empty

    def to_json(self, date, time):
        # A Group block lists the code of every node it contains. Without it the editor builds the nodes
        # but they belong to no group, and loading dies with a NullReferenceException.
        codes = self.node_codes
        chunks = [codes[i:i + self.GROUP_SLOTS] for i in range(0, max(len(codes), 1), self.GROUP_SLOTS)]
        for i, chunk in enumerate(chunks):
            params = [("Type", "Group"), ("Name", "Default" if i == 0 else f"Group {i + 1}"), ("Hide", "False"), ("Solo", "False")]
            params += [("Node", c) for c in chunk] + [("Node", "")] * (self.GROUP_SLOTS - len(chunk))
            self.blocks.append({"parameters": [{"name": k, "value": v} for k, v in params]})
        return json.dumps({"type": "Custom Level", "name": self.name, "date": date, "time": time, "blocks": self.blocks}, indent=2)


def sea_point(h, rng, cx, cy, rmin, rmax, clearance=60, floor=2):
    """Random sea cell with no land within `clearance` px, between rmin and rmax of (cx, cy).
    If no such spot exists the clearance is relaxed in steps rather than silently placing the point on land."""
    for scale in (1.0, 0.75, 0.5, 0.3, 0.15):
        c = max(floor, int(clearance * scale))      # relax in steps, never below `floor` (covers nodes at fixed offsets)
        for _ in range(3000):
            ang = rng.uniform(0, 2 * np.pi)
            r = rng.uniform(rmin, rmax)
            x, y = int(cx + r * np.cos(ang)), int(cy + r * np.sin(ang))
            if c <= x < N - c and c <= y < N - c and not h[y - c:y + c + 1, x - c:x + c + 1].any():
                return x, y
    raise RuntimeError("Not enough open water for the mission. Use fewer or smaller landmasses, or a larger spread.")


def build_graph(name, h, centres, rng, calibrate, difficulty):
    g = Graph(name)
    cx = cy = N / 2
    # player start: open water near the middle of the island group
    sx, sy = sea_point(h, rng, cx, cy, 0, 230, clearance=90 if calibrate else 30, floor=72 if calibrate else 30)
    gx, gy = sea_point(h, rng, cx, cy, 130, 260, clearance=40, floor=30)
    start = g.node(rng, "MissionStart", sx, sy, Mission=name, Stars=1, **{"Target Time": "5", "Target Score": "50000", "Combat Heat": "false", "Detection Range": "1"})
    g.node(rng, "Settings", sx + 8, sy + 8, Zoom=1, New="false", **{"Player Boat": 1, "Time of Day": f"{rng.uniform(0.3, 0.7):.5f}", "Weather Intensity": f"{rng.uniform(0, 0.5):.5f}"})
    tele = g.node(rng, "Teleport", sx, sy - 6, rng.uniform(0, 360), **{"Camera Angle": 0, "Dont Reverse Direction": "true", "Camera Distance": 1, "Camera Y": "302.47"})
    g.link(start, tele, "triggered")
    goal = g.node(rng, "Waypoint", gx, gy, Name="None", Statement="Default", Hidden="false", Inverse="false", **{"Bypass Detect": "true", "Detection Range": 0})
    g.link(start, goal, "to")
    t_end = g.node(rng, "Time", gx, gy + 14, Statement="Default", **{"Trigger Time": 5, "Critical": "false", "Special": "false"})
    end = g.node(rng, "MissionEnd", gx, gy + 28, Fail="false", **{"Bypass Detect": "true", "Detection Range": 200})
    g.link(goal, t_end, "triggered")
    g.link(t_end, end, "triggered")
    # enemy waves at sea, each patrolling toward a waypoint near the start
    t_wave = g.node(rng, "Time", sx + 20, sy + 20, Statement="Default", **{"Trigger Time": 1, "Critical": "false", "Special": "false"})
    g.link(start, t_wave, "triggered")
    kinds = [("LightBoat1", 3), ("LightBoat2", 2), ("Destroyer2", 1), ("Destroyer3", 1), ("LightFighter1", 3)]
    n_sp = 3 + difficulty * 2
    for i in range(n_sp):
        name_, count = kinds[rng.randrange(len(kinds)) if difficulty > 1 else rng.randrange(3)]
        ex, ey = sea_point(h, rng, cx, cy, 270, 350, clearance=10)
        wx, wy = sea_point(h, rng, sx, sy, 20, 70, clearance=6)
        sp = g.node(rng, "Spawner", ex, ey, rng.uniform(0, 360), **{"Spawn Name": name_, "Spawn Count": count, "Minimum Gap": 20, "Continuous": "false", "Critical": "false", "Dont Reverse Direction": "true", "Spawn Range": "0.009", "Influence Range": 99, "Spawn Player Distance": 99, "Despawn Player Distance": 99})
        wp = g.node(rng, "Waypoint", wx, wy, Name="None", Statement="Default", Hidden="false", Inverse="false", **{"Bypass Detect": "false", "Detection Range": 0})
        g.link(sp, wp, "from")
        g.link(t_wave, sp, "triggered")
    if calibrate:
        # four markers at +-10 grid units (2500 world units, 78 px) from the player start
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            g.node(rng, "Waypoint", sx + dx * 70, sy + dy * 70, Name="None", Statement="Default", Hidden="false", Inverse="false", **{"Bypass Detect": "true", "Detection Range": 0})
    return g, (sx, sy), (gx, gy)


# ---------- preview ----------
def render_preview(h, start, goal, path, size=512):
    img = np.zeros((N, N, 3), np.uint8)
    img[:] = (20, 60, 120)
    land = h > 0
    t = np.clip(h / max(1, h.max()), 0, 1)
    img[land] = np.stack([60 + 150 * t[land], 120 + 100 * t[land], 50 + 100 * t[land]], 1).astype(np.uint8)
    # crop to land bounds with margin, square
    ys, xs = np.nonzero(land)
    cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
    half = int(max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 * 1.2) + 40
    x0, y0 = max(0, cx - half), max(0, cy - half)
    crop = img[y0:y0 + 2 * half, x0:x0 + 2 * half]
    Image.fromarray(crop).resize((size, size), Image.LANCZOS).save(path)
    return (x0, y0, 2 * half)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--style", choices=["landmass", "archipelago", "islands"], default="landmass", help="landmass: long bodies with bays and islets; archipelago: many small islands; islands: round islands")
    ap.add_argument("--islands", type=int, default=None, help="how many landmasses or islands (default 3, 9 or 6 by style)")
    ap.add_argument("--spread", type=float, default=220, help="how far islands scatter from the centre, in px (32 world units each)")
    ap.add_argument("--island-size", type=float, default=55, help="typical island radius in px")
    ap.add_argument("--ruggedness", type=float, default=0.9)
    ap.add_argument("--peak", type=int, default=4000, help="highest terrain value (sample maps peak at 2500-4700)")
    ap.add_argument("--difficulty", type=int, default=1, choices=[0, 1, 2, 3])
    ap.add_argument("--version", type=int, default=None, help="n in SOURCE_<n>.BCD / SOURCE_<n>_Terrain.BCT (default: one above any SOURCE_<n> already in the output folder, else 1, because the game loads the highest)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--author", default="bc_mapgen")
    ap.add_argument("--calibrate", action="store_true", help="add four marker waypoints on a known square")
    ap.add_argument("--out", default="./generated")
    a = ap.parse_args()

    STYLE_NAMES = {"landmass": "Random Landmasses", "archipelago": "Random Archipelago", "islands": "Random Islands"}
    if a.islands is None:
        a.islands = {"landmass": 3, "archipelago": 9, "islands": 6}[a.style]
    name = a.name or f"{STYLE_NAMES[a.style]} {a.seed}"
    rng = random.Random(a.seed * 7919)
    h, centres = make_terrain(a.seed, a.islands, a.spread, a.island_size, a.ruggedness, a.peak, a.style)
    if not (h > 0).any():
        raise SystemExit("These settings produced no land at all. Use a larger --island-size or lower --ruggedness.")
    g, start, goal = build_graph(name, h, centres, rng, a.calibrate, a.difficulty)

    folder = os.path.join(a.out, name)
    os.makedirs(folder, exist_ok=True)
    if a.version is None:
        # the game loads the highest-numbered SOURCE_<n>; number this save above any the editor left here
        present = [int(m.group(1)) for fn in os.listdir(folder) for m in [re.match(r"SOURCE_(\d+)", fn, re.I)] if m]
        a.version = max(present, default=0) + 1
    bct = f"SOURCE_{a.version}_Terrain.BCT"
    bcd = f"SOURCE_{a.version}.BCD"
    h.astype("<u2").tofile(os.path.join(folder, bct))
    with open(os.path.join(folder, bcd), "wb") as f:
        # the game's own files are gzip'd UTF-8 JSON with a BOM and CRLF newlines
        f.write(gzip.compress(("﻿" + g.to_json("01/10/2026", "12:00").replace("\n", "\r\n")).encode("utf-8"), 9))
    desc = f"{STYLE_NAMES[a.style].replace('Random ', '')}, seed {a.seed}. {len(centres)} {'landmasses' if a.style == 'landmass' else 'islands'}; reach the marker to finish."
    with open(os.path.join(folder, "PreviewData.BCI"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(f"Title: {name}\nAuthor: {a.author}\nDescription: {desc}\n")
    render_preview(h, start, goal, os.path.join(folder, "PreviewImage.png"))

    bcp = os.path.join(a.out, name + ".BCP")
    with zipfile.ZipFile(bcp, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in (bct, bcd, "PreviewData.BCI", "PreviewImage.png"):
            z.write(os.path.join(folder, fn), fn)
    land = (h > 0)
    yy, xx = np.nonzero(land[::4, ::4])
    far = np.hypot(xx * 4 - N / 2, yy * 4 - N / 2) > PLAY_RADIUS_PX
    if far.any():
        print(f"WARNING: {100 * far.mean():.1f}% of land lies outside the +-{PLAY_RADIUS_PX}px play area; lower --spread or --island-size")
    print(f"{name}: {len(centres)} {'landmasses' if a.style == 'landmass' else 'islands'}, land {100 * land.mean():.2f}%, peak {h.max()}")
    sxw, syw = (start[0] - N / 2) * UNITS_PER_PX, (start[1] - N / 2) * UNITS_PER_PX
    print(f"player start px {start} -> world X{sxw:.0f} Y{syw:.0f} -> editor grid ({sxw / GRID_UNIT:.1f}, {syw / GRID_UNIT:.1f})")
    print(f"folder: {os.path.abspath(folder)}\nbcp:    {os.path.abspath(bcp)}")


if __name__ == "__main__":
    main()
