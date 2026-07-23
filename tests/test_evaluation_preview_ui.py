import json
import subprocess
import unittest
from pathlib import Path


class EvaluationPreviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/index.html").read_text(encoding="utf-8")

    def run_controller_probe(self, scenario):
        start = self.html.index("class PreviewController")
        end = self.html.index("const previewController", start)
        scenario = scenario.replace("{{", "{").replace("}}", "}")
        script = f"{self.html[start:end]}\n{scenario}"
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def run_preview_probe(self, start_marker, end_marker, scenario):
        start = self.html.index(start_marker)
        end = self.html.index(end_marker, start)
        script = f"{self.html[start:end]}\n{scenario}"
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def css_rule(self, selector, start=0):
        try:
            rule_start = self.html.index(f"{selector} {{", start)
        except ValueError:
            self.fail(f"missing CSS rule for {selector}")
        body_start = self.html.index("{", rule_start) + 1
        body_end = self.html.index("}", body_start)
        return self.html[body_start:body_end]

    def test_shared_preview_controls_exist(self):
        for marker in (
            'class="preview-toolbar',
            'previewToolButton("sync"',
            'previewToolButton("fit"',
            'previewToolButton("fit-width"',
            'previewToolButton("fit-height"',
            'previewToolButton("actual"',
            'previewToolButton("magnifier"',
            'previewToolButton("reset"',
            'previewToolButton("background"',
            'previewToolButton("fullscreen"',
            'previewToolButton("zoom-out"',
            'previewToolButton("zoom-in"',
            'data-preview-action="collapse"',
            'previewToolButton("help"',
        ):
            self.assertIn(marker, self.html)
        self.assertNotIn('previewToolButton("compare-left"', self.html)
        self.assertNotIn('previewToolButton("compare-right"', self.html)
        self.assertIn("function renderInlineCompareControls(", self.html)

    def test_hold_compare_builds_two_directions_and_three_per_three_image_gap(self):
        result = self.run_preview_probe(
            "function buildHoldComparePairs(",
            "function startHoldCompare(",
            """
console.log(JSON.stringify({
    two: buildHoldComparePairs([
        { id: "left", label: "候选图 A" },
        { id: "right", label: "候选图 B" }
    ]),
    three: buildHoldComparePairs([
        { id: "reference", label: "参考图" },
        { id: "left", label: "候选图 A" },
        { id: "right", label: "候选图 B" }
    ])
}));
""",
        )
        self.assertEqual(
            result,
            {
                "two": [
                    {
                        "sourceId": "right",
                        "targetId": "left",
                        "label": "候选图 B 覆盖候选图 A",
                        "slot": "only-upper",
                        "kind": "adjacent",
                        "symbol": "←",
                    },
                    {
                        "sourceId": "left",
                        "targetId": "right",
                        "label": "候选图 A 覆盖候选图 B",
                        "slot": "only-lower",
                        "kind": "adjacent",
                        "symbol": "→",
                    }
                ],
                "three": [
                    {
                        "sourceId": "left",
                        "targetId": "reference",
                        "label": "候选图 A 覆盖参考图",
                        "slot": "left-upper",
                        "kind": "adjacent",
                        "symbol": "←",
                    },
                    {
                        "sourceId": "reference",
                        "targetId": "left",
                        "label": "参考图 覆盖候选图 A",
                        "slot": "left-middle",
                        "kind": "adjacent",
                        "symbol": "→",
                    },
                    {
                        "sourceId": "right",
                        "targetId": "reference",
                        "label": "候选图 B 覆盖参考图",
                        "slot": "left-lower",
                        "kind": "folded",
                        "symbol": "└←",
                    },
                    {
                        "sourceId": "right",
                        "targetId": "left",
                        "label": "候选图 B 覆盖候选图 A",
                        "slot": "right-upper",
                        "kind": "adjacent",
                        "symbol": "←",
                    },
                    {
                        "sourceId": "left",
                        "targetId": "right",
                        "label": "候选图 A 覆盖候选图 B",
                        "slot": "right-middle",
                        "kind": "adjacent",
                        "symbol": "→",
                    },
                    {
                        "sourceId": "reference",
                        "targetId": "right",
                        "label": "参考图 覆盖候选图 B",
                        "slot": "right-lower",
                        "kind": "folded",
                        "symbol": "→┘",
                    },
                ],
            },
        )

    def test_inline_compare_controls_render_three_buttons_in_each_gap(self):
        source = self.html[
            self.html.index("function buildHoldComparePairs(") : self.html.index(
                "function startHoldCompare("
            )
        ]
        script = f"""
{source}
console.log(renderInlineCompareControls("main", [
    {{ id: "reference", label: "参考图" }},
    {{ id: "left", label: "候选图 A" }},
    {{ id: "right", label: "候选图 B" }}
]));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        ).stdout
        self.assertEqual(result.count('data-hold-compare="true"'), 6)
        self.assertIn('data-compare-slot="left-upper"', result)
        self.assertIn('data-compare-slot="left-middle"', result)
        self.assertIn('data-compare-slot="left-lower"', result)
        self.assertIn('data-compare-slot="right-upper"', result)
        self.assertIn('data-compare-slot="right-middle"', result)
        self.assertIn('data-compare-slot="right-lower"', result)
        self.assertEqual(result.count('data-compare-kind="folded"'), 2)
        self.assertIn('class="inline-compare-icon folded"', result)
        self.assertIn('points="21,18 12,5 4,18"', result)
        self.assertIn('points="4.5,12.5 4,18 8.8,15.1"', result)
        self.assertIn('points="3,18 12,5 20,18"', result)
        self.assertIn('points="15.2,15.1 20,18 19.5,12.5"', result)
        self.assertNotIn('points="8,14 4,18 8,22"', result)
        self.assertNotIn('points="16,14 20,18 16,22"', result)
        self.assertEqual(result.count('class="inline-compare-icon folded"'), 2)
        self.assertNotIn("<polygon", result)
        self.assertNotIn("└←", result)
        self.assertNotIn("→┘", result)

    def test_hold_compare_overlay_uses_explicit_source_target_and_cleans_up(self):
        source = self.html[
            self.html.index("function startHoldCompare(") : self.html.index(
                "function bindLightboxControls"
            )
        ]
        script = f"""
