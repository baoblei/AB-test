import unittest
from pathlib import Path


class VideoDashboardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def function_source(self, name, next_name):
        start = self.html.index(f"function {name}")
        return self.html[start : self.html.index(f"function {next_name}", start)]

    def test_video_summary_uses_two_rows_without_changing_image_grid(self):
        self.assertIn(".summary-grid.video-dimensions", self.html)
        video_rule = self.html[self.html.index(".summary-grid.video-dimensions") :]
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", video_rule[:300])
        base_rule = self.html[self.html.index(".summary-grid {") :]
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr))", base_rule[:250])
        render = self.function_source("renderPairs", "renderSummaryBox")
        self.assertIn('state.config.media_type === "video"', render)
        self.assertIn('summary.classList.add("video-dimensions")', render)

    def test_detail_list_remains_first_frame_images_only(self):
        source = self.function_source("renderDetailTable", "renderResultRow")
        self.assertIn('createNode("img", "preview-img")', source)
        self.assertIn("detailThumbnailUrl", source)
        self.assertNotIn('createNode("video"', source)

    def test_hd_preview_creates_video_only_for_video_panes(self):
        source = self.function_source("renderDashboardPreviewPane", "openDashboardPreview")
        self.assertIn('pane.mediaType === "video"', source)
        self.assertIn('createNode("video")', source)
        self.assertIn('createNode("img")', source)
        normalize = self.function_source("normalizeDashboardPreview", "buildHoldComparePairs")
        self.assertIn('mediaType: "image"', normalize)
        self.assertIn('payload.mediaType === "video" ? "video" : "image"', normalize)

    def test_preview_cleanup_destroys_video_group_and_removes_media(self):
        source = self.function_source("closeImagePreview", "bindPreviewOverlayEvents")
        self.assertIn("dashboardVideoPlayback.destroy()", source)
        self.assertIn('querySelectorAll?.("video")', source)
        self.assertIn('removeAttribute("src")', source)

    def test_dashboard_loads_shared_video_controller(self):
        self.assertIn('<script src="/static/video_media.js"></script>', self.html)


if __name__ == "__main__":
    unittest.main()
