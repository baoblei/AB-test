# 高清预览完整浅色主题修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让评测界面和看板界面的高清预览在切换到浅色时，遮罩、弹窗、标题、内容区、pane、媒体留白、工具栏及提示全部使用浅色主题，并可可靠切回深色。

**Architecture:** 保留两个模板各自的 `PreviewController.darkBackground` 作为唯一状态源，在每个模板内增加一个小型主题同步函数，将状态投射到高清预览根节点和现有 pane。根节点使用语义化 CSS 变量为所有后代提供背景、文字、边框和浮层颜色；动态 pane 通过继承变量自动获得正确主题。

**Tech Stack:** Python `unittest`、Node.js 运行时探针、Headless Chrome/Chromium 计算样式探针、内嵌 HTML/CSS/JavaScript

## Global Constraints

- 浅色主题覆盖遮罩、弹窗、标题与 Prompt、内容区、pane 标题、媒体留白、工具栏、提示文字、边框和加载/错误提示。
- 图片和视频画面本身不做颜色变换。
- 视频播放控件与放大镜等小型交互浮层可以保留必要的半透明对比底色，但不得形成大面积固定深色背景。
- 普通评测区现有的单个图片背景切换行为保持兼容。
- 不修改后端接口、预览缩放/同步状态结构或媒体数据流。
- 不抽取跨模板公共前端组件，不修改未跟踪的 `database.db`。

## File Structure

- `tests/test_evaluation_preview_ui.py`：新增评测高清预览主题状态与计算样式回归测试。
- `templates/index.html`：同步评测高清预览根节点主题，并用 CSS 变量覆盖完整弹窗表面。
- `tests/test_dashboard_image_preview_ui.py`：新增看板高清预览主题状态、关闭清理与计算样式回归测试。
- `templates/dashboard.html`：同步看板高清预览根节点主题，并用 CSS 变量覆盖完整覆盖层表面。

---

### Task 1: 评测界面高清预览完整浅色主题

**Files:**
- Modify: `tests/test_evaluation_preview_ui.py`
- Modify: `templates/index.html:214-420`
- Modify: `templates/index.html:738-825`
- Modify: `templates/index.html:2175-2295`
- Modify: `templates/index.html:2520-2538`
- Modify: `templates/index.html:2753-2760`

**Interfaces:**
- Consumes: `previewController.groups.get(groupId).darkBackground: boolean`
- Produces: `applyPreviewBackgroundTheme(groupId: string): void`
- Produces: `#lightbox.preview-light-theme` as the single CSS scope for the complete light theme

- [ ] **Step 1: Add failing JavaScript state regression test**

Add this test beside the existing background-tool contract tests in `tests/test_evaluation_preview_ui.py`:

```python
def test_lightbox_background_toggle_updates_root_theme_and_is_reversible(self):
    source = self.html[
        self.html.index("function applyPreviewBackgroundTheme("):
        self.html.index("function renderMagnifier(")
    ]
    script = f"""
{source}
const classes = initial => {{
    const values = new Set(initial);
    return {{
        contains: name => values.has(name),
        toggle(name, enabled) {{
            enabled ? values.add(name) : values.delete(name);
            return enabled;
        }}
    }};
}};
const pane = {{ classList: classes(["preview-dark"]) }};
const root = {{ classList: classes([]) }};
const button = {{
    textContent: "深色背景",
    classList: classes(["active"]),
    setAttribute() {{}},
    querySelector: () => null
}};
const group = {{ darkBackground: true }};
const previewController = {{ groups: new Map([["lightbox", group]]) }};
const document = {{
    getElementById: id => id === "lightbox" ? root : null,
    querySelectorAll: () => [pane],
    querySelector: () => button
}};
togglePreviewBackground("lightbox");
const light = {{
    darkBackground: group.darkBackground,
    rootLight: root.classList.contains("preview-light-theme"),
    paneDark: pane.classList.contains("preview-dark")
}};
togglePreviewBackground("lightbox");
console.log(JSON.stringify({{
    light,
    dark: {{
        darkBackground: group.darkBackground,
        rootLight: root.classList.contains("preview-light-theme"),
        paneDark: pane.classList.contains("preview-dark")
    }}
}}));
"""
    result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
    self.assertEqual(result, {
        "light": {"darkBackground": False, "rootLight": True, "paneDark": False},
        "dark": {"darkBackground": True, "rootLight": False, "paneDark": True},
    })
```