const makeClassList = () => {{
    const values = new Set();
    return {{
        add: (...names) => names.forEach(name => values.add(name)),
        remove: (...names) => names.forEach(name => values.delete(name)),
        contains: name => values.has(name)
    }};
}};
const sourceImage = {{ currentSrc: "b.png", src: "b.png" }};
const targetImage = {{ style: {{ cssText: "width: 320px; transform: translate(4px, 8px);" }} }};
const targetChildren = [];
const sourceContainer = {{
    dataset: {{ previewPane: "right", previewLabel: "候选图 B" }},
    querySelector: selector => selector === "img" ? sourceImage : null
}};
const targetContainer = {{
    dataset: {{ previewPane: "left", previewLabel: "候选图 A" }},
    querySelector: selector => selector === "img" ? targetImage : null,
    appendChild: child => targetChildren.push(child)
}};
const button = {{
    classList: makeClassList(),
    attributes: {{}},
    setAttribute(name, value) {{ this.attributes[name] = value; }}
}};
const document = {{
    querySelectorAll: () => [targetContainer, sourceContainer],
    createElement: tag => tag === "img"
        ? {{ style: {{ cssText: "" }}, src: "", alt: "" }}
        : {{
            className: "",
            dataset: {{}},
            children: [],
            appendChild(child) {{ this.children.push(child); }},
            remove() {{ this.removed = true; }}
        }}
}};
const previewController = {{
    groups: new Map([["main", {{ activePaneId: "left" }}]])
}};
let activeHoldCompare = null;
{source}
const started = startHoldCompare("main", "right", "left", button);
const layer = targetChildren[0];
const overlayImage = layer.children[0];
const label = layer.children[1];
const during = {{
    started,
    src: overlayImage.src,
    style: overlayImage.style.cssText,
    label: label.textContent,
    active: button.classList.contains("active"),
    pressed: button.attributes["aria-pressed"]
}};
stopHoldCompare();
console.log(JSON.stringify({{
    during,
    removed: layer.removed,
    activeAfter: button.classList.contains("active"),
    pressedAfter: button.attributes["aria-pressed"]
}}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "during": {
                    "started": True,
                    "src": "b.png",
                    "style": "width: 320px; transform: translate(4px, 8px);",
                    "label": "候选图 B → 候选图 A",
                    "active": True,
                    "pressed": "true",
                },
                "removed": True,
                "activeAfter": False,
                "pressedAfter": "false",
            },
        )

    def test_hold_compare_controls_release_on_pointer_keyboard_and_window_blur(self):
        controls = self.html[
            self.html.index("function bindLightboxControls()") : self.html.index(
                "let previewSpacePan = false;"
            )
        ]
        for marker in (
            'button.matches("[data-hold-compare]")',
            "button.dataset.compareSource",
            "button.dataset.compareTarget",
            'document.addEventListener("pointerup", stopHoldCompare)',
            'document.addEventListener("pointercancel", stopHoldCompare)',
            'document.addEventListener("keyup"',
            'window.addEventListener("blur", stopHoldCompare)',
            'document.addEventListener("visibilitychange"',
        ):
            self.assertIn(marker, controls)

    def test_hold_compare_overlay_and_buttons_have_clear_visual_state(self):
        overlay_rule = self.css_rule(".hold-compare-layer")
        self.assertIn("position: absolute", overlay_rule)
        self.assertIn("pointer-events: none", overlay_rule)
        self.assertIn("z-index:", overlay_rule)
        button_rule = self.css_rule(".inline-compare-btn")
        self.assertIn("touch-action: none", button_rule)
        self.assertIn("position: absolute", button_rule)
        self.assertIn("width: 26px", button_rule)

    def test_inline_compare_buttons_do_not_change_image_grid_columns(self):
        self.assertIn("position: relative", self.css_rule(".compare-grid"))
        self.assertIn("position: relative", self.css_rule(".lightbox-grid"))
        source = self.html[
            self.html.index("function renderCompareGrid()") : self.html.index(
                "function renderImageCard", self.html.index("function renderCompareGrid()")
            )
        ]
        self.assertIn('cards.join("") + renderInlineCompareControls("main", panes)', source)

    def test_toolbar_is_collapsible_and_exposes_shortcut_help(self):
        toolbar_start = self.html.index("function renderPreviewToolbar")
        toolbar_end = self.html.index("function renderCompareGrid", toolbar_start)
        toolbar_source = self.html[toolbar_start:toolbar_end]
        self.assertIn('class="preview-toolbar-content"', toolbar_source)
        self.assertIn('data-preview-help="${groupId}"', toolbar_source)
        self.assertIn("滚轮缩放", toolbar_source)
        self.assertIn("双指缩放", toolbar_source)
        self.assertIn("+ / -", toolbar_source)
        self.assertIn(
            "display: none", self.css_rule(".preview-toolbar.collapsed .preview-toolbar-content")
        )

        lightbox_start = self.html.index('<div class="lightbox-head">')
        lightbox_end = self.html.index('<div id="lightbox-preview-toolbar">', lightbox_start)
        lightbox_header = self.html[lightbox_start:lightbox_end]
        self.assertNotIn(">100%<", lightbox_header)
        self.assertIn(">适应/复位<", lightbox_header)

    def test_desktop_toolbar_uses_non_overlapping_icon_rail_and_horizontal_collapse(self):
        stage_rule = self.css_rule(".preview-stage")
        toolbar_rule = self.css_rule(".preview-toolbar")
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", stage_rule)
        self.assertNotIn("position: fixed", toolbar_rule)
        self.assertIn("width: 44px", toolbar_rule)
        self.assertIn('class="preview-tool-icon"', self.html)
        self.assertIn('class="preview-tool-label visually-hidden"', self.html)
        self.assertIn('data-collapse-direction="right"', self.html)
        self.assertIn('aria-label="向右收起工具"', self.html)
        self.assertIn('button.dataset.collapseDirection = collapsed ? "left" : "right"', self.html)
        self.assertIn('arrow.textContent = collapsed ? "《" : "》"', self.html)

        lightbox_rule = self.css_rule(".lightbox-dialog.preview-stage")
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", lightbox_rule)

    def test_mobile_toolbar_is_in_flow_below_images_without_overlap(self):
        media_start = self.html.index("@media (max-width: 760px)")
        media = self.html[media_start : self.html.index("</style>", media_start)]
        self.assertIn("grid-template-columns: minmax(0, 1fr)", media)
        self.assertIn("#main-preview-toolbar", media)
        self.assertIn("grid-row: 2", media)
        self.assertIn("position: static", media)
        self.assertIn("width: 100%", media)

    def test_collapsed_toolbar_releases_grid_width_and_uses_edge_handle(self):
        collapsed_rule = self.css_rule(".preview-toolbar.collapsed")
        self.assertIn("width: 0", collapsed_rule)
        self.assertIn("padding: 0", collapsed_rule)
        handle_rule = self.css_rule(".preview-toolbar.collapsed > [data-preview-action=\"collapse\"]")
        self.assertIn("position: fixed", handle_rule)
        self.assertIn("right: 0", handle_rule)

    def test_active_preview_tools_have_distinct_shadow_state(self):
        active_rule = self.css_rule(".preview-toolbar .lightbox-btn.active")
        self.assertIn("box-shadow:", active_rule)
        self.assertIn("border-color:", active_rule)

    def test_magnifier_icon_is_larger_than_other_tool_icons(self):
        rule = self.css_rule('.preview-toolbar [data-preview-action="magnifier"] .preview-tool-icon')
        self.assertIn("width: 21px", rule)
        self.assertIn("height: 21px", rule)

    def test_toolbar_prioritizes_magnifier_then_enlarged_reset(self):
        source = self.html[
            self.html.index("function renderPreviewToolbar") : self.html.index(
                "function buildHoldComparePairs"
            )
        ]
        self.assertLess(
            source.index('previewToolButton("magnifier"'),
            source.index('previewToolButton("reset"'),
        )
        self.assertLess(
            source.index('previewToolButton("reset"'),
            source.index('previewToolButton("sync"'),
        )
        reset_rule = self.css_rule('.preview-toolbar [data-preview-action="reset"]')
        self.assertIn("width: 40px", reset_rule)
        self.assertIn("height: 40px", reset_rule)
        reset_icon_rule = self.css_rule(
            '.preview-toolbar [data-preview-action="reset"] .preview-tool-icon'
        )
        self.assertIn("width: 23px", reset_icon_rule)
        self.assertIn("height: 23px", reset_icon_rule)

    def test_collapse_control_uses_double_angle_glyphs(self):
        self.assertIn('<span class="collapse-arrow" aria-hidden="true">》</span>', self.html)
        self.assertIn('arrow.textContent = collapsed ? "《" : "》"', self.html)
        self.assertNotIn('arrow.textContent = collapsed ? "←" : "→"', self.html)

    def test_toolbar_zoom_collapse_and_help_actions_delegate_precisely(self):
        source = self.html[
            self.html.index("function bindLightboxControls()") : self.html.index(
                "let previewSpacePan = false;"
            )
        ]
        script = f"""
const listeners = {{}};
const group = {{ sync: true, magnifier: false }};
const previewController = {{ groups: new Map([["main", group]]), setSync() {{}} }};
const toolbarClasses = new Set();
const helpClasses = new Set(["hidden"]);
const help = {{ classList: {{
    toggle(name) {{ helpClasses.has(name) ? helpClasses.delete(name) : helpClasses.add(name); return helpClasses.has(name); }},
    add(name) {{ helpClasses.add(name); }}
}} }};
const toolbar = {{
    dataset: {{ previewGroup: "main" }},
    classList: {{
        toggle(name) {{ toolbarClasses.has(name) ? toolbarClasses.delete(name) : toolbarClasses.add(name); return toolbarClasses.has(name); }},
        remove(name) {{ toolbarClasses.delete(name); }}
    }},
    querySelector: selector => selector === '[data-preview-help="main"]'
        ? help
        : selector === '[data-preview-action="help"]' ? buttons.help : null
}};
const makeButton = action => ({{
    dataset: {{ previewAction: action }},
    textContent: action,
    expanded: null,
    classList: {{ toggle() {{}} }},
    setAttribute(name, value) {{ if (name === "aria-expanded") this.expanded = value; }},
    closest(selector) {{ return selector === "[data-preview-action]" ? this : toolbar; }}
}});
const buttons = Object.fromEntries(["zoom-out", "zoom-in", "collapse", "help"].map(action => [action, makeButton(action)]));
const document = {{
    addEventListener: (name, fn) => listeners[name] = fn,
    getElementById: () => ({{ classList: {{ contains: () => false }} }})
}};
let lightboxBound = false;
let activeLightboxPane = "left";
let activeHoldCompare = null;
const startHoldCompare = () => false;
const stopHoldCompare = () => null;
const zoomCalls = [];
const adjustPreviewZoom = (groupId, delta) => zoomCalls.push({{ groupId, delta }});
const setPreviewMode = () => null;
const resetPreviewGroup = () => null;
const togglePreviewMagnifier = () => null;
const togglePreviewBackground = () => null;
const openLightbox = () => null;
const closeLightbox = () => null;
{source}
bindLightboxControls();
const click = action => listeners.click({{ target: buttons[action] }});
click("zoom-out");
click("zoom-in");
click("help");
click("collapse");
console.log(JSON.stringify({{
    zoomCalls,
    collapsed: toolbarClasses.has("collapsed"),
    collapseExpanded: buttons.collapse.expanded,
    helpVisible: !helpClasses.has("hidden"),
    helpExpanded: buttons.help.expanded
}}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "zoomCalls": [
                    {"groupId": "main", "delta": -0.16},
                    {"groupId": "main", "delta": 0.16},
                ],
                "collapsed": True,
                "collapseExpanded": "false",
                "helpVisible": False,
                "helpExpanded": "false",
            },
        )

    def test_space_preview_shortcut_does_not_intercept_toolbar_buttons(self):
        self.assertIn(
            '["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(event.target.tagName)',
            self.html,
        )

    def test_dragging_preview_image_suppresses_followup_fullscreen_click(self):
        self.assertIn("function handlePreviewImageClick(event, paneId)", self.html)
        self.assertIn("container.dataset.suppressPreviewClickUntil", self.html)
        self.assertIn("Math.hypot(event.clientX - startX, event.clientY - startY) > 5", self.html)
        self.assertIn('onclick="handlePreviewImageClick(event,', self.html)
        self.assertNotIn('`onclick="openLightbox(\'${key}\')"`', self.html)

    def test_main_preview_cards_share_dynamic_unclipped_image_stage(self):
        main_viewport = self.css_rule(".main-preview-viewport")
        image_stage = self.css_rule(".main-preview-viewport .image-shell")

        self.assertRegex(
            main_viewport,
            r"--main-preview-height:\s*clamp\([^;]*100dvh[^;]*\);",
        )
        self.assertNotIn("height: auto", main_viewport)
        self.assertIn("overflow: visible", main_viewport)
        self.assertIn("height: var(--main-preview-height)", image_stage)
        self.assertIn("min-height: 0", image_stage)
        self.assertIn("overflow: hidden", image_stage)
        self.assertIn('<div class="main-preview-viewport">', self.html)

    def test_ti2i_main_and_lightbox_use_three_equal_columns_until_narrow(self):
        self.assertEqual(
            self.css_rule(".compare-grid.ti2i").strip(),
            "grid-template-columns: repeat(3, minmax(0, 1fr));",
        )
        self.assertEqual(
            self.css_rule(".lightbox-grid.ti2i").strip(),
            "grid-template-columns: repeat(3, minmax(0, 1fr));",
        )

        medium_start = self.html.index("@media (max-width: 1100px)")
        narrow_start = self.html.index("@media (max-width: 760px)", medium_start)
        medium = self.html[medium_start:narrow_start]
        self.assertNotIn(".compare-grid.ti2i", medium)
        self.assertNotIn(".lightbox-grid.ti2i", medium)

        narrow = self.html[narrow_start : self.html.index("</style>", narrow_start)]
        self.assertRegex(
            narrow,
            r"\.compare-grid\.t2i,\s*\.compare-grid\.ti2i,\s*"
            r"\.lightbox-grid\.t2i,\s*\.lightbox-grid\.ti2i\s*\{\s*"
            r"grid-template-columns:\s*minmax\(0, 1fr\);",
        )

    def test_desktop_toolbar_stays_scrollably_within_viewport_and_mobile_uses_horizontal_scroll(self):
        desktop_start = self.html.index(".preview-toolbar {")
        desktop_end = self.html.index("}", desktop_start)
        desktop = self.html[desktop_start:desktop_end]
        self.assertIn("position: sticky", desktop)
        self.assertIn("max-height: calc(100dvh - 100px)", desktop)
        self.assertIn("overflow-y: auto", desktop)

        mobile_start = self.html.index("@media (max-width: 760px)")
        mobile_end = self.html.index("}", self.html.index(".preview-toolbar {", mobile_start))
        mobile = self.html[mobile_start:mobile_end]
        self.assertIn("position: static", mobile)
        self.assertIn("max-height: none", mobile)
        self.assertIn("overflow-x: auto", mobile)
        self.assertIn("overflow-y: hidden", mobile)

    def test_narrow_preview_layout_can_shrink_to_viewport_without_changing_toolbar_axis(self):
        media_start = self.html.index("@media (max-width: 760px)")
        media = self.html[media_start : self.html.index("</style>", media_start)]
        for selector in (
            ".preview-stage",
            ".compare-grid",
            ".image-card",
            ".image-shell",
            ".image-shell img",
        ):
            self.assertIn(selector, media)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", media)
        self.assertIn("min-width: 0", media)
        self.assertIn("max-width: 100%", media)
        self.assertIn("overflow-x: auto", media)
        self.assertIn("overflow-y: hidden", media)

        script = r"""
