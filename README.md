# Boat Crew map tools

A random level generator and map viewer for [Boat Crew](https://store.steampowered.com/app/1633370/). It makes custom levels you can open in the game's level editor: landmasses with bays and peninsulas, archipelagos, or round islands, with a player start, a goal and timed enemy waves already wired up.

<p>
  <img src="docs/example-landmass.png" width="300" alt="A generated landmass level">
  <img src="docs/example-archipelago.png" width="300" alt="A generated archipelago level">
</p>

> Unofficial fan project, not affiliated with the developer. It contains no game assets.

## Try it in the browser

Open `docs/index.html` in Chrome or Edge (or the hosted copy, if this repository has GitHub Pages turned on). Press **Random map**, tweak the options, then **Download .zip** and unzip it into the game's `GameData/LevelEditor` folder. **Save to folder** writes the files there directly in browsers that allow it (Chrome and Edge; use the zip if yours refuses). No install, and nothing leaves your machine.

The viewer also opens existing levels (`.BCP` files, or the files from a level folder) and draws the terrain with every node, link and spawner on top, which is handy for checking a level before you load it.

## Put a level in the game

A level is a folder of four files. Put it here, then open the game's level editor and look for it in the list:

```
<Boat Crew install>/Boat Crew_Data/GameData/LevelEditor/<map name>/
    SOURCE_1_Terrain.BCT
    SOURCE_1.BCD
    PreviewData.BCI
    PreviewImage.png
```

It shows up in the **level editor** list, not the user levels list. From there you can edit it or use "save and play". If you re-save in the editor it writes a new `SOURCE_2.BCD`; the highest number is the one the game loads.

## Command line

The Python script makes the same kind of level and also writes a `.BCP`. It needs Python 3, `numpy` and `Pillow`.

```
pip install numpy Pillow
python tools/bc_mapgen.py --seed 7 --style landmass --out ./generated
```

| Option | Meaning |
| --- | --- |
| `--style` | `landmass` (default: long bodies with bays and islets), `archipelago` (many small islands) or `islands` (round islands) |
| `--islands` | How many bodies (default 3, 9 or 6 by style) |
| `--island-size` | Typical radius in pixels (default 55; one pixel is about 32 m) |
| `--spread` | How far bodies scatter from the centre, in pixels (default 220) |
| `--ruggedness`, `--peak` | How rough the coasts and terrain are, and the highest point |
| `--difficulty` | 0 to 3: more enemy spawners and tougher boats |
| `--calibrate` | Adds four marker waypoints around the player start, to check the scale in the editor |
| `--seed` | The same seed gives the same map |

Everything stays inside the area the editor's grid shows. If you pack in too much land the generator stops with "Not enough open water for the mission" rather than putting nodes on land.

The browser version is a port of this script. The design and scale are the same, but it has its own random numbers, so the same seed gives a similar map, not an identical one.

## How well does it work?

Tested in the game, with the round-island style: the level appears in the editor list, loads with its islands, and "save and play" starts you at sea. **Not tested:** the landmass and archipelago styles in the game (they are only checked structurally by the test scripts), that the enemy waves arrive, and that the goal ends the mission. The scale (about 32 world units per pixel) was measured from screenshots and is good to a few percent. Details and what's still unknown are in [docs/format.md](docs/format.md), which also documents the level file format, including the one thing that will bite anyone writing these files by hand (the group block).

## The campaign map

The default viewer in this repository bundles no game maps. If you own the game you can build the Solomons campaign map from your own install and view it locally:

```
pip install UnityPy numpy Pillow
python tools/extract_campaign.py --game "D:/Steam/steamapps/common/Boat Crew"
python viewer/build.py --data viewer/data --out dist/index.html
```

`dist/index.html` then includes the campaign map with its settlements and patrol routes. It is derived from the game's assets, so keep it to yourself.

## Development

```
python viewer/build.py          # rebuilds docs/index.html from viewer/viewer.template.html + viewer/mapgen.js
node tests/test_mapgen.js       # browser generator checks
python tests/check_generated.py # command-line generator checks
```

`viewer/mapgen.js` is the browser generator and `tools/bc_mapgen.py` the Python one. If you change the island design, change both. The viewer is a single self-contained HTML file; it loads [JSZip](https://stuk.github.io/jszip/) from a CDN for the zip export.

## Credits and licence

MIT, see [LICENSE](LICENSE). Boat Crew is by Tabbing Tabby. The level format notes come from inspecting levels and from testing generated ones in the game's own editor.
