#!/usr/bin/env python3
"""Build the Solomons campaign map for the viewer from YOUR OWN Boat Crew install.

The campaign world is not a loose file. It lives in a Unity addressables bundle
(Boat Crew_Data/StreamingAssets/aa/StandaloneWindows64/world_assets_all_*.bundle) as:
  * one TextAsset, RELEASE_0: gzip'd JSON of type "World" (settlements, patrol routes, island positions, labels)
  * three images per island: <Island>_Coastline (1 px outline), _ShallowSilhouette (filled shallows),
    _TerrainSilhouette (filled land, red channel = height band)

This script reads them (read-only), composites the islands into one downsampled height grid and writes
viewer/data/campaign.json, which `viewer/build.py --data viewer/data` can bundle into a LOCAL copy of the viewer.
That output is derived from the game's assets, so keep it to yourself and do not commit or share it.

    pip install UnityPy numpy Pillow
    python tools/extract_campaign.py --game "D:/Steam/steamapps/common/Boat Crew"

Findings this relies on (measured, see docs/format.md): each island image is centred on its WorldPiece node
at 0.0385 campaign units per image pixel with image-up = world +Y (all 38 settlements land within ~25 px of a
coastline), and the campaign unit is probably a kilometre.
"""
import argparse, base64, glob, gzip, json, os, re, sys

import numpy as np

PIXEL_UNITS = 0.0385      # campaign units per island-image pixel
DOWNSAMPLE = 6            # keep the composite small: 6x fewer pixels per side
PAD = 10                  # campaign units of sea around the outermost island


def pick_bundle(aa_dir):
    """The bundle the game's catalog actually references (older copies can be left behind by updates)."""
    bundles = sorted(glob.glob(os.path.join(aa_dir, 'StandaloneWindows64', 'world_assets_all_*.bundle')))
    if not bundles:
        sys.exit(f'No world_assets_all_*.bundle in {aa_dir}. Is --game the Boat Crew folder?')
    catalog = os.path.join(aa_dir, 'catalog.bin')
    if os.path.exists(catalog):
        data = open(catalog, 'rb').read()
        for b in bundles:
            if os.path.basename(b).encode() in data:
                return b
    return max(bundles, key=os.path.getmtime)


def load_world(bundle):
    try:
        import UnityPy
    except ImportError:
        sys.exit('This needs UnityPy: pip install UnityPy')
    env = UnityPy.load(bundle)
    world, tex = None, {}
    for o in env.objects:
        if o.type.name == 'TextAsset':
            d = o.read()
            if d.m_Name == 'RELEASE_0':
                s = d.m_Script
                raw = s.encode('utf-8', 'surrogateescape') if isinstance(s, str) else bytes(s)
                world = json.loads(gzip.decompress(raw).decode('utf-8-sig'))
        elif o.type.name == 'Texture2D':
            d = o.read()
            if d.m_Name.endswith(('_ShallowSilhouette', '_TerrainSilhouette')):
                tex[d.m_Name] = np.array(d.image)[..., 0]
    if world is None:
        sys.exit('RELEASE_0 not found in the bundle.')
    return world, tex


def params(block):
    return {p['name']: p['value'] for p in block['parameters']}


def composite(world, tex):
    pieces = {}
    for b in world['blocks']:
        d = params(b)
        if d.get('NodeType') == 'WorldPiece':
            m = re.match(r'X(\S+) Y(\S+)', d['Orientation'])
            pieces[d['Piece Name']] = (float(m[1]), float(m[2]))
    ext = []
    for n, (px, py) in pieces.items():
        h, w = tex[f'{n}_TerrainSilhouette'].shape
        ext.append((px - w / 2 * PIXEL_UNITS, px + w / 2 * PIXEL_UNITS, py - h / 2 * PIXEL_UNITS, py + h / 2 * PIXEL_UNITS))
    x0 = min(e[0] for e in ext) - PAD; x1 = max(e[1] for e in ext) + PAD
    y0 = min(e[2] for e in ext) - PAD; y1 = max(e[3] for e in ext) + PAD
    upp = PIXEL_UNITS * DOWNSAMPLE
    W, H = int(np.ceil((x1 - x0) / upp)), int(np.ceil((y1 - y0) / upp))
    out = np.zeros((H, W), np.uint8)          # 0 deep sea, 1 shallows, 2+ land (the island image's height band)
    F = DOWNSAMPLE
    for n, (px, py) in pieces.items():
        ter = tex[f'{n}_TerrainSilhouette']
        shal = tex[f'{n}_ShallowSilhouette'] > 0
        h, w = ter.shape
        hh, ww = (h // F) * F, (w // F) * F
        blk = lambda a, fn: fn(a[:hh, :ww].reshape(hh // F, F, ww // F, F))
        t = blk(ter.astype(np.float32), lambda b: b.max((1, 3)))
        cov = blk((ter > 0).astype(np.float32), lambda b: b.mean((1, 3)))
        s = blk(shal.astype(np.float32), lambda b: b.mean((1, 3))) >= 0.5
        cell = np.zeros(t.shape, np.uint8)
        cell[s] = 1
        land = (cov >= 0.35) | ((t > 0) & (cov >= 0.15))
        cell[land] = np.maximum(2, t[land]).astype(np.uint8)
        ox = int(round((px - w / 2 * PIXEL_UNITS - x0) / upp))
        oy = int(round((y1 - (py + h / 2 * PIXEL_UNITS)) / upp))
        sub = out[oy:oy + cell.shape[0], ox:ox + cell.shape[1]]
        np.maximum(sub, cell[:sub.shape[0], :sub.shape[1]], out=sub)
    return out, dict(w=W, h=H, upp=upp, cwx=(x0 + x1) / 2, cwy=(y0 + y1) / 2)


def slim_nodes(world):
    blocks = []
    for b in world['blocks']:
        d = params(b)
        if d.get('Type') == 'Group':
            continue
        if d.get('NodeType') == 'Patrol':
            d = {k: v for k, v in d.items() if k in ('Type', 'NodeType', 'Code', 'Orientation', 'Locality')}
        blocks.append({'parameters': [{'name': k, 'value': v} for k, v in d.items()]})
    return {'type': 'World', 'name': world.get('name', 'Solomons'), 'blocks': blocks}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', required=True, help='the Boat Crew install folder (the one containing Boat Crew.exe)')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'data', 'campaign.json'))
    a = ap.parse_args()

    aa = os.path.join(a.game, 'Boat Crew_Data', 'StreamingAssets', 'aa')
    bundle = pick_bundle(aa)
    print('reading', os.path.basename(bundle))
    world, tex = load_world(bundle)
    grid, geo = composite(world, tex)
    enc = lambda raw: base64.b64encode(gzip.compress(raw, 9)).decode()
    out = {
        'title': 'Solomons campaign', 'author': 'built-in world',
        'description': "The standard campaign map, rebuilt from the game's island images and world data. Settlement positions come from the game; terrain is downsampled 6x.",
        'file': 'world_assets (built-in)', **geo, 'ysign': -1,
        'terrain': enc(grid.tobytes()),
        'bcd': enc(json.dumps(slim_nodes(world), separators=(',', ':')).encode()),
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    print(f'wrote {os.path.abspath(a.out)}  ({geo["w"]} x {geo["h"]} cells, {int((grid >= 2).sum()):,} land cells)')
    print('Bundle it into a local viewer with: python viewer/build.py --data viewer/data --out dist/index.html')


if __name__ == '__main__':
    main()
