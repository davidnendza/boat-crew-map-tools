#!/usr/bin/env python3
"""Run tools/bc_mapgen.py for each style and validate what it writes. Run: python tests/check_generated.py"""
import glob, gzip, json, os, re, subprocess, sys, tempfile, zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, '..', 'tools', 'bc_mapgen.py')
N = 4096
failures = 0


def check(ok, msg):
    global failures
    if not ok:
        failures += 1
        print('  FAIL:', msg)


def validate(folder, label):
    a = np.fromfile(os.path.join(folder, 'SOURCE_1_Terrain.BCT'), dtype='<u2')
    check(a.size == N * N, f'{label}: terrain has {a.size} cells')
    a = a.reshape(N, N)
    raw = gzip.decompress(open(os.path.join(folder, 'SOURCE_1.BCD'), 'rb').read())
    check(raw.startswith(b'\xef\xbb\xbf'), f'{label}: level file has no BOM')
    j = json.loads(raw.decode('utf-8-sig'))
    ps = [{x['name']: x['value'] for x in b['parameters']} for b in j['blocks']]
    nodes = [p for p in ps if p['Type'] == 'Node']
    codes = {p['Code'] for p in nodes}
    on_land = 0
    for p in nodes:
        m = re.match(r'X(\S+) Y(\S+)', p['Orientation'])
        on_land += a[int(N / 2 + float(m[2]) / 32), int(N / 2 + float(m[1]) / 32)] > 0
    group = [b for b in j['blocks'] if b['parameters'][0]['value'] == 'Group'][0]['parameters']
    listed = [x['value'] for x in group if x['name'] == 'Node' and x['value']]
    check(on_land == 0, f'{label}: {on_land} node(s) on land')
    check(len(codes) == len(nodes), f'{label}: duplicate node codes')
    check(all(p['From'] in codes and p['To'] in codes for p in ps if p['Type'] == 'Link'), f'{label}: dangling link')
    check(len(group) == 68 and sorted(listed) == sorted(codes), f'{label}: group block does not list every node')
    check((a > 0).mean() > 0.0005, f'{label}: almost no land')
    for f in ('PreviewData.BCI', 'PreviewImage.png'):
        check(os.path.exists(os.path.join(folder, f)), f'{label}: missing {f}')
    print(f'{label}: {len(nodes)} nodes, land {100 * (a > 0).mean():.2f}%')


with tempfile.TemporaryDirectory() as out:
    for style in ('landmass', 'archipelago', 'islands'):
        r = subprocess.run([sys.executable, GEN, '--seed', '3', '--style', style, '--calibrate', '--out', out], capture_output=True, text=True)
        check(r.returncode == 0, f'{style}: generator failed\n{r.stderr}')
    for folder in sorted(glob.glob(os.path.join(out, '*', ''))):
        validate(folder, os.path.basename(os.path.dirname(folder)))
    # the game loads the highest SOURCE_<n>, so a rerun into a folder that already has SOURCE_3 must write SOURCE_4
    folder = os.path.join(out, 'Random Landmasses 3')
    open(os.path.join(folder, 'SOURCE_3.BCD'), 'wb').close()
    r = subprocess.run([sys.executable, GEN, '--seed', '3', '--out', out], capture_output=True, text=True)
    check(r.returncode == 0 and os.path.exists(os.path.join(folder, 'SOURCE_4.BCD')) and os.path.exists(os.path.join(folder, 'SOURCE_4_Terrain.BCT')), 'rerun did not number its save above the existing SOURCE_3')
    # no land at all must stop with a message, not a traceback
    r = subprocess.run([sys.executable, GEN, '--seed', '3', '--island-size', '0.01', '--out', os.path.join(out, 'noland')], capture_output=True, text=True)
    check(r.returncode != 0 and 'no land' in (r.stdout + r.stderr) and 'Traceback' not in r.stderr, 'no-land case did not fail cleanly')
    bcps = glob.glob(os.path.join(out, '*.BCP'))
    check(len(bcps) == 3, f'expected 3 .BCP files, found {len(bcps)}')
    for b in bcps:
        names = sorted(zipfile.ZipFile(b).namelist())
        check(names == ['PreviewData.BCI', 'PreviewImage.png', 'SOURCE_1.BCD', 'SOURCE_1_Terrain.BCT'], f'{os.path.basename(b)}: unexpected contents {names}')

print(f'\n{failures} check(s) failed' if failures else '\nall checks passed')
sys.exit(1 if failures else 0)
