/* Boat Crew random island generator, browser edition.
 *
 * Mirrors bc_mapgen.py: irregular islands in a 4096 x 4096 uint16 heightmap (0 = sea) and a node graph
 * (start, settings, teleport, goal, timed enemy waves) in the custom level format the game's editor loads.
 * It uses its own seeded generator, so a seed gives a similar map, not the same map, as the Python script.
 *
 * Scale (measured by opening generated maps in the level editor):
 *   32 world units per terrain pixel, origin at the map centre, editor grid label = world units / 250.
 * Everything stays within PLAY_RADIUS_PX of the centre so it fits the editor's grid.
 */
const BCG = (() => {
  const N = 4096, S = 1024, K = N / S;
  const UNITS_PER_PX = 32, GRID_UNIT = 250, PLAY_RADIUS_PX = 375;

  // ---------- seeded random numbers (mulberry32) ----------
  function rngFrom(seed) {
    let a = (seed >>> 0) || 1;
    const next = () => {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    return {
      next,
      uniform: (lo, hi) => lo + (hi - lo) * next(),
      int: (lo, hi) => lo + Math.floor(next() * (hi - lo + 1)),
      index: n => Math.floor(next() * n)
    };
  }

  // ---------- FFT noise (1/f^beta, normalised to 0..1) ----------
  const fftPlan = (() => {
    const n = S, cos = new Float64Array(n / 2), sin = new Float64Array(n / 2), rev = new Uint32Array(n);
    for (let i = 0; i < n / 2; i++) { cos[i] = Math.cos(2 * Math.PI * i / n); sin[i] = Math.sin(2 * Math.PI * i / n); }
    const bits = Math.log2(n);
    for (let i = 0; i < n; i++) { let r = 0; for (let b = 0; b < bits; b++) if (i & (1 << b)) r |= 1 << (bits - 1 - b); rev[i] = r; }
    return (re, im) => {
      for (let i = 0; i < n; i++) { const j = rev[i]; if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
      for (let size = 2; size <= n; size <<= 1) {
        const half = size >> 1, step = n / size;
        for (let i = 0; i < n; i += size) {
          for (let j = i, k = 0; j < i + half; j++, k += step) {
            const l = j + half, c = cos[k], s = sin[k];
            const tr = re[l] * c - im[l] * s, ti = re[l] * s + im[l] * c;
            re[l] = re[j] - tr; im[l] = im[j] - ti; re[j] += tr; im[j] += ti;
          }
        }
      }
    };
  })();

  function fractalNoise(beta, rng) {
    const re = new Float64Array(S * S), im = new Float64Array(S * S);
    const freq = i => (i < S / 2 ? i : i - S) / S;
    for (let y = 0; y < S; y++) {
      const fy = freq(y);
      for (let x = 0; x < S; x++) {
        const i = y * S + x;
        if (i === 0) continue;                                     // zero DC term
        const fx = freq(x), amp = Math.pow(Math.sqrt(fx * fx + fy * fy), -beta / 2), ph = rng.next() * 2 * Math.PI;
        re[i] = amp * Math.cos(ph); im[i] = amp * Math.sin(ph);
      }
    }
    for (let y = 0; y < S; y++) fftPlan(re.subarray(y * S, (y + 1) * S), im.subarray(y * S, (y + 1) * S));
    const cr = new Float64Array(S), ci = new Float64Array(S);
    for (let x = 0; x < S; x++) {
      for (let y = 0; y < S; y++) { cr[y] = re[y * S + x]; ci[y] = im[y * S + x]; }
      fftPlan(cr, ci);
      for (let y = 0; y < S; y++) { re[y * S + x] = cr[y]; }
    }
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < re.length; i++) { const v = re[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
    const out = new Float32Array(S * S), span = hi - lo || 1;
    for (let i = 0; i < re.length; i++) out[i] = (re[i] - lo) / span;
    return out;
  }

  const tick = () => new Promise(r => setTimeout(r, 0));          // let the page repaint between heavy steps

  // ---------- terrain ----------
  async function makeTerrain(p, rngPlace, rngNoise, progress) {
    const style = p.style || 'landmass';
    const base = new Float32Array(S * S), lobes = [], masses = [];
    const LIM = (PLAY_RADIUS_PX - 25) / K;                        // keep every lobe inside the editor grid (in 1024-grid cells)
    const clash = (cx, cy, r) => lobes.some(l => Math.hypot(cx - l.cx, cy - l.cy) < (r + l.rad) * 0.75);
    if (style === 'islands') {
      // one warped ellipse per island
      for (let i = 0; i < p.islands; i++) {
        for (let t = 0; t < 200; t++) {
          const ang = rngPlace.uniform(0, 2 * Math.PI), dist = rngPlace.uniform(0.15, 1.0) * p.spread / K;
          const cx = S / 2 + dist * Math.cos(ang), cy = S / 2 + dist * Math.sin(ang), rad = rngPlace.uniform(0.5, 1.0) * p.islandSize / K;
          if (lobes.every(c => Math.hypot(cx - c.cx, cy - c.cy) > (rad + c.rad) * 0.9)) {
            lobes.push({ cx, cy, rad, a: rngPlace.uniform(0, Math.PI), stretch: rngPlace.uniform(1.0, 2.4) });
            masses.push([lobes[lobes.length - 1]]);
            break;
          }
        }
      }
    } else {
      // landmasses: a chain of overlapping lobes wandering across the map, so bodies are long, bent and lumpy
      const big = style === 'landmass', rad0 = p.islandSize / K * (big ? 1.25 : 0.6);
      for (let m = 0; m < p.islands; m++) {
        let placed = null;
        for (let attempt = 0; attempt < 80 && !placed; attempt++) {
          const ang = rngPlace.uniform(0, 2 * Math.PI), dist = rngPlace.uniform(0, 1) * p.spread / K;
          let x = S / 2 + dist * Math.cos(ang), y = S / 2 + dist * Math.sin(ang), dir = rngPlace.uniform(0, 2 * Math.PI);
          const n = big ? rngPlace.int(4, 7) : rngPlace.int(2, 4), chain = [];
          for (let k = 0; k < n; k++) {
            const r = rad0 * rngPlace.uniform(0.55, 1.0);
            if (k > 0) {
              dir += rngPlace.uniform(-0.8, 0.8);
              const step = (chain[k - 1].rad + r) * rngPlace.uniform(0.45, 0.7);
              x += Math.cos(dir) * step; y += Math.sin(dir) * step;
            }
            const dd = Math.hypot(x - S / 2, y - S / 2), maxd = Math.max(4, LIM - r * 1.35);
            if (dd > maxd) { const f = maxd / dd; x = S / 2 + (x - S / 2) * f; y = S / 2 + (y - S / 2) * f; dir += Math.PI / 2; }   // turn away from the edge
            chain.push({ cx: x, cy: y, rad: r, a: rngPlace.uniform(0, Math.PI), stretch: rngPlace.uniform(1.0, 1.7) });
          }
          if (chain.every(l => !clash(l.cx, l.cy, l.rad))) placed = chain;
        }
        if (placed) { lobes.push(...placed); masses.push(placed); }
      }
      // small islets just off the coasts
      for (let k = 0, n = big ? Math.max(3, masses.length * 3) : 0; k < n && lobes.length; k++) {
        const l = lobes[rngPlace.index(lobes.length)], ang = rngPlace.uniform(0, 2 * Math.PI), d = l.rad * rngPlace.uniform(1.5, 2.4), r = rad0 * rngPlace.uniform(0.12, 0.28);
        const cx = l.cx + d * Math.cos(ang), cy = l.cy + d * Math.sin(ang);
        if (Math.hypot(cx - S / 2, cy - S / 2) + r * 1.35 <= LIM && !clash(cx, cy, r)) lobes.push({ cx, cy, rad: r, a: rngPlace.uniform(0, Math.PI), stretch: rngPlace.uniform(1.0, 1.5) });
      }
    }
    progress('Shaping coastlines');
    await tick();
    const wxn = fractalNoise(2.4, rngNoise), wyn = fractalNoise(2.4, rngNoise);
    for (const l of lobes) {
      const ca = Math.cos(l.a), sa = Math.sin(l.a), amp = l.rad * 0.9, R = Math.ceil(l.rad * Math.max(1, l.stretch) + amp * 0.5) + 2;
      const y0 = Math.max(0, Math.floor(l.cy - R)), y1 = Math.min(S - 1, Math.ceil(l.cy + R)), x0 = Math.max(0, Math.floor(l.cx - R)), x1 = Math.min(S - 1, Math.ceil(l.cx + R));
      for (let y = y0; y <= y1; y++) {
        for (let x = x0; x <= x1; x++) {
          const i = y * S + x, dx = x - l.cx + (wxn[i] - 0.5) * amp, dy = y - l.cy + (wyn[i] - 0.5) * amp;
          const u = (dx * ca + dy * sa) / l.stretch, v = -dx * sa + dy * ca;
          const d = Math.sqrt(u * u + v * v) / l.rad;
          if (d < 1) { const val = Math.pow(1 - d, 0.7); if (val > base[i]) base[i] = val; }
        }
      }
    }
    progress('Adding mountains');
    await tick();
    const detail = fractalNoise(2.6, rngNoise), ridgeN = fractalNoise(2.2, rngNoise), fine = fractalNoise(2.2, rngNoise);
    const rug = p.ruggedness, landS = new Float32Array(S * S), rowLand = new Uint8Array(S);
    let coast = null, cMean = 0, cStd = 1;
    if (style !== 'islands') {
      // coast noise, standardised, carves bays and peninsulas into the lobe footprint
      coast = fractalNoise(2.0, rngNoise);
      let s1 = 0, s2 = 0; for (let i = 0; i < coast.length; i++) { s1 += coast[i]; s2 += coast[i] * coast[i]; }
      cMean = s1 / coast.length; cStd = Math.sqrt(Math.max(1e-9, s2 / coast.length - cMean * cMean));
    }
    const carve = 0.16 * (0.6 + 0.8 * rug);
    for (let y = 0; y < S; y++) {
      for (let x = 0; x < S; x++) {
        const i = y * S + x, b = base[i];
        const ridge = 1 - Math.abs(ridgeN[i] * 2 - 1), inland = Math.min(1, b * 1.6);
        if (style === 'islands') {
          if (b > 0.04) {
            const f = b * (0.55 + 0.9 * rug * (detail[i] - 0.2) + 0.5 * rug * (ridge - 0.5) * inland) - 0.05;
            if (f > 0) { landS[i] = f; rowLand[y] = 1; }
          }
        } else {
          // signed field: positive is land, negative is sea. Keeping the sea side lets the 4x upscale place the
          // coastline between cells instead of snapping to them.
          if (b > 0.02) {
            const e = b + ((coast[i] - cMean) / cStd) * carve - 0.22;
            if (e > 0) {
              const mult = Math.max(0.2, 0.55 + 0.9 * rug * (detail[i] - 0.2) + 0.5 * rug * (ridge - 0.5) * inland);
              landS[i] = e * mult; rowLand[y] = 1;
            } else landS[i] = Math.max(e, -0.3);
          } else landS[i] = -0.3;
        }
      }
    }
    // bilinear upscale 1024 -> 4096, with fine noise added on land
    const X0 = new Int32Array(N), X1 = new Int32Array(N), TX = new Float32Array(N);
    for (let ox = 0; ox < N; ox++) {
      const fx = (ox + 0.5) / K - 0.5, x0 = Math.floor(fx);
      X0[ox] = Math.max(0, Math.min(S - 1, x0)); X1[ox] = Math.max(0, Math.min(S - 1, x0 + 1)); TX[ox] = fx - x0;
    }
    const valAt = (ox, oy, y0, y1, ty) => {
      const r0 = y0 * S, r1 = y1 * S, xa = X0[ox], xb = X1[ox], tx = TX[ox];
      const a = landS[r0 + xa], b = landS[r0 + xb], c = landS[r1 + xa], d = landS[r1 + xb];
      if (a <= 0 && b <= 0 && c <= 0 && d <= 0) return 0;
      const lv = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
      if (lv <= 0) return 0;
      const fv = (fine[r0 + xa] * (1 - tx) + fine[r0 + xb] * tx) * (1 - ty) + (fine[r1 + xa] * (1 - tx) + fine[r1 + xb] * tx) * ty;
      const v = lv + (fv - 0.5) * 0.03;
      return v > 0 ? v : 0;
    };
    const rowInfo = oy => {
      const fy = (oy + 0.5) / K - 0.5, y0 = Math.floor(fy);
      return [Math.max(0, Math.min(S - 1, y0)), Math.max(0, Math.min(S - 1, y0 + 1)), fy - y0];
    };
    progress('Raising terrain');
    await tick();
    let max = 0;
    for (let oy = 0; oy < N; oy++) {
      const [y0, y1, ty] = rowInfo(oy);
      if (!rowLand[y0] && !rowLand[y1]) continue;
      for (let ox = 0; ox < N; ox++) { const v = valAt(ox, oy, y0, y1, ty); if (v > max) max = v; }
    }
    const h = new Uint16Array(N * N);
    for (let oy = 0; oy < N; oy++) {
      const [y0, y1, ty] = rowInfo(oy);
      if (!rowLand[y0] && !rowLand[y1]) continue;
      for (let ox = 0; ox < N; ox++) {
        const v = valAt(ox, oy, y0, y1, ty);
        if (v > 0) { let hh = Math.floor(Math.pow(v / (max || 1), 0.9) * p.peak); if (hh < 1) hh = 1; h[oy * N + ox] = hh; }
      }
    }
    return { h, centres: masses };
  }

  // ---------- open-water lookup ----------
  function makeSeaFinder(h) {
    // 1/4-resolution land mask with a summed-area table, so "is there land within c px" is O(1)
    const P = S + 1, sum = new Int32Array(P * P);
    for (let cy = 0; cy < S; cy++) {
      let rowSum = 0;
      for (let cx = 0; cx < S; cx++) {
        let land = 0;
        for (let dy = 0; dy < K && !land; dy++) { const row = (cy * K + dy) * N + cx * K; for (let dx = 0; dx < K; dx++) if (h[row + dx]) { land = 1; break; } }
        rowSum += land;
        sum[(cy + 1) * P + cx + 1] = sum[cy * P + cx + 1] + rowSum;
      }
    }
    const landIn = (x0, y0, x1, y1) => {                      // inclusive pixel box
      const a = Math.floor(x0 / K), b = Math.floor(y0 / K), c = Math.floor(x1 / K) + 1, d = Math.floor(y1 / K) + 1;
      return sum[d * P + c] - sum[b * P + c] - sum[d * P + a] + sum[b * P + a] > 0;
    };
    return (rng, cx, cy, rmin, rmax, clearance, floor = 2) => {
      // the clearance relaxes in steps, but never below `floor`, which covers the nodes placed at fixed offsets from this point
      for (const scale of [1.0, 0.75, 0.5, 0.3, 0.15]) {
        const c = Math.max(floor, Math.floor(clearance * scale));
        for (let t = 0; t < 3000; t++) {
          const ang = rng.uniform(0, 2 * Math.PI), r = rng.uniform(rmin, rmax);
          const x = Math.trunc(cx + r * Math.cos(ang)), y = Math.trunc(cy + r * Math.sin(ang));
          if (c <= x && x < N - c && c <= y && y < N - c && !landIn(x - c, y - c, x + c, y + c)) return [x, y];
        }
      }
      throw new Error('Not enough open water for the mission. Use fewer or smaller landmasses, or a larger spread.');
    };
  }

  // ---------- node graph ----------
  class Graph {
    constructor(name) { this.name = name; this.blocks = []; this.used = new Set(); this.codes = []; }
    code(rng) { for (;;) { const c = rng.int(1000000, 2100000000); if (!this.used.has(c)) { this.used.add(c); return String(c); } } }
    node(rng, type, px, py, rot, props) {
      const X = (px - N / 2) * UNITS_PER_PX, Y = (py - N / 2) * UNITS_PER_PX, code = this.code(rng);
      this.codes.push(code);
      const d = { Type: 'Node', NodeType: type, Code: code, Orientation: `X${X.toFixed(2)} Y${Y.toFixed(2)} R${(rot || 0).toFixed(2)}`, ...props };
      this.blocks.push({ parameters: Object.entries(d).map(([name, value]) => ({ name, value: String(value), _color: { r: 1.0, g: 1.0, b: 1.0, a: 1.0 } })) });
      return code;
    }
    link(a, b, kind) {
      this.blocks.push({ parameters: [['Type', 'Link'], ['From', a], ['To', b], ['Link', kind]].map(([name, value]) => ({ name, value, _color: { r: 1.0, g: 1.0, b: 1.0, a: 1.0 } })) });
    }
    // A Group block lists the code of every node in it, padded to 64 slots. Without it the editor builds the
    // nodes but they belong to no group and loading fails with a NullReferenceException.
    finish(date, time) {
      const SLOTS = 64, blocks = this.blocks.slice();
      for (let i = 0, g = 0; i < Math.max(this.codes.length, 1); i += SLOTS, g++) {
        const chunk = this.codes.slice(i, i + SLOTS);
        const params = [['Type', 'Group'], ['Name', g === 0 ? 'Default' : `Group ${g + 1}`], ['Hide', 'False'], ['Solo', 'False']]
          .concat(chunk.map(c => ['Node', c]), Array(SLOTS - chunk.length).fill(['Node', '']));
        blocks.push({ parameters: params.map(([name, value]) => ({ name, value })) });
      }
      return { type: 'Custom Level', name: this.name, date, time, blocks };
    }
  }

  function buildGraph(name, seaPoint, rng, calibrate, difficulty) {
    const g = new Graph(name), cx = N / 2, cy = N / 2;
    const [sx, sy] = seaPoint(rng, cx, cy, 0, 230, calibrate ? 90 : 30, calibrate ? 72 : 30);
    const [gx, gy] = seaPoint(rng, cx, cy, 130, 260, 40, 30);
    const start = g.node(rng, 'MissionStart', sx, sy, 0, { Mission: name, Stars: 1, 'Target Time': '5', 'Target Score': '50000', 'Combat Heat': 'false', 'Detection Range': '1' });
    g.node(rng, 'Settings', sx + 8, sy + 8, 0, { Zoom: 1, New: 'false', 'Player Boat': 1, 'Time of Day': rng.uniform(0.3, 0.7).toFixed(5), 'Weather Intensity': rng.uniform(0, 0.5).toFixed(5) });
    const tele = g.node(rng, 'Teleport', sx, sy - 6, rng.uniform(0, 360), { 'Camera Angle': 0, 'Dont Reverse Direction': 'true', 'Camera Distance': 1, 'Camera Y': '302.47' });
    g.link(start, tele, 'triggered');
    const goal = g.node(rng, 'Waypoint', gx, gy, 0, { Name: 'None', Statement: 'Default', Hidden: 'false', Inverse: 'false', 'Bypass Detect': 'true', 'Detection Range': 0 });
    g.link(start, goal, 'to');
    const tEnd = g.node(rng, 'Time', gx, gy + 14, 0, { Statement: 'Default', 'Trigger Time': 5, Critical: 'false', Special: 'false' });
    const end = g.node(rng, 'MissionEnd', gx, gy + 28, 0, { Fail: 'false', 'Bypass Detect': 'true', 'Detection Range': 200 });
    g.link(goal, tEnd, 'triggered'); g.link(tEnd, end, 'triggered');
    const tWave = g.node(rng, 'Time', sx + 20, sy + 20, 0, { Statement: 'Default', 'Trigger Time': 1, Critical: 'false', Special: 'false' });
    g.link(start, tWave, 'triggered');
    const kinds = [['LightBoat1', 3], ['LightBoat2', 2], ['Destroyer2', 1], ['Destroyer3', 1], ['LightFighter1', 3]];
    for (let i = 0; i < 3 + difficulty * 2; i++) {
      const [spawn, count] = kinds[rng.index(difficulty > 1 ? kinds.length : 3)];
      const [ex, ey] = seaPoint(rng, cx, cy, 270, 350, 10), [wx, wy] = seaPoint(rng, sx, sy, 20, 70, 6);
      const sp = g.node(rng, 'Spawner', ex, ey, rng.uniform(0, 360), { 'Spawn Name': spawn, 'Spawn Count': count, 'Minimum Gap': 20, Continuous: 'false', Critical: 'false', 'Dont Reverse Direction': 'true', 'Spawn Range': '0.009', 'Influence Range': 99, 'Spawn Player Distance': 99, 'Despawn Player Distance': 99 });
      const wp = g.node(rng, 'Waypoint', wx, wy, 0, { Name: 'None', Statement: 'Default', Hidden: 'false', Inverse: 'false', 'Bypass Detect': 'false', 'Detection Range': 0 });
      g.link(sp, wp, 'from'); g.link(tWave, sp, 'triggered');
    }
    if (calibrate) {
      for (const [dx, dy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]])
        g.node(rng, 'Waypoint', sx + dx * 70, sy + dy * 70, 0, { Name: 'None', Statement: 'Default', Hidden: 'false', Inverse: 'false', 'Bypass Detect': 'true', 'Detection Range': 0 });
    }
    return { g, start: [sx, sy], goal: [gx, gy] };
  }

  // ---------- entry point ----------
  const DEFAULTS = { seed: 7, style: 'landmass', islands: 3, spread: 220, islandSize: 55, ruggedness: 0.9, peak: 4000, difficulty: 1, calibrate: false };

  async function generate(options, progress = () => {}) {
    const p = { ...DEFAULTS, ...options };
    p.spread = Math.min(p.spread, 330);
    const STYLE_NAMES = { landmass: 'Random Landmasses', archipelago: 'Random Archipelago', islands: 'Random Islands' };
    const name = p.name || `${STYLE_NAMES[p.style] || STYLE_NAMES.landmass} ${p.seed}`;
    const rngPlace = rngFrom(p.seed), rngNoise = rngFrom((p.seed ^ 0x9E3779B9) + 12345), rngGraph = rngFrom(p.seed * 7919);
    const { h, centres } = await makeTerrain(p, rngPlace, rngNoise, progress);
    progress('Placing the mission');
    await tick();
    const { g, start, goal } = buildGraph(name, makeSeaFinder(h), rngGraph, p.calibrate, p.difficulty);
    const now = new Date(), pad = n => String(n).padStart(2, '0');
    const graph = g.finish(`${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()}`, `${pad(now.getHours())}:${pad(now.getMinutes())}`);
    let land = 0, outside = 0;
    for (let y = 0; y < N; y += 2) for (let x = 0; x < N; x += 2) if (h[y * N + x]) { land++; if (Math.hypot(x - N / 2, y - N / 2) > PLAY_RADIUS_PX) outside++; }
    const sxw = (start[0] - N / 2) * UNITS_PER_PX, syw = (start[1] - N / 2) * UNITS_PER_PX;
    return {
      name, params: p, h, graph, centres: centres.length, start, goal,
      nodeCount: g.codes.length, landPct: 100 * land / (N * N / 4), outsidePct: land ? 100 * outside / land : 0,
      startGrid: [sxw / GRID_UNIT, syw / GRID_UNIT],
      description: `${(STYLE_NAMES[p.style] || STYLE_NAMES.landmass).replace('Random ', '')}, seed ${p.seed}. ${centres.length} ${p.style === 'landmass' ? 'landmasses' : 'islands'}; reach the marker to finish.`
    };
  }

  return { generate, DEFAULTS, N, UNITS_PER_PX, GRID_UNIT, PLAY_RADIUS_PX };
})();