const css = process.argv[1];
const narrow = css.slice(css.indexOf("@media (max-width: 760px)"));
const required = [".preview-stage", ".compare-grid", ".image-card", ".image-shell", ".image-shell img"];
const shrinkable = required.every(selector => narrow.includes(selector));
const singleTrack = narrow.includes("grid-template-columns: minmax(0, 1fr)");
const toolbarHorizontal = narrow.includes("overflow-x: auto") && narrow.includes("overflow-y: hidden");
console.log(JSON.stringify({ shrinkable, singleTrack, toolbarHorizontal }));
"""
        result = subprocess.run(
            ["node", "-e", script, self.html], check=True, capture_output=True, text=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"shrinkable": True, "singleTrack": True, "toolbarHorizontal": True},
        )

    def test_compact_toolbar_has_accessible_medium_width_density(self):
        marker = "@media (min-width: 761px) and (max-width: 1180px)"
        self.assertIn(marker, self.html)
        media_start = self.html.index(marker)
        media_end = self.html.index("@media", media_start + len(marker))
        media = self.html[media_start:media_end]
        button_rule = self.css_rule(
            ".preview-toolbar.compact .lightbox-btn", media_start
        )
        self.assertIn("padding: 6px 9px", button_rule)
        self.assertIn("font-size: 0.72rem", button_rule)
        self.assertIn(".preview-toolbar.compact .preview-info", media)
        self.assertIn(".preview-toolbar.compact .preview-shortcut-help", media)
        self.assertNotIn("display: none", media)

    def test_reference_image_can_open_fullscreen_preview(self):
        self.assertIn('renderImageCard("reference", "参考图", task.ref_img, true)', self.html)

    def test_shared_preview_controller_contract_exists(self):
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

    def test_preview_controller_synchronizes_normalized_center_only_when_enabled(self):
        result = self.run_controller_probe("""
const updates = {{ a: [], b: [] }};
const controller = new PreviewController();
controller.createGroup("probe");
controller.addPane("probe", "a", {{
    naturalWidth: 1200,
    naturalHeight: 800,
    viewportWidth: 600,
    viewportHeight: 400,
    apply: state => updates.a.push(state.normalizedCenter)
}});
controller.addPane("probe", "b", {{
    naturalWidth: 800,
    naturalHeight: 1200,
    viewportWidth: 400,
    viewportHeight: 600,
    apply: state => updates.b.push(state.normalizedCenter)
}});
controller.setCenter("probe", "a", {{ x: 0.7, y: 0.35 }});
const synced = updates.b.at(-1);
controller.setSync("probe", false);
controller.setCenter("probe", "a", {{ x: 0.2, y: 0.8 }});
console.log(JSON.stringify({{ synced, unchanged: updates.b.at(-1) }}));
""")
        self.assertEqual(
            result,
            {
                "synced": {"x": 0.7, "y": 0.35},
                "unchanged": {"x": 0.7, "y": 0.35},
            },
        )

    def test_hidden_pane_dimensions_are_refreshed_before_fit_is_applied(self):
        open_start = self.html.index("function openLightbox(")
        open_end = self.html.index("function closeLightbox()", open_start)
        open_source = self.html[open_start:open_end]
        self.assertLess(
            open_source.index('classList.add("open")'),
            open_source.index('refreshPreviewGroup("lightbox")'),
        )
        result = self.run_controller_probe("""
let viewportWidth = 0;
let viewportHeight = 0;
const scales = [];
const controller = new PreviewController();
controller.createGroup("lightbox");
controller.addPane("lightbox", "left", {{
    measure: () => ({{ naturalWidth: 1000, naturalHeight: 500, viewportWidth, viewportHeight }}),
    apply: state => scales.push(state.scale)
}});
viewportWidth = 500;
viewportHeight = 250;
controller.refreshGroup("lightbox");
console.log(JSON.stringify(scales));
""")
        self.assertEqual(result[-1], 0.5)
        self.assertTrue(all(scale >= 0 for scale in result))

    def test_resize_refresh_recomputes_fit_without_moving_normalized_center(self):
        result = self.run_controller_probe("""
let viewportWidth = 500;
let viewportHeight = 250;
const applied = [];
const controller = new PreviewController();
controller.createGroup("probe");
controller.addPane("probe", "left", {{
    measure: () => ({{ naturalWidth: 1000, naturalHeight: 500, viewportWidth, viewportHeight }}),
    apply: state => applied.push({{ scale: state.scale, center: state.normalizedCenter }})
}});
controller.setCenter("probe", "left", {{ x: 0.72, y: 0.31 }});
controller.setZoom("probe", "left", 1.5);
viewportWidth = 300;
viewportHeight = 300;
controller.refreshGroup("probe");
console.log(JSON.stringify(applied.at(-1)));
""")
        self.assertAlmostEqual(result["scale"], 0.45)
        self.assertEqual(result["center"], {"x": 0.72, "y": 0.31})

    def test_resize_binding_refreshes_groups_and_cleans_observer_lifecycle(self):
        self.assertIn("const previewResizeCleanups = new Map();", self.html)
        result = self.run_preview_probe(
            "const previewResizeCleanups = new Map();",
            "function togglePreviewMagnifier",
            """
const observed = [];
const disconnected = [];
class ResizeObserver {
    constructor(callback) { this.callback = callback; observed.push(this); }
    observe(container) { this.container = container; }
    disconnect() { disconnected.push(this); }
}
const containers = [{ id: "stage" }];
const document = { querySelectorAll: () => containers };
const window = { addEventListener() {}, removeEventListener() {} };
const refreshed = [];
const refreshPreviewGroup = groupId => refreshed.push(groupId);
bindPreviewResize("main");
observed[0].callback();
bindPreviewResize("main");
releasePreviewResize("main");
console.log(JSON.stringify({
    observed: observed.length,
    observedContainer: observed[0].container.id,
    disconnected: disconnected.length,
    refreshed
}));
""",
        )
        self.assertEqual(
            result,
            {
                "observed": 2,
                "observedContainer": "stage",
                "disconnected": 2,
                "refreshed": ["main"],
            },
        )

    def test_lightbox_rebinds_resize_observer_after_reopening(self):
        open_start = self.html.index("function openLightbox(")
        open_end = self.html.index("function closeLightbox()", open_start)
        source = self.html[open_start:open_end]
        self.assertIn('bindPreviewResize("lightbox")', source)
        self.assertLess(
            source.index('classList.add("open")'),
            source.index('bindPreviewResize("lightbox")'),
        )
        self.assertLess(
            source.index('bindPreviewResize("lightbox")'),
            source.index('refreshPreviewGroup("lightbox")'),
        )

    def test_main_preview_images_are_registered_as_controller_panes(self):
        for marker in (
            'data-preview-pane="${key}"',
            'data-preview-group-pane="main"',
            'registerPreviewPane("main", key',
            'refreshPreviewGroup("main")',
        ):
            self.assertIn(marker, self.html)

    def test_anchor_zoom_preserves_pointer_content_and_updates_normalized_center(self):
        result = self.run_controller_probe("""