- [ ] **Step 2: Run the JavaScript regression test and verify RED**

Run:

```bash
python3 -m unittest tests/test_evaluation_preview_ui.py -v
```

Expected: FAIL in `test_lightbox_background_toggle_updates_root_theme_and_is_reversible` because `function applyPreviewBackgroundTheme(` and the root theme synchronization do not exist.

- [ ] **Step 3: Add failing complete-surface CSS contract test**

Add this test after the JavaScript test:

```python
def test_lightbox_light_theme_defines_every_visible_surface(self):
    light_rule = self.css_rule(".lightbox.preview-light-theme")
    for declaration in (
        "--preview-overlay-bg: #edf1f5",
        "--preview-surface-bg: #ffffff",
        "--preview-panel-bg: #f8fafc",
        "--preview-media-bg: #f1f4f7",
        "--preview-text: #253245",
        "--preview-muted-text: #5d6b7e",
        "--preview-border: #d7dee7",
    ):
        self.assertIn(declaration, light_rule)

    expected_consumers = {
        ".lightbox": "background: var(--preview-overlay-bg)",
        ".lightbox-dialog": "background: var(--preview-surface-bg)",
        ".lightbox-head": "color: var(--preview-text)",
        ".lightbox-prompt": "color: var(--preview-muted-text)",
        ".lightbox-grid": "background: var(--preview-border)",
        ".pane": "background: var(--preview-surface-bg)",
        ".pane-head": "color: var(--preview-text)",
        ".pane-body": "background: var(--preview-media-bg)",
    }
    for selector, declaration in expected_consumers.items():
        self.assertIn(declaration, self.css_rule(selector))

    self.assertIn(
        "background: var(--preview-panel-bg)",
        self.css_rule(".lightbox .preview-toolbar"),
    )
    self.assertIn(
        "background: var(--preview-media-bg)",
        self.css_rule(".lightbox .video-shell video"),
    )
```

Also add `shutil`, `tempfile`, and `HTMLParser` imports, then add this parser and browser helper so the regression verifies browser-computed colors rather than source text alone:

```python
class StyleResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capturing = False
        self.value = ""

    def handle_starttag(self, tag, attrs):
        if dict(attrs).get("id") == "style-result":
            self.capturing = True

    def handle_endtag(self, tag):
        if self.capturing:
            self.capturing = False

    def handle_data(self, data):
        if self.capturing:
            self.value += data
```

```python
def run_browser_style_probe(self, body, scenario):
    chrome = next((candidate for candidate in (
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ) if candidate and Path(candidate).exists()), None)
    if not chrome:
        self.skipTest("Chrome/Chromium is required for browser style coverage")
    style_start = self.html.index("<style>") + len("<style>")
    style_end = self.html.index("</style>", style_start)
    page = f'''<!doctype html><html><head><meta charset="utf-8">
<style>{self.html[style_start:style_end]}</style></head><body>{body}
<pre id="style-result"></pre><script>
document.getElementById("style-result").textContent = JSON.stringify((() => {{ {scenario} }})());
</script></body></html>'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "probe.html"
        path.write_text(page, encoding="utf-8")
        result = subprocess.run([
            chrome,
            "--headless=new",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-gpu",
            "--no-sandbox",
            "--dump-dom",
            path.as_uri(),
        ], check=True, capture_output=True, text=True, timeout=20)
    parser = StyleResultParser()
    parser.feed(result.stdout)
    parser.close()
    self.assertTrue(parser.value, result.stderr or result.stdout[-2000:])
    return json.loads(parser.value)
```

Add the computed-style assertion:

