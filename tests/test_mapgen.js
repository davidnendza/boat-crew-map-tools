// Node test for viewer/mapgen.js. Run: node tests/test_mapgen.js
const fs = require('fs'), path = require('path'), crypto = require('crypto');
eval(fs.readFileSync(path.join(__dirname, '..', 'viewer', 'mapgen.js'), 'utf8') + '; globalThis.BCG = BCG;');

const N = 4096;
const params = (b) => Object.fromEntries(b.parameters.map((x) => [x.name, x.value]));
let failures = 0;
const check = (ok, msg) => { if (!ok) { failures++; console.log('  FAIL: ' + msg); } };

(async () => {
  for (const style of ['landmass', 'archipelago', 'islands']) {
    for (const seed of [1, 2, 3]) {
      const label = `${style} seed ${seed}`;
      const r = await BCG.generate({ style, seed, calibrate: seed % 2 === 0 }, () => {});
      const blocks = r.graph.blocks.map(params);
      const nodes = blocks.filter((p) => p.Type === 'Node'), links = blocks.filter((p) => p.Type === 'Link');
      const codes = new Set(nodes.map((p) => p.Code));
      const group = r.graph.blocks.filter((b) => b.parameters[0].value === 'Group')[0].parameters;
      const listed = group.filter((p) => p.name === 'Node' && p.value).map((p) => p.value);
      let onLand = 0;
      for (const p of nodes) {
        const m = /X(\S+) Y(\S+)/.exec(p.Orientation);
        if (r.h[Math.trunc(N / 2 + +m[2] / BCG.UNITS_PER_PX) * N + Math.trunc(N / 2 + +m[1] / BCG.UNITS_PER_PX)]) onLand++;
      }
      check(r.h.length === N * N, `${label}: terrain is ${r.h.length} cells`);
      check(r.landPct > 0.05, `${label}: almost no land (${r.landPct.toFixed(3)}%)`);
      check(r.outsidePct < 0.5, `${label}: ${r.outsidePct.toFixed(1)}% of the land is outside the editor grid`);
      check(onLand === 0, `${label}: ${onLand} node(s) on land`);
      check(codes.size === nodes.length, `${label}: duplicate node codes`);
      check(links.every((p) => codes.has(p.From) && codes.has(p.To)), `${label}: a link points at a missing node`);
      check(group.length === 4 + 64, `${label}: group block has ${group.length} params, expected 68`);
      check(listed.length === nodes.length && listed.every((c) => codes.has(c)), `${label}: group block does not list every node`);
      console.log(`${label}: ${r.centres} bodies, land ${r.landPct.toFixed(2)}%, ${nodes.length} nodes`);
    }
  }
  // the same seed must give the same map
  const hash = async (o) => crypto.createHash('md5').update(Buffer.from((await BCG.generate(o, () => {})).h.buffer)).digest('hex');
  check((await hash({ seed: 5 })) === (await hash({ seed: 5 })), 'same seed gave different terrain');
  check((await hash({ seed: 5 })) !== (await hash({ seed: 6 })), 'different seeds gave the same terrain');
  console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