const controller = new PreviewController();
controller.createGroup("probe");
controller.addPane("probe", "a", {{
    naturalWidth: 1000,
    naturalHeight: 1000,
    viewportWidth: 100,
    viewportHeight: 100,
    apply: () => null
}});
controller.setZoom("probe", "a", 2, {{ x: 75, y: 50 }});
const pane = controller.groups.get("probe").panes.get("a");
console.log(JSON.stringify(pane.normalizedCenter));
""")
        self.assertEqual(result, {"x": 0.625, "y": 0.5})

    def test_main_and_lightbox_zoom_anchors_use_adapter_content_geometry(self):
        anchor_start = self.html.index("function setPreviewZoom(")
        anchor_end = self.html.index("function setPreviewCenter", anchor_start)
        anchor_source = self.html[anchor_start:anchor_end]
        self.assertIn("pane.adapter.geometry()", anchor_source)
        self.assertNotIn("- 18", anchor_source)

        main_start = self.html.index("function registerPreviewPane(")
        main_end = self.html.index("function applyTransform", main_start)
        self.assertIn(
            "geometry: () => measurePreviewGeometry(container, img, 0)",
            self.html[main_start:main_end],
        )
        lightbox_start = main_end
        lightbox_end = self.html.index("function adjustZoom", lightbox_start)
        self.assertIn(
            "geometry: () => measurePreviewGeometry(container, img, 18)",
            self.html[lightbox_start:lightbox_end],
        )

        result = self.run_preview_probe(
            "function setPreviewZoom(",
            "function setPreviewCenter",
            """
const calls = [];
const panes = new Map([
    ["main", { adapter: { geometry: () => ({ content: { left: 100, top: 50 } }) } }],
    ["lightbox", { adapter: { geometry: () => ({ content: { left: 118, top: 68 } }) } }]
]);
const previewController = {
    groups: new Map([
        ["main", { panes: new Map([["left", panes.get("main")]]) }],
        ["lightbox", { panes: new Map([["left", panes.get("lightbox")]]) }]
    ]),
    setZoom: (...args) => calls.push(args)
};
const anchor = { clientX: 175, clientY: 100 };
setPreviewZoom("main", "left", 2, anchor);
setPreviewZoom("lightbox", "left", 2, anchor);
console.log(JSON.stringify(calls.map(call => call[3])));
""",
        )
        self.assertEqual(result, [{"x": 75, "y": 50}, {"x": 57, "y": 32}])

    def test_preview_adapter_geometry_reports_content_and_rendered_image_rects(self):
        self.assertIn("function measurePreviewGeometry", self.html)
        result = self.run_preview_probe(
            "function measurePreviewGeometry",
            "function registerPreviewPane",
            """
const container = {
    clientLeft: 2,
    clientTop: 3,
    clientWidth: 400,
    clientHeight: 300,
    getBoundingClientRect: () => ({ left: 10, top: 20 })
};
const img = {
    getBoundingClientRect: () => ({ left: 42, top: 58, width: 240, height: 160 })
};
console.log(JSON.stringify(measurePreviewGeometry(container, img, 18)));
""",
        )
        self.assertEqual(
            result,
            {
                "content": {"left": 30, "top": 41, "width": 364, "height": 264},
                "image": {"left": 42, "top": 58, "width": 240, "height": 160},
            },
        )

    def test_sync_button_exposes_pressed_and_active_state(self):
        for marker in (
            'previewToolButton("sync", "同步开", "🔗", { pressed: true, active: true })',
            'updatePreviewToggleControl(groupId, "sync", group.sync, "同步开", "同步关")',
        ):
            self.assertIn(marker, self.html)

    def test_delegated_toolbar_clicks_update_main_and_lightbox_controls(self):
        source = self.html[
            self.html.index("function bindLightboxControls()") : self.html.index("let previewSpacePan = false;")
        ]
        lightbox_blocks_document_click = 'onclick="event.stopPropagation()"' in self.html
        script = f"""
const listeners = {{}};
const groups = new Map([
    ["main", {{ sync: true, magnifier: false }}],
    ["lightbox", {{ sync: true, magnifier: false }}]
]);
const previewController = {{
    groups,
    setSync(groupId, enabled) {{ groups.get(groupId).sync = enabled; }}
}};
const document = {{
    addEventListener: (name, fn) => listeners[name] = fn,
    getElementById: () => ({{ classList: {{ contains: () => false }} }})
}};
let lightboxBound = false;
let activeLightboxPane = "left";
let activeHoldCompare = null;
const startHoldCompare = () => false;
const stopHoldCompare = () => null;
const setPreviewMode = () => null;
const resetPreviewGroup = () => null;
const togglePreviewBackground = () => null;
const openLightbox = () => null;
const closeLightbox = () => null;
const updatePreviewToggleControl = (groupId, action, enabled, enabledText, disabledText) => {{
    const button = buttons[`${{groupId}}:${{action}}`];
    button.classList.toggle("active", enabled);
    button.setAttribute("aria-pressed", String(enabled));
    button.textContent = enabled ? enabledText : disabledText;
}};
const togglePreviewMagnifier = groupId => {{
    const group = groups.get(groupId);
    group.magnifier = !group.magnifier;
    const button = buttons[`${{groupId}}:magnifier`];
    button.classList.toggle("active", group.magnifier);
    button.setAttribute("aria-pressed", String(group.magnifier));
    button.textContent = group.magnifier ? "放大镜开" : "放大镜关";
}};
const toolbar = groupId => ({{ dataset: {{ previewGroup: groupId }} }});
const makeButton = (groupId, action, pressed, text) => ({{
    dataset: {{ previewAction: action }},
    ariaPressed: pressed,
    textContent: text,
    classList: {{ toggle() {{}} }},
    setAttribute(name, value) {{ if (name === "aria-pressed") this.ariaPressed = value; }},
    closest(selector) {{ return selector === "[data-preview-action]" ? this : toolbar(groupId); }}
}});
const buttons = {{}};
for (const groupId of ["main", "lightbox"]) {{
    buttons[`${{groupId}}:sync`] = makeButton(groupId, "sync", "true", "同步开");
    buttons[`${{groupId}}:magnifier`] = makeButton(groupId, "magnifier", "false", "放大镜关");
}}
{source}
bindLightboxControls();
const click = button => listeners.click({{ target: button }});
click(buttons["main:sync"]);
click(buttons["main:magnifier"]);
if (!{str(lightbox_blocks_document_click).lower()}) {{
    click(buttons["lightbox:sync"]);
    click(buttons["lightbox:magnifier"]);
}}
console.log(JSON.stringify(Object.fromEntries([...groups].map(([groupId, group]) => [groupId, {{
    sync: group.sync,
    magnifier: group.magnifier,
    syncPressed: buttons[`${{groupId}}:sync`].ariaPressed,
    syncText: buttons[`${{groupId}}:sync`].textContent,
    magnifierPressed: buttons[`${{groupId}}:magnifier`].ariaPressed,
    magnifierText: buttons[`${{groupId}}:magnifier`].textContent
}}]))));
"""
        result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        expected = {
            "sync": False,
            "magnifier": True,
            "syncPressed": "false",
            "syncText": "同步关",
            "magnifierPressed": "true",
            "magnifierText": "放大镜开",
        }
        self.assertEqual(json.loads(result.stdout), {"main": expected, "lightbox": expected})

    def test_preview_groups_bind_wheel_pointer_and_magnifier_interactions(self):
        for marker in (
            "function bindPreviewGroup(groupId, generation)",
            'addEventListener("wheel"',
            'addEventListener("pointerdown"',
            'addEventListener("pointermove"',
            "setPointerCapture",
            "releasePointerCapture",
            "renderMagnifier(groupId, paneId, point)",
            'addEventListener("pointerleave"',
        ):
            self.assertIn(marker, self.html)

    def test_preview_tools_expose_magnifier_background_and_image_information(self):
        for marker in (
            "function togglePreviewMagnifier(groupId)",
            "function togglePreviewBackground(groupId)",
            'class="magnifier-layer"',
            'data-preview-info="${groupId}"',
            "自然尺寸",
            "缩放",
            "模式",
        ):
            self.assertIn(marker, self.html)

    def test_magnifier_maps_transformed_image_coordinates_and_syncs_full_lenses(self):
        source = self.html[
            self.html.index("function renderMagnifier") : self.html.index(
                "function bindLightboxControls"
            )
        ]
        self.assertNotIn("300% 300%", source)
        script = f"""
