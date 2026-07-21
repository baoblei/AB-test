# Dashboard Image Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade dashboard detail and bad-case image overlays to the evaluation page's zoomable inspection experience while keeping bad cases single-image and detail rows fully comparable.

**Architecture:** Keep the existing dependency-free, inline-template frontend. Add a `PreviewController` and one reusable dashboard overlay renderer inside `templates/dashboard.html`; detail clicks pass two or three panes with synchronization and hold-to-compare enabled, while bad-case clicks pass one pane with both features disabled. Cover controller math and rendering contracts with a focused Python/Node test module.

**Tech Stack:** FastAPI/Jinja HTML template, vanilla CSS and JavaScript, Python `unittest`, Node.js runtime probes.

## Global Constraints

- Do not modify detail, bad-case, or image backend APIs.
- Do not change dashboard filtering, statistics, exports, permissions, or evaluation behavior.
- Detail preview renders T2I A/B and TI2I Ref/A/B when the reference exists.
- Bad-case preview renders only the clicked model image and never fills in Ref or the other model.
- Bad-case preview hides synchronization and inter-image comparison controls.
- Preserve image aspect ratio without cropping or stretching.
- Clamp preview zoom to `0.1`–`12`.
- Add no third-party frontend dependency.
- Do not extract a cross-template static component in this change.

## File Structure

- Create `tests/test_dashboard_image_preview_ui.py`: source-level contracts plus Node probes for controller state, pane selection, and renderer feature flags.
- Modify `templates/dashboard.html`: responsive overlay CSS and markup, preview controller, toolbar/pointer/magnifier bindings, detail and single-image renderer, hold-to-compare layers, and lifecycle cleanup.
- Read-only regression target `tests/test_evaluation_preview_ui.py`: confirms the existing evaluation preview remains unchanged.

---

### Task 1: Preview Controller and Immersive Overlay Shell

**Files:**
- Create: `tests/test_dashboard_image_preview_ui.py`
- Modify: `templates/dashboard.html:358-400`
- Modify: `templates/dashboard.html:774-776`
- Modify: `templates/dashboard.html:778-810`

**Interfaces:**
- Consumes: existing `#image-overlay`, `#image-preview`, `createNode()`, and browser image natural dimensions.
- Produces: `class PreviewController`, `previewController`, `createPreviewGroup(groupId)`, `setPreviewMode(groupId, mode)`, `setPreviewZoom(groupId, paneId, zoom, anchor)`, `setPreviewCenter(groupId, paneId, center)`, `resetPreviewGroup(groupId)`, `.dashboard-preview-stage`, and `.dashboard-preview-viewport`.

- [ ] **Step 1: Create failing structure and controller tests**

Create `tests/test_dashboard_image_preview_ui.py` with the following initial content:

```python
import json
import subprocess
import unittest
from pathlib import Path


class DashboardImagePreviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def controller_source(self):
        start = self.html.index("class PreviewController")
        end = self.html.index("const previewController", start)
        return self.html[start:end]

    def run_controller_probe(self, scenario):
        script = f"{self.controller_source()}\n{scenario}"
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def test_overlay_has_immersive_preview_shell(self):
        for marker in (
            'class="dashboard-preview-stage"',
            'id="dashboard-preview-title"',
            'id="dashboard-preview-toolbar"',
            'class="dashboard-preview-grid',
            'aria-modal="true"',
            'function closeImagePreview(',
        ):
            self.assertIn(marker, self.html)

    def test_controller_contract_and_zoom_bounds(self):
        for marker in (
            "class PreviewController",
            "normalizedCenter",
            'mode: "fit"',
            "sync: true",
            '"fit-width"',
            '"fit-height"',
            '"actual"',
            "resetGroup(",
        ):
            self.assertIn(marker, self.html)

        result = self.run_controller_probe(
            """
const applied = [];
const adapter = {
    measure: () => ({ naturalWidth: 1000, naturalHeight: 500, viewportWidth: 500, viewportHeight: 500 }),
    apply: state => applied.push(state)
};
const controller = new PreviewController();
controller.createGroup("overlay", { sync: true });
controller.addPane("overlay", "left", adapter);
controller.setZoom("overlay", "left", 99);
const high = controller.groups.get("overlay").panes.get("left").zoom;
controller.setZoom("overlay", "left", -3);
const low = controller.groups.get("overlay").panes.get("left").zoom;
console.log(JSON.stringify({ high, low }));
"""
        )
        self.assertEqual(result, {"high": 12, "low": 0.1})

    def test_controller_syncs_normalized_center_and_can_unlock(self):
        result = self.run_controller_probe(
            """
const adapter = {
    measure: () => ({ naturalWidth: 800, naturalHeight: 600, viewportWidth: 400, viewportHeight: 300 }),
    apply: () => {}
};
const controller = new PreviewController();
controller.createGroup("overlay", { sync: true });
controller.addPane("overlay", "a", adapter);
controller.addPane("overlay", "b", adapter);
controller.setCenter("overlay", "a", { x: 0.7, y: 0.35 });
const synced = controller.groups.get("overlay").panes.get("b").normalizedCenter;
controller.setSync("overlay", false);
controller.setCenter("overlay", "a", { x: 0.2, y: 0.8 });
const unlocked = controller.groups.get("overlay").panes.get("b").normalizedCenter;
controller.resetGroup("overlay");
const reset = controller.groups.get("overlay").panes.get("a").normalizedCenter;
console.log(JSON.stringify({ synced, unlocked, reset }));
"""
        )
        self.assertEqual(result["synced"], {"x": 0.7, "y": 0.35})
        self.assertEqual(result["unlocked"], {"x": 0.7, "y": 0.35})
        self.assertEqual(result["reset"], {"x": 0.5, "y": 0.5})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui -v
```

