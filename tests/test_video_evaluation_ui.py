import json
import subprocess
import unittest
from pathlib import Path


class VideoPlaybackGroupTests(unittest.TestCase):
    def test_loop_replay_coalesces_by_target_and_cleans_up_pending_work(self):
        script = r'''
const { VideoPlaybackGroup } = require("./static/video_media.js");
function deferred() {
    let resolve, reject;
    return { promise: new Promise((res, rej) => { resolve = res; reject = rej; }), resolve, reject };
}
function fakeVideo(name, plannedPlays = []) {
    const listeners = new Map();
    return {
        name, paused: true, currentTime: 0, duration: 4,
        playCalls: 0, pauseCalls: 0,
        addEventListener(type, callback) {
            if (!listeners.has(type)) listeners.set(type, new Set());
            listeners.get(type).add(callback);
        },
        removeEventListener(type, callback) { listeners.get(type)?.delete(callback); },
        dispatch(type) { for (const callback of [...(listeners.get(type) || [])]) callback(); },
        play() {
            this.playCalls += 1;
            this.paused = false;
            this.dispatch("play");
            return plannedPlays.shift() || Promise.resolve();
        },
        pause() { this.pauseCalls += 1; this.paused = true; this.dispatch("pause"); },
        removeAttribute() {}, load() {},
        listenerCount() { return [...listeners.values()].reduce((sum, value) => sum + value.size, 0); }
    };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    const firstReplay = deferred();
    const secondReplay = deferred();
    const left = fakeVideo("left", [firstReplay.promise]);
    const right = fakeVideo("right", [secondReplay.promise]);
    const independent = new VideoPlaybackGroup({ sync: false });
    independent.add("left", left);
    independent.add("right", right);
    left.currentTime = 4;
    left.dispatch("ended");
    right.currentTime = 4;
    right.dispatch("ended");
    left.dispatch("ended");
    const overlappingIndependent = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime]
    };
    firstReplay.resolve();
    secondReplay.resolve();
    await settle();

    const syncFirst = deferred();
    const syncSecond = deferred();
    const syncLeft = fakeVideo("sync-left", [syncFirst.promise]);
    const syncRight = fakeVideo("sync-right", [syncSecond.promise]);
    const synced = new VideoPlaybackGroup({ sync: true });
    synced.add("left", syncLeft);
    synced.add("right", syncRight);
    syncLeft.currentTime = 4;
    syncRight.currentTime = 4;
    syncLeft.dispatch("ended");
    syncRight.dispatch("ended");
    const overlappingSync = {
        plays: [syncLeft.playCalls, syncRight.playCalls],
        times: [syncLeft.currentTime, syncRight.currentTime]
    };
    syncFirst.resolve();
    syncSecond.resolve();
    await settle();

    const rejectedReplay = deferred();
    const rejected = fakeVideo("rejected", [rejectedReplay.promise, Promise.resolve()]);
    const rejectedGroup = new VideoPlaybackGroup({ sync: false });
    const unhandled = [];
    process.on("unhandledRejection", reason => unhandled.push(String(reason)));
    rejectedGroup.add("rejected", rejected);
    rejected.currentTime = 4;
    rejected.dispatch("ended");
    rejectedReplay.reject(new Error("autoplay denied"));
    await settle();
    rejected.currentTime = 4;
    rejected.dispatch("ended");
    await settle();

    const removedReplay = deferred();
    const removed = fakeVideo("removed", [removedReplay.promise]);
    const removedGroup = new VideoPlaybackGroup({ sync: false });
    removedGroup.add("removed", removed);
    removed.currentTime = 4;
    removed.dispatch("ended");
    removedGroup.remove("removed");
    removed.dispatch("ended");
    removedReplay.resolve();
    await settle();

    const destroyedReplay = deferred();
    const destroyed = fakeVideo("destroyed", [destroyedReplay.promise]);
    const destroyedGroup = new VideoPlaybackGroup({ sync: false });
    destroyedGroup.add("destroyed", destroyed);
    destroyed.currentTime = 4;
    destroyed.dispatch("ended");
    destroyedGroup.destroy();
    destroyed.dispatch("ended");
    destroyedReplay.resolve();
    await settle();

    console.log(JSON.stringify({
        overlappingIndependent, overlappingSync,
        rejected: { plays: rejected.playCalls, unhandled },
        removed: { plays: removed.playCalls, listeners: removed.listenerCount() },
        destroyed: { plays: destroyed.playCalls, listeners: destroyed.listenerCount() }
    }));
})().catch(error => { console.error(error); process.exit(1); });
'''
        completed = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["overlappingIndependent"], {
            "plays": [1, 1],
            "times": [0, 0],
        })
        self.assertEqual(result["overlappingSync"], {
            "plays": [1, 1],
            "times": [0, 0],
        })
        self.assertEqual(result["rejected"], {"plays": 2, "unhandled": []})
        self.assertEqual(result["removed"], {"plays": 1, "listeners": 0})
        self.assertEqual(result["destroyed"], {"plays": 1, "listeners": 0})

    def test_sync_and_independent_playback_and_cleanup(self):
        script = r'''
const { VideoPlaybackGroup } = require("./static/video_media.js");
function fakeVideo(name) {
    const listeners = new Map();
    return {
        name, paused: true, currentTime: 0, duration: 4, src: `${name}.mp4`,
        playCalls: 0, pauseCalls: 0, loadCalls: 0, removed: [],
        addEventListener(type, callback) {
            if (!listeners.has(type)) listeners.set(type, new Set());
            listeners.get(type).add(callback);
        },
        removeEventListener(type, callback) { listeners.get(type)?.delete(callback); },
        dispatch(type) { for (const callback of [...(listeners.get(type) || [])]) callback(); },
        play() { this.playCalls += 1; this.paused = false; this.dispatch("play"); return Promise.resolve(); },
        pause() { this.pauseCalls += 1; this.paused = true; this.dispatch("pause"); },
        removeAttribute(name) { this.removed.push(name); if (name === "src") this.src = ""; },
        load() { this.loadCalls += 1; },
        listenerCount() { return [...listeners.values()].reduce((sum, value) => sum + value.size, 0); }
    };
}
(async () => {
    const left = fakeVideo("left");
    const right = fakeVideo("right");
    const group = new VideoPlaybackGroup({ sync: true });
    group.add("left", left);
    group.add("right", right);
    await group.play("left");
    group.seek("left", 1.75);
    group.pause("right");
    const synced = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime],
        pauses: [left.pauseCalls, right.pauseCalls],
        frameTools: group.canUseFrameTools()
    };
    group.setSync(false);
    await group.play("left");
    group.seek("left", 2.5);
    const independent = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime],
        frameToolsWhilePlaying: group.canUseFrameTools()
    };
    group.pause("left");
    const frameToolsAfterPause = group.canUseFrameTools();
    left.currentTime = 4;
    right.currentTime = 2.5;
    left.dispatch("ended");
    await new Promise(resolve => setImmediate(resolve));
    const independentLoop = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime]
    };

    group.setSync(true);
    left.currentTime = 4;
    right.currentTime = 3.5;
    right.dispatch("ended");
    await new Promise(resolve => setImmediate(resolve));
    const syncedLoop = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime]
    };

    group.remove("left", true);
    const playsBeforeRemovedEnded = left.playCalls;
    left.currentTime = 4;
    left.dispatch("ended");
    await new Promise(resolve => setImmediate(resolve));
    const removedLoop = {
        playsBefore: playsBeforeRemovedEnded,
        playsAfter: left.playCalls,
        listeners: left.listenerCount()
    };
    group.destroy();
    console.log(JSON.stringify({
        synced, independent, frameToolsAfterPause,
        independentLoop, syncedLoop, removedLoop,
        cleanup: {
            sources: [left.src, right.src],
            loads: [left.loadCalls, right.loadCalls],
            listeners: [left.listenerCount(), right.listenerCount()]
        }
    }));
})().catch(error => { console.error(error); process.exit(1); });
'''
        completed = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["synced"]["plays"], [1, 1])
        self.assertEqual(result["synced"]["times"], [1.75, 1.75])
        self.assertTrue(result["synced"]["frameTools"])
        self.assertEqual(result["independent"]["plays"], [2, 1])
        self.assertEqual(result["independent"]["times"], [2.5, 1.75])
        self.assertFalse(result["independent"]["frameToolsWhilePlaying"])
        self.assertTrue(result["frameToolsAfterPause"])
        self.assertEqual(result["independentLoop"], {
            "plays": [3, 1],
            "times": [0, 2.5],
        })
        self.assertEqual(result["syncedLoop"], {
            "plays": [4, 2],
            "times": [0, 0],
        })
        self.assertEqual(result["removedLoop"], {
            "playsBefore": 4,
            "playsAfter": 4,
            "listeners": 0,
        })
        self.assertEqual(result["cleanup"]["sources"], ["", ""])
        self.assertEqual(result["cleanup"]["loads"], [1, 1])
        self.assertEqual(result["cleanup"]["listeners"], [0, 0])


class VideoEvaluationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/index.html").read_text(encoding="utf-8")
        cls.main = Path("main.py").read_text(encoding="utf-8")

    def function_source(self, name, next_name):
        start = self.html.index(f"function {name}")
        return self.html[start : self.html.index(f"function {next_name}", start)]

    def test_static_controller_and_video_dimension_selector_are_wired(self):
        self.assertIn('app.mount("/static", StaticFiles(directory="static")', self.main)
        self.assertIn('<script src="/static/video_media.js"></script>', self.html)
        self.assertIn('id="video-dimension-selector"', self.html)
        self.assertIn('state.config.media_type === "video"', self.html)
        self.assertIn("state.selectedDimensions", self.html)

    def test_setup_card_exposes_dashboard_entry_and_video_loop_copy(self):
        self.assertIn('class="setup-actions"', self.html)
        self.assertIn(
            '<button class="submit-btn" onclick="startTest()">进入评测</button>',
            self.html,
        )
        self.assertIn(
            '<a class="setup-dashboard-link" href="/dashboard" target="_blank" rel="noopener">进入看板</a>',
            self.html,
        )
        self.assertIn(".setup-dashboard-link", self.html)
        source = self.function_source("handleTaskTypeChange", "handleVersionInput")
        self.assertIn("播放结束后自动循环", source)

    def test_session_uses_selected_dimensions_only_for_video(self):
        source = self.function_source("prepareEvalSession", "renderEvalTable")
        self.assertIn('params.set("dimensions", JSON.stringify(state.selectedDimensions))', source)
        self.assertIn('params.set("overwrite_dimensions"', source)
        self.assertIn("isVideoTask()", source)

    def test_media_cards_keep_reference_as_image_and_candidates_as_video(self):
        source = self.function_source("renderCompareGrid", "renderImageCard")
        self.assertIn("renderMediaCard", source)
        self.assertIn('renderImageCard("reference", "参考图"', source)
        self.assertIn("isVideoTask()", source)
        self.assertIn("renderImageCard", source)
        media = self.function_source("renderMediaCard", "renderBadcasePanels")
        self.assertIn("<video", media)
        self.assertIn('preload="metadata"', media)
        self.assertIn("resultThumbnailUrl", media)
        self.assertIn('class="video-controls"', media)

    def test_video_payload_contains_selected_dimensions_and_all_scores(self):
        source = self.function_source("submitVote", "skipTask")
        self.assertIn("selected_dimensions", source)
        for dimension in (
            "text_consistency",
            "motion_reasonableness",
            "dynamism",
            "physical_plausibility",
            "visual_quality",
            "image_consistency",
        ):
            self.assertIn(f"{dimension}:", source)

    def test_video_controls_are_translucent_and_hide_outside_interaction(self):
        self.assertIn(".video-controls", self.html)
        self.assertIn("opacity: 0", self.html)
        self.assertIn(".video-shell:hover .video-controls", self.html)
        self.assertIn(".video-shell:focus-within .video-controls", self.html)


if __name__ == "__main__":
    unittest.main()