const makeLayer = (width, height) => {{
    const classes = new Set();
    return {{
        classes,
        style: {{}},
        offsetWidth: width,
        offsetHeight: height,
        classList: {{
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name)
        }}
    }};
}};
const sourceLayer = makeLayer(150, 150);
const siblingLayer = makeLayer(150, 150);
const sourceImage = {{ src: "source.png", currentSrc: "source.png" }};
const siblingImage = {{ src: "sibling.png", currentSrc: "sibling.png" }};
const containers = {{
    source: {{
        clientWidth: 240,
        clientHeight: 160,
        getBoundingClientRect: () => ({{ left: 0, top: 0, width: 240, height: 160 }}),
        querySelector: selector => selector === "img" ? sourceImage : sourceLayer
    }},
    sibling: {{
        clientWidth: 140,
        clientHeight: 240,
        getBoundingClientRect: () => ({{ left: 300, top: 0, width: 140, height: 240 }}),
        querySelector: selector => selector === "img" ? siblingImage : siblingLayer
    }}
}};
const panes = new Map([
    ["source", {{ failed: false, adapter: {{ geometry: () => ({{
        content: {{ left: 0, top: 0, width: 240, height: 160 }},
        image: {{ left: 20, top: 10, width: 200, height: 100 }}
    }}) }} }}],
    ["sibling", {{ failed: false, adapter: {{ geometry: () => ({{
        content: {{ left: 300, top: 0, width: 140, height: 240 }},
        image: {{ left: 320, top: 40, width: 100, height: 200 }}
    }}) }} }}]
]);
const group = {{ magnifier: true, sync: true, panes }};
const previewController = {{ groups: new Map([["main", group]]) }};
const document = {{
    querySelector: selector => selector.includes('data-preview-pane="source"') ? containers.source : containers.sibling
}};
const hidePreviewMagnifiers = () => [sourceLayer, siblingLayer].forEach(layer => layer.classList.remove("visible", "marker"));
{source}
const shown = renderMagnifier("main", "source", {{ clientX: 120, clientY: 60 }});
const synced = {{
    shown,
    source: {{
        visible: sourceLayer.classes.has("visible"),
        marker: sourceLayer.classes.has("marker"),
        left: sourceLayer.style.left,
        top: sourceLayer.style.top,
        size: sourceLayer.style.backgroundSize,
        position: sourceLayer.style.backgroundPosition
    }},
    sibling: {{
        visible: siblingLayer.classes.has("visible"),
        marker: siblingLayer.classes.has("marker"),
        left: siblingLayer.style.left,
        top: siblingLayer.style.top,
        size: siblingLayer.style.backgroundSize,
        position: siblingLayer.style.backgroundPosition
    }}
}};
group.sync = false;
renderMagnifier("main", "source", {{ clientX: 120, clientY: 60 }});
const unsyncedSiblingVisible = siblingLayer.classes.has("visible");
const outside = renderMagnifier("main", "source", {{ clientX: 5, clientY: 60 }});
console.log(JSON.stringify({{ synced, unsyncedSiblingVisible, outside, sourceVisibleAfterOutside: sourceLayer.classes.has("visible") }}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "synced": {
                    "shown": True,
                    "source": {
                        "visible": True,
                        "marker": False,
                        "left": "45px",
                        "top": "0px",
                        "size": "600px 300px",
                        "position": "-225px -90px",
                    },
                    "sibling": {
                        "visible": True,
                        "marker": False,
                        "left": "0px",
                        "top": "65px",
                        "size": "300px 600px",
                        "position": "-80px -225px",
                    },
                },
                "unsyncedSiblingVisible": False,
                "outside": False,
                "sourceVisibleAfterOutside": False,
            },
        )

    def test_magnifier_uses_small_radius_rectangle(self):
        magnifier_rule = self.css_rule(".magnifier-layer")
        self.assertIn("border-radius: 12px", magnifier_rule)
        self.assertNotIn("border-radius: 50%", magnifier_rule)

    def test_magnifier_clamps_to_viewport_edges_and_preserves_pointer_anchor(self):
        source = self.html[
            self.html.index("function renderMagnifier") : self.html.index(
                "function bindLightboxControls"
            )
        ]
        script = f"""
const classes = new Set();
const layer = {{
    style: {{}},
    offsetWidth: 150,
    offsetHeight: 150,
    classList: {{
        add: (...names) => names.forEach(name => classes.add(name)),
        remove: (...names) => names.forEach(name => classes.delete(name)),
        toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name)
    }}
}};
const image = {{ src: "source.png", currentSrc: "source.png" }};
const container = {{
    clientWidth: 240,
    clientHeight: 160,
    getBoundingClientRect: () => ({{ left: 0, top: 0, width: 240, height: 160 }}),
    querySelector: selector => selector === "img" ? image : layer
}};
const pane = {{ failed: false, adapter: {{ geometry: () => ({{
    content: {{ left: 0, top: 0, width: 240, height: 160 }},
    image: {{ left: 20, top: 10, width: 200, height: 100 }}
}}) }} }};
const group = {{ magnifier: true, sync: false, panes: new Map([["source", pane]]) }};
const previewController = {{ groups: new Map([["main", group]]) }};
const document = {{ querySelector: () => container }};
const hidePreviewMagnifiers = () => layer.classList.remove("visible", "marker");
{source}
renderMagnifier("main", "source", {{ clientX: 20, clientY: 10 }});
const topLeft = {{
    left: layer.style.left,
    top: layer.style.top,
    position: layer.style.backgroundPosition
}};
renderMagnifier("main", "source", {{ clientX: 220, clientY: 110 }});
console.log(JSON.stringify({{
    topLeft,
    bottomRight: {{
        left: layer.style.left,
        top: layer.style.top,
        position: layer.style.backgroundPosition
    }}
}}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "topLeft": {"left": "0px", "top": "0px", "position": "20px 10px"},
                "bottomRight": {
                    "left": "90px",
                    "top": "10px",
                    "position": "-470px -200px",
                },
            },
        )

    def test_touch_skips_magnifier_and_pinch_preserves_single_pointer_pan(self):
        result = self.run_preview_probe(
            "let previewSpacePan = false;",
            "const observer =",
            """
const listeners = {};
const classes = new Set();
const captured = new Set();
const image = { addEventListener() {} };
const container = {
    dataset: { previewPane: "left" },
    classList: {
        toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
        add: name => classes.add(name),
        remove: name => classes.delete(name)
    },
    querySelector: () => image,
    addEventListener: (name, fn) => listeners[name] = fn,
    setPointerCapture: pointerId => captured.add(pointerId),
    hasPointerCapture: pointerId => captured.has(pointerId),
    releasePointerCapture: pointerId => captured.delete(pointerId),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 })
};
const pane = {
    failed: false,
    zoom: 1,
    normalizedCenter: { x: 0.5, y: 0.5 },
    adapter: { measure: () => ({ naturalWidth: 100, naturalHeight: 100 }) }
};
const group = { mode: "actual", magnifier: true, darkBackground: false, panes: new Map([["left", pane]]) };
const document = { querySelectorAll: () => [container] };
const previewController = { groups: new Map([["main", group]]), fitScale: () => 1 };
let activeLightboxPane = "";
let magnifierCalls = 0;
const renderMagnifier = () => magnifierCalls++;
const hidePreviewMagnifiers = () => null;
const zoomCalls = [];
const centerCalls = [];
const setPreviewZoom = (groupId, paneId, zoom, anchor) => { pane.zoom = zoom; zoomCalls.push({ zoom, anchor }); };
const setPreviewCenter = (groupId, paneId, center) => { pane.normalizedCenter = center; centerCalls.push(center); };
bindPreviewGroup("main");
const touch = (pointerId, clientX, clientY = 10) => ({
    button: 0, pointerId, pointerType: "touch", clientX, clientY, preventDefault() {}
});
listeners.pointerdown(touch(1, 10));
listeners.pointermove(touch(1, 20));
listeners.pointerdown(touch(2, 40));
listeners.pointermove(touch(2, 60));
listeners.pointerup(touch(2, 60));
listeners.pointermove(touch(1, 30));
console.log(JSON.stringify({ magnifierCalls, zoomCalls, centerCalls }));
""",
        )
        self.assertEqual(result["magnifierCalls"], 0)
        self.assertEqual(
            result["zoomCalls"],
            [{"zoom": 2, "anchor": {"clientX": 40, "clientY": 10}}],
        )
        self.assertEqual(result["centerCalls"][0], {"x": 0.4, "y": 0.5})
        self.assertAlmostEqual(result["centerCalls"][1]["x"], 0.35)
        self.assertEqual(result["centerCalls"][1]["y"], 0.5)

    def test_preview_keyboard_shortcuts_preserve_scoring_keys_and_ignore_form_fields(self):
        for marker in (
            'let previewSpacePan = false',
            'event.key === " "',
            'event.key === "+"',
            'event.key === "-"',
            '["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(event.target.tagName)',
        ):
            self.assertIn(marker, self.html)

        scoring_start = self.html.index('document.addEventListener("keydown", event => {', self.html.index("const observer"))
        scoring_source = self.html[scoring_start:self.html.index("init();", scoring_start)]
        for key in ('event.key === "1"', 'event.key === "2"', 'event.key === "3"', 'event.key === "Enter"'):
            self.assertIn(key, scoring_source)

    def test_lightbox_accepts_any_source_pane_and_resets_group_to_synced_fit(self):
        self.assertIn("function openLightbox(sourcePaneId)", self.html)
        self.assertIn("activeLightboxPane = sourcePaneId", self.html)
        self.assertIn('previewController.setSync("lightbox", true)', self.html)
        self.assertIn('setPreviewMode("lightbox", "fit")', self.html)

    def test_lightbox_prompt_is_synchronized_as_header_text(self):
        self.assertIn('id="lightbox-prompt"', self.html)
        sync_start = self.html.index("function syncLightboxPrompt()")
        sync_end = self.html.index("function openLightbox(", sync_start)
        sync_source = self.html[sync_start:sync_end]
        script = f"""
