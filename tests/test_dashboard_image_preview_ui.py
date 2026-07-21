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
