# ClipForge — Project Workspace Plan (P0 implemented)

P0 turns the single-video Studio into a persistent project workspace with a
unified asset library. P1–P4 (multitrack timeline, scenes, director asset
tools, Anime.js animation controls/exports, version history) are deferred.

## Data model (filesystem, no database)

```
storage/projects/<project_id>/project.json
storage/projects/<project_id>/assets/<asset_id>/asset.json
storage/projects/<project_id>/assets/<asset_id>/original.<ext>
storage/projects/<project_id>/assets/<asset_id>/sanitized.svg   (SVG only)
```

- `ProjectRecord` (`packages/contracts/clipforge_contracts/project.py`):
  `project_id (prj_+12hex)`, `title`, `mode (edit|idea)`, timestamps.
- `AssetRecord`: `asset_id (ast_+12hex)`, `project_id`, `kind
  (video|audio|image|text|graphics)`, filenames, `mime`, `size_bytes`,
  `sha256`, `provenance (upload|session_source|generated|local_render)`,
  optional media metadata (dimensions, duration, fps, audio codec/channels,
  text lines/cue count, sanitized flag).
- `JobRecord.project_id` links each editing job to its project. Project =
  workspace, Asset = resource, Job = one AI processing operation.

`ProjectStore` (`packages/jobs/clipforge_jobs/project_store.py`) uses the
same atomic discipline as `JobStore` (temp file + `os.replace`, per-call
locks). IDs are generated server-side; lookups validate the id pattern so no
user-supplied string can escape its directory.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/projects` | Create project (`{title?, mode?}` → 201) |
| `GET /api/projects` | List projects with asset counts |
| `GET /api/projects/{id}` | Project payload |
| `PATCH /api/projects/{id}` | Rename |
| `POST /api/projects/{id}/assets` | Multipart import, content-validated (201) |
| `GET …/assets` | List asset sidecars |
| `GET …/assets/{aid}` | One sidecar (project-bound; cross-project → 404) |
| `GET …/assets/{aid}/file` | Serve bytes (SVG: sanitized copy only, `image/svg+xml` + CSP) |
| `DELETE …/assets/{aid}` | Remove one asset directory |
| `POST /api/uploads` (+ optional `project_id` form field) | Unchanged job flow; reuses/creates the project and registers the source as a `session_source` asset. No AI triggered by library imports. |

## Validation (`apps/api/clipforge_api/assets.py`)

- Video: existing ffprobe MVP limits (≤720p/≤10.5s/≤30FPS).
- Audio (wav/mp3/m4a/ogg/webm): ffprobe audio stream + duration (≤600s); records codec/channels.
- Images (png/jpg/webp): magic bytes + Pillow decode; records dimensions.
- Text (txt/md/srt/vtt, ≤1MB): UTF-8; VTT must start with `WEBVTT`; SRT/VTT require ≥1 `-->` cue.
- SVG (≤2MB): rejects DOCTYPE/ENTITY, non-SVG roots; allowlists
  tags/attributes (lowercased); rejects `on*`, `script`/`foreignObject`/active
  elements, SMIL `<animate>`, `<style>` blocks, external `href` (only `#fragment`
  and `data:image/{png,jpeg,webp};base64` allowed), unsafe `url(`/`expression`/
  `@import`/`javascript:` in styles. Original preserved immutably;
  `sanitized.svg` served with `Content-Security-Policy: default-src 'none'`.
  Malicious fixtures (script/onload/foreignObject/DOCTYPE/external/style-url/
  animate) covered in `tests/test_project_workspace.py`.
- Failures delete the asset directory (no orphans). 100MB per-file cap.

## Studio UI

Left column is now the Asset Library: project title (click to rename),
session-clip card (existing single-video flow preserved), multi-file import
zone (drag-drop + picker), `All/Video/Audio/Images/Text/Graphics` filters,
search, per-asset metadata line, inline preview (video/image/audio/text via
fetch/SVG via `<img>` — never inline HTML), two-step Remove. `localStorage`
holds only `clipforge.projectId`; the backend is source of truth, so reloads
restore title + assets. Library imports never create jobs. Palette, type and
layout language unchanged; no timeline/scene/animation UI added.

## Verification

`tests/test_project_workspace.py` (12 tests): project CRUD/persistence,
upload→project link, project reuse, multi-video, audio/image metadata,
text/subtitle parsing, SVG sanitize, malicious rejection, cross-project
isolation + traversal probes, failure cleanup, single-video regression. Full
backend suite green; `tsc` + production `next build` green; browser check of
library import → reload persistence → remove + full mock edit → verified
download with zero console errors.

## Deferred (not in P0)

Multitrack timeline, scene editor, director project context/tools, Anime.js
controls, animated export, version history, Muse Image/auth/database changes.
`timeline.trim`, `transition.apply`, `keyframe.animate`, `multitrack.edit`,
`audio.mix`, `captions.animate` stay `disabled` in the capability registry.
