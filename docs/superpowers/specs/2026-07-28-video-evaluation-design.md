# T2V and TI2V Evaluation Design

## Goal

Extend the existing T2I/TI2I A/B evaluation platform with T2V and TI2V workflows that have equivalent dataset upload, result upload, blind evaluation, dashboard, detail preview, bad-case, ranking, and export capabilities. Video-specific behavior must remain isolated so the existing T2I/TI2I layout and interaction remain unchanged.

## Approved Approach

Use a configuration-driven incremental extension of the current FastAPI services and server-rendered vanilla JavaScript pages.

Each task type declares its media kind, accepted result extensions, scoring dimensions, reference-image behavior, and dashboard dimensions. Shared upload, task, result, dashboard, and export flows branch on these capabilities instead of duplicating an independent video application or rewriting all scores into a normalized dimension table.

The internal configuration is not user-editable. It exists to keep media behavior out of scattered task-type conditionals.

## Task Types and Dimensions

The existing image task definitions remain unchanged.

T2V uses these dimensions in this exact configured order:

| Key | Label |
|---|---|
| `overall` | 整体 |
| `text_consistency` | 文本一致性 |
| `motion_reasonableness` | 运动合理性 |
| `dynamism` | 动态度 |
| `physical_plausibility` | 物理规律与常识 |
| `visual_quality` | 画面细节与美感 |

TI2V uses all T2V dimensions and appends:

| Key | Label |
|---|---|
| `image_consistency` | 图像一致性 |

All video dimensions, including Overall, are optional. The setup UI selects all dimensions by default and requires at least one selected dimension before evaluation can start.

The task configuration gains a `media_type` capability (`image` or `video`) and a result-extension list. T2V/TI2V accept `.mp4` and `.webm`. Existing `show_ref` and `upload_has_ref` capabilities are reused: T2V does not require a reference image, while TI2V does.

## Persistence

### Evaluation scopes

Add an `evaluation_scopes` table with the following logical fields:

- `id`
- `user_id`
- `task_type`
- canonical `v_a` and `v_b`
- `scene`
- `selected_dimensions`, stored as canonical JSON in task-config order
- `created_at`
- `updated_at`

The unique key is `(user_id, task_type, v_a, v_b, scene)`. This row is the canonical dimension selection for one evaluator's video evaluation scope and prevents different evaluators from affecting one another.

### Results

Add these nullable score columns to `results_log`:

- `text_consistency`
- `motion_reasonableness`
- `dynamism`
- `physical_plausibility`
- `visual_quality`
- `image_consistency`

Add `selected_dimensions TEXT` to `results_log`. Every video result stores the canonical JSON selection used for that result. Unselected score columns remain `NULL`. Existing image records and score columns are not migrated or reinterpreted.

Video tasks use `eval_mode=selected`. T2I/TI2I continue using the current `full` and `overall` modes without UI or behavior changes.

### Canonicalization

The server rejects unknown dimension keys and duplicates, requires at least one dimension, and writes keys in task-config order. Set comparisons use keys rather than list length:

- Equal sets resume the existing evaluation.
- A strict superset can replace the existing evaluation after confirmation.
- A strict subset is rejected.
- An incomparable set—removing at least one old dimension while adding another—is rejected.

## Evaluation Session Lifecycle

The video setup page sends the selected dimension list to the start-session endpoint. The service compares it with `evaluation_scopes` inside a write transaction.

For a new scope, the service creates the scope and pair tasks. For an equal set, it resumes existing pending or working tasks and preserves completed results.

For a strict superset, the first request returns `requires_confirmation` and identifies the previous and next dimension labels. When the user confirms, the second request uses an explicit overwrite flag. The service atomically:

1. Deletes all prior result rows for that evaluator, task type, canonical model pair, and scene, including skipped rows.
2. Resets all owned pair tasks in the scope to `pending` and assigns `eval_mode=selected`.
3. Replaces the scope's canonical dimensions.

Evaluation then restarts from the first item. If any part fails, the transaction rolls back and the old results remain usable.

For a subset or incomparable set, the service returns a domain error and the setup page shows a blocking dialog explaining that previously evaluated dimensions cannot be removed. No data changes occur.

Task retrieval returns the scope's selected dimensions. Vote submission includes the selected list, and the server verifies it against both the current scope and the owned working task before writing. A stale tab therefore cannot submit after another tab changes the scope.

