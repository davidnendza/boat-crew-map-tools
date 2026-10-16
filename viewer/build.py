#!/usr/bin/env python3
"""Build the single-file viewer from viewer.template.html, mapgen.js and vendor/jszip.min.js, then syntax-check its script.

    python viewer/build.py                      public build -> docs/index.html (no game data inside)
    python viewer/build.py --data viewer/data --out dist/index.html
                                                local build that also bundles any maps found in viewer/data/
                                                (campaign.json from tools/extract_campaign.py, samples.json).
                                                Keep that output to yourself: it contains game-derived data.

Needs Python 3 and, for the syntax check, node (skipped with a warning if node is missing).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO_URL = 'https://github.com/davidnendza/boat-crew-map-tools'


def read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', help='folder with optional campaign.json / samples.json to bundle (leave out for the public build)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'index.html'))
    ap.add_argument('--repo-url', default=REPO_URL)
    a = ap.parse_args()

    samples = {}
    if a.data:
        for name in ('campaign.json', 'samples.json'):
            path = os.path.join(a.data, name)
            if os.path.exists(path):
                data = json.loads(read(path))
                samples.update({'campaign': data} if name == 'campaign.json' else data)
    html = (read(HERE, 'viewer.template.html')
            .replace('/*__JSZIP__*/', read(HERE, 'vendor', 'jszip.min.js'))    # vendored so the page works offline
            .replace('/*__MAPGEN__*/', read(HERE, 'mapgen.js'))
            .replace('__SAMPLES__', json.dumps(samples, separators=(',', ':')))
            .replace('__REPO_URL__', a.repo_url))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print(f'built {os.path.relpath(a.out, ROOT)} ({len(html):,} bytes, {len(samples)} bundled map(s))')

    if not shutil.which('node'):
        print('warning: node not found, skipped the script syntax check')
        return
    for i, script in enumerate(re.findall(r'<script>(.*?)</script>', html, re.S)):   # the vendored JSZip block and the app block
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(script)
        r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True)
        os.unlink(f.name)
        if r.returncode:
            print(f'SYNTAX ERROR in script block {i + 1}\n' + r.stderr[:3000])
            sys.exit(1)
    print('script syntax ok')


if __name__ == '__main__':
    main()
