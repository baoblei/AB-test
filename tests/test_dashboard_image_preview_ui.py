import json
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


class PreviewStageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.onclick = ""
        self.opening_tag = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "div" and "dashboard-preview-stage" in attributes.get("class", "").split():
            self.onclick = attributes.get("onclick", "")
            self.opening_tag = self.get_starttag_text()


class ElementTextParser(HTMLParser):
    def __init__(self, element_id):
        super().__init__()
        self.element_id = element_id
        self.capturing = False
        self.value = ""

    def handle_starttag(self, tag, attrs):
        if dict(attrs).get("id") == self.element_id:
            self.capturing = True

    def handle_endtag(self, tag):
        if self.capturing:
            self.capturing = False

    def handle_data(self, data):
        if self.capturing:
            self.value += data


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

    def render_toolbar_markup(self, show_sync):
        start = self.html.index("function renderDashboardPreviewToolbar(")
        end = self.html.index("function updateDashboardPreviewToolbar(", start)
        source = self.html[start:end]
        script = f"""
{source}
console.log(renderDashboardPreviewToolbar({{ groupId: "overlay", showSync: {str(show_sync).lower()} }}));
"""
        return subprocess.check_output(["node", "-e", script], text=True)

    def run_browser_geometry_probe(self, body, scenario, width=700, height=1000):
        chrome = next((candidate for candidate in (
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ) if candidate and Path(candidate).exists()), None)
        if not chrome:
            self.skipTest("Chrome/Chromium is required for browser geometry coverage")
        style_start = self.html.index("<style>") + len("<style>")
        style_end = self.html.index("</style>", style_start)
        page = f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><style>{self.html[style_start:style_end]}</style></head>