```python
def test_lightbox_light_theme_computes_light_colors_for_all_major_surfaces(self):
    body = '''
<div id="lightbox" class="lightbox open preview-light-theme">
  <div class="lightbox-dialog preview-stage">
    <div class="lightbox-head"><div><div id="lightbox-prompt" class="lightbox-prompt">Prompt</div></div></div>
    <div id="lightbox-preview-toolbar"><div class="preview-toolbar"><div class="preview-info">Info</div></div></div>
    <div id="lightbox-grid" class="lightbox-grid preview-viewport t2i">
      <div class="pane"><div class="pane-head">A</div><div class="pane-body video-shell"><video></video></div></div>
    </div>
  </div>
</div>'''
    result = self.run_browser_style_probe(body, '''
const color = selector => getComputedStyle(document.querySelector(selector)).backgroundColor;
return {
  overlay: color("#lightbox"),
  dialog: color(".lightbox-dialog"),
  grid: color(".lightbox-grid"),
  pane: color(".pane"),
  media: color(".pane-body"),
  video: color("video"),
  toolbar: color(".preview-toolbar")
};''')
    self.assertEqual(result, {
        "overlay": "rgb(237, 241, 245)",
        "dialog": "rgb(255, 255, 255)",
        "grid": "rgb(215, 222, 231)",
        "pane": "rgb(255, 255, 255)",
        "media": "rgb(241, 244, 247)",
        "video": "rgb(241, 244, 247)",
        "toolbar": "rgb(248, 250, 252)",
    })
```

- [ ] **Step 4: Run the CSS contract and verify RED**

Run:

```bash
python3 -m unittest tests/test_evaluation_preview_ui.py -v
```

Expected: FAIL because `.lightbox.preview-light-theme` and the theme-variable consumers are missing; the browser probe still computes the current dark colors.

- [ ] **Step 5: Implement the minimal evaluation theme variables and state projection**

In `templates/index.html`, define the dark defaults on `.lightbox`, add the light override, and replace the fixed colors in the listed consumers:

```css
.lightbox {
    --preview-overlay-bg: rgba(15, 12, 10, 0.9);
    --preview-surface-bg: rgba(31, 24, 19, 0.96);
    --preview-panel-bg: rgba(255, 253, 248, 0.96);
    --preview-media-bg: #171310;
    --preview-text: #ffffff;
    --preview-muted-text: rgba(255, 255, 255, 0.82);
    --preview-border: rgba(255, 255, 255, 0.08);
    /* keep the existing positioning declarations */
    background: var(--preview-overlay-bg);
}
.lightbox.preview-light-theme {
    --preview-overlay-bg: #edf1f5;
    --preview-surface-bg: #ffffff;
    --preview-panel-bg: #f8fafc;
    --preview-media-bg: #f1f4f7;
    --preview-text: #253245;
    --preview-muted-text: #5d6b7e;
    --preview-border: #d7dee7;
}
.lightbox-dialog { background: var(--preview-surface-bg); }
.lightbox-head {
    color: var(--preview-text);
    border-bottom-color: var(--preview-border);
}
.lightbox-prompt { color: var(--preview-muted-text); }
.lightbox-grid { background: var(--preview-border); }
.pane { background: var(--preview-surface-bg); }
.pane-head { color: var(--preview-text); }
.pane-body { background: var(--preview-media-bg); }
.lightbox .preview-toolbar {
    color: var(--preview-text);
    background: var(--preview-panel-bg);
    border-color: var(--preview-border);
}
.lightbox .preview-shortcut-help,
.lightbox .preview-info {
    color: var(--preview-muted-text);
    background: var(--preview-panel-bg);
}
.lightbox .image-loading,
.lightbox .preview-loading,
.lightbox .image-error-message { color: var(--preview-muted-text); }
.lightbox .video-shell video { background: var(--preview-media-bg); }
```

Add the state projection immediately before `togglePreviewBackground` and use it from both toggle and bind paths:

```javascript
function applyPreviewBackgroundTheme(groupId) {
    const group = previewController.groups.get(groupId);
    if (!group) return;
    document.querySelectorAll(`[data-preview-group-pane="${groupId}"]`).forEach(pane => {
        pane.classList.toggle("preview-dark", group.darkBackground);
    });
    if (groupId === "lightbox") {
        document.getElementById("lightbox")?.classList.toggle(
            "preview-light-theme",
            !group.darkBackground
        );
    }
}

function togglePreviewBackground(groupId) {
    const group = previewController.groups.get(groupId);
    if (!group) return;
    group.darkBackground = !group.darkBackground;
    applyPreviewBackgroundTheme(groupId);
    const button = document.querySelector(`[data-preview-group="${groupId}"] [data-preview-action="background"]`);
    if (button) {
        const label = group.darkBackground ? "深色背景" : "浅色背景";
        button.classList.toggle("active", group.darkBackground);
        button.setAttribute("aria-pressed", String(group.darkBackground));
        button.setAttribute("aria-label", label);
        button.setAttribute("title", label);
        const labelNode = button.querySelector ? button.querySelector(".preview-tool-label") : null;
        if (labelNode) labelNode.textContent = label;
        else button.textContent = label;
    }
}
```

At the start of `bindPreviewGroup(groupId, generation)`, call `applyPreviewBackgroundTheme(groupId)` once and remove the duplicated per-container `preview-dark` toggle from inside the loop.

- [ ] **Step 6: Run evaluation preview tests and verify GREEN**

Run:

```bash
python3 -m unittest tests/test_evaluation_preview_ui.py -v
```

Expected: PASS with all evaluation preview tests green and no Node errors.

- [ ] **Step 7: Commit the evaluation half**

```bash
git add templates/index.html tests/test_evaluation_preview_ui.py
git commit -m "fix: theme entire evaluation preview"
```

---

### Task 2: 看板界面高清预览完整浅色主题

**Files:**
- Modify: `tests/test_dashboard_image_preview_ui.py`
- Modify: `templates/dashboard.html:373-575`
- Modify: `templates/dashboard.html:1530-1585`
- Modify: `templates/dashboard.html:2711-2740`
- Modify: `templates/dashboard.html:3082-3125`

**Interfaces:**
- Consumes: `previewController.groups.get(groupId).darkBackground: boolean`
- Produces: `applyDashboardPreviewBackgroundTheme(groupId: string): void`
- Produces: `#image-overlay.preview-light-theme` as the single CSS scope for the complete light theme

- [ ] **Step 1: Add failing look-and-lifecycle regression tests**

Replace the helper signature and its first overlay replacement with the following exact code so tests can opt into a root theme class:

```python
def production_dashboard_overlay_markup(
    self,
    toolbar="",
    grid_class="single",
    grid_content="",
    stage_classes=(),
    overlay_classes=(),
):
    overlay_start = self.html.index('<div id="image-overlay"')
    overlay_end = self.html.index("\n\n    <script>", overlay_start)
    body = self.html[overlay_start:overlay_end]
    self.assertIn('<div id="image-overlay"', body)
    self.assertIn('class="dashboard-preview-stage"', body)
    self.assertIn('<div class="dashboard-preview-content">', body)
    self.assertIn('<div id="dashboard-preview-toolbar"></div>', body)
    self.assertIn(
        '<div class="dashboard-preview-grid single" id="image-preview"></div>', body
    )
    overlay_class = f' class="{" ".join(overlay_classes)}"' if overlay_classes else ""
    body = body.replace(
        '<div id="image-overlay"',
        f'<div id="image-overlay"{overlay_class} style="display:flex"',
        1,
    )
    body = body.replace(
        'class="dashboard-preview-stage"',
        f'class="dashboard-preview-stage{" " if stage_classes else ""}{" ".join(stage_classes)}"',
        1,
    )
    body = body.replace(
        '<div id="dashboard-preview-toolbar"></div>',
        f'<div id="dashboard-preview-toolbar">{toolbar}</div>',
        1,
    )
    body = body.replace(
        '<div class="dashboard-preview-grid single" id="image-preview"></div>',
        f'<div class="dashboard-preview-grid {grid_class}" id="image-preview">{grid_content}</div>',
        1,
    )
    return body
```

Then add:

```python
def test_dashboard_light_theme_covers_overlay_stage_grid_viewport_and_toolbar(self):
    toolbar = self.render_toolbar_markup(show_sync=True)
    body = self.production_dashboard_overlay_markup(
        toolbar=toolbar,
        grid_content='<section class="dashboard-preview-viewport"><video></video><strong class="dashboard-preview-label">A</strong></section>',
        overlay_classes=("preview-light-theme",),
    )
    result = self.run_browser_geometry_probe(body, """
const color = selector => getComputedStyle(document.querySelector(selector)).backgroundColor;
return {
    overlay: color("#image-overlay"),
    stage: color(".dashboard-preview-stage"),
    grid: color(".dashboard-preview-grid"),
    viewport: color(".dashboard-preview-viewport"),
    video: color(".dashboard-preview-viewport video"),
    toolbar: color(".dashboard-preview-toolbar")
};
""")
    self.assertEqual(result, {
        "overlay": "rgb(237, 241, 245)",
        "stage": "rgb(255, 255, 255)",
        "grid": "rgb(255, 255, 255)",
        "viewport": "rgb(241, 244, 247)",
        "video": "rgb(241, 244, 247)",
        "toolbar": "rgb(248, 250, 252)",
    })

def test_close_removes_dashboard_light_theme(self):
    source = self.function_source("closeImagePreview")
    self.assertIn('overlay.classList.remove("preview-light-theme")', source)
```

- [ ] **Step 2: Run dashboard tests and verify RED**

Run:

```bash
python3 -m unittest tests/test_dashboard_image_preview_ui.py -v
```

Expected: FAIL because `overlay_classes` is not represented in the markup, the computed colors remain dark, and close does not remove `preview-light-theme`.

- [ ] **Step 3: Add failing JavaScript state projection test**

Add:

```python
def test_dashboard_background_projection_updates_root_and_panes(self):
    self.assertIn("function applyDashboardPreviewBackgroundTheme(groupId)", self.html)
    source = self.function_source("applyDashboardPreviewBackgroundTheme")
    self.assertIn('getElementById("image-overlay")', source)
    self.assertIn('"preview-light-theme"', source)
    self.assertIn('"preview-light"', source)
    toolbar_source = self.function_source("bindDashboardPreviewToolbar")
    self.assertIn("applyDashboardPreviewBackgroundTheme(groupId)", toolbar_source)
    open_source = self.function_source("openDashboardPreview")
    self.assertIn('applyDashboardPreviewBackgroundTheme("overlay")', open_source)
```

- [ ] **Step 4: Run dashboard tests and confirm the new projection test is RED**

Run:

```bash
python3 -m unittest tests/test_dashboard_image_preview_ui.py -v
```

Expected: FAIL because `applyDashboardPreviewBackgroundTheme` is absent.

- [ ] **Step 5: Implement dashboard root variables and state projection**

Replace fixed preview colors with variables scoped to `#image-overlay`:

```css
#image-overlay {
    --preview-overlay-bg: rgba(5, 9, 15, 0.96);
    --preview-surface-bg: #111820;
    --preview-panel-bg: rgba(17, 24, 32, 0.9);
    --preview-media-bg: #0b1016;
    --preview-text: #ffffff;
    --preview-muted-text: #dceaf4;
    --preview-border: rgba(255, 255, 255, 0.18);
    /* keep the existing positioning declarations */
    background: var(--preview-overlay-bg);
}
#image-overlay.preview-light-theme {
    --preview-overlay-bg: #edf1f5;
    --preview-surface-bg: #ffffff;
    --preview-panel-bg: #f8fafc;
    --preview-media-bg: #f1f4f7;
    --preview-text: #253245;
    --preview-muted-text: #5d6b7e;
    --preview-border: #d7dee7;
}
.dashboard-preview-stage {
    color: var(--preview-text);
    background: var(--preview-surface-bg);
}
.preview-prompt { color: var(--preview-muted-text); }
.dashboard-preview-content,
.dashboard-preview-grid { background: var(--preview-surface-bg); }
.dashboard-preview-toolbar {
    color: var(--preview-text);
    background: var(--preview-panel-bg);
    border-color: var(--preview-border);
}
.preview-tool { color: var(--preview-text); }
.preview-tool:hover,
.preview-tool.active { color: #ffffff; }
.preview-info,
.preview-shortcut-help {
    color: var(--preview-muted-text);
    background: var(--preview-panel-bg);
}
.dashboard-preview-viewport,
.dashboard-preview-viewport.preview-light,
.dashboard-preview-viewport video { background: var(--preview-media-bg); }
.dashboard-preview-loading,
.dashboard-preview-error,
.dashboard-preview-label {
    color: var(--preview-text);
    background: var(--preview-panel-bg);
}
```

