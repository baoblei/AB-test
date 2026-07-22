# Dashboard Preview Parity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard high-resolution preview match the evaluation preview for folded cross-image icons, non-overlapping help/info panels, and synchronized magnifier lenses.

**Architecture:** Keep the dashboard preview self-contained in `templates/dashboard.html`, but copy the already-proven visual and coordinate patterns from `templates/index.html`. Preserve the existing `PreviewController` and preview payload boundaries; only the renderer, toolbar presentation state, and magnifier presentation change.

**Tech Stack:** Server-rendered HTML/CSS/JavaScript, Python `unittest`, Node.js runtime probes, headless Chrome geometry probes.

## Global Constraints

- Do not modify detail, bad-case, thumbnail, or image backend APIs.
- Do not change dashboard filtering, pagination, statistics, exports, permissions, or evaluation behavior.
- Detail preview remains T2I A/B and TI2I Ref/A/B when the reference exists.
- Bad-case preview remains the clicked single model image with no synchronization or cross-image comparison controls.
- Preserve aspect ratio without crop or stretch and keep zoom clamped to `0.1–12`.
- Add no third-party dependency and do not extract a cross-template static component.
- Preserve the user's existing uncommitted `.gitignore` and `database.db` files.

---

### Task 1: Render evaluation-style folded comparison icons

**Files:**
- Modify: `templates/dashboard.html` comparison-button CSS and `renderInlineCompareControls()`
- Test: `tests/test_dashboard_image_preview_ui.py`

**Interfaces:**
- Consumes: `buildHoldComparePairs(panes) -> Array<{kind, symbol, ...}>`
- Produces: `foldedCompareIcon(direction: "left" | "right") -> string` and folded buttons containing `.inline-compare-icon` SVG markup

- [ ] **Step 1: Write the failing SVG-rendering test**

Add a test beside `test_detail_has_two_way_and_three_way_hold_compare_controls`:

```python
def test_folded_compare_buttons_use_evaluation_svg_paths(self):
    folded = self.function_source("foldedCompareIcon")
    script = f"""
{folded}
console.log(JSON.stringify({{
    left: foldedCompareIcon("left"),
    right: foldedCompareIcon("right")
}}));
"""
    result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
    for direction in ("left", "right"):
        self.assertIn('class="inline-compare-icon folded"', result[direction])
        self.assertEqual(result[direction].count("<polyline"), 2)
    self.assertIn('points="21,18 12,5 4,18"', result["left"])
    self.assertIn('points="3,18 12,5 20,18"', result["right"])

    renderer = self.function_source("renderInlineCompareControls")
    self.assertIn('pair.kind === "folded"', renderer)
    self.assertIn("foldedCompareIcon", renderer)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_folded_compare_buttons_use_evaluation_svg_paths -v
```

Expected: FAIL because `foldedCompareIcon` does not exist and the renderer still inserts raw `└←` / `→┘` text.

- [ ] **Step 3: Add the folded SVG helper and icon styles**

Copy the proven path geometry from `templates/index.html` into dashboard-local code:

```javascript
function foldedCompareIcon(direction) {
    const path = direction === "left"
        ? '<polyline points="21,18 12,5 4,18"></polyline><polyline class="arrow-head" points="4.5,12.5 4,18 8.8,15.1"></polyline>'
        : '<polyline points="3,18 12,5 20,18"></polyline><polyline class="arrow-head" points="15.2,15.1 20,18 19.5,12.5"></polyline>';
    return `<svg class="inline-compare-icon folded" viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
}
```

In `renderInlineCompareControls()`, keep adjacent arrow text unchanged and assign the helper output to folded buttons:

```javascript
const folded = pair.kind === "folded";
const button = createNode("button", "inline-compare-btn", folded ? "" : pair.symbol);
if (folded) button.innerHTML = foldedCompareIcon(pair.symbol === "└←" ? "left" : "right");
```

Add the evaluation-equivalent local CSS:

```css
.inline-compare-icon { width: 20px; height: 20px; display: block; overflow: visible; pointer-events: none; }
.inline-compare-icon polyline { fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.inline-compare-icon .arrow-head { stroke-width: 2.4; }
```

- [ ] **Step 4: Run comparison and responsive geometry tests**

Run:

```bash
python3 -m unittest \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_folded_compare_buttons_use_evaluation_svg_paths \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_detail_has_two_way_and_three_way_hold_compare_controls \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_mobile_compare_controls_follow_stacked_pane_gaps_at_700px -v
```

Expected: 3 tests PASS; the existing six-button geometry remains unchanged.

- [ ] **Step 5: Commit Task 1**

```bash
git add templates/dashboard.html tests/test_dashboard_image_preview_ui.py
git commit -m "fix: match dashboard folded compare icons"
```

---

### Task 2: Hide text by default and expand a non-overlapping help sidebar

**Files:**
- Modify: `templates/dashboard.html` toolbar CSS, `renderDashboardPreviewToolbar()`, and help action in `bindDashboardPreviewToolbar()`
- Test: `tests/test_dashboard_image_preview_ui.py`

**Interfaces:**
- Consumes: existing toolbar root `[data-preview-group="overlay"]` and stage `.dashboard-preview-stage`
- Produces: `.help-open` on the toolbar, `.preview-help-open` on the stage, and synchronized `aria-expanded` / `.hidden` state for help and info

- [ ] **Step 1: Replace the old always-visible panel test with a failing state-and-geometry test**

Update `test_desktop_toolbar_text_panels_expand_left_without_clipping` so it uses `render_toolbar_markup(True)` and checks both closed and open states in headless Chrome:

```python
toolbar = self.render_toolbar_markup(True)
body = f"""
<div id="image-overlay" style="display:flex">
  <div class="dashboard-preview-stage">
    <div id="dashboard-preview-toolbar">{toolbar}</div>
    <div id="image-preview" class="dashboard-preview-grid ti2i">
      <section class="dashboard-preview-viewport"></section>
      <section class="dashboard-preview-viewport"></section>
      <section class="dashboard-preview-viewport"></section>
    </div>
  </div>
</div>"""
```

The browser scenario must record closed-state panel display and grid right edge, then apply the exact production open classes and record the open geometry:

```javascript
const stageNode = document.querySelector(".dashboard-preview-stage");
const toolbarNode = document.querySelector(".dashboard-preview-toolbar");
const gridNode = document.querySelector(".dashboard-preview-grid");
const infoNode = document.querySelector(".preview-info");
const helpNode = document.querySelector(".preview-shortcut-help");
const closed = {
    info: getComputedStyle(infoNode).display,
    help: getComputedStyle(helpNode).display
};
toolbarNode.classList.add("help-open");
stageNode.classList.add("preview-help-open");
infoNode.classList.remove("hidden");
helpNode.classList.remove("hidden");
const stage = stageNode.getBoundingClientRect();
const grid = gridNode.getBoundingClientRect();
const toolbar = toolbarNode.getBoundingClientRect();
const panels = [infoNode, helpNode].map(node => node.getBoundingClientRect());
return {
    closed,
    toolbarWidth: toolbar.width,
    gridClearsToolbar: grid.right <= toolbar.left,
    panelsInsideStage: panels.every(panel => panel.left >= stage.left && panel.right <= stage.right)
};
```

Assert closed displays are `none`, expanded width is at least 220px, the grid clears the toolbar, and both panels remain inside the stage.

- [ ] **Step 2: Run the desktop geometry test and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_desktop_toolbar_text_panels_expand_left_without_clipping -v
```

Expected: FAIL because `.preview-info` is visible by default and the grid does not react to help state.

- [ ] **Step 3: Write a failing runtime test for the help action**

Add `test_help_action_expands_toolbar_and_stage_without_leaking_state`. Execute the real `bindDashboardPreviewToolbar()` with fake class lists and assert the first click adds `help-open` / `preview-help-open`, reveals both text nodes, and sets `aria-expanded="true"`; the second click reverses all five states.

The probe must expose these exact nodes:

```javascript
const toolbar = { dataset: { previewGroup: "overlay" }, classList: classes(), querySelector: selector => selector.includes("preview-help") ? help : selector.includes("preview-info") ? info : null };
const stage = { classList: classes() };
const helpButton = { dataset: { previewAction: "help" }, closest: selector => selector === "[data-preview-action]" ? helpButton : selector === "[data-preview-group]" ? toolbar : null, setAttribute(name, value) { this[name] = value; } };
```

- [ ] **Step 4: Run the runtime test and verify RED**

Run the new test alone. Expected: FAIL because the current click handler only toggles the shortcut text `.hidden` class.

- [ ] **Step 5: Implement the dashboard-local help state**

Render both text nodes hidden initially and add `aria-expanded="false"` to the help button. In the help click branch:

```javascript
const open = !toolbar.classList.contains("help-open");
toolbar.classList.toggle("help-open", open);
toolbar.closest(".dashboard-preview-stage")?.classList.toggle("preview-help-open", open);
toolbar.querySelector(`[data-preview-help="${groupId}"]`)?.classList.toggle("hidden", !open);
toolbar.querySelector(`[data-preview-info="${groupId}"]`)?.classList.toggle("hidden", !open);
button.setAttribute("aria-expanded", String(open));
```

Implement desktop layout state without changing the existing short-height/mobile breakpoints:

```css
.dashboard-preview-toolbar.help-open { width: 220px; align-items: flex-end; }
.dashboard-preview-stage.preview-help-open .dashboard-preview-grid { padding-right: 248px; }
.dashboard-preview-toolbar:not(.help-open) .preview-info,
.dashboard-preview-toolbar:not(.help-open) .preview-shortcut-help { display: none; }
.dashboard-preview-toolbar.help-open .preview-info,
.dashboard-preview-toolbar.help-open .preview-shortcut-help { right: 50px; width: 160px; }
```

In both bottom-toolbar media queries, explicitly reset `.help-open` to `width:auto`, keep text nodes static/flex items, and retain horizontal scrolling. Ensure `closeImagePreview()` removes `preview-help-open` before the next open.

- [ ] **Step 6: Run desktop, short-height, mobile, close-lifecycle, and keyboard tests**

Run:

```bash
python3 -m unittest \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_desktop_toolbar_text_panels_expand_left_without_clipping \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_help_action_expands_toolbar_and_stage_without_leaking_state \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_short_desktop_complete_toolbars_keep_every_control_reachable \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_responsive_overlay_keeps_single_column_and_bottom_tools \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_close_cleans_every_transient_preview_resource -v
```

Expected: all tests PASS at 1024×800, 1024×500, and the existing 700px layout.

- [ ] **Step 7: Commit Task 2**

```bash
git add templates/dashboard.html tests/test_dashboard_image_preview_ui.py
git commit -m "fix: keep dashboard preview text out of images"
```

---

### Task 3: Synchronize full magnifier lenses across panes

**Files:**
- Modify: `templates/dashboard.html` magnifier markup, CSS, `hidePreviewMagnifiers()`, and `renderMagnifier()`
- Test: `tests/test_dashboard_image_preview_ui.py`

**Interfaces:**
- Consumes: `PreviewController.groups[groupId].sync`, pane adapter `geometry()`, and each pane's `.magnifier-layer`
- Produces: `renderMagnifier(groupId, sourcePaneId, {clientX, clientY}) -> boolean` with one lens per eligible synchronized pane

- [ ] **Step 1: Replace the marker-oriented magnifier test with a failing synchronized-lens probe**

Create three viewports (`reference`, `left`, `right`), each with its own image URL and lens. Use different image rectangles to prove normalized coordinate mapping rather than copying pixel coordinates.

After calling the real function with `sync: true`, assert:

```python
self.assertTrue(result["shown"])
self.assertEqual(result["visibleLenses"], ["reference", "left", "right"])
self.assertEqual(result["backgrounds"], [
    'url("ref.jpg")', 'url("a.jpg")', 'url("b.jpg")'
])
self.assertTrue(result["distinctPositions"])
self.assertFalse(result["anyMarkerVisible"])
```

Then set `group.sync = false`, invoke from `left`, and assert only `left` remains visible. Finally invoke outside the source image and assert every lens is hidden.

- [ ] **Step 2: Run the synchronized-lens test and verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_magnifier_hides_when_pointer_leaves_rendered_image -v
```

Expected: FAIL because current synchronized targets receive `.correspondence-marker` dots instead of full lenses.

- [ ] **Step 3: Port the evaluation magnifier loop into the dashboard renderer**

After calculating the source normalized point, hide all old layers once, then render eligible panes:

```javascript
group.panes.forEach((pane, targetId) => {
    if (pane.failed || (targetId !== paneId && !group.sync)) return;
    const viewport = document.querySelector(`[data-preview-group-pane="${groupId}"][data-preview-pane="${targetId}"]`);
    const image = viewport?.querySelector("img");
    const lens = viewport?.querySelector(".magnifier-layer");
    if (!viewport || !image || !lens) return;
    const geometry = pane.adapter.geometry();
    const targetImage = geometry.image;
    const pointX = targetImage.left + normalizedPoint.x * targetImage.width - geometry.viewport.left;
    const pointY = targetImage.top + normalizedPoint.y * targetImage.height - geometry.viewport.top;
    const lensLeft = Math.max(0, Math.min(viewport.clientWidth - lens.offsetWidth, pointX - lens.offsetWidth / 2));
    const lensTop = Math.max(0, Math.min(viewport.clientHeight - lens.offsetHeight, pointY - lens.offsetHeight / 2));
    lens.style.left = `${lensLeft}px`;
    lens.style.top = `${lensTop}px`;
    lens.style.backgroundImage = `url("${image.currentSrc || image.src}")`;
    lens.style.backgroundSize = `${targetImage.width * 3}px ${targetImage.height * 3}px`;
    lens.style.backgroundPosition = `${pointX - lensLeft - normalizedPoint.x * targetImage.width * 3}px ${pointY - lensTop - normalizedPoint.y * targetImage.height * 3}px`;
    lens.classList.add("visible");
});
```

Remove `.correspondence-marker` creation and CSS because it is no longer part of either synchronized or unsynchronized behavior. Keep existing failure, pointer-leave, toggle-off, close, and render-generation cleanup calls.

- [ ] **Step 4: Run magnifier and lifecycle tests**

Run:

```bash
python3 -m unittest \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_magnifier_hides_when_pointer_leaves_rendered_image \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_pointer_magnifier_and_keyboard_bindings_exist \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_close_cleans_every_transient_preview_resource \
  tests.test_dashboard_image_preview_ui.DashboardImagePreviewUiTests.test_registered_failed_pane_is_excluded_from_controller_and_magnifier -v
```

Expected: all tests PASS; failed panes and sync-off sibling panes show no lens.

- [ ] **Step 5: Commit Task 3**

```bash
git add templates/dashboard.html tests/test_dashboard_image_preview_ui.py
git commit -m "fix: synchronize dashboard magnifier lenses"
```

---

### Task 4: Combined browser verification and regression gate

**Files:**
- Verify: `templates/dashboard.html`
- Verify: `tests/test_dashboard_image_preview_ui.py`
- Verify: `tests/test_dashboard_detail_performance_ui.py`

**Interfaces:**
- Consumes: Tasks 1–3 at their committed HEADs
- Produces: browser evidence and a clean, reviewable branch

- [ ] **Step 1: Run the dashboard preview and detail-performance suites**

```bash
python3 -m unittest tests.test_dashboard_image_preview_ui tests.test_dashboard_detail_performance_ui -v
```

Expected: every test passes, including real Chrome geometry probes.

- [ ] **Step 2: Run JavaScript syntax and whitespace checks**

```bash
sed -n '/<script>/,/<\/script>/p' templates/dashboard.html | sed '1d;$d' | node --check
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Perform a real TI2I browser smoke test**

Open a TI2I detail preview with Ref/A/B and verify:

1. Both folded buttons are `^`-shaped SVG paths with the correct arrow direction.
2. Help/info text is absent while the toolbar is closed.
3. Clicking `?` expands the right sidebar and reduces the image-grid width so no text overlaps the right image.
4. With sync on, hovering any image shows three complete lenses using three distinct image sources.
5. With sync off, only the hovered image shows a lens.
6. Bad-case preview remains one pane with no sync or compare controls.

- [ ] **Step 4: Run the full test suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: all repository tests pass with zero failures or errors.

- [ ] **Step 5: Prepare final review package**

```bash
BASE=$(git merge-base main HEAD)
bash /Users/baobinglei/.cc-switch/skills/subagent-driven-development/scripts/review-package "$BASE" HEAD
git status --short
```

Expected: review diff is generated and the feature worktree is clean.