Expected: FAIL because `class PreviewController` and the immersive overlay shell do not exist.

- [ ] **Step 3: Replace the static overlay CSS and markup**

Replace the current `#image-overlay`, `.compare-preview`, and `.compare-box` rules with rules implementing these exact selectors and responsibilities:

```css
#image-overlay {
    position: fixed;
    inset: 0;
    display: none;
    padding: 12px;
    background: rgba(5, 9, 15, 0.96);
    z-index: 80;
}
.dashboard-preview-stage {
    position: relative;
    width: 100%;
    height: calc(100dvh - 24px);
    overflow: hidden;
    border-radius: 20px;
    background: #111820;
    color: white;
}
.dashboard-preview-head {
    position: absolute;
    inset: 12px 12px auto 12px;
    z-index: 8;
    display: flex;
    justify-content: space-between;
    align-items: center;
    pointer-events: none;
}
.dashboard-preview-head button { pointer-events: auto; }
.dashboard-preview-grid {
    display: grid;
    width: 100%;
    height: 100%;
    gap: 10px;
    padding: 62px 70px 18px 18px;
}
.dashboard-preview-grid.single { grid-template-columns: minmax(0, 1fr); }
.dashboard-preview-grid.t2i { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.dashboard-preview-grid.ti2i { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.dashboard-preview-viewport {
    position: relative;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    border-radius: 14px;
    background: #0b1016;
    touch-action: none;
}
.dashboard-preview-viewport img {
    position: absolute;
    left: 50%;
    top: 50%;
    max-width: none;
    max-height: none;
    user-select: none;
    -webkit-user-drag: none;
    transform-origin: center;
}
@media (max-width: 760px) {
    .dashboard-preview-grid.t2i,
    .dashboard-preview-grid.ti2i { grid-template-columns: 1fr; }
    .dashboard-preview-grid { overflow-y: auto; padding: 62px 12px 82px; }
    .dashboard-preview-viewport { min-height: 62dvh; }
}
```

Replace the old two-node overlay markup with:

```html
<div id="image-overlay" role="dialog" aria-modal="true" aria-labelledby="dashboard-preview-title" aria-hidden="true">
    <div class="dashboard-preview-stage" onclick="event.stopPropagation()">
        <div class="dashboard-preview-head">
            <strong id="dashboard-preview-title">高清预览</strong>
            <button class="btn btn-outline" type="button" data-preview-close>关闭</button>
        </div>
        <div id="dashboard-preview-toolbar"></div>
        <div class="dashboard-preview-grid single" id="image-preview"></div>
    </div>
</div>
```

- [ ] **Step 4: Add the minimal controller**

Add `PreviewController` before the main `state` declaration. Its public methods must use these signatures and rules:

```javascript
class PreviewController {
    constructor() { this.groups = new Map(); }

    createGroup(groupId, options = {}) {
        const group = {
            mode: "fit",
            sync: options.sync !== false,
            magnifier: false,
            darkBackground: true,
            activePaneId: "",
            zoom: 1,
            normalizedCenter: { x: 0.5, y: 0.5 },
            panes: new Map()
        };
        this.groups.set(groupId, group);
        return group;
    }

    addPane(groupId, paneId, adapter) {
        const group = this.groups.get(groupId) || this.createGroup(groupId);
        group.panes.set(paneId, {
            adapter,
            failed: false,
            zoom: group.zoom,
            normalizedCenter: { ...group.normalizedCenter }
        });
        this.applyPane(group, paneId);
    }

    fitScale(mode, adapter) {
        const size = adapter.measure();
        const widthScale = size.viewportWidth / size.naturalWidth;
        const heightScale = size.viewportHeight / size.naturalHeight;
        if (mode === "fit-width") return widthScale;
        if (mode === "fit-height") return heightScale;
        if (mode === "actual") return 1;
        return Math.min(widthScale, heightScale);
    }

    applyPane(group, paneId) {
        const pane = group.panes.get(paneId);
        if (!pane || pane.failed) return;
        const size = pane.adapter.measure();
        if (Math.min(size.naturalWidth, size.naturalHeight, size.viewportWidth, size.viewportHeight) <= 0) return;
        pane.adapter.apply({
            mode: group.mode,
            zoom: pane.zoom,
            scale: this.fitScale(group.mode, pane.adapter) * pane.zoom,
            normalizedCenter: { ...pane.normalizedCenter }
        });
    }

    refreshGroup(groupId) {
        const group = this.groups.get(groupId);
        if (group) group.panes.forEach((_, paneId) => this.applyPane(group, paneId));
    }

    setMode(groupId, mode) {
        const group = this.groups.get(groupId);
        if (!group || !["fit", "fit-width", "fit-height", "actual"].includes(mode)) return;
        group.mode = mode;
        this.refreshGroup(groupId);
    }

    setZoom(groupId, paneId, zoom, anchor) {
        const group = this.groups.get(groupId);
        const pane = group?.panes.get(paneId);
        if (!pane || pane.failed) return;
        const nextZoom = Math.max(0.1, Math.min(12, Number(zoom)));
        if (anchor) {
            const size = pane.adapter.measure();
            const baseScale = this.fitScale(group.mode, pane.adapter);
            const previousWidth = size.naturalWidth * baseScale * pane.zoom;
            const previousHeight = size.naturalHeight * baseScale * pane.zoom;
            const nextWidth = size.naturalWidth * baseScale * nextZoom;
            const nextHeight = size.naturalHeight * baseScale * nextZoom;
            const contentX = (anchor.x - size.viewportWidth / 2 + pane.normalizedCenter.x * previousWidth) / previousWidth;
            const contentY = (anchor.y - size.viewportHeight / 2 + pane.normalizedCenter.y * previousHeight) / previousHeight;
            this.setCenter(groupId, paneId, {
                x: contentX + (size.viewportWidth / 2 - anchor.x) / nextWidth,
                y: contentY + (size.viewportHeight / 2 - anchor.y) / nextHeight
            });
        }
        const targets = group.sync ? group.panes : new Map([[paneId, pane]]);
        targets.forEach((target, targetId) => {
            if (target.failed) return;
            target.zoom = nextZoom;
            this.applyPane(group, targetId);
        });
        if (group.sync) group.zoom = nextZoom;
    }

    setCenter(groupId, paneId, center) {
        const group = this.groups.get(groupId);
        const pane = group?.panes.get(paneId);
        if (!pane || pane.failed) return;
        const normalizedCenter = {
            x: Math.max(0, Math.min(1, Number(center.x))),
            y: Math.max(0, Math.min(1, Number(center.y)))
        };
        const targets = group.sync ? group.panes : new Map([[paneId, pane]]);
        targets.forEach((target, targetId) => {
            if (target.failed) return;
            target.normalizedCenter = { ...normalizedCenter };
            this.applyPane(group, targetId);
        });
        if (group.sync) group.normalizedCenter = { ...normalizedCenter };
    }

    setSync(groupId, enabled) {
        const group = this.groups.get(groupId);
        if (group) group.sync = Boolean(enabled);
    }

    resetGroup(groupId) {
        const group = this.groups.get(groupId);
        if (!group) return;
        group.mode = "fit";
        group.zoom = 1;
        group.normalizedCenter = { x: 0.5, y: 0.5 };
        group.panes.forEach((pane, paneId) => {
            pane.zoom = 1;
            pane.normalizedCenter = { ...group.normalizedCenter };
            this.applyPane(group, paneId);
        });
    }
}

const previewController = new PreviewController();
function createPreviewGroup(groupId, options) { return previewController.createGroup(groupId, options); }
function setPreviewMode(groupId, mode) { previewController.setMode(groupId, mode); }
function setPreviewZoom(groupId, paneId, zoom, anchor) { previewController.setZoom(groupId, paneId, zoom, anchor); }
function setPreviewCenter(groupId, paneId, center) { previewController.setCenter(groupId, paneId, center); }
function resetPreviewGroup(groupId) { previewController.resetGroup(groupId); }
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui tests.test_dashboard_export_ui -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add tests/test_dashboard_image_preview_ui.py templates/dashboard.html
git commit -m "feat: add dashboard preview controller"
```