Add the projection function before `bindDashboardPreviewToolbar`:

```javascript
function applyDashboardPreviewBackgroundTheme(groupId) {
    const group = previewController.groups.get(groupId);
    if (!group) return;
    const light = !group.darkBackground;
    document.querySelectorAll(`[data-preview-group-pane="${groupId}"]`).forEach(viewport => {
        viewport.classList.toggle("preview-light", light);
    });
    if (groupId === "overlay") {
        document.getElementById("image-overlay")?.classList.toggle("preview-light-theme", light);
    }
}
```

Replace the background action body with:

```javascript
if (action === "background") {
    group.darkBackground = !group.darkBackground;
    applyDashboardPreviewBackgroundTheme(groupId);
}
```

Immediately after `createPreviewGroup("overlay", { sync: normalized.showSync });` in `openDashboardPreview`, call `applyDashboardPreviewBackgroundTheme("overlay")`. In `closeImagePreview`, remove the root class before hiding the overlay:

```javascript
const overlay = document.getElementById("image-overlay");
overlay.classList.remove("preview-light-theme");
overlay.style.display = "none";
overlay.setAttribute("aria-hidden", "true");
```

For every existing test double representing `#image-overlay`, add this exact minimal property so the new projection and close paths exercise real class operations without changing unrelated assertions:

```javascript
classList: {
    toggle() {},
    remove() {}
},
```

- [ ] **Step 6: Run dashboard preview tests and verify GREEN**

Run:

```bash
python3 -m unittest tests/test_dashboard_image_preview_ui.py -v
```

Expected: PASS, including the headless Chrome computed-style assertions.

- [ ] **Step 7: Commit the dashboard half**

```bash
git add templates/dashboard.html tests/test_dashboard_image_preview_ui.py
git commit -m "fix: theme entire dashboard preview"
```

---

### Task 3: 交叉回归与最终验证

**Files:**
- Verify: `templates/index.html`
- Verify: `templates/dashboard.html`
- Verify: `tests/test_evaluation_preview_ui.py`
- Verify: `tests/test_dashboard_image_preview_ui.py`

**Interfaces:**
- Consumes: both root theme projection functions and their tests
- Produces: verified reversible theme behavior with no unrelated file changes

- [ ] **Step 1: Run both focused suites together**

```bash
python3 -m unittest tests/test_evaluation_preview_ui.py tests/test_dashboard_image_preview_ui.py -v
```

Expected: PASS with zero failures and zero errors.

- [ ] **Step 2: Run the complete Python suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS with zero failures and zero errors.

- [ ] **Step 3: Run repository whitespace and change-scope checks**

```bash
git diff --check
git status --short
git diff --stat 566053c..HEAD
```

Expected: no whitespace errors; `database.db` remains untracked and unchanged; implementation changes are limited to the two templates and two preview test files plus this plan.

- [ ] **Step 4: Inspect change impact with GitNexus fallback noted**

GitNexus has no index for this repository, so run direct reference checks:

```bash
rg -n "applyPreviewBackgroundTheme|applyDashboardPreviewBackgroundTheme|preview-light-theme" templates tests
```

Expected: every helper is defined once, called by its toggle path, synchronized during open/bind, and asserted by its matching tests.

- [ ] **Step 5: Review the final diff against the design**

```bash
git diff 566053c..HEAD -- templates/index.html templates/dashboard.html tests/test_evaluation_preview_ui.py tests/test_dashboard_image_preview_ui.py
```

Expected: every production change maps to full-surface theme styling, state projection, or lifecycle cleanup; no backend or unrelated UI changes appear.