Only selected dimensions are required in a vote. Each selected value is normalized with the existing four-way A/B choice logic. Every unselected video score is forced to `NULL`, even if a client sends a value for it.

## Dataset and Result Upload

### Dataset upload

T2V follows the T2I dataset contract: a scene name and UTF-8 tab-separated Prompt TXT.

TI2V follows the TI2I dataset contract: the Prompt TXT plus a reference-image ZIP. Reference-image stems must match the Prompt IDs exactly. The existing supported image formats remain valid for TI2V references.

Dataset download follows the same split: T2V downloads Prompt TXT; TI2V can download Prompt TXT alone or a ZIP containing Prompt TXT and references.

### Result upload

T2V/TI2V result ZIPs accept only MP4 and WebM entries. Filename validation uses the existing exact-stem match and optional prefix-based automatic rename behavior. Image tasks continue accepting only the current image formats.

Video extraction occurs in a staging directory. Every candidate video must yield a readable first frame before the staged scene replaces an existing model scene. If any video cannot be decoded or has no usable frame, the upload fails, staging is removed, and existing results remain intact.

Add `imageio-ffmpeg>=0.5,<0.6` to the runtime dependencies and use its managed FFmpeg executable for frame extraction. The extracted frame is converted to the existing WebP thumbnail format and keyed by source path, file identity, and thumbnail size. Successful uploads warm the first-frame cache so the first dashboard visit does not launch one decoder process per visible row.

Public result URLs remain under the existing `/images/...` static mount for compatibility, even when the asset is a video. Shared storage helpers choose allowed extensions from the task configuration and describe counts as media or videos in video responses.

## Mock Evaluation Data

Add a reproducible generator script and its generated data. The data is synthetic and has no external copyright dependency.

T2V contains one scene with three Prompt IDs and two model directories. Each model contains three matching MP4 results. TI2V contains one scene with three Prompt IDs, three matching reference images, and two model directories with three matching MP4 results each.

The resulting fixture count is:

- Four model directories total.
- Twelve H.264 MP4 videos total.
- Six Prompt rows total.
- Three TI2V reference images total.

Videos are 640×360, approximately four seconds, use browser-compatible `yuv420p`, and contain no audio. Paired models show visibly different motion, speed, paths, or camera behavior so the data can exercise every video evaluation screen. MP4 is used for the bundled mock data, while upload tests also cover WebM acceptance.

## Evaluation Page

### Setup

Only T2V/TI2V display the dimension multi-select. It uses selectable chips, selects all options by default, and disables entry until at least one remains selected. T2I/TI2I retain their existing Overall-only checkbox and fixed-dimension descriptions.

The existing model and scene selectors, resolution/metadata area, prompt, progress, bad-case panels, four-way evaluation table, shortcuts, and completion behavior are reused. Video metadata replaces image-resolution wording where necessary without changing the image copy.

### Media layout

T2V uses the current two-pane A/B layout. TI2V uses the current three-pane reference/A/B layout, with a static reference image and two videos. Videos use first-frame posters and `preload=metadata`; original media bytes are requested as needed for evaluation playback.

The evaluation timer starts after both A/B video panes can display a first frame. It does not wait for the complete files to download.

### Custom video controls

Each video pane has a custom translucent bottom control bar containing:

- Play/pause.
- Current time and total duration.
- Seek progress.

Native controls remain disabled so behavior and synchronization are predictable. Controls appear on pointer entry or keyboard focus and hide on pointer leave when focus is outside the pane. Videos are muted by default; volume controls and audio evaluation are outside this feature's scope.

The existing sidebar Sync button controls both visual transforms and video timing:

- When Sync is on, play, pause, and seek on either A/B video are mirrored to the other video. A small reentrancy guard prevents event loops, and drift beyond a small tolerance is corrected during playback.
- When Sync is off, A/B play, pause, and seek independently. Visual tools affect only the active pane, following existing preview-controller semantics.
- The TI2V reference image has no timeline and is excluded from playback synchronization.

### Paused-frame tools

The current sidebar buttons and inline hold-to-compare controls remain in their current positions. Pan, zoom, fit, actual size, background, and reset use a media adapter that reads `videoWidth`/`videoHeight` for videos and `naturalWidth`/`naturalHeight` for images.

