# Evaluation Image Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ref/A/B images fill the available evaluation viewport consistently and add shared synchronized inspection tools to both the main page and fullscreen preview.

**Architecture:** Keep the existing dependency-free single-page template, but replace the lightbox-only zoom globals with a reusable `PreviewController` that owns one state record per preview group. Main and fullscreen stages register the same event model, using normalized image centers so different source resolutions stay aligned.

**Tech Stack:** FastAPI/Jinja HTML template, vanilla CSS and JavaScript, Python `unittest`, Node.js runtime probes.

## Global Constraints

- Do not change evaluation task, vote, bad-case, or backend API behavior.
- Preserve image aspect ratio without cropping or stretching.
- Synchronization is enabled by default after every task change.
- Desktop tools float on the right; narrow-screen tools become a bottom horizontal bar.
- Existing `1 / 2 / 3 / Enter` scoring shortcuts remain unchanged.
- Add no third-party frontend dependency.

---

### Task 1: Preview Contract and Responsive Layout

**Files:**
- Create: `tests/test_evaluation_preview_ui.py`
- Modify: `templates/index.html:1`

**Interfaces:**
- Consumes: existing `renderCompareGrid()`, `renderImageCard()`, and lightbox markup.
- Produces: `.preview-stage`, `.preview-toolbar`, `.preview-viewport`, `[data-preview-action]`, and `renderPreviewToolbar(groupId, compact)` markup used by later tasks.

- [ ] **Step 1: Write failing structural tests**

```python
import unittest
from pathlib import Path


class EvaluationPreviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/index.html").read_text(encoding="utf-8")

    def test_shared_preview_controls_exist(self):
        for marker in (
            'class="preview-toolbar',
            'data-preview-action="sync"',
            'data-preview-action="fit"',
            'data-preview-action="fit-width"',
            'data-preview-action="fit-height"',
            'data-preview-action="actual"',
            'data-preview-action="magnifier"',
            'data-preview-action="reset"',
            'data-preview-action="background"',
            'data-preview-action="fullscreen"',
        ):
            self.assertIn(marker, self.html)

    def test_preview_layout_uses_equal_columns_and_viewport_height(self):
        self.assertIn("repeat(3, minmax(0, 1fr))", self.html)
        self.assertIn("clamp(360px", self.html)
        self.assertIn("100dvh", self.html)

    def test_reference_image_can_open_fullscreen_preview(self):
        self.assertIn('renderImageCard("reference", "参考图", task.ref_img, true)', self.html)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_evaluation_preview_ui -v`

Expected: FAIL because shared toolbar markers and equal-height stage rules do not exist.

- [ ] **Step 3: Add responsive preview layout and toolbar markup**

Implement CSS rules in `templates/index.html` with these exact responsibilities:

```css
.main { max-width: 1920px; padding-inline: clamp(10px, 1.4vw, 24px); }
.compare-grid.ti2i { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.preview-stage { position: relative; }
.preview-viewport { height: clamp(360px, calc(100dvh - 270px), 820px); overflow: hidden; }
.preview-toolbar { position: fixed; right: 18px; top: 50%; z-index: 35; }
@media (max-width: 760px) {
  .preview-toolbar { top: auto; right: 10px; bottom: 10px; left: 10px; overflow-x: auto; }
}
```

Add `renderPreviewToolbar(groupId, compact)` and render it once for `main` and once for `lightbox`. Change the reference card call to pass `true` for fullscreen availability.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m unittest tests.test_evaluation_preview_ui -v`

Expected: PASS.

---

### Task 2: Shared Synchronized Preview Controller

**Files:**
- Modify: `tests/test_evaluation_preview_ui.py`
- Modify: `templates/index.html:620`

**Interfaces:**
- Consumes: preview group elements carrying `data-preview-group` and image panes carrying `data-preview-pane`.
- Produces: `PreviewController`, `createPreviewGroup(groupId)`, `setPreviewMode(groupId, mode)`, `setPreviewZoom(groupId, paneId, zoom, anchor)`, `setPreviewCenter(groupId, paneId, center)`, and `resetPreviewGroup(groupId)`.

- [ ] **Step 1: Add failing controller contract and runtime tests**

Add tests asserting the source contains:

```python
for marker in (
    "class PreviewController",
    "normalizedCenter",
    "sync: true",
    "fit-width",
    "fit-height",
    "actual",
    "resetGroup(",
):
    self.assertIn(marker, self.html)
```

Add a Node probe that constructs the controller with two pane adapters of different natural sizes, updates pane A to normalized center `{x: 0.7, y: 0.35}`, and asserts pane B receives the same normalized center while sync is enabled but remains unchanged after sync is disabled.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_evaluation_preview_ui -v`