---

### Task 2: Toolbar, Pointer Gestures, Magnifier, and Keyboard Controls

**Files:**
- Modify: `tests/test_dashboard_image_preview_ui.py`
- Modify: `templates/dashboard.html:358-400`
- Modify: `templates/dashboard.html:778-900`

**Interfaces:**
- Consumes: Task 1 `PreviewController`, `previewController.groups`, `#dashboard-preview-toolbar`, and registered pane adapters.
- Produces: `renderDashboardPreviewToolbar(options)`, `bindDashboardPreviewToolbar()`, `registerPreviewPane(groupId, paneId, viewport, image)`, `bindPreviewGroup(groupId)`, `renderMagnifier(groupId, paneId, point)`, `hidePreviewMagnifiers()`, and `releasePreviewPointers(groupId)`.

- [ ] **Step 1: Add failing toolbar and interaction contracts**

Append these tests to `DashboardImagePreviewUiTests`:

```python
    def test_toolbar_contains_evaluation_inspection_tools(self):
        for marker in (
            'data-preview-action="magnifier"',
            'data-preview-action="reset"',
            'data-preview-action="fit"',
            'data-preview-action="fit-width"',
            'data-preview-action="fit-height"',
            'data-preview-action="actual"',
            'data-preview-action="zoom-out"',
            'data-preview-action="zoom-in"',
            'data-preview-action="background"',
            'data-preview-action="help"',
            "function renderDashboardPreviewToolbar(",
            "function updateDashboardPreviewToolbar(",
        ):
            self.assertIn(marker, self.html)

    def test_pointer_magnifier_and_keyboard_bindings_exist(self):
        for marker in (
            'addEventListener("wheel"',
            'addEventListener("pointerdown"',
            'addEventListener("pointermove"',
            'setPointerCapture(',
            "renderMagnifier(",
            "releasePreviewPointers(",
            '["INPUT", "SELECT", "TEXTAREA"]',
            'event.key === "+"',
            'event.key === "-"',
            'event.key === "Escape"',
        ):
            self.assertIn(marker, self.html)

    def test_single_preview_toolbar_can_hide_sync(self):
        start = self.html.index("function renderDashboardPreviewToolbar(")
        end = self.html.index("function updateDashboardPreviewToolbar(", start)
        source = self.html[start:end]
        script = f"""
{source}
console.log(JSON.stringify({{
    detail: renderDashboardPreviewToolbar({{ groupId: "overlay", showSync: true }}),
    single: renderDashboardPreviewToolbar({{ groupId: "overlay", showSync: false }})
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertIn('data-preview-action="sync"', result["detail"])
        self.assertNotIn('data-preview-action="sync"', result["single"])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui -v
```

Expected: FAIL because the toolbar and bindings are absent.

- [ ] **Step 3: Implement configurable toolbar markup and styles**

Add `.dashboard-preview-toolbar`, `.preview-tool`, `.preview-info`, `.preview-shortcut-help`, `.magnifier-layer`, and `.correspondence-marker` rules. The toolbar must float on the right on wide screens and move to a bottom horizontally scrollable row below `760px`.

Implement the renderer with the sync button gated exactly by `showSync`:

```javascript
function previewToolButton(action, label, symbol, pressed) {
    const pressedAttribute = pressed == null ? "" : ` aria-pressed="${pressed}"`;
    return `<button type="button" class="preview-tool" data-preview-action="${action}" aria-label="${label}" title="${label}"${pressedAttribute}><span aria-hidden="true">${symbol}</span></button>`;
}

function renderDashboardPreviewToolbar({ groupId, showSync }) {
    return `
        <div class="dashboard-preview-toolbar" data-preview-group="${groupId}">
            ${previewToolButton("magnifier", "放大镜关", "🔍", false)}
            ${previewToolButton("reset", "重置", "↺")}
            ${showSync ? previewToolButton("sync", "同步开", "🔗", true) : ""}
            ${previewToolButton("fit", "适应窗口", "▣")}
            ${previewToolButton("fit-width", "适应宽度", "↔")}
            ${previewToolButton("fit-height", "适应高度", "↕")}
            ${previewToolButton("actual", "原始尺寸", "1:1")}
            ${previewToolButton("zoom-out", "缩小（-）", "−")}
            ${previewToolButton("zoom-in", "放大（+）", "+")}
            ${previewToolButton("background", "深色背景", "◐", true)}
            ${previewToolButton("help", "快捷键帮助", "?", false)}
            <span class="preview-shortcut-help hidden" data-preview-help="${groupId}">滚轮缩放；拖动平移；+ / - 缩放；空格临时平移；Esc 关闭。</span>
            <span class="preview-info" data-preview-info="${groupId}">自然尺寸 - · 渲染比例 - · 适应倍率 100% · 模式 适应</span>
        </div>`;
}
```

Use DOM event delegation in `bindDashboardPreviewToolbar()` to map each `data-preview-action` to controller calls and update `aria-pressed`, active styles, mode label, natural dimensions, and zoom percentage in `updateDashboardPreviewToolbar(groupId)`.

- [ ] **Step 4: Implement pane adapter, wheel, drag, magnifier, and keyboard behavior**

`registerPreviewPane()` must register an adapter whose `measure()` reads `image.naturalWidth`, `image.naturalHeight`, `viewport.clientWidth`, and `viewport.clientHeight`; `apply()` must compute the translated center from the normalized center and apply a single CSS transform:

```javascript
const renderedWidth = image.naturalWidth * scale;
const renderedHeight = image.naturalHeight * scale;
const offsetX = (0.5 - normalizedCenter.x) * renderedWidth;
const offsetY = (0.5 - normalizedCenter.y) * renderedHeight;
image.style.width = `${image.naturalWidth * scale}px`;
image.style.height = `${image.naturalHeight * scale}px`;
image.style.transform = `translate(calc(-50% + ${offsetX}px), calc(-50% + ${offsetY}px))`;
```

`bindPreviewGroup("overlay")` must:

```javascript
viewport.addEventListener("wheel", onWheel, { passive: false });
viewport.addEventListener("pointerdown", onPointerDown);
viewport.addEventListener("pointermove", onPointerMove);
viewport.addEventListener("pointerup", onPointerUp);
viewport.addEventListener("pointercancel", onPointerUp);
viewport.addEventListener("pointerleave", onPointerLeave);
```

