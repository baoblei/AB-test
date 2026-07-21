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

    def preview_close_source(self):
        start = self.html.find("function closePreview")
        self.assertNotEqual(start, -1, "preview close function is missing")
        end = self.html.index("function buildPreviewPayload", start)
        return self.html[start:end]

    def run_preview_close_probe(self, scenario):
        script = f"{self.preview_close_source()}\n{scenario}"
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
            'data-preview-close',
        ):
            self.assertIn(marker, self.html)

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
const overlay = {
    style: { display: "flex" },
    attributes: { "aria-hidden": "false" },
    setAttribute: (name, value) => { overlay.attributes[name] = value; },
    addEventListener: (name, handler) => { handlers[name] = handler; }
};
const document = { getElementById: id => {
    if (id !== "image-overlay") throw new Error(`unexpected element ${id}`);
    return overlay;
} };
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

    def test_single_preview_renders_one_clicked_image_without_sync(self):
        start = self.html.index("function renderDashboardPreview(payload)")
        end = self.html.index("function openPreview(payload)", start)
        source = self.html[start:end]
        script = f"""
const created = [];
let groupOptions;
let toolbarOptions;
const grid = {{ replaceChildren: (...children) => {{ grid.children = children; }} }};
const toolbar = {{ innerHTML: "" }};
const document = {{ getElementById: id => id === "image-preview" ? grid : toolbar }};
const createDashboardPreviewPane = (...args) => {{ created.push(args); return {{ args }}; }};
const releasePreviewPointers = () => null;
const hidePreviewMagnifiers = () => null;
const createPreviewGroup = (groupId, options) => {{ groupOptions = {{ groupId, ...options }}; }};
const renderDashboardPreviewToolbar = options => {{ toolbarOptions = options; return "toolbar"; }};
const bindPreviewGroup = () => null;
const updateDashboardPreviewToolbar = () => null;
{source}
renderDashboardPreview({{ mode: "single", a: "/clicked.png", labels: ["Clicked"] }});
console.log(JSON.stringify({{ created, groupOptions, toolbarOptions, className: grid.className, toolbar: toolbar.innerHTML }}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(result["created"], [["overlay", "single", "/clicked.png", "Clicked"]])
        self.assertEqual(result["groupOptions"], {"groupId": "overlay", "sync": False})
        self.assertEqual(result["toolbarOptions"], {"groupId": "overlay", "showSync": False})
        self.assertEqual(result["className"], "dashboard-preview-grid single")
        self.assertEqual(result["toolbar"], "toolbar")


if __name__ == "__main__":
    unittest.main()