Expected: FAIL because `PreviewController` is absent.

- [ ] **Step 3: Implement minimal shared controller**

Implement a dependency-free controller with this state shape:

```javascript
class PreviewController {
    constructor() { this.groups = new Map(); }
    createGroup(groupId) {
        this.groups.set(groupId, {
            mode: "fit",
            sync: true,
            magnifier: false,
            darkBackground: true,
            zoom: 1,
            normalizedCenter: { x: 0.5, y: 0.5 },
            panes: new Map()
        });
    }
}
```

Calculate fit scales from viewport and natural dimensions, clamp zoom to `0.1`–`12`, synchronize normalized center and zoom when `sync` is true, and constrain pan so an image cannot be moved completely outside its viewport. Replace `lightboxZoom`, `lightboxPan`, `setZoom`, and `resetZoom` with controller calls.

- [ ] **Step 4: Run targeted tests**

Run: `python -m unittest tests.test_evaluation_preview_ui tests.test_frontend_time_contract -v`

Expected: PASS, including existing task timing and action guards.

---

### Task 3: Pointer, Magnifier, Fullscreen, and Keyboard Tools

**Files:**
- Modify: `tests/test_evaluation_preview_ui.py`
- Modify: `templates/index.html:408`

**Interfaces:**
- Consumes: `PreviewController` group state from Task 2.
- Produces: `bindPreviewGroup(groupId)`, `togglePreviewMagnifier(groupId)`, `renderMagnifier(groupId, paneId, point)`, `togglePreviewBackground(groupId)`, and `openLightbox(sourcePaneId)`.

- [ ] **Step 1: Add failing interaction tests**

Assert the template contains wheel and pointer bindings, `pointermove` magnifier handling, the `Space` temporary-pan flag, `+`/`-` preview shortcuts, an image information label, and guards that skip keyboard handling for `INPUT`, `SELECT`, and `TEXTAREA` targets.

Add a source-level assertion that the existing scoring handler still includes keys `1`, `2`, `3`, and `Enter`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_evaluation_preview_ui -v`

Expected: FAIL because magnifier and shared bindings are absent.

- [ ] **Step 3: Implement pointer and tool behavior**

Bind wheel zoom around the pointer location, pointer drag with capture/release cleanup, and temporary Space-to-pan. Implement one magnifier layer per group using the active image as a background image with a `3×` scale; show correspondence markers on sibling panes using normalized coordinates. Hide all magnifier layers on pointer leave, task change, image error, and lightbox close.

Toolbar actions call controller methods and update `aria-pressed`, active labels, zoom percentage, natural dimensions, and mode text. `openLightbox()` accepts Ref/A/B sources and initializes the fullscreen group to fit mode with synchronization enabled.

- [ ] **Step 4: Run targeted tests**

Run: `python -m unittest tests.test_evaluation_preview_ui tests.test_frontend_time_contract -v`

Expected: PASS.

---

### Task 4: Loading States, Regression Verification, and Documentation

**Files:**
- Modify: `tests/test_evaluation_preview_ui.py`
- Modify: `templates/index.html:880`
- Modify: `README.md:1`

**Interfaces:**
- Consumes: completed preview groups and existing `waitForTaskImages()`.
- Produces: stable loading/error states and user-facing preview shortcut documentation.

- [ ] **Step 1: Add failing edge-state tests**

Assert each preview viewport includes a loading indicator and image error handler, failed panes receive an error class, task loading resets both preview groups, and lightbox close calls pointer/magnifier cleanup.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_evaluation_preview_ui -v`

Expected: FAIL until loading/error/reset hooks exist.

- [ ] **Step 3: Implement edge states and documentation**

Add loading placeholders removed on `load`, readable error placeholders on `error`, and exclude failed panes from synchronized transform updates. Reset the main group in `loadNextTask()` before rendering a new task and dispose transient fullscreen listeners in `closeLightbox()`.

Document in `README.md`:

```markdown
### 图片预览工具

评测页和高清预览支持默认同步的 Ref/A/B 缩放与平移、适应窗口/宽度/高度、1:1、局部放大镜、背景切换和复位。滚轮缩放，拖动平移，空格可临时进入平移模式，`+`/`-` 调整缩放，`Esc` 关闭高清预览。
```

- [ ] **Step 4: Run complete verification**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

Run: `git diff --check`

Expected: no output and exit code `0`.

- [ ] **Step 5: Review the rendered page manually**

Run: `uvicorn main:app --reload`

Verify T2I and TI2I layouts, equal stage sizes, synchronized and unlocked transforms, magnifier edges, Ref fullscreen opening, narrow-screen bottom toolbar, task changes, and failed-image placeholders.

