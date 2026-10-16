# Boat Crew custom level format

Notes on the files the Boat Crew level editor reads and writes, worked out by inspecting levels and by opening generated ones in the editor. This is unofficial and incomplete. Where something was measured or tested it says so; everything else is inference.

## Where levels live

Paths are relative to the game's `Boat Crew_Data/GameData`.

| Folder | What it holds |
| --- | --- |
| `LevelEditor/<name>/` | Levels made or placed locally. A level put here shows up in the **level editor** list (not the "user levels" list). This is where the generator output is meant to go. |
| `Workshop/CustomLevel/<id>/` | Unpacked Steam Workshop levels. Steam manages this folder, so don't write there. |

A Workshop download is a single `.BCP` file, which is a plain zip of the same files as a level folder.

## Files in a level folder

| File | Contents |
| --- | --- |
| `SOURCE_<n>_Terrain.BCT` | Raw little-endian `uint16` heightmap, 4096 × 4096, no header, so always exactly 33,554,432 bytes. `0` is sea, anything above is land height. |
| `SOURCE_<n>.BCD` | gzip of UTF-8 JSON (with a byte order mark and CRLF newlines): the node graph. |
| `PreviewData.BCI` | Text: `Title:`, `Author:` and `Description:` lines. |
| `PreviewImage.png` | Thumbnail. |
| `SOURCE_<n>_LoadoutCraft.BCS`, `SOURCE_<n>_LoadoutCrew.BCS` | Optional. gzip JSON "Game Save" holding the player boat loadout. The generator doesn't write these. |

`n` is a save counter. The editor writes a new `SOURCE_<n+1>.BCD` each time you save, and the terrain file is found separately, so the two numbers can differ. The highest-numbered `.BCD` wins, which means a stray empty save from the editor will shadow a generated file. Delete it.

## The node graph (`.BCD`)

```json
{"type": "Custom Level", "name": "...", "date": "...", "time": "...",
 "blocks": [ {"parameters": [ {"name": "Type", "value": "Node"}, ... ]}, ... ]}
```

Every value is a string. A block is either a node, a link or a group, told apart by its `Type` parameter.

- **Node:** `Type=Node`, `NodeType`, `Code` (a unique integer as a string), `Orientation` as `X<f> Y<f> R<degrees>`, then parameters for that type.
- **Link:** `Type=Link`, `From` and `To` (node codes) and `Link` as `to`, `from` or `triggered`. A spawner links to its patrol waypoint with `from`; the start node links to the player's goal waypoint with `to`; everything that fires another node is `triggered`.
- **Group:** `Type=Group`, `Name`, `Hide`, `Solo`, then exactly 64 `Node` parameters. The first ones are the codes of the nodes in the group and the rest are empty strings.

**The group block is required.** A level whose group lists no node codes makes the editor build every node and then throw a `NullReferenceException` in its level builder, so the terrain and nodes never appear and "save and play" runs on an empty level. This was found the hard way and fixed by listing the codes. A level with more than 64 nodes probably needs more than one group; that is untested.

### Node types and the parameters seen

| `NodeType` | Parameters |
| --- | --- |
| `MissionStart` | Mission, Stars, Target Time, Target Score, Combat Heat, Detection Range |
| `Settings` | Zoom, New, Player Boat, Time of Day, Weather Intensity |
| `Teleport` | Camera Angle, Dont Reverse Direction, Camera Distance, Camera Y |
| `Waypoint` | Name, Statement, Hidden, Inverse, Bypass Detect, Detection Range |
| `Time` | Statement, Trigger Time, Critical, Special |
| `MissionEnd` | Fail, Bypass Detect, Detection Range |
| `Spawner` | Spawn Name, Spawn Count, Minimum Gap, Continuous, Critical, Dont Reverse Direction, Spawn Range, Influence Range, Spawn Player Distance, Despawn Player Distance |
| `Clear` | Statement, Clear Spawners, Clear Alive, Clear Range |
| `Formation` | Spacing, Detection Range |
| `Structure` | Team, Tier, Seed, Anchor Range |
| `Alert` | Alert Level, Detection Range |
| `Dialog` | Message, Break (a `Message` such as `CaptainOnly` is an editor command) |

`Spawn Name` values seen in other people's levels include `LightBoat1`, `LightBoat2`, `Destroyer2`, `Destroyer3`, `LightFighter1`, `MediumFighter1` and `GroundTarget9`. The editor's toolbar calls some of these nodes by other names (Start is `MissionStart`, Timer is `Time`, End is `MissionEnd`, Eliminate is probably `Clear`).

## Scale and coordinates

Measured by generating levels and opening them in the editor:

- **1 world unit is 1 metre.** The editor says so in a corner panel.
- **The editor's grid labels are world units divided by 250.**
- **The terrain is about 32 world units per pixel**, with the origin at the middle of the 4096 × 4096 grid and Y not flipped: `px = 2048 + X / 32`, `py = 2048 + Y / 32`. Two isolated islands predicted at grid (16.4, 7.8) and (-20.6, 11.0) appeared at about (16, 8) and (-22, 10.5), so this is good to a few percent. It is not read from the game.
- The terrain therefore covers about 131 km, but the editor's grid shows only about −50 to +50 labels, roughly the middle 800 pixels. The generator keeps everything within 375 px of the centre so it all fits.

## What has and hasn't been tested

Tested in the game (round-island levels): a generated level in `LevelEditor/` appears in the editor list, loads with its islands once the group block is right, and "save and play" puts the player's boat at sea. Not tested: landmass and archipelago levels in the game (checked structurally only), that enemy waves arrive, that the goal ends the mission, levels with more than 64 nodes, and any grid size other than 4096 × 4096.

## The campaign map (for the viewer)

The campaign is an open world. The game builds a local area like a custom level from wherever you are. The world is stored in an addressables bundle (`StreamingAssets/aa/StandaloneWindows64/world_assets_all_*.bundle`) as a `RELEASE_0` text asset (the same gzip-JSON container, type `World`, with settlements, patrol routes, island positions and labels) plus three images per island. `tools/extract_campaign.py` reads these from your own install; this repository ships none of that data. Campaign coordinates are a different system: each island image is centred on its position at 0.0385 units per pixel, and a unit is probably a kilometre.