<body>{body}<pre id=\"geometry-result\"></pre><script>
document.getElementById("geometry-result").textContent = JSON.stringify((() => {{ {scenario} }})());
</script></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            page_path = directory / "probe.html"
            page_path.write_text(page, encoding="utf-8")
            result = subprocess.run(
                [
                    chrome,
                    "--headless=new",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-sync",
                    "--disable-breakpad",
                    "--disable-crash-reporter",
                    "--disable-gpu",
                    "--no-sandbox",
                    f"--window-size={width},{height}",
                    "--virtual-time-budget=1000",
                    "--dump-dom",
                    page_path.as_uri(),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
        parser = ElementTextParser("geometry-result")
        parser.feed(result.stdout)
        parser.close()
        self.assertTrue(parser.value, result.stderr or result.stdout[-2000:])
        return json.loads(parser.value)

    def preview_close_source(self):
        start = self.html.find("function closeImagePreview")
        self.assertNotEqual(start, -1, "preview close function is missing")
        end = self.html.index("function buildPreviewPayload", start)
        return self.html[start:end]

    def run_preview_close_probe(self, scenario):
        script = f"{self.preview_close_source()}\n{scenario}"
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def dashboard_preview_lifecycle_source(self):
        start = self.html.index("let dashboardPreviewGeneration")
        end = self.html.index("function openDashboardPreview", start)
        return self.html[start:end]

    def preview_event_delegation_source(self):
        controller_start = self.html.index("class PreviewController")
        toolbar_start = self.html.index("function renderDashboardPreviewToolbar", controller_start)
        return "\n".join((
            self.html[controller_start:toolbar_start],
            self.function_source("updateDashboardPreviewToolbar"),
            self.function_source("bindDashboardPreviewToolbar"),
            self.preview_close_source(),
        ))

    def test_overlay_has_immersive_preview_shell(self):
        for marker in (
            'class="dashboard-preview-stage"',
            'id="dashboard-preview-title"',
            'id="dashboard-preview-toolbar"',
            'class="dashboard-preview-grid',
            'aria-modal="true"',
            'data-preview-close',
        ):
            self.assertIn(marker, self.html)

    def test_delegated_preview_clicks_reach_document_without_closing_stage(self):
        result = self.run_preview_event_delegation_probe(self.preview_stage_opening_tag())
        self.assertEqual(result, {
            "afterContent": {"display": "flex", "ariaHidden": "false"},
            "afterZoom": {"zoom": 1.1, "scales": [0.55]},
            "afterClose": {"display": "none", "ariaHidden": "true"},
        })

    def test_equivalent_inline_stage_handler_blocks_delegated_controls(self):
        result = self.run_preview_event_delegation_probe(
            '<div class="dashboard-preview-stage" onclick=" event . stopPropagation ( ) ; ">'
        )
        self.assertEqual(result, {
            "afterContent": {"display": "flex", "ariaHidden": "false"},
            "afterZoom": {"zoom": 1, "scales": []},
            "afterClose": {"display": "flex", "ariaHidden": "false"},
        })

    def preview_stage_opening_tag(self):
        parser = PreviewStageParser()
        parser.feed(self.html)
        parser.close()
        self.assertTrue(parser.opening_tag, "preview stage is missing")
        return parser.opening_tag

    def preview_stage_inline_handler(self, stage_opening_tag):
        parser = PreviewStageParser()
        parser.feed(stage_opening_tag)
        parser.close()
        return parser.onclick

    def run_preview_event_delegation_probe(self, stage_opening_tag):
        inline_handler = self.preview_stage_inline_handler(stage_opening_tag)
        script = f"""
{self.preview_event_delegation_source()}
const makeNode = (dataset = {{}}, parent = null) => {{
    const node = {{ dataset, parent, style: {{}}, listeners: new Map(), children: [] }};
    node.addEventListener = (type, listener) => {{
        const listeners = node.listeners.get(type) || [];
        listeners.push(listener);
        node.listeners.set(type, listeners);
    }};
    node.closest = selector => {{
        for (let current = node; current; current = current.parent) {{
            if (selector === "[data-preview-action]" && current.dataset.previewAction) return current;
            if (selector === "[data-preview-group]" && current.dataset.previewGroup) return current;
            if (selector === "[data-preview-close]" && current.dataset.previewClose !== undefined) return current;
        }}
        return null;
    }};
    node.replaceChildren = (...children) => {{ node.children = children; }};
    return node;
}};
const document = makeNode();
document.getElementById = id => ids.get(id);
document.querySelector = () => null;
document.querySelectorAll = () => [];
const dispatchClick = target => {{
    const event = {{
        target,
        stopped: false,
        stopPropagation() {{ this.stopped = true; }}
    }};
    for (let current = target; current; current = current.parent) {{
        (current.listeners.get("click") || []).forEach(listener => listener(event));
        if (event.stopped) break;
    }}
}};
const overlay = makeNode({{}}, document);
overlay.style.display = "flex";
overlay.setAttribute = (name, value) => {{ overlay[name] = value; }};
overlay["aria-hidden"] = "false";
const stage = makeNode({{}}, overlay);
const inlineStageHandler = {json.dumps(inline_handler)};
const compiledStageHandler = inlineStageHandler ? new Function("event", inlineStageHandler) : null;
if (compiledStageHandler) stage.addEventListener("click", event => compiledStageHandler.call(stage, event));
const ordinaryContent = makeNode({{}}, stage);
const toolbar = makeNode({{ previewGroup: "overlay" }}, stage);
const zoomButton = makeNode({{ previewAction: "zoom-in" }}, toolbar);
const zoomIcon = makeNode({{}}, zoomButton);
const closeButton = makeNode({{ previewClose: "" }}, stage);
const closeIcon = makeNode({{}}, closeButton);
const toolbarContainer = makeNode();
const imagePreview = makeNode();
const ids = new Map([
    ["image-overlay", overlay],
    ["dashboard-preview-toolbar", toolbarContainer],
    ["image-preview", imagePreview],
]);
const beginDashboardPreviewRender = () => null;
const releasePreviewPointers = () => null;
const hidePreviewMagnifiers = () => null;
const stopHoldCompare = () => null;
const applied = [];
const adapter = {{
    measure: () => ({{ naturalWidth: 1000, naturalHeight: 500, viewportWidth: 500, viewportHeight: 500 }}),
    apply: state => applied.push(state.scale)
}};
previewController.createGroup("overlay", {{ sync: true }});
previewController.addPane("overlay", "left", adapter);
applied.length = 0;
bindDashboardPreviewToolbar();
bindPreviewOverlayEvents();
dispatchClick(ordinaryContent);
const afterContent = {{ display: overlay.style.display, ariaHidden: overlay["aria-hidden"] }};
dispatchClick(zoomIcon);
const afterZoom = {{
    zoom: previewController.groups.get("overlay").panes.get("left").zoom,
    scales: applied
}};
dispatchClick(closeIcon);
console.log(JSON.stringify({{
    afterContent,
    afterZoom,
    afterClose: {{ display: overlay.style.display, ariaHidden: overlay["aria-hidden"] }}
}}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def test_controller_contract_and_zoom_bounds(self):
        for marker in (
            "class PreviewController",
            "normalizedCenter",
            'mode: "fit"',
            "sync: options.sync !== false",
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

    def test_controller_rejects_nonnumeric_zoom(self):
        result = self.run_controller_probe(
            """
const adapter = {
    measure: () => ({ naturalWidth: 1000, naturalHeight: 500, viewportWidth: 500, viewportHeight: 500 }),
    apply: () => {}
};
const controller = new PreviewController();
controller.createGroup("overlay");
controller.addPane("overlay", "left", adapter);
controller.setZoom("overlay", "left", "not-a-number");
const zoom = controller.groups.get("overlay").panes.get("left").zoom;
console.log(JSON.stringify({ zoom, valid: Number.isFinite(zoom) && zoom >= 0.1 && zoom <= 12 }));
"""
        )
        self.assertEqual(result, {"zoom": 1, "valid": True})

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

    def test_legacy_preview_markup_has_compatibility_styles(self):
        for marker in (
            ".compare-preview {",
            ".compare-preview.t2i",
            ".compare-preview.ti2i",
            ".compare-box {",
            ".compare-label {",
        ):
            self.assertIn(marker, self.html)

        medium_breakpoint = self.html[
            self.html.index("@media (max-width: 1180px)"):
            self.html.index("@media (max-width: 720px)")
        ]
        self.assertIn(".compare-preview.t2i", medium_breakpoint)
        self.assertIn(".compare-preview.ti2i", medium_breakpoint)

    def test_preview_close_controls_close_only_the_preview_overlay(self):
        result = self.run_preview_close_probe(
            """
const handlers = {};
let dashboardPreviewOverlayBound = false;
const beginDashboardPreviewRender = () => null;
const releasePreviewPointers = () => null;
const hidePreviewMagnifiers = () => null;
const stopHoldCompare = () => null;
const previewController = { groups: new Map() };
const overlay = {
    style: { display: "flex" },
    attributes: { "aria-hidden": "false" },
    setAttribute: (name, value) => { overlay.attributes[name] = value; },
    addEventListener: (name, handler) => { handlers[name] = handler; }
};
const document = { getElementById: id => id === "image-overlay" ? overlay : { replaceChildren: () => null } };
bindPreviewOverlayEvents();
handlers.click({ target: overlay });
const afterBackdrop = { display: overlay.style.display, ariaHidden: overlay.attributes["aria-hidden"] };
overlay.style.display = "flex";
overlay.attributes["aria-hidden"] = "false";
handlers.click({ target: { closest: selector => selector === "[data-preview-close]" ? {} : null } });
console.log(JSON.stringify({ afterBackdrop, afterButton: { display: overlay.style.display, ariaHidden: overlay.attributes["aria-hidden"] } }));
"""
        )
        self.assertEqual(result, {
            "afterBackdrop": {"display": "none", "ariaHidden": "true"},
            "afterButton": {"display": "none", "ariaHidden": "true"},
        })

    def test_toolbar_contains_evaluation_inspection_tools(self):
        start = self.html.index("function renderDashboardPreviewToolbar(")
        end = self.html.index("function updateDashboardPreviewToolbar(", start)
        source = self.html[start:end]
        script = f"""
{source}
console.log(renderDashboardPreviewToolbar({{ groupId: "overlay", showSync: true }}));
"""
        markup = subprocess.check_output(["node", "-e", script], text=True)
        for action in (
            "magnifier", "reset", "fit", "fit-width", "fit-height", "actual",
            "zoom-out", "zoom-in", "background", "help",
        ):
            self.assertIn(f'data-preview-action="{action}"', markup)

    def test_pointer_magnifier_and_keyboard_bindings_exist(self):
        for marker in (
            'addEventListener("wheel"',
            'addEventListener("pointerdown"',
            'addEventListener("pointermove"',
            'setPointerCapture(',
            "renderMagnifier(",
            "releasePreviewPointers(",
            '["INPUT", "SELECT", "TEXTAREA", "BUTTON"]',
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

    def test_open_dashboard_preview_renders_normalized_single_image_without_sync(self):
        source = self.function_source("openDashboardPreview")
        script = f"""
const created = [];
let groupOptions;
let toolbarOptions;
let normalizedPayload;
const grid = {{ replaceChildren: (...children) => {{ grid.children = children; }} }};
const toolbar = {{ innerHTML: "" }};
const overlay = {{ style: {{}}, setAttribute: (name, value) => {{ overlay[name] = value; }} }};
const document = {{ getElementById: id => id === "image-preview" ? grid : id === "dashboard-preview-toolbar" ? toolbar : overlay }};
const normalizeDashboardPreview = payload => {{
    normalizedPayload = payload;
    return {{ kind: "single", panes: [{{ id: "single", src: payload.src, label: payload.label }}], showSync: false, showCompare: false }};
}};
const renderDashboardPreviewPane = pane => {{ created.push(pane); return pane; }};
const renderInlineCompareControls = () => {{ throw new Error("single preview must not render compare controls"); }};
const stopHoldCompare = () => null;
const releasePreviewPointers = () => null;
const hidePreviewMagnifiers = () => null;
const beginDashboardPreviewRender = () => null;
const createPreviewGroup = (groupId, options) => {{ groupOptions = {{ groupId, ...options }}; }};
const renderDashboardPreviewToolbar = options => {{ toolbarOptions = options; return "toolbar"; }};
const bindPreviewGroup = () => null;
const updateDashboardPreviewToolbar = () => null;
{source}
openDashboardPreview({{ single: true, src: "/clicked.png", label: "Clicked" }});
console.log(JSON.stringify({{ normalizedPayload, created, groupOptions, toolbarOptions, className: grid.className, toolbar: toolbar.innerHTML, display: overlay.style.display, ariaHidden: overlay["aria-hidden"] }}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result["normalizedPayload"], {"single": True, "src": "/clicked.png", "label": "Clicked"})
        self.assertEqual(result["created"], [{"id": "single", "src": "/clicked.png", "label": "Clicked"}])
        self.assertEqual(result["groupOptions"], {"groupId": "overlay", "sync": False})
        self.assertEqual(result["toolbarOptions"], {"groupId": "overlay", "showSync": False})
        self.assertEqual(result["className"], "dashboard-preview-grid single")
        self.assertEqual(result["toolbar"], "toolbar")
        self.assertEqual(result["display"], "flex")
        self.assertEqual(result["ariaHidden"], "false")
        self.assertNotIn("function createDashboardPreviewPane(", self.html)
        self.assertNotIn("function renderDashboardPreview(", self.html)

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

        source = self.function_source("buildHoldComparePairs")
        script = f"""
{source}
console.log(JSON.stringify({{
    two: buildHoldComparePairs([{{ id: "left", label: "A" }}, {{ id: "right", label: "B" }}]),
    three: buildHoldComparePairs([{{ id: "reference", label: "参考图" }}, {{ id: "left", label: "A" }}, {{ id: "right", label: "B" }}])
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(
            [(item["sourceId"], item["targetId"], item["slot"], item["symbol"]) for item in result["two"]],
            [("right", "left", "only-upper", "←"), ("left", "right", "only-lower", "→")],
        )
        self.assertEqual(
            [(item["sourceId"], item["targetId"], item["slot"], item["kind"], item["symbol"]) for item in result["three"]],
            [
                ("left", "reference", "left-upper", "adjacent", "←"),
                ("reference", "left", "left-middle", "adjacent", "→"),
                ("right", "reference", "left-lower", "folded", "└←"),
                ("right", "left", "right-upper", "adjacent", "←"),
                ("left", "right", "right-middle", "adjacent", "→"),
                ("reference", "right", "right-lower", "folded", "→┘"),
            ],
        )

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

    def test_three_way_compare_renderer_uses_folded_svg_only_for_folded_pairs(self):
        script = f"""
{self.function_source("createNode")}
{self.function_source("buildHoldComparePairs")}
{self.function_source("foldedCompareIcon")}
{self.function_source("renderInlineCompareControls")}
const document = {{
    createDocumentFragment: () => ({{ children: [], append(...nodes) {{ this.children.push(...nodes); }} }}),
    createElement: tag => ({{ tag, dataset: {{}}, attributes: {{}}, textContent: "", innerHTML: "", setAttribute(name, value) {{ this.attributes[name] = value; }} }})
}};
const controls = renderInlineCompareControls("overlay", [
    {{ id: "reference", label: "参考图" }},
    {{ id: "left", label: "A" }},
    {{ id: "right", label: "B" }}
]);
console.log(JSON.stringify(controls.children.map(button => ({{
    text: button.textContent,
    html: button.innerHTML,
    source: button.dataset.compareSource,
    target: button.dataset.compareTarget,
    slot: button.dataset.compareSlot,
    kind: button.dataset.compareKind
}}))));
"""
        buttons = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(len(buttons), 6)
        self.assertEqual(
            [(button["slot"], button["source"], button["target"], button["kind"]) for button in buttons],
            [
                ("left-upper", "left", "reference", "adjacent"),
                ("left-middle", "reference", "left", "adjacent"),
                ("left-lower", "right", "reference", "folded"),
                ("right-upper", "right", "left", "adjacent"),
                ("right-middle", "left", "right", "adjacent"),
                ("right-lower", "reference", "right", "folded"),
            ],
        )
        self.assertEqual([button["text"] for button in buttons[:2] + buttons[3:5]], ["←", "→", "←", "→"])
        self.assertEqual([button["html"].count("<polyline") for button in buttons], [0, 0, 2, 0, 0, 2])
        self.assertIn('points="21,18 12,5 4,18"', buttons[2]["html"])
        self.assertIn('points="3,18 12,5 20,18"', buttons[5]["html"])

    def test_hold_compare_requires_loaded_panes_and_cleans_up(self):
        start = self.function_source("startHoldCompare")
        stop = self.function_source("stopHoldCompare")
        script = f"""
let activeHoldCompare = null;
const classes = () => {{
    const names = new Set();
    return {{ add: (...items) => items.forEach(item => names.add(item)), remove: (...items) => items.forEach(item => names.delete(item)), contains: item => names.has(item) }};
}};
const node = tag => ({{
    tag,
    dataset: {{}},
    style: {{}},
    attributes: {{}},
    children: [],
    classList: classes(),
    append(...items) {{ this.children.push(...items); }},
    setAttribute(name, value) {{ this.attributes[name] = value; }},
    remove() {{ this.removed = true; }}
}});
const createNode = (tag, className) => {{ const item = node(tag); item.className = className; return item; }};
const sourceImage = {{ currentSrc: "source-current.jpg", src: "source.jpg", alt: "Source", draggable: true, style: {{ width: "420px", height: "280px", transform: "translate(-50%) scale(1.3)" }} }};
const targetImage = {{ src: "target.jpg", style: {{ width: "300px", height: "200px", transform: "translate(-50%)" }} }};
const sourceViewport = {{ dataset: {{ previewLabel: "Source" }}, querySelector: () => sourceImage }};
const targetChildren = [];
const targetViewport = {{ dataset: {{ previewLabel: "Target" }}, querySelector: () => targetImage, append: layer => targetChildren.push(layer) }};
let panes = new Map([["source", {{}}], ["target", {{}}]]);
const previewController = {{ groups: new Map([["overlay", {{ panes }}]]) }};
const document = {{ querySelector: selector => selector.includes('data-preview-pane="source"') ? sourceViewport : selector.includes('data-preview-pane="target"') ? targetViewport : null }};
const button = node("button");
{stop}
{start}
const started = startHoldCompare("overlay", "source", "target", button);
const layer = targetChildren[0];
const overlayImage = layer.children[0];
const during = {{
    started,
    source: overlayImage.src,
    width: overlayImage.style.width,
    height: overlayImage.style.height,
    transform: overlayImage.style.transform,
    attachedToTarget: targetChildren.length,
    active: button.classList.contains("active"),
    pressed: button.attributes["aria-pressed"]
}};
stopHoldCompare();
panes = new Map([["target", {{}}]]);
previewController.groups.set("overlay", {{ panes }});
const missingSource = startHoldCompare("overlay", "source", "target", button);
panes = new Map([["source", {{}}]]);
previewController.groups.set("overlay", {{ panes }});
const missingTarget = startHoldCompare("overlay", "source", "target", button);
console.log(JSON.stringify({{ during, removed: layer.removed, activeAfter: button.classList.contains("active"), pressedAfter: button.attributes["aria-pressed"], missingSource, missingTarget, layers: targetChildren.length }}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result["during"], {
            "started": True,
            "source": "source-current.jpg",
            "width": "420px",
            "height": "280px",
            "transform": "translate(-50%) scale(1.3)",
            "attachedToTarget": 1,
            "active": True,
            "pressed": "true",
        })
        self.assertTrue(result["removed"])
        self.assertFalse(result["activeAfter"])
        self.assertEqual(result["pressedAfter"], "false")
        self.assertFalse(result["missingSource"])
        self.assertFalse(result["missingTarget"])
        self.assertEqual(result["layers"], 1)

    def test_bad_case_click_stays_single_image(self):
        source = self.function_source("openSinglePreview")
        self.assertIn("single: true", source)
        self.assertNotIn("state.currentBadcase", source)
        self.assertNotIn("ref_img", source)
        self.assertNotIn("imageUrl(", source)

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
        result = self.run_preview_close_probe(
            """
const classes = initial => {
    const values = new Set(initial);
    return { contains: name => values.has(name), remove: name => values.delete(name) };
};
const stage = { classList: classes(["preview-help-open"]) };
const toolbar = { replaceChildren: () => null };
const preview = { replaceChildren: () => null };
const overlay = {
    style: { display: "flex" },
    attributes: { "aria-hidden": "false" },
    setAttribute(name, value) { this.attributes[name] = value; }
};
const document = {
    querySelector: selector => selector === ".dashboard-preview-stage" ? stage : null,
    getElementById: id => ({
        "dashboard-preview-toolbar": toolbar,
        "image-preview": preview,
        "image-overlay": overlay
    })[id]
};
const beginDashboardPreviewRender = () => null;
const releasePreviewPointers = () => null;
const hidePreviewMagnifiers = () => null;
const stopHoldCompare = () => null;
const previewController = { groups: new Map() };
closeImagePreview();
console.log(JSON.stringify({
    stageOpen: stage.classList.contains("preview-help-open"),
    overlayDisplay: overlay.style.display,
    overlayAriaHidden: overlay.attributes["aria-hidden"]
}));
"""
        )
        self.assertEqual(result, {
            "stageOpen": False,
            "overlayDisplay": "none",
            "overlayAriaHidden": "true",
        })
        for marker in (
            'releasePreviewPointers("overlay")',
            "hidePreviewMagnifiers()",
            "stopHoldCompare()",
            'previewController.groups.delete("overlay")',
            'classList.remove("preview-help-open")',
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

    def test_mobile_compare_controls_follow_stacked_pane_gaps_at_700px(self):
        cases = {
            "t2i": (
                ["left", "right"],
                ["only-upper", "only-lower"],
                {"only-upper": (0, 1), "only-lower": (0, 1)},
            ),
            "ti2i": (
                ["reference", "left", "right"],
                ["left-upper", "left-middle", "left-lower", "right-upper", "right-middle", "right-lower"],
                {
                    "left-upper": (0, 1), "left-middle": (0, 1), "left-lower": (0, 1),
                    "right-upper": (1, 2), "right-middle": (1, 2), "right-lower": (1, 2),
                },
            ),
        }
        for kind, (pane_ids, slots, mappings) in cases.items():
            with self.subTest(kind=kind):
                panes = "".join(
                    f'<section class="dashboard-preview-viewport" data-preview-pane="{pane_id}"></section>'
                    for pane_id in pane_ids
                )
                buttons = "".join(
                    f'<button class="inline-compare-btn" data-compare-slot="{slot}"></button>'
                    for slot in slots
                )
                body = f"""
<div id="image-overlay" style="display:flex">
  <div class="dashboard-preview-stage">
    <div id="image-preview" class="dashboard-preview-grid {kind}">{panes}{buttons}</div>
  </div>
</div>"""
                result = self.run_browser_geometry_probe(
                    body,
                    f"""
const paneRects = [...document.querySelectorAll("[data-preview-pane]")].map(node => node.getBoundingClientRect());
const mappings = {json.dumps(mappings)};
const controls = [...document.querySelectorAll("[data-compare-slot]")].map(button => {{
    const rect = button.getBoundingClientRect();
    const [upperIndex, lowerIndex] = mappings[button.dataset.compareSlot];
    const upper = paneRects[upperIndex];
    const lower = paneRects[lowerIndex];
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    return {{
        slot: button.dataset.compareSlot,
        centeredInGap: Math.abs(centerY - (upper.bottom + lower.top) / 2) < 1,
        alignedWithPanes: centerX >= Math.max(upper.left, lower.left) && centerX <= Math.min(upper.right, lower.right)
    }};
}});
return {{ width: document.documentElement.clientWidth, controls }};
""",
                )
                self.assertEqual(result["width"], 700)
                self.assertTrue(all(item["centeredInGap"] for item in result["controls"]), result)
                self.assertTrue(all(item["alignedWithPanes"] for item in result["controls"]), result)

    def test_desktop_toolbar_text_panels_expand_left_without_clipping(self):
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
        result = self.run_browser_geometry_probe(
            body,
            """
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
""",
            width=1024,
            height=800,
        )
        self.assertEqual(result["closed"], {"info": "none", "help": "none"})
        self.assertGreaterEqual(result["toolbarWidth"], 220)
        self.assertTrue(result["gridClearsToolbar"], result)
        self.assertTrue(result["panelsInsideStage"], result)

    def test_help_action_expands_toolbar_and_stage_without_leaking_state(self):
        source = self.function_source("bindDashboardPreviewToolbar")
        script = f"""
const classes = (initial = []) => {{
    const values = new Set(initial);
    return {{
        add: name => values.add(name),
        remove: name => values.delete(name),
        contains: name => values.has(name),
        toggle(name, force) {{
            const enabled = force === undefined ? !values.has(name) : force;
            if (enabled) values.add(name); else values.delete(name);
            return enabled;
        }}
    }};
}};
const help = {{ classList: classes(["hidden"]) }};
const info = {{ classList: classes(["hidden"]) }};
const toolbar = {{ dataset: {{ previewGroup: "overlay" }}, classList: classes(), querySelector: selector => selector.includes("preview-help") ? help : selector.includes("preview-info") ? info : null }};
const stage = {{ classList: classes() }};
toolbar.closest = selector => selector === ".dashboard-preview-stage" ? stage : null;
const helpButton = {{ dataset: {{ previewAction: "help" }}, closest: selector => selector === "[data-preview-action]" ? helpButton : selector === "[data-preview-group]" ? toolbar : null, setAttribute(name, value) {{ this[name] = value; }} }};
const listeners = new Map();
const document = {{ addEventListener(type, listener) {{ listeners.set(type, listener); }} }};
let dashboardPreviewToolbarBound = false;
let dashboardPreviewKeyboardBound = true;
const previewController = {{ groups: new Map([["overlay", {{ activePaneId: null, panes: new Map() }}]]) }};
const updateDashboardPreviewToolbar = () => null;
{source}
bindDashboardPreviewToolbar();
const click = () => listeners.get("click")({{ target: helpButton }});
click();
const opened = {{
    toolbar: toolbar.classList.contains("help-open"),
    stage: stage.classList.contains("preview-help-open"),
    helpHidden: help.classList.contains("hidden"),
    infoHidden: info.classList.contains("hidden"),
    ariaExpanded: helpButton["aria-expanded"]
}};
click();
const closed = {{
    toolbar: toolbar.classList.contains("help-open"),
    stage: stage.classList.contains("preview-help-open"),
    helpHidden: help.classList.contains("hidden"),
    infoHidden: info.classList.contains("hidden"),
    ariaExpanded: helpButton["aria-expanded"]
}};
console.log(JSON.stringify({{ opened, closed }}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result["opened"], {
            "toolbar": True,
            "stage": True,
            "helpHidden": False,
            "infoHidden": False,
            "ariaExpanded": "true",
        })
        self.assertEqual(result["closed"], {
            "toolbar": False,
            "stage": False,
            "helpHidden": True,
            "infoHidden": True,
            "ariaExpanded": "false",
        })

    def test_short_desktop_complete_toolbars_keep_every_control_reachable(self):
        for show_sync, expected_count in ((True, 11), (False, 10)):
            for width, height in ((1024, 500), (700, 1000)):
                with self.subTest(show_sync=show_sync, width=width, height=height):
                    toolbar = self.render_toolbar_markup(show_sync)
                    body = f"""
<div id="image-overlay" style="display:flex">
  <div class="dashboard-preview-stage preview-help-open">
    <div id="dashboard-preview-toolbar">{toolbar}</div>
  </div>
</div>"""
                    result = self.run_browser_geometry_probe(
                        body,
                        """
const stage = document.querySelector(".dashboard-preview-stage").getBoundingClientRect();
const toolbar = document.querySelector(".dashboard-preview-toolbar");
toolbar.classList.add("help-open");
toolbar.querySelector(".preview-info").classList.remove("hidden");
toolbar.querySelector(".preview-shortcut-help").classList.remove("hidden");
const toolbarRect = toolbar.getBoundingClientRect();
const buttons = [...toolbar.querySelectorAll("[data-preview-action]")];
const text = [toolbar.querySelector(".preview-info"), toolbar.querySelector(".preview-shortcut-help")];
const maxScroll = Math.max(0, toolbar.scrollWidth - toolbar.clientWidth);
const reachable = [...buttons, ...text].map(node => {
    toolbar.scrollLeft = Math.min(maxScroll, Math.max(0, node.offsetLeft - toolbar.clientWidth / 2));
    const rect = node.getBoundingClientRect();
    return rect.left >= toolbarRect.left && rect.right <= toolbarRect.right
        && rect.top >= stage.top && rect.bottom <= stage.bottom;
});
return {
    buttonCount: buttons.length,
    textCount: text.length,
    direction: getComputedStyle(toolbar).flexDirection,
    overflowX: getComputedStyle(toolbar).overflowX,
    toolbarInsideStage: toolbarRect.left >= stage.left && toolbarRect.right <= stage.right
        && toolbarRect.top >= stage.top && toolbarRect.bottom <= stage.bottom,
    reachable
};
""",
                        width=width,
                        height=height,
                    )
                    self.assertEqual(result["buttonCount"], expected_count)
                    self.assertEqual(result["textCount"], 2)
                    self.assertEqual(result["direction"], "row")
                    self.assertEqual(result["overflowX"], "auto")
                    self.assertTrue(result["toolbarInsideStage"], result)
                    self.assertTrue(all(result["reachable"]), result)

    def test_global_shortcuts_preserve_button_space_and_compare_button_keydown(self):
        toolbar_source = self.function_source("bindDashboardPreviewToolbar")
        compare_source = self.function_source("bindDashboardPreviewCompareControls")
        script = f"""
let dashboardPreviewToolbarBound = false;
let dashboardPreviewKeyboardBound = false;
let dashboardPreviewCompareBound = false;
let dashboardPreviewSpacePan = false;
let activeHoldCompare = null;
const handlers = {{}};
const document = {{
    addEventListener(type, listener) {{ (handlers[type] ||= []).push(listener); }},
    querySelectorAll: () => []
}};
const window = {{ addEventListener() {{}} }};
const previewController = {{ groups: new Map(), setSync() {{}} }};
let closes = 0;
let hides = 0;
let compareStarts = 0;
const closeImagePreview = () => {{ closes += 1; }};
const hidePreviewMagnifiers = () => {{ hides += 1; }};
const updateDashboardPreviewToolbar = () => null;
const setPreviewMode = () => null;
const resetPreviewGroup = () => null;
const setPreviewZoom = () => null;
const stopHoldCompare = () => null;
const startHoldCompare = () => {{ compareStarts += 1; return true; }};
{toolbar_source}
{compare_source}
bindDashboardPreviewToolbar();
bindDashboardPreviewCompareControls();
const dispatchKeydown = (target, key) => {{
    const event = {{ target, key, repeat: false, defaultPrevented: false, preventDefault() {{ this.defaultPrevented = true; }} }};
    handlers.keydown.forEach(listener => listener(event));
    return event.defaultPrevented;
}};
const ordinaryButton = {{ tagName: "BUTTON", closest: () => null }};
const compareButton = {{
    tagName: "BUTTON",
    dataset: {{ previewGroupId: "overlay", compareSource: "left", compareTarget: "right" }},
    closest: selector => selector === "[data-hold-compare]" ? compareButton : null,
    matches: selector => selector === "[data-hold-compare]"
}};
const ordinarySpacePrevented = dispatchKeydown(ordinaryButton, " ");
const spacePanAfterOrdinaryButton = dashboardPreviewSpacePan;
dispatchKeydown(ordinaryButton, "Escape");
const compareSpacePrevented = dispatchKeydown(compareButton, " ");
console.log(JSON.stringify({{
    ordinarySpacePrevented,
    spacePanAfterOrdinaryButton,
    compareSpacePrevented,
    closes,
    hides,
    compareStarts
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {
            "ordinarySpacePrevented": False,
            "spacePanAfterOrdinaryButton": False,
            "compareSpacePrevented": True,
            "closes": 1,
            "hides": 0,
            "compareStarts": 1,
        })

    def test_pointer_cleanup_releases_capture_and_lost_capture_clears_dragging(self):
        release_source = self.function_source("releasePreviewPointers")
        bind_source = self.function_source("bindPreviewGroup")
        script = f"""
const previewPointerCleanups = new Map();
const listeners = new Map();
const classes = new Set();
const captures = new Set();
const released = [];
const viewport = {{
    dataset: {{ previewPane: "left" }},
    classList: {{ add: name => classes.add(name), remove: name => classes.delete(name) }},
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: type => listeners.delete(type),
    setPointerCapture: pointerId => captures.add(pointerId),
    hasPointerCapture: pointerId => captures.has(pointerId),
    releasePointerCapture: pointerId => {{ released.push(pointerId); captures.delete(pointerId); }},
    getBoundingClientRect: () => ({{ left: 0, top: 0 }})
}};
const pane = {{ failed: false, normalizedCenter: {{ x: 0.5, y: 0.5 }}, zoom: 1, adapter: {{ measure: () => ({{ naturalWidth: 100, naturalHeight: 100 }}) }} }};
const previewController = {{ groups: new Map([["overlay", {{ panes: new Map([["left", pane]]), mode: "fit" }}]]), fitScale: () => 1 }};
const document = {{ querySelectorAll: () => [viewport] }};
let dashboardPreviewSpacePan = false;
const updateDashboardPreviewToolbar = () => null;
const setPreviewZoom = () => null;
const setPreviewCenter = () => null;
const renderMagnifier = () => null;
const hidePreviewMagnifiers = () => null;
{release_source}
{bind_source}
bindPreviewGroup("overlay");
listeners.get("pointerdown")({{ button: 0, pointerType: "mouse", pointerId: 7, clientX: 10, clientY: 10, preventDefault() {{}} }});
const lostCaptureHandler = listeners.get("lostpointercapture");
captures.delete(7);
if (lostCaptureHandler) lostCaptureHandler({{ pointerId: 7 }});
const afterLost = {{ dragging: classes.has("dragging"), captures: [...captures] }};
listeners.get("pointerdown")({{ button: 0, pointerType: "mouse", pointerId: 8, clientX: 10, clientY: 10, preventDefault() {{}} }});
releasePreviewPointers("overlay");
console.log(JSON.stringify({{
    afterLost,
    hasLostCaptureHandler: Boolean(lostCaptureHandler),
    released,
    draggingAfterClose: classes.has("dragging"),
    capturesAfterClose: [...captures],
    listenerCountAfterClose: listeners.size,
    cleanupRemoved: !previewPointerCleanups.has("overlay")
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {
            "afterLost": {"dragging": False, "captures": []},
            "hasLostCaptureHandler": True,
            "released": [8],
            "draggingAfterClose": False,
            "capturesAfterClose": [],
            "listenerCountAfterClose": 0,
            "cleanupRemoved": True,
        })

    def test_magnifier_hides_when_pointer_leaves_rendered_image(self):
        source = self.function_source("renderMagnifier")
        script = f"""
const classes = () => {{
    const values = new Set();
    return {{ add: name => values.add(name), remove: name => values.delete(name), contains: name => values.has(name) }};
}};
const makePane = (image, geometry, clientWidth, clientHeight) => {{
    const lens = {{ classList: classes(), style: {{}}, offsetWidth: 20, offsetHeight: 20 }};
    return {{
        image,
        lens,
        geometry,
        viewport: {{
            clientWidth,
            clientHeight,
            querySelector: selector => selector === "img" ? image : selector === ".magnifier-layer" ? lens : null
        }}
    }};
}};
const reference = makePane(
    {{ currentSrc: "ref.jpg", src: "ref.jpg" }},
    {{ viewport: {{ left: 100, top: 100 }}, image: {{ left: 110, right: 310, top: 130, bottom: 230, width: 200, height: 100 }} }},
    240,
    180
);
const left = makePane(
    {{ currentSrc: "a.jpg", src: "a.jpg" }},
    {{ viewport: {{ left: 360, top: 30 }}, image: {{ left: 380, right: 500, top: 80, bottom: 320, width: 120, height: 240 }} }},
    180,
    320
);
const right = makePane(
    {{ currentSrc: "b.jpg", src: "b.jpg" }},
    {{ viewport: {{ left: 620, top: 160 }}, image: {{ left: 650, right: 950, top: 190, bottom: 340, width: 300, height: 150 }} }},
    340,
    220
);
const panes = new Map([
    ["reference", {{ failed: false, adapter: {{ geometry: () => reference.geometry }} }}],
    ["left", {{ failed: false, adapter: {{ geometry: () => left.geometry }} }}],
    ["right", {{ failed: false, adapter: {{ geometry: () => right.geometry }} }}]
]);
const previewController = {{ groups: new Map([["overlay", {{ magnifier: true, sync: true, panes }}]]) }};
const paneFor = selector => selector.includes('data-preview-pane="reference"') ? reference : selector.includes('data-preview-pane="left"') ? left : right;
const document = {{
    querySelector: selector => paneFor(selector).viewport,
    querySelectorAll: () => [reference.viewport, left.viewport, right.viewport]
}};
const hidePreviewMagnifiers = groupId => {{
    [reference, left, right].forEach(pane => pane.lens.classList.remove("visible"));
}};
{source}
const shown = renderMagnifier("overlay", "reference", {{ clientX: 190, clientY: 190 }});
const visibleLenses = ["reference", "left", "right"].filter(id => ({{ reference, left, right }})[id].lens.classList.contains("visible"));
const backgrounds = [reference, left, right].map(pane => pane.lens.style.backgroundImage);
const positions = [reference, left, right].map(pane => `${{pane.lens.style.left}},${{pane.lens.style.top}}`);
const distinctPositions = new Set(positions).size === positions.length;
const anyMarkerVisible = false;
previewController.groups.get("overlay").sync = false;
const shownUnsynced = renderMagnifier("overlay", "left", {{ clientX: 428, clientY: 224 }});
const unsyncedVisibleLenses = ["reference", "left", "right"].filter(id => ({{ reference, left, right }})[id].lens.classList.contains("visible"));
const shownOutside = renderMagnifier("overlay", "left", {{ clientX: 20, clientY: 20 }});
console.log(JSON.stringify({{
    shown,
    visibleLenses,
    backgrounds,
    distinctPositions,
    anyMarkerVisible,
    shownUnsynced,
    unsyncedVisibleLenses,
    shownOutside,
    visibleLensesOutside: ["reference", "left", "right"].filter(id => ({{ reference, left, right }})[id].lens.classList.contains("visible"))
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {
            "shown": True,
            "visibleLenses": ["reference", "left", "right"],
            "backgrounds": ['url("ref.jpg")', 'url("a.jpg")', 'url("b.jpg")'],
            "distinctPositions": True,
            "anyMarkerVisible": False,
            "shownUnsynced": True,
            "unsyncedVisibleLenses": ["left"],
            "shownOutside": False,
            "visibleLensesOutside": [],
        })
        self.assertNotIn("correspondence-marker", self.html)

    def test_unused_legacy_preview_opener_is_removed(self):
        self.assertNotIn("function openPreviewOverlay(", self.html)

    def test_stale_image_callbacks_after_close_and_reopen_do_not_mutate_current_preview(self):
        close_source = self.function_source("closeImagePreview")
        lifecycle_source = self.dashboard_preview_lifecycle_source()
        script = f"""
const classList = initial => {{
    const values = new Set(initial ? initial.split(" ") : []);
    return {{
        add: (...names) => names.forEach(name => values.add(name)),
        remove: (...names) => names.forEach(name => values.delete(name)),
        contains: name => values.has(name)
    }};
}};
const createNode = (tag, className = "", text = "") => {{
    const node = {{
        tag, className, textContent: text, dataset: {{}}, style: {{}}, children: [],
        classList: classList(className), listeners: new Map(), complete: false,
        naturalWidth: 0, naturalHeight: 0,
        append(...children) {{ this.children.push(...children); }},
        addEventListener(type, listener) {{ this.listeners.set(type, listener); }},
        removeEventListener() {{}},
        replaceChildren(...children) {{ this.children = children; }},
        setAttribute(name, value) {{ this[name] = value; }}
    }};
    return node;
}};
const overlay = createNode("div");
const toolbar = createNode("div");
const grid = createNode("div");
const document = {{ getElementById: id => id === "image-overlay" ? overlay : id === "image-preview" ? grid : toolbar }};
const previewController = {{ groups: new Map() }};
let registrations = 0;
let magnifierClears = 0;
const registerPreviewPane = (groupId, paneId) => {{
    registrations += 1;
    previewController.groups.get(groupId).panes.set(paneId, {{ failed: false }});
}};
const updateDashboardPreviewToolbar = () => null;
const hidePreviewMagnifiers = () => {{ magnifierClears += 1; }};
const releasePreviewPointers = () => null;
const stopHoldCompare = () => null;
{close_source}
{lifecycle_source}
beginDashboardPreviewRender();
previewController.groups.set("overlay", {{ panes: new Map(), activePaneId: "" }});
const staleViewport = renderDashboardPreviewPane({{ id: "stale", src: "/stale.png", label: "stale" }});
const staleImage = staleViewport.children[0];
const staleLoad = staleImage.listeners.get("load");
const staleError = staleImage.listeners.get("error");
closeImagePreview();
previewController.groups.set("overlay", {{ panes: new Map(), activePaneId: "" }});
const currentViewport = renderDashboardPreviewPane({{ id: "current", src: "/current.png", label: "current" }});
const clearsBeforeStaleCallbacks = magnifierClears;
staleLoad();
staleError();
console.log(JSON.stringify({{
    registrations,
    currentLoading: currentViewport.classList.contains("loading"),
    currentFailed: currentViewport.classList.contains("failed"),
    groupPanes: [...previewController.groups.get("overlay").panes.keys()],
    staleCallbacksClearedMagnifier: magnifierClears !== clearsBeforeStaleCallbacks
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {
            "registrations": 0,
            "currentLoading": True,
            "currentFailed": False,
            "groupPanes": [],
            "staleCallbacksClearedMagnifier": False,
        })

    def test_registered_failed_pane_is_excluded_from_controller_and_magnifier(self):
        mark_source = self.function_source("markPreviewPaneFailed")
        magnifier_source = self.function_source("renderMagnifier")
        script = f"""
{self.controller_source()}
const applied = [];
const adapter = {{
    measure: () => ({{ naturalWidth: 400, naturalHeight: 300, viewportWidth: 200, viewportHeight: 150 }}),
    geometry: () => ({{ viewport: {{ left: 0, top: 0 }}, image: {{ left: 0, right: 1, top: 0, bottom: 1, width: 1, height: 1 }} }}),
    apply: state => applied.push(state)
}};
const previewController = new PreviewController();
previewController.createGroup("overlay", {{ sync: true }});
previewController.addPane("overlay", "failed", adapter);
applied.length = 0;
const document = {{ querySelector: () => null }};
{mark_source}
{magnifier_source}
markPreviewPaneFailed("overlay", "failed");
previewController.setZoom("overlay", "failed", 2);
previewController.groups.get("overlay").magnifier = true;
const magnifierResult = renderMagnifier("overlay", "failed", {{ clientX: 10, clientY: 10 }});
console.log(JSON.stringify({{
    failed: previewController.groups.get("overlay").panes.get("failed").failed,
    appliedAfterFailure: applied.length,
    magnifierResult
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {
            "failed": True,
            "appliedAfterFailure": 0,
            "magnifierResult": False,
        })

    def test_close_and_overlay_binding_are_idempotent_at_runtime(self):
        close_source = self.function_source("closeImagePreview")
        binding_source = self.function_source("bindPreviewOverlayEvents")
        script = f"""
let dashboardPreviewOverlayBound = false;
const handlers = [];
const counts = {{ begin: 0, release: 0, hide: 0, hold: 0, toolbar: 0, grid: 0 }};
const overlay = {{
    style: {{ display: "flex" }},
    setAttribute: (name, value) => {{ overlay[name] = value; }},
    addEventListener: (type, listener) => handlers.push({{ type, listener }})
}};
const toolbar = {{ replaceChildren: () => {{ counts.toolbar += 1; }} }};
const grid = {{ replaceChildren: () => {{ counts.grid += 1; }} }};
const document = {{ getElementById: id => id === "image-overlay" ? overlay : id === "image-preview" ? grid : toolbar }};
const previewController = {{ groups: new Map([["overlay", {{ panes: new Map() }}]]) }};
const beginDashboardPreviewRender = () => {{ counts.begin += 1; }};
const releasePreviewPointers = () => {{ counts.release += 1; }};
const hidePreviewMagnifiers = () => {{ counts.hide += 1; }};
const stopHoldCompare = () => {{ counts.hold += 1; }};
{close_source}
{binding_source}
bindPreviewOverlayEvents();
bindPreviewOverlayEvents();
handlers[0].listener({{ target: overlay }});
closeImagePreview();
console.log(JSON.stringify({{
    listenerCount: handlers.length,
    counts,
    groupDeleted: !previewController.groups.has("overlay"),
    display: overlay.style.display,
    ariaHidden: overlay["aria-hidden"]
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {
            "listenerCount": 1,
            "counts": {"begin": 2, "release": 2, "hide": 2, "hold": 2, "toolbar": 2, "grid": 2},
            "groupDeleted": True,
            "display": "none",
            "ariaHidden": "true",
        })

    def test_resize_refreshes_once_and_skips_deleted_overlay_group(self):
        resize_source = self.function_source("bindDashboardPreviewResize")
        script = f"""
let dashboardPreviewResizeBound = false;
let dashboardPreviewResizePending = false;
const resizeListeners = [];
const frameCallbacks = [];
const window = {{ addEventListener: (type, listener) => resizeListeners.push({{ type, listener }}) }};
const requestAnimationFrame = callback => {{ frameCallbacks.push(callback); return frameCallbacks.length; }};
let refreshes = 0;
const previewController = {{
    groups: new Map([["overlay", {{}}]]),
    refreshGroup: () => {{ refreshes += 1; }}
}};
{resize_source}
bindDashboardPreviewResize();
bindDashboardPreviewResize();
resizeListeners[0].listener();
resizeListeners[0].listener();
frameCallbacks.shift()();
previewController.groups.delete("overlay");
resizeListeners[0].listener();
frameCallbacks.shift()();
console.log(JSON.stringify({{ listenerCount: resizeListeners.length, refreshes, queuedFrames: frameCallbacks.length }}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result, {"listenerCount": 1, "refreshes": 1, "queuedFrames": 0})


if __name__ == "__main__":
    unittest.main()
