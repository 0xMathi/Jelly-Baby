# Fruit Rush — design

Portfolio showcase (category AI) built on scottstts/Jelly-Baby (GPL-3.0). The fork stays GPL-3.0, credit is visible in the UI.

## Game
- 60 s round. Start via button/Enter. Free movement on the (already endless) table, hop, grab/throw still work.
- ~5 fruits live around the jelly (0.14–0.42 m away), respawn on pickup or when left far behind.
- Pickup = jelly centre touches fruit (horizontal distance). Score +1 per fruit.
- Pickup crossfades the jelly to that fruit's flavour (surface colour + absorption, ~0.3 s) and plays a Sonic-ring style "bling" (procedural Web Audio, no files).
- End card: score, local top 5 (localStorage, try/catch), play again.

## Fruits → flavour
| fruit | flavour |
|---|---|
| strawberry | strawberry (red) |
| grape | grape (purple, new) |
| blueberry | blueberry |
| mandarin | orange (new) |
| lemon | lemon (yellow) |
| green grape | lime |

Fruits are real small fruits but oversized and plump: ~3.5–4.5 cm next to the 7 cm jelly.

## Visuals
- Fruits are 3D (Blender via MCP, PBR, GLB), lit by the same HDR environment, opaque so they refract through the jelly, soft blob contact shadow. GPT Image 2 only for concept/texture reference.
- Phase 1 ships placeholder meshes behind the same interface; GLBs replace them later.
- Character: keep the jelly, nudge toward a rounder Kirby-like silhouette (rounder body, stubby arms, oval feet, bigger blush) via the SDF in `refs/jelly_baby_mesh.html` + `npm run build:model`. Not a Kirby copy.

## Out of scope
Global leaderboard, combos/power-ups, obstacles.
