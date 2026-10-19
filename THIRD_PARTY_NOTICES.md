# Third-party notices

The player bundles the following third-party files so it works offline.

| Component | Files | License |
|---|---|---|
| [IBM Plex Sans and IBM Plex Mono](https://github.com/IBM/plex) (via Fontsource) | `plugins/plan-tour/skills/tour/player/fonts/*.woff2` | SIL Open Font License 1.1, see `player/fonts/OFL.txt` |
| [marked](https://github.com/markedjs/marked) 15.0.12 | `plugins/plan-tour/skills/tour/player/marked.umd.js` | MIT, see `player/marked.LICENSE.md` |

At runtime the engine uses [edge-tts](https://github.com/rany2/edge-tts) (LGPL-3.0), which the user installs separately with pip. It is not bundled.