const classes = new Set(["hidden"]);
const promptNode = {{
    textContent: "stale prompt",
    classList: {{
        toggle(name, enabled) {{ enabled ? classes.add(name) : classes.delete(name); }}
    }}
}};
const document = {{ getElementById: id => id === "lightbox-prompt" ? promptNode : null }};
let state = {{ currentTask: {{ prompt: "line one\\nline two" }} }};
{sync_source}
syncLightboxPrompt();
const shown = {{ text: promptNode.textContent, hidden: classes.has("hidden") }};
state.currentTask.prompt = "";
syncLightboxPrompt();
console.log(JSON.stringify({{
    shown,
    hidden: {{ text: promptNode.textContent, hidden: classes.has("hidden") }}
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(
            result,
            {
                "shown": {"text": "line one\nline two", "hidden": False},
                "hidden": {"text": "", "hidden": True},
            },
        )

        open_start = self.html.index("function openLightbox(")
        open_end = self.html.index("function handlePreviewImageClick", open_start)
        open_source = self.html[open_start:open_end]
        self.assertLess(
            open_source.index("syncLightboxPrompt()"),
            open_source.index('classList.add("open")'),
        )
        self.assertIn("grid-row: 1", self.css_rule(".lightbox-dialog.preview-stage .lightbox-head"))
        self.assertIn("grid-row: 2", self.css_rule("#lightbox-grid"))

    def test_open_lightbox_prompt_tracks_task_advance_and_close(self):
        source = self.html[
            self.html.index("function renderLightbox()") : self.html.index(
                "function measurePreviewGeometry"
            )
        ]
        script = f"""
const makeClasses = initial => {{
    const values = new Set(initial);
    return {{
        add: (...names) => names.forEach(name => values.add(name)),
        remove: (...names) => names.forEach(name => values.delete(name)),
        contains: name => values.has(name),
        toggle(name, enabled) {{
            if (enabled === undefined) enabled = !values.has(name);
            enabled ? values.add(name) : values.delete(name);
            return enabled;
        }}
    }};
}};
const promptNode = {{ textContent: "", classList: makeClasses(["hidden"]) }};
const lightbox = {{ classList: makeClasses(["open"]) }};
const grid = {{ className: "", innerHTML: "" }};
const toolbar = {{ innerHTML: "" }};
const document = {{
    body: {{ style: {{ overflow: "hidden" }} }},
    getElementById(id) {{
        if (id === "lightbox-prompt") return promptNode;
        if (id === "lightbox") return lightbox;
        if (id === "lightbox-grid") return grid;
        if (id === "lightbox-preview-toolbar") return toolbar;
        return null;
    }},
    querySelector: () => null
}};
let state = {{
    currentTask: {{ prompt: "old prompt", left_img: "old-a", right_img: "old-b" }},
    config: {{ show_ref: false }},
    taskType: "T2I"
}};
let activeLightboxPane = "left";
const previewController = {{ groups: new Map([["lightbox", {{ activePaneId: "left" }}]]) }};
const stopHoldCompare = () => null;
const releasePreviewPointers = () => null;
const beginPreviewRender = () => 1;
const renderInlineCompareControls = () => "";
const renderPreviewToolbar = () => "";
const createPreviewGroup = () => null;
const bindLightboxControls = () => null;
const bindPreviewGroup = () => null;
const hidePreviewMagnifiers = () => null;
const setPreviewSpacePan = () => null;
{source}
syncLightboxPrompt();
state.currentTask = {{ prompt: "next prompt", left_img: "next-a", right_img: "next-b" }};
renderLightbox();
const afterNext = {{ text: promptNode.textContent, hidden: promptNode.classList.contains("hidden") }};
state.currentTask = {{ prompt: "", left_img: "empty-a", right_img: "empty-b" }};
renderLightbox();
const afterEmpty = {{ text: promptNode.textContent, hidden: promptNode.classList.contains("hidden") }};
state.currentTask = {{ prompt: "close prompt", left_img: "close-a", right_img: "close-b" }};
syncLightboxPrompt();
closeLightbox();
console.log(JSON.stringify({{
    afterNext,
    afterEmpty,
    afterClose: {{
        text: promptNode.textContent,
        hidden: promptNode.classList.contains("hidden"),
        open: lightbox.classList.contains("open")
    }}
}}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", script], text=True))
        self.assertEqual(
            result,
            {
                "afterNext": {"text": "next prompt", "hidden": False},
                "afterEmpty": {"text": "", "hidden": True},
                "afterClose": {"text": "", "hidden": True, "open": False},
            },
        )

    def test_lightbox_close_and_reopen_restores_toggle_state_and_controls(self):
        source = self.html[
            self.html.index("function renderLightbox()") : self.html.index(
                "function measurePreviewGeometry"
            )
        ]
        script = f"""
const makeClasses = initial => {{
    const values = new Set(initial);
    return {{
        values,
        add: name => values.add(name),
        remove: name => values.delete(name),
        contains: name => values.has(name),
        toggle(name, enabled) {{
            if (enabled === undefined) enabled = !values.has(name);
            enabled ? values.add(name) : values.delete(name);
            return enabled;
        }}
    }};
}};
const makeButton = (pressed, text, active) => ({{
    textContent: text,
    pressed,
    classList: makeClasses(active ? ["active"] : []),
    setAttribute(name, value) {{ if (name === "aria-pressed") this.pressed = value; }}
}});
const syncButton = makeButton("false", "同步关", false);
const magnifierButton = makeButton("true", "放大镜开", true);
const lightbox = {{ classList: makeClasses([]) }};
const promptNode = {{ textContent: "", classList: makeClasses(["hidden"]) }};
const state = {{ currentTask: {{ prompt: "" }} }};
const group = {{ sync: false, magnifier: true, activePaneId: "right" }};
const previewController = {{
    groups: new Map([["lightbox", group]]),
    setSync(groupId, enabled) {{ this.groups.get(groupId).sync = enabled; }}
}};
const document = {{
    body: {{ style: {{ overflow: "" }} }},
    getElementById: id => id === "lightbox" ? lightbox : id === "lightbox-prompt" ? promptNode : null,
    querySelector: selector => selector.includes('data-preview-action="sync"') ? syncButton : magnifierButton
}};
let activeLightboxPane = "right";
const hidden = [];
const hidePreviewMagnifiers = groupId => hidden.push(groupId === undefined ? "all" : groupId);
const setPreviewMode = () => null;
const resetPreviewGroup = () => null;
const bindPreviewResize = () => null;
const refreshPreviewGroup = () => null;
const setPreviewSpacePan = () => null;
const releasePreviewPointers = () => null;
{source}
closeLightbox();
const afterClose = {{
    magnifier: group.magnifier,
    magnifierText: magnifierButton.textContent,
    magnifierPressed: magnifierButton.pressed,
    magnifierActive: magnifierButton.classList.contains("active")
}};
openLightbox("left");
console.log(JSON.stringify({{
    afterClose,
    reopened: {{
        sync: group.sync,
        syncText: syncButton.textContent,
        syncPressed: syncButton.pressed,
        syncActive: syncButton.classList.contains("active"),
        magnifier: group.magnifier,
        magnifierText: magnifierButton.textContent,
        magnifierPressed: magnifierButton.pressed,
        magnifierActive: magnifierButton.classList.contains("active")
    }}
}}));
"""
        result = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "afterClose": {
                    "magnifier": False,
                    "magnifierText": "放大镜关",
                    "magnifierPressed": "false",
                    "magnifierActive": False,
                },
                "reopened": {
                    "sync": True,
                    "syncText": "同步开",
                    "syncPressed": "true",
                    "syncActive": True,
                    "magnifier": False,
                    "magnifierText": "放大镜关",
                    "magnifierPressed": "false",
                    "magnifierActive": False,
                },
            },
        )

    def test_space_pan_requires_a_matching_pointer_drag(self):
        result = self.run_preview_probe(
            "let previewSpacePan = false;",
            "const observer =",
            """
const listeners = {};
const imageListeners = {};
const centers = [];
const container = {
    dataset: { previewPane: "left" },
    classList: { toggle() {}, add() {}, remove() {} },
    querySelector: () => ({ addEventListener: (name, fn) => imageListeners[name] = fn }),
    addEventListener: (name, fn) => listeners[name] = fn,
    setPointerCapture() {}, hasPointerCapture: () => false,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 })
};
const pane = { zoom: 1, normalizedCenter: { x: 0.5, y: 0.5 }, adapter: { measure: () => ({ naturalWidth: 100, naturalHeight: 100 }) } };
const group = { mode: "actual", darkBackground: false, panes: new Map([["left", pane]]) };
const document = { querySelectorAll: () => [container] };
const previewController = { groups: new Map([["main", group]]), fitScale: () => 1 };
let activeLightboxPane = "";
const renderMagnifier = () => null;
const setPreviewZoom = () => null;
const setPreviewCenter = (...args) => centers.push(args);
const hidePreviewMagnifiers = () => null;
bindPreviewGroup("main");
previewSpacePan = true;
listeners.pointermove({ pointerId: 9, clientX: 70, clientY: 50 });
listeners.pointerdown({ button: 0, pointerId: 4, clientX: 50, clientY: 50, preventDefault() {} });
listeners.pointermove({ pointerId: 9, clientX: 80, clientY: 50 });
listeners.pointermove({ pointerId: 4, clientX: 60, clientY: 50 });
console.log(JSON.stringify({ centerCalls: centers.length, center: centers[0][2] }));
""",
        )
        self.assertEqual(result, {"centerCalls": 1, "center": {"x": 0.4, "y": 0.5}})

    def test_image_error_cleanup_is_bound_before_dimensions_are_available(self):
        result = self.run_preview_probe(
            "let previewSpacePan = false;",
            "const observer =",
            """
const imageListeners = {};
const container = {
    dataset: { previewPane: "left" },
    classList: { toggle() {} },
    querySelector: () => ({ naturalWidth: 0, addEventListener: (name, fn) => imageListeners[name] = fn }),
    addEventListener() {}
};
const document = { querySelectorAll: () => [container] };
const previewController = { groups: new Map([["main", { darkBackground: false }]]) };
const hidden = [];
const hidePreviewMagnifiers = groupId => hidden.push(groupId);
bindPreviewGroup("main");
if (imageListeners.error) imageListeners.error();
console.log(JSON.stringify({ bound: Boolean(imageListeners.error), hidden }));
""",
        )
        self.assertEqual(result, {"bound": True, "hidden": ["main"]})

    def test_preview_panes_expose_loading_and_error_states(self):
        for marker in (
            'class="image-loading"',
            'class="preview-loading"',
            'classList.remove("loading")',
            'classList.add("image-error")',
            '图片加载失败',
        ):
            self.assertIn(marker, self.html)

    def test_failed_panes_are_excluded_from_synchronized_updates(self):
        self.assertIn("failed: false", self.html)
        self.assertIn("if (target.failed) return;", self.html)

    def test_loading_a_task_resets_both_preview_groups(self):
        start = self.html.index("async function loadNextTask()")
        end = self.html.index("function setTaskActionPending", start)
        source = self.html[start:end]
        self.assertIn('resetPreviewGroup("main")', source)
        self.assertIn('resetPreviewGroup("lightbox")', source)

    def test_close_lightbox_cleans_pointer_and_magnifier_state(self):
        start = self.html.index("function closeLightbox()")
        end = self.html.index("function registerPreviewPane", start)
        source = self.html[start:end]
        self.assertIn("setPreviewSpacePan(false)", source)
        self.assertIn('releasePreviewPointers("lightbox", true)', source)

    def test_close_preserves_pointer_cleanup_bindings_for_lightbox_reopen(self):
        result = self.run_preview_probe(
            "function releasePreviewPointers",
            "const previewResizeCleanups",
            """
let cleaned = 0;
const previewPointerCleanups = new Map([["lightbox", [() => cleaned++]]]);
const releasePreviewResize = () => null;
releasePreviewPointers("lightbox", true);
const retained = previewPointerCleanups.has("lightbox");
releasePreviewPointers("lightbox");
console.log(JSON.stringify({ cleaned, retained, removed: !previewPointerCleanups.has("lightbox") }));
""",
        )
        self.assertEqual(result, {"cleaned": 2, "retained": True, "removed": True})

        close_start = self.html.index("function closeLightbox()")
        close_end = self.html.index("function measurePreviewGeometry", close_start)
        self.assertIn(
            'releasePreviewPointers("lightbox", true)',
            self.html[close_start:close_end],
        )

    def test_repeated_preview_render_releases_old_pointer_cleanup_without_growth(self):
        result = self.run_preview_probe(
            "function renderCompareGrid()",
            "function renderImageCard",
            """
const previewPointerCleanups = new Map();
const cleaned = [];
const releasePreviewPointers = groupId => {
    (previewPointerCleanups.get(groupId) || []).forEach(cleanup => cleanup());
    previewPointerCleanups.delete(groupId);
};
const container = { dataset: { previewPane: "left" }, querySelector: () => ({ addEventListener() {}, complete: false }) };
const grid = { className: "", innerHTML: "", querySelectorAll: () => [container] };
const document = {
    getElementById: id => id === "compare-grid" ? grid : { innerHTML: "" }
};
const state = { currentTask: { left_img: "a", right_img: "b" }, config: { show_ref: false }, taskType: "T2I" };
const hidePreviewMagnifiers = () => null;
let renderGeneration = 0;
const beginPreviewRender = () => ++renderGeneration;
const isPreviewGenerationCurrent = (groupId, generation) => generation === renderGeneration;
const addPreviewImageListener = (groupId, image, name, callback, options) => image.addEventListener(name, callback, options);
const renderImageCard = () => "";
const renderInlineCompareControls = () => "";
const renderPreviewToolbar = () => "";
const createPreviewGroup = () => null;
const registerPreviewPane = () => null;
const refreshPreviewGroup = () => null;
const bindPreviewGroup = groupId => {
    const cleanups = previewPointerCleanups.get(groupId) || [];
    cleanups.push(() => cleaned.push(groupId));
    previewPointerCleanups.set(groupId, cleanups);
};
renderCompareGrid();
renderCompareGrid();
console.log(JSON.stringify({ cleaned, retained: previewPointerCleanups.get("main").length }));
""",
        )
        self.assertEqual(result, {"cleaned": ["main"], "retained": 1})
        lightbox_start = self.html.index("function renderLightbox()")
        lightbox_end = self.html.index("function renderLightboxPane", lightbox_start)
        self.assertIn('releasePreviewPointers("lightbox")', self.html[lightbox_start:lightbox_end])

    def test_late_main_image_load_cannot_register_into_new_render_generation(self):
        self.assertIn("const previewRenderGenerations = new Map();", self.html)
        result = self.run_preview_probe(
            "const previewRenderGenerations = new Map();",
            "function renderImageCard",
            """
const removed = [];
const makeImage = id => ({
    id,
    complete: false,
    naturalWidth: 100,
    handlers: {},
    addEventListener(name, callback) { this.handlers[name] = callback; },
    removeEventListener(name, callback) {
        if (this.handlers[name] === callback) {
            removed.push(`${this.id}:${name}`);
            delete this.handlers[name];
        }
    }
});
const images = [makeImage("old"), makeImage("new")];
const containers = images.map(image => ({
    dataset: { previewPane: "left" },
    querySelector: () => image
}));
let renderIndex = -1;
const grid = {
    className: "",
    set innerHTML(value) { renderIndex += 1; },
    querySelectorAll: () => [containers[renderIndex]]
};
const toolbar = { innerHTML: "" };
const document = { getElementById: id => id === "compare-grid" ? grid : toolbar };
const state = {
    currentTask: { left_img: "a", right_img: "b" },
    config: { show_ref: false },
    taskType: "T2I"
};
const releasePreviewPointers = () => null;
const hidePreviewMagnifiers = () => null;
const renderImageCard = () => "";
const renderInlineCompareControls = () => "";
const renderPreviewToolbar = () => "";
const createPreviewGroup = () => null;
const registered = [];
const registerPreviewPane = (groupId, paneId, container, image) => registered.push(image.id);
const refreshPreviewGroup = () => null;
const bindPreviewGroup = () => null;
renderCompareGrid();
const staleLoad = images[0].handlers.load;
renderCompareGrid();
staleLoad();
images[1].handlers.load();
console.log(JSON.stringify({ removed, registered }));
""",
        )
        self.assertEqual(result, {"removed": ["old:load"], "registered": ["new"]})

    def test_stale_load_and_error_state_callbacks_ignore_replaced_group(self):
        result = self.run_preview_probe(
            "function bindPreviewImageState",
            "function releasePreviewPointers",
            """
const classes = new Set(["loading"]);
const container = {
    classList: {
        add: name => classes.add(name),
        remove: name => classes.delete(name)
    }
};
const handlers = {};
const img = {
    complete: false,
    addEventListener: (name, callback) => handlers[name] = callback
};
const pane = { failed: false };
const previewController = { groups: new Map([["main", { panes: new Map([["left", pane]]) }]]) };
const previewRenderGenerations = new Map([["main", 2]]);
const isPreviewGenerationCurrent = (groupId, generation) => previewRenderGenerations.get(groupId) === generation;
const addPreviewImageListener = (groupId, target, name, callback) => target.addEventListener(name, callback);
let hidden = 0;
const hidePreviewMagnifiers = () => hidden++;
bindPreviewImageState("main", "left", container, img, 1);
handlers.load();
handlers.error();
console.log(JSON.stringify({
    loading: classes.has("loading"),
    imageError: classes.has("image-error"),
    failed: pane.failed,
    hidden
}));
""",
        )
        self.assertEqual(
            result,
            {"loading": True, "imageError": False, "failed": False, "hidden": 0},
        )

    def test_render_generations_cover_lightbox_bindings_and_callbacks(self):
        lightbox_start = self.html.index("function renderLightbox()")
        lightbox_end = self.html.index("function renderLightboxPane", lightbox_start)
        self.assertIn(
            'const generation = beginPreviewRender("lightbox")',
            self.html[lightbox_start:lightbox_end],
        )
        bind_start = self.html.index("function bindPreviewGroup(groupId")
        bind_end = self.html.index("const observer =", bind_start)
        bind_source = self.html[bind_start:bind_end]
        self.assertIn("isPreviewGenerationCurrent(groupId, generation)", bind_source)
        self.assertIn("addPreviewImageListener(groupId, img, \"load\"", bind_source)

    def test_failed_controller_source_cannot_zoom_or_pan(self):
        result = self.run_controller_probe("""
const updates = [];
const controller = new PreviewController();
controller.createGroup("probe");
controller.addPane("probe", "failed", { naturalWidth: 100, naturalHeight: 100, viewportWidth: 100, viewportHeight: 100, apply: state => updates.push(state) });
const pane = controller.groups.get("probe").panes.get("failed");
pane.failed = true;
controller.setZoom("probe", "failed", 2);
controller.setCenter("probe", "failed", { x: 0.2, y: 0.3 });
console.log(JSON.stringify({ zoom: pane.zoom, center: pane.normalizedCenter, updates: updates.length }));
""")
        self.assertEqual(result, {"zoom": 1, "center": {"x": 0.5, "y": 0.5}, "updates": 1})

    def test_failed_pane_cannot_start_pointer_interaction_or_render_magnifier(self):
        bind_source = self.html[
            self.html.index("let previewSpacePan = false;") : self.html.index("const observer =")
        ]
        magnifier_source = self.html[
            self.html.index("function renderMagnifier") : self.html.index("function bindLightboxControls")
        ]
        script = f"""
const listeners = {{}};
const classes = new Set();
const layer = {{ classList: {{ add: () => classes.add("visible"), toggle() {{}} }}, style: {{}}, offsetWidth: 10, offsetHeight: 10 }};
const image = {{ addEventListener() {{}}, src: "x" }};
const container = {{
    dataset: {{ previewPane: "failed" }},
    classList: {{ toggle() {{}}, add: name => classes.add(name), remove: name => classes.delete(name) }},
    querySelector: selector => selector === "img" ? image : layer,
    addEventListener: (name, fn) => listeners[name] = fn,
    getBoundingClientRect: () => ({{ left: 0, top: 0, width: 100, height: 100 }}),
    setPointerCapture() {{}}, hasPointerCapture: () => false
}};
const pane = {{ failed: true, zoom: 1, normalizedCenter: {{ x: 0.5, y: 0.5 }} }};
const group = {{ magnifier: true, darkBackground: false, panes: new Map([["failed", pane]]) }};
const document = {{ querySelectorAll: () => [container], querySelector: () => container }};
const previewController = {{ groups: new Map([["main", group]]) }};
const hidePreviewMagnifiers = () => null;
const bindPreviewImageState = () => null;
let activeLightboxPane = "";
let zoomCalls = 0;
const setPreviewZoom = () => zoomCalls++;
const renderMagnifierCalls = [];
{magnifier_source}
{bind_source}
bindPreviewGroup("main");
listeners.wheel({{ deltaY: -1, clientX: 10, clientY: 10, preventDefault() {{}} }});
listeners.pointerdown({{ button: 0, pointerId: 1, clientX: 10, clientY: 10, preventDefault() {{}} }});
renderMagnifier("main", "failed", {{ x: 0.5, y: 0.5 }});
console.log(JSON.stringify({{ zoomCalls, dragging: classes.has("dragging"), magnifier: classes.has("visible") }}));
"""
        result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), {"zoomCalls": 0, "dragging": False, "magnifier": False})

    def test_close_lightbox_clears_magnifiers_for_every_group(self):
        result = self.run_preview_probe(
            "function updatePreviewToggleControl",
            "function registerPreviewPane",
            """
const hidden = [];
const hidePreviewMagnifiers = groupId => hidden.push(groupId === undefined ? "all" : groupId);
const previewController = { groups: new Map([["lightbox", { magnifier: true }]]) };
const lightbox = { classList: { remove() {} } };
const promptNode = { textContent: "prompt", classList: { add() {} } };
const document = {
    body: { style: {} },
    getElementById: id => id === "lightbox-prompt" ? promptNode : lightbox,
    querySelector: () => null
};
closeLightbox();
console.log(JSON.stringify(hidden));
""",
        )
        self.assertEqual(result, ["lightbox", "all"])

    def test_active_pane_owns_synced_information_and_mode_pressed_state(self):
        result = self.run_preview_probe(
            "function updatePreviewInfo(groupId, paneId)",
            "function hidePreviewMagnifiers",
            """
const label = { textContent: "" };
const buttons = ["fit", "actual"].map(action => ({
    dataset: { previewAction: action },
    classList: { toggle() {} },
    pressed: null,
    setAttribute(name, value) { if (name === "aria-pressed") this.pressed = value; }
}));
const panes = new Map([
    ["left", { zoom: 2, adapter: { measure: () => ({ naturalWidth: 640, naturalHeight: 480 }) } }],
    ["right", { zoom: 2, adapter: { measure: () => ({ naturalWidth: 1920, naturalHeight: 1080 }) } }]
]);
const previewController = {
    groups: new Map([["main", { mode: "fit", activePaneId: "left", panes }]]),
    fitScale: () => 0.5
};
const document = {
    querySelector: () => label,
    querySelectorAll: () => buttons
};
updatePreviewInfo("main", "left");
updatePreviewInfo("main", "right");
console.log(JSON.stringify({ text: label.textContent, pressed: buttons.map(button => button.pressed) }));
""",
        )
        self.assertEqual(
            result,
            {
                "text": "自然尺寸 640×480 · 渲染比例 100% · 适应倍率 200% · 模式 适应",
                "pressed": ["true", "false"],
            },
        )

    def test_unregistered_pane_ignores_wheel_and_pointerdown(self):
        result = self.run_preview_probe(
            "let previewSpacePan = false;",
            "const observer =",
            """
const listeners = {};
const container = {
    dataset: { previewPane: "missing" },
    classList: { toggle() {}, add() {} },
    querySelector: () => ({ addEventListener() {} }),
    addEventListener: (name, fn) => listeners[name] = fn
};
const group = { darkBackground: false, panes: new Map() };
const document = { querySelectorAll: () => [container] };
const previewController = { groups: new Map([["main", group]]) };
let activeLightboxPane = "";
const hidePreviewMagnifiers = () => null;
let zoomCalls = 0;
const setPreviewZoom = () => zoomCalls++;
bindPreviewGroup("main");
let wheelSafe = true;
let pointerSafe = true;
try { listeners.wheel({ deltaY: -1, preventDefault() {} }); } catch (_) { wheelSafe = false; }
try { listeners.pointerdown({ button: 0, pointerId: 3, clientX: 10, clientY: 10, preventDefault() {} }); } catch (_) { pointerSafe = false; }
console.log(JSON.stringify({ wheelSafe, pointerSafe, zoomCalls }));
""",
        )
        self.assertEqual(result, {"wheelSafe": True, "pointerSafe": True, "zoomCalls": 0})

    def test_space_key_temporarily_marks_pan_and_pauses_magnifier(self):
        start = self.html.index("let previewSpacePan = false;")
        end = self.html.index("        document.addEventListener(\"keydown\", event => {", self.html.index("document.addEventListener(\"keyup\"", start))
        source = self.html[start:end]
        setup = """
const listeners = {};
const classes = new Set();
const imageListeners = {};
const container = {
    dataset: { previewPane: "left" },
    classList: {
        toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
        add(name) { classes.add(name); }, remove(name) { classes.delete(name); }
    },
    querySelector: () => ({ addEventListener: (name, fn) => imageListeners[name] = fn }),
    addEventListener: (name, fn) => listeners[name] = fn,
    setPointerCapture() {}, hasPointerCapture: () => false,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 })
};
const pane = { zoom: 1, normalizedCenter: { x: 0.5, y: 0.5 }, adapter: { measure: () => ({ naturalWidth: 100, naturalHeight: 100 }) } };
const group = { mode: "actual", darkBackground: false, panes: new Map([["left", pane]]) };
const keyListeners = {};
const lightbox = { classList: { contains: () => false } };
const document = {
    querySelectorAll: selector => selector.includes("data-preview-group-pane") ? [container] : [],
    getElementById: () => lightbox,
    addEventListener: (name, fn) => keyListeners[name] = fn
};
class MutationObserver { constructor() {} observe() {} }
const previewController = { groups: new Map([["main", group]]), fitScale: () => 1 };
let activeLightboxPane = "";
let magnifierCalls = 0;
const renderMagnifier = () => magnifierCalls++;
const hidePreviewMagnifiers = () => null;
const setPreviewZoom = () => null;
const setPreviewCenter = () => null;
"""
        assertions = """
bindPreviewGroup("main");
keyListeners.keydown({ key: " ", target: { tagName: "BODY" }, preventDefault() {} });
listeners.pointermove({ pointerId: 8, clientX: 20, clientY: 20 });
const during = { state: previewSpacePan, active: classes.has("pan-active"), magnifierCalls };
keyListeners.keyup({ key: " " });
console.log(JSON.stringify({ during, after: { state: previewSpacePan, active: classes.has("pan-active") } }));
"""
        result = subprocess.run(
            ["node", "-e", f"{setup}\n{source}\n{assertions}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "during": {"state": True, "active": True, "magnifierCalls": 0},
                "after": {"state": False, "active": False},
            },
        )


if __name__ == "__main__":
    unittest.main()
