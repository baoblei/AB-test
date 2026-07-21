import json
import re
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
        stage = re.search(
            r'<div class="dashboard-preview-stage"[^>]*>',
            self.html,
        )
        self.assertIsNotNone(stage, "preview stage is missing")
        stage_stops_propagation = "onclick=\"event.stopPropagation()\"" in stage.group(0)
        result = self.run_preview_event_delegation_probe(stage_stops_propagation)
        self.assertEqual(result, {
            "afterContent": {"display": "flex", "ariaHidden": "false"},
            "afterZoom": {"zoom": 1.1, "scales": [0.55]},
            "afterClose": {"display": "none", "ariaHidden": "true"},
        })

    def run_preview_event_delegation_probe(self, stage_stops_propagation):
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
if ({json.dumps(stage_stops_propagation)}) stage.addEventListener("click", event => event.stopPropagation());
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
