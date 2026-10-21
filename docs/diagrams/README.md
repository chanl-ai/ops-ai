# Architecture diagrams

Status: current.

Each diagram here is a data file (`<name>.yaml`) and the SVG exported from it (`<name>.svg`). Markdown pages show the
SVG, which GitHub renders; the docs site (`apps/docs`) draws the same diagram live from the data file, in its theme, with
each box that names a page linking to it. Edit the YAML, then run `pnpm --filter docs diagrams`; the site build fails
when an SVG no longer matches its data file.

| Diagram | Shown on |
|---|---|
| `platform-map` | `design/workflows/workflows-and-agents.md` |
| `component-map` | `architecture/service-map.md` |
| `deployment` | `deploy/compose.md` |
| `enterprise-architecture` | `architecture/enterprise-architecture.md` (free layout) |

## Data file

| Key | What it holds |
|---|---|
| `title` | The diagram's accessible name |
| `width` | Drawing width in pixels (default 980) |
| `bands` | Rows of groups, top to bottom; `gap` is the space under a band (default 70, room for link labels) |
| `groups` | Boxes drawn as one frame: `id`, `label`, `note`, `style`, `span` (relative width), `columns` (a grid), `rows` |
| `rows` | `boxes` (a row of boxes), `chips` (a label and small pills) or `text` (a line of small text) |
| `boxes` | `id`, `label`, `note` (a second line), `style`, `bold`, `href` (a page under `docs/`) |
| `links` | `from` and `to` (box, chip or group ids), `label`, `style: dashed`, `fromX` and `toX` (0 to 1 along the edge), `straight` (a plain vertical line into a lower target) |

A data file with `layout: free` places every band, group and box at the coordinates it gives (`x`, `y`, `w`, `h`),
with `color` from green, indigo, violet, teal, blue, amber, rose and slate, a `status` pill, a `number` dot, and
`edges` from `node.side` to `node.side` (`l`, `r`, `t`, `b`) drawn as curves; the enterprise picture uses it.

Styles: `default`, `new` (dashed green: designed, not built), `pack` (purple pills), `host` (blue), `port` (soft),
`muted` (dotted grey).