Frame-specific tools require affected videos to be paused. The page captures the current same-origin frame to a canvas for magnifier and hold-to-compare overlays. If a required video is playing, the action is not started and the page prompts the evaluator to pause first. When paused, these tools match the existing image interaction as closely as the current frame allows.

A load or decode failure is isolated to its pane. The pane shows an error and retry control; the other pane remains operable. Submission remains unavailable until all selected dimensions have votes, as it is today.

## Dashboard

Dashboard overview, per-scene statistics, evaluator statistics, ranking, bad cases, and details continue using the configured dimension list and existing four-way result logic.

For video task types, dimensions displayed for a model pair are the configured-order union of dimensions that have at least one non-null score in the current data. A row that did not select a dimension is excluded from that dimension's denominator; it is never treated as a tie or missing vote.

Video task dimension cards use a video-only grid capped at four columns, producing two rows for the six T2V or seven TI2V dimensions. No video grid class is attached for T2I/TI2I, so their current single-row desktop layout remains unchanged. Existing responsive breakpoints still collapse cards on narrow screens.

### Detail and bad-case previews

Detail tables and bad-case tables never create video elements. They request cached first-frame WebP thumbnails with lazy loading. TI2V details include the static reference thumbnail between the A/B first frames, following the existing TI2I order.

Clicking a video first frame opens the HD preview; only then does the page create video elements and request original MP4/WebM sources. The modal reuses the evaluation page's custom controls, Sync semantics, media toolbar, and paused-frame comparison behavior. Closing the modal pauses videos, clears media sources, releases object state, and prevents background downloads.

## Export

Dashboard export options are driven by the task's active dimensions. Spreadsheet score sheets include the six new video score columns where selected. Spreadsheet visual previews use cached first frames because an XLSX workbook cannot provide the platform's video playback experience.

For video task types, the export option is labeled as media/video export and the ZIP contains original MP4/WebM files. TI2V archives also include reference images. Image task export labels, workbook previews, and image archive behavior remain unchanged.

## Error Handling and Security

- Unknown task types, invalid dimension keys, duplicates, and empty selections are rejected server-side.
- Strict-subset and incomparable dimension changes never mutate stored results.
- Strict-superset replacement is explicit, confirmed, and transactional.
- Video ZIP processing retains existing safe-name and path-containment rules.
- Decoding operates on temporary staged files and does not pass user-controlled command fragments to a shell.
- A failed first-frame extraction leaves the previous uploaded scene intact.
- Browser media failures are displayed per pane and do not silently count as completed evaluations.

## Testing and Verification

Implementation follows red-green-refactor cycles. Automated coverage includes:

- T2V/TI2V task configuration, labels, formats, and reference requirements.
- MP4/WebM ZIP matching, optional rename, safe staging, first-frame extraction, cache warming, and rollback on decode failure.
- New/equal/superset/subset/incomparable dimension-set transitions and transactional replacement.
- Stale-tab submission rejection, selected-only validation, and forced `NULL` values for unselected dimensions.
- Non-null dashboard denominators, configured dimension order, ranking, detail payloads, and export fields.
- Video-only setup chips and dashboard grid classes, with explicit assertions that T2I/TI2I retain their existing controls and layout classes.
- Detail tables containing only image thumbnails and HD preview creating video elements on demand.
- Independent versus synchronized play, pause, and seek; paused-frame tool gating; control visibility; and modal cleanup.
- Mock fixture structure and decodability: four model directories, twelve videos, six Prompt rows, and three TI2V references.

Run the complete existing test suite after focused tests. Then launch the local application and walk through T2I, TI2I, T2V, and TI2V using the in-app browser. Verify upload copy, layout, video loading, independent and synchronized playback, progress seeking, paused-frame tools, two-row video dashboard cards, first-frame-only table loading, HD preview cleanup, and image-task regressions.

## Compatibility and Scope Boundaries

- Existing T2I/TI2I dimensions, data, setup controls, layouts, task modes, and exports do not change.
- Existing result URLs and authentication/permission boundaries remain in place.
- The feature does not transcode arbitrary codecs, evaluate audio, add volume controls, normalize every score into a new table, or redesign unrelated templates.
- MP4 and WebM are accepted containers; successful server-side frame extraction does not guarantee every browser supports every codec inside those containers. Pane-level playback errors remain visible and retryable.