- `onWheel` calls `preventDefault()` and adjusts the active pane zoom by `1.1` or `1 / 1.1` around the pointer.
- `onPointerDown` records pointer id/start center, calls `setPointerCapture()`, and marks the pane active.
- `onPointerMove` converts pixel drag distance to normalized image-space center deltas and calls `setPreviewCenter()`; when magnifier is active and no drag is active, it calls `renderMagnifier()`.
- `onPointerUp` releases capture and removes transient drag state.
- `releasePreviewPointers()` removes every listener saved for the group.
- `renderMagnifier()` shows a fixed-size `3×` background-image lens only on the hovered pane and normalized correspondence markers on sibling panes.
- the document key handler returns immediately when `event.target.tagName` is in `["INPUT", "SELECT", "TEXTAREA"]`; otherwise it handles `+`, `-`, Space, and `Escape`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui tests.test_evaluation_preview_ui -v
```

Expected: PASS, including the existing evaluation preview suite.

- [ ] **Step 6: Commit Task 2**

```bash
git add tests/test_dashboard_image_preview_ui.py templates/dashboard.html
git commit -m "feat: add dashboard preview inspection tools"
```

---

### Task 3: Detail Comparison and Bad-Case Single-Image Rendering

**Files:**
- Modify: `tests/test_dashboard_image_preview_ui.py`
- Modify: `templates/dashboard.html:1532-1550`
- Modify: `templates/dashboard.html:1722-1730`
- Modify: `templates/dashboard.html:1753-1800`

**Interfaces:**
- Consumes: Task 2 preview controller and bindings, existing `buildPreviewPayload(row, v1, v2)`, `imageUrl(model, scene, filename)`, and thumbnail click handlers.
- Produces: `normalizeDashboardPreview(payload)`, `openDashboardPreview(payload)`, `renderDashboardPreviewPane(pane)`, `buildHoldComparePairs(panes)`, `renderInlineCompareControls(groupId, panes)`, `startHoldCompare(groupId, sourceId, targetId, button)`, `stopHoldCompare()`, `openPreview(payload)`, and `openSinglePreview(src, label)`.

- [ ] **Step 1: Add failing renderer and comparison tests**

Append these tests:

```python
    def function_source(self, name):
        start = self.html.index(f"function {name}")
        brace = self.html.index("{", start)
        depth = 0
        for index in range(brace, len(self.html)):
            if self.html[index] == "{":
                depth += 1
            elif self.html[index] == "}":
                depth -= 1
                if depth == 0:
                    return self.html[start:index + 1]
        self.fail(f"function {name} is incomplete")

    def test_preview_normalization_keeps_detail_and_single_boundaries(self):
        source = self.function_source("normalizeDashboardPreview")
        script = f"""
{source}
console.log(JSON.stringify({{
    t2i: normalizeDashboardPreview({{ mode: "T2I", a: "a.jpg", b: "b.jpg", labels: ["A", "B"] }}),
    ti2i: normalizeDashboardPreview({{ mode: "TI2I", ref: "ref.jpg", a: "a.jpg", b: "b.jpg", labels: ["A", "B"] }}),
    missingRef: normalizeDashboardPreview({{ mode: "TI2I", ref: null, a: "a.jpg", b: "b.jpg", labels: ["A", "B"] }}),
    single: normalizeDashboardPreview({{ single: true, src: "bad.jpg", label: "A" }})
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual([p["id"] for p in result["t2i"]["panes"]], ["left", "right"])
        self.assertEqual([p["id"] for p in result["ti2i"]["panes"]], ["reference", "left", "right"])
        self.assertEqual([p["id"] for p in result["missingRef"]["panes"]], ["left", "right"])
        self.assertTrue(result["t2i"]["showSync"])
        self.assertTrue(result["t2i"]["showCompare"])
        self.assertEqual([p["id"] for p in result["single"]["panes"]], ["single"])
        self.assertFalse(result["single"]["showSync"])
        self.assertFalse(result["single"]["showCompare"])

    def test_detail_has_two_way_and_three_way_hold_compare_controls(self):
        for marker in (
            "function buildHoldComparePairs(",
            "function renderInlineCompareControls(",
            'data-hold-compare="true"',
            "function startHoldCompare(",
            "function stopHoldCompare(",
        ):
            self.assertIn(marker, self.html)

    def test_bad_case_click_stays_single_image(self):
        source = self.function_source("openSinglePreview")
        self.assertIn("single: true", source)
        self.assertNotIn("state.currentBadcase", source)
        self.assertNotIn("ref_img", source)
        self.assertNotIn("imageUrl(", source)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui -v
```

Expected: FAIL because normalized payloads and hold comparison are absent.

- [ ] **Step 3: Normalize detail and single-image payloads**

Implement the payload boundary exactly once:

```javascript
function normalizeDashboardPreview(payload) {
    if (payload.single) {
        return {
            kind: "single",
            panes: [{ id: "single", src: payload.src, label: payload.label }],
            showSync: false,
            showCompare: false
        };
    }
    const panes = [];
    if (payload.mode === "TI2I" && payload.ref) {
        panes.push({ id: "reference", src: payload.ref, label: "参考图" });
    }
    panes.push(
        { id: "left", src: payload.a, label: payload.labels[0] },
        { id: "right", src: payload.b, label: payload.labels[1] }
    );
    return { kind: panes.length === 3 ? "ti2i" : "t2i", panes, showSync: true, showCompare: true };
}

function openPreview(payload) {
    openDashboardPreview(payload);
}

function openSinglePreview(src, label) {
    openDashboardPreview({ single: true, src, label });
}
```

`openDashboardPreview()` must create a fresh `overlay` group with `{ sync: normalized.showSync }`, render the configurable toolbar, render each pane with `createNode()`/`textContent`, register images only for the current render generation, append comparison controls only when `showCompare` is true, set `aria-hidden="false"`, and display the overlay.

- [ ] **Step 4: Implement safe pane rendering and hold-to-compare**

`renderDashboardPreviewPane(pane)` must create this DOM shape without interpolating backend strings into `innerHTML`:

```html
<section class="dashboard-preview-viewport" data-preview-pane="left" data-preview-label="model-name">
    <img alt="model-name">
    <span class="dashboard-preview-loading">图片加载中…</span>
    <span class="dashboard-preview-error">图片加载失败</span>
    <span class="magnifier-layer"></span>
    <strong class="dashboard-preview-label">model-name</strong>
</section>
```

Implement the complete two-pane and three-pane pair mapping:

```javascript
function buildHoldComparePairs(panes) {
    if (panes.length === 2) {
        return [
            {
                sourceId: panes[1].id,
                targetId: panes[0].id,
                label: `${panes[1].label} 覆盖${panes[0].label}`,
                slot: "only-upper",
                kind: "adjacent",
                symbol: "←"
            },
            {
                sourceId: panes[0].id,
                targetId: panes[1].id,
                label: `${panes[0].label} 覆盖${panes[1].label}`,
                slot: "only-lower",
                kind: "adjacent",
                symbol: "→"
            }
        ];
    }
    if (panes.length === 3) {
        return [
            {
                sourceId: panes[1].id,
                targetId: panes[0].id,
                label: `${panes[1].label} 覆盖${panes[0].label}`,
                slot: "left-upper",
                kind: "adjacent",
                symbol: "←"
            },
            {
                sourceId: panes[0].id,
                targetId: panes[1].id,
                label: `${panes[0].label} 覆盖${panes[1].label}`,
                slot: "left-middle",
                kind: "adjacent",
                symbol: "→"
            },
            {
                sourceId: panes[2].id,
                targetId: panes[0].id,
                label: `${panes[2].label} 覆盖${panes[0].label}`,
                slot: "left-lower",
                kind: "folded",
                symbol: "└←"
            },
            {
                sourceId: panes[2].id,
                targetId: panes[1].id,
                label: `${panes[2].label} 覆盖${panes[1].label}`,
                slot: "right-upper",
                kind: "adjacent",
                symbol: "←"
            },
            {
                sourceId: panes[1].id,
                targetId: panes[2].id,
                label: `${panes[1].label} 覆盖${panes[2].label}`,
                slot: "right-middle",
                kind: "adjacent",
                symbol: "→"
            },
            {
                sourceId: panes[0].id,
                targetId: panes[2].id,
                label: `${panes[0].label} 覆盖${panes[2].label}`,
                slot: "right-lower",
                kind: "folded",
                symbol: "→┘"
            }
        ];
    }
    return [];
}
```

`renderInlineCompareControls()` may produce static button markup because pane ids are fixed internal identifiers, but it must assign labels with DOM text/attributes rather than raw backend HTML. `startHoldCompare()` must copy the source image's current `src`, size, and transform into a temporary layer attached to the target viewport. `stopHoldCompare()` must remove that layer and reset the button's active and `aria-pressed` state on pointer release, keyboard release, pointer cancel, window blur, and overlay close.

- [ ] **Step 5: Run targeted tests and existing XSS contracts**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui tests.test_dashboard_export_ui tests.test_task_0_review_fixes -v
```

Expected: PASS. The existing dynamic-renderer test must continue to confirm that `openPreview` and `openSinglePreview` contain neither `innerHTML` nor inline `onclick=` construction.

- [ ] **Step 6: Commit Task 3**

```bash
git add tests/test_dashboard_image_preview_ui.py templates/dashboard.html
git commit -m "feat: compare dashboard detail previews"
```

---

### Task 4: Loading Failures, Stale Render Cleanup, Responsive Verification, and Regression Suite

**Files:**
- Modify: `tests/test_dashboard_image_preview_ui.py`
- Modify: `templates/dashboard.html:358-400`
- Modify: `templates/dashboard.html:774-810`
- Modify: `templates/dashboard.html:1753-1800`

**Interfaces:**
- Consumes: Tasks 1–3 overlay renderer, render generations, pointer cleanup map, magnifier layers, and hold comparison state.
- Produces: `beginDashboardPreviewRender()`, `isDashboardPreviewRenderCurrent(generation)`, `markPreviewPaneFailed(groupId, paneId)`, `closeImagePreview()`, idempotent overlay event binding, and resize refresh.

- [ ] **Step 1: Add failing lifecycle and edge-state tests**

Append:

```python
    def test_preview_lifecycle_has_loading_failure_and_stale_guards(self):
        for marker in (
            "function beginDashboardPreviewRender(",
            "function isDashboardPreviewRenderCurrent(",
            "function markPreviewPaneFailed(",
            'classList.remove("loading")',
            'classList.add("failed")',
            "function closeImagePreview(",
            'setAttribute("aria-hidden", "true")',
            'addEventListener("resize"',
        ):
            self.assertIn(marker, self.html)

    def test_close_cleans_every_transient_preview_resource(self):
        source = self.function_source("closeImagePreview")
        for marker in (
            'releasePreviewPointers("overlay")',
            "hidePreviewMagnifiers()",
            "stopHoldCompare()",
            'previewController.groups.delete("overlay")',
            "replaceChildren()",
        ):
            self.assertIn(marker, source)

    def test_overlay_click_and_escape_close_only_preview(self):
        self.assertIn('event.target === overlay', self.html)
        self.assertIn('event.key === "Escape"', self.html)
        close_source = self.function_source("closeImagePreview")
        self.assertNotIn("closeModal(", close_source)
        self.assertNotIn('detail-modal', close_source)
        self.assertNotIn('badcase-modal', close_source)

    def test_responsive_overlay_keeps_single_column_and_bottom_tools(self):
        self.assertIn("@media (max-width: 760px)", self.html)
        self.assertIn("grid-template-columns: 1fr", self.html)
        self.assertIn("overflow-x: auto", self.html)
        self.assertIn("100dvh", self.html)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m unittest tests.test_dashboard_image_preview_ui -v
```

Expected: FAIL until lifecycle hooks and edge states are complete.

- [ ] **Step 3: Implement generation guards and failure exclusion**

Use one monotonic counter:

```javascript
let dashboardPreviewGeneration = 0;

function beginDashboardPreviewRender() {
    dashboardPreviewGeneration += 1;
    return dashboardPreviewGeneration;
}

function isDashboardPreviewRenderCurrent(generation) {
    return dashboardPreviewGeneration === generation;
}

function markPreviewPaneFailed(groupId, paneId) {
    const pane = previewController.groups.get(groupId)?.panes.get(paneId);
    if (pane) pane.failed = true;
}
```

For each image, register `load` and `error` callbacks capturing the current generation. Ignore callbacks if `isDashboardPreviewRenderCurrent(generation)` is false. On load, remove `loading` and register the pane. On error, remove `loading`, add `failed`, reveal the error message, and call `markPreviewPaneFailed()` if the pane was already registered.

- [ ] **Step 4: Implement idempotent close and global lifecycle bindings**

`closeImagePreview()` must be safe when the overlay is already closed:

```javascript
function closeImagePreview() {
    beginDashboardPreviewRender();
    releasePreviewPointers("overlay");
    hidePreviewMagnifiers();
    stopHoldCompare();
    previewController.groups.delete("overlay");
    document.getElementById("dashboard-preview-toolbar").replaceChildren();
    document.getElementById("image-preview").replaceChildren();
    const overlay = document.getElementById("image-overlay");
    overlay.style.display = "none";
    overlay.setAttribute("aria-hidden", "true");
}
```

Bind the overlay backdrop and `[data-preview-close]` once during page initialization. Backdrop clicks close only when `event.target === overlay`. The document Escape handler calls only `closeImagePreview()`. Add a debounced or animation-frame resize handler that calls `previewController.refreshGroup("overlay")` only while the overlay group exists.

- [ ] **Step 5: Run all automated verification**

Run:

```bash
python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests PASS; `git diff --check` prints no output and exits `0`.

- [ ] **Step 6: Perform browser smoke verification**

Run the app:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

Verify at `http://127.0.0.1:8000/dashboard`:

1. T2I detail opens A/B with equal-width panes, synchronized zoom/pan, and two-way hold comparison.
2. TI2I detail opens Ref/A/B when Ref exists, with synchronized zoom/pan and six directional comparison controls.
3. TI2I detail without Ref falls back to A/B and retains the actual model labels.
4. Bad-case preview opens only the clicked image and has no sync or comparison button.
5. All preview types support wheel zoom, drag pan, four display modes, magnifier, background, reset, `+`/`-`, and `Esc`.
6. Closing the overlay leaves the detail or bad-case filter modal open underneath.
7. Reopening another row does not show the previous row, comparison layer, magnifier, or zoom state.
8. At a viewport below `760px`, panes stack vertically and the toolbar is usable at the bottom.

- [ ] **Step 7: Commit Task 4**

```bash
git add tests/test_dashboard_image_preview_ui.py templates/dashboard.html
git commit -m "fix: harden dashboard preview lifecycle"
```
