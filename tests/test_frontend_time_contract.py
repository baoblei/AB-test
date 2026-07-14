import json
import subprocess
import unittest
from pathlib import Path


TEMPLATES = Path("templates")


class FrontendTimeContractTests(unittest.TestCase):
    def read_template(self, name):
        return (TEMPLATES / name).read_text(encoding="utf-8")

    def function_source(self, html, name):
        start = html.find(f"function {name}(")
        self.assertNotEqual(start, -1, f"missing function {name}")
        if html[max(0, start - 6):start] == "async ":
            start -= 6
        brace = html.find("{", start)
        depth = 0
        for index in range(brace, len(html)):
            if html[index] == "{":
                depth += 1
            elif html[index] == "}":
                depth -= 1
                if depth == 0:
                    return html[start:index + 1]
        self.fail(f"unterminated function {name}")

    def run_node(self, script):
        result = subprocess.run(
            ["node", "-e", script],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout, "node runtime probe did not produce JSON")
        return json.loads(result.stdout)

    def run_runtime_scenario(self, scenario):
        html = self.read_template("index.html")
        functions = "\n\n".join(
            self.function_source(html, name)
            for name in (
                "startTimer",
                "stopTimer",
                "elapsedSeconds",
                "waitForTaskImages",
                "loadNextTask",
                "submitVote",
            )
        )
        setup = r'''
let state = {
    worker: "worker", taskType: "T2I", scene: "scene", v1: "model-a", v2: "model-b",
    currentTask: null, config: {}, overallOnly: false
};
let currentVotes = { overall: "tie" };
let timerInterval = null;
let startTime = null;
let badCaseSelections = { left: new Set(), right: new Set() };
let activeBadCaseCategory = { left: "", right: "" };
let loadGeneration = 0;
let images = [];
let now = 1000;
let nextTimerId = 1;
let intervalStarts = 0;
const timeouts = new Map();
const intervals = new Map();
const requests = [];
const submitPayloads = [];
const events = [];
const nodes = {
    timer: { textContent: "", style: {} },
    "prompt-text": { textContent: "", style: {} },
    "progress-label": { textContent: "", style: {} },
    "progress-fill": { textContent: "", style: {} }
};
function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
    return { promise, resolve, reject };
}
function makeImage(complete = false) {
    const listeners = { load: new Set(), error: new Set() };
    return {
        complete,
        calls: 0,
        addEventListener(type, listener) { listeners[type].add(listener); },
        removeEventListener(type, listener) { listeners[type].delete(listener); },
        fire(type) {
            for (const listener of [...listeners[type]]) {
                this.calls += 1;
                listener();
            }
        },
        listenerCount() { return listeners.load.size + listeners.error.size; }
    };
}
async function flush() {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
}
function fireTimeouts() {
    for (const [id, callback] of [...timeouts]) {
        timeouts.delete(id);
        callback();
    }
}
function api(url, options) {
    if (url.startsWith("/api/get_task")) {
        const request = deferred();
        requests.push(request);
        events.push("get");
        return request.promise.then(task => ({ json: () => Promise.resolve(task) }));
    }
    if (url === "/api/submit") {
        submitPayloads.push(JSON.parse(options.body));
        events.push("submit");
        return Promise.resolve({});
    }
    throw new Error(`unexpected api request: ${url}`);
}
function renderCompareGrid() { images = state.currentTask.images || []; }
function renderLightbox() {}
function renderBadcasePanels() {}
function getEvalMode() { return "full"; }
function getActiveEvalDims() { return [{ key: "overall" }]; }
async function updateProgress() { events.push("progress"); }
const document = {
    getElementById(id) {
        if (!nodes[id]) nodes[id] = { textContent: "", style: {} };
        return nodes[id];
    },
    querySelectorAll(selector) {
        return selector === "#compare-grid img" ? images : [];
    }
};
const window = { location: { reload() { events.push("reload"); } } };
const alert = () => {};
const console = { error() { events.push("error"); } };
const setTimeout = callback => {
    const id = nextTimerId++;
    timeouts.set(id, callback);
    return id;
};
const clearTimeout = id => timeouts.delete(id);
const setInterval = callback => {
    const id = nextTimerId++;
    intervalStarts += 1;
    intervals.set(id, callback);
    return id;
};
const clearInterval = id => intervals.delete(id);
const Date = { now: () => now };
'''
        runtime_source = json.dumps(setup + "\n" + functions)
        scenario_source = json.dumps(f"(async () => {{\n{scenario}\n}})()")
        script = f'''
const vm = require("vm");
const context = vm.createContext({{
    Promise, Set, Map, JSON, URLSearchParams, process
}});
vm.runInContext({runtime_source}, context, {{ filename: "index-runtime.js" }});
vm.runInContext({scenario_source}, context, {{ filename: "scenario.js" }}).then(result => process.stdout.write(JSON.stringify(result))).catch(error => {{
    process.stderr.write(error.stack);
    process.exit(1);
}});
'''
        return self.run_node(script)

    def test_all_business_time_pages_use_stable_formatter(self):
        for template in ("dashboard.html", "profile.html", "admin.html"):
            with self.subTest(template=template):
                html = self.read_template(template)
                formatter = self.function_source(html, "formatBusinessTime")
                self.assertIn('if (!value) return "-";', formatter)
                self.assertIn("String(value)", formatter)
                self.assertIn('replace("T", " ")', formatter)
                self.assertIn('replace("+08:00", "")', formatter)
                self.assertNotIn("new Date", formatter)

    def test_business_time_formatter_accepts_truthy_non_strings_at_runtime(self):
        for template in ("dashboard.html", "profile.html", "admin.html"):
            with self.subTest(template=template):
                formatter = self.function_source(
                    self.read_template(template), "formatBusinessTime"
                )
                result = self.run_node(
                    f"{formatter}\nprocess.stdout.write(JSON.stringify([formatBusinessTime(123), formatBusinessTime('2026-07-15T09:30:00+08:00'), formatBusinessTime(null)]));"
                )
                self.assertEqual(result, ["123", "2026-07-15 09:30:00", "-"])

    def test_all_stored_business_time_fields_use_formatter(self):
        expectations = {
            "dashboard.html": ("formatBusinessTime(row.time)", "formatBusinessTime(row.time)"),
            "profile.html": (
                "formatBusinessTime(data.created_at)",
                "formatBusinessTime(r.timestamp)",
            ),
            "admin.html": (
                "formatBusinessTime(u.created_at)",
                "formatBusinessTime(u.last_login)",
                "formatBusinessTime(l.timestamp)",
            ),
        }
        for template, calls in expectations.items():
            html = self.read_template(template)
            for call in set(calls):
                with self.subTest(template=template, call=call):
                    self.assertGreaterEqual(html.count(call), calls.count(call))

    def test_dashboard_last_update_is_explicitly_beijing_time(self):
        html = self.read_template("dashboard.html")
        formatter = self.function_source(html, "formatBeijingNow")
        self.assertIn('timeZone: "Asia/Shanghai"', formatter)
        self.assertIn("formatBeijingNow()", html)
        self.assertNotIn("new Date().toLocaleTimeString()", html)

    def test_runtime_waits_for_immediately_complete_t2i_and_ti2i_images(self):
        result = self.run_runtime_scenario(r'''
images = [makeImage(true), makeImage(true)];
await waitForTaskImages();
const t2i = { count: images.length, listeners: images.map(image => image.listenerCount()), timeouts: timeouts.size };
images = [makeImage(true), makeImage(true), makeImage(true)];
await waitForTaskImages();
return { t2i, ti2i: { count: images.length, listeners: images.map(image => image.listenerCount()), timeouts: timeouts.size } };
''')
        self.assertEqual(result["t2i"], {"count": 2, "listeners": [0, 0], "timeouts": 0})
        self.assertEqual(result["ti2i"], {"count": 3, "listeners": [0, 0, 0], "timeouts": 0})

    def test_runtime_wait_resolves_load_error_and_timeout_once_with_cleanup(self):
        result = self.run_runtime_scenario(r'''
const loadImage = makeImage();
images = [loadImage];
const loaded = waitForTaskImages();
loadImage.fire("load");
await loaded;
loadImage.fire("error");
const load = { calls: loadImage.calls, listeners: loadImage.listenerCount(), timeouts: timeouts.size };
const errorImage = makeImage();
images = [errorImage];
const errored = waitForTaskImages();
errorImage.fire("error");
await errored;
errorImage.fire("load");
const error = { calls: errorImage.calls, listeners: errorImage.listenerCount(), timeouts: timeouts.size };
const timeoutImage = makeImage();
images = [timeoutImage];
const timedOut = waitForTaskImages();
fireTimeouts();
await timedOut;
timeoutImage.fire("load");
return { load, error, timeout: { calls: timeoutImage.calls, listeners: timeoutImage.listenerCount(), timeouts: timeouts.size } };
''')
        self.assertEqual(result, {
            "load": {"calls": 1, "listeners": 0, "timeouts": 0},
            "error": {"calls": 1, "listeners": 0, "timeouts": 0},
            "timeout": {"calls": 0, "listeners": 0, "timeouts": 0},
        })

    def test_runtime_finished_and_fetch_error_leave_timer_reset(self):
        result = self.run_runtime_scenario(r'''
const finished = loadNextTask();
requests[0].resolve({ status: "finished" });
await finished;
const afterFinished = { timer: nodes.timer.textContent, startTime, intervals: intervalStarts, reloads: events.filter(event => event === "reload").length };
const failed = loadNextTask();
requests[1].reject(new Error("network"));
await failed;
return { afterFinished, afterError: { timer: nodes.timer.textContent, startTime, intervals: intervalStarts, errors: events.filter(event => event === "error").length } };
''')
        self.assertEqual(result["afterFinished"], {"timer": "00:00", "startTime": None, "intervals": 0, "reloads": 1})
        self.assertEqual(result["afterError"], {"timer": "00:00", "startTime": None, "intervals": 0, "errors": 1})

    def test_runtime_new_task_wins_when_old_fetch_returns_late(self):
        result = self.run_runtime_scenario(r'''
const oldLoad = loadNextTask();
const newLoad = loadNextTask();
requests[1].resolve({ task_id: "new", prompt: "new", images: [makeImage(true), makeImage(true)] });
await newLoad;
requests[0].resolve({ task_id: "old", prompt: "old", images: [makeImage(true), makeImage(true)] });
await oldLoad;
return { taskId: state.currentTask.task_id, timer: nodes.timer.textContent, starts: intervalStarts };
''')
        self.assertEqual(result, {"taskId": "new", "timer": "00:00", "starts": 1})

    def test_runtime_old_image_wait_cannot_restart_new_task_timer(self):
        result = self.run_runtime_scenario(r'''
const oldImage = makeImage();
const oldLoad = loadNextTask();
requests[0].resolve({ task_id: "old", prompt: "old", images: [oldImage, makeImage(true)] });
await flush();
const newLoad = loadNextTask();
requests[1].resolve({ task_id: "new", prompt: "new", images: [makeImage(true), makeImage(true)] });
await newLoad;
const afterNew = { starts: intervalStarts, taskId: state.currentTask.task_id };
oldImage.fire("load");
await oldLoad;
return { afterNew, afterOld: { starts: intervalStarts, taskId: state.currentTask.task_id } };
''')
        self.assertEqual(result["afterNew"], {"starts": 1, "taskId": "new"})
        self.assertEqual(result["afterOld"], {"starts": 1, "taskId": "new"})

    def test_runtime_current_task_starts_only_after_all_images_settle(self):
        result = self.run_runtime_scenario(r'''
const left = makeImage();
const right = makeImage();
const loading = loadNextTask();
requests[0].resolve({ task_id: "current", prompt: "prompt", images: [left, right] });
await flush();
const before = { startTime, starts: intervalStarts, timer: nodes.timer.textContent };
left.fire("load");
await flush();
const afterOne = { startTime, starts: intervalStarts };
right.fire("error");
await loading;
return { before, afterOne, afterAll: { startTime, starts: intervalStarts, timer: nodes.timer.textContent } };
''')
        self.assertEqual(result["before"], {"startTime": None, "starts": 0, "timer": "00:00"})
        self.assertEqual(result["afterOne"], {"startTime": None, "starts": 0})
        self.assertEqual(result["afterAll"], {"startTime": 1000, "starts": 1, "timer": "00:00"})

    def test_runtime_submit_snapshots_duration_before_next_task_load(self):
        result = self.run_runtime_scenario(r'''
state.currentTask = { task_id: "current", v_left: "model-a", v_right: "model-b", scene: "scene", filename: "current.png" };
startTime = 2500;
now = 12500;
const submitting = submitVote();
await flush();
const payloadBeforeNextTask = submitPayloads[0].duration_seconds;
const requestStartedAfterSubmit = events.indexOf("get") > events.indexOf("submit");
requests[0].resolve({ status: "finished" });
await submitting;
return { payloadBeforeNextTask, requestStartedAfterSubmit, timer: nodes.timer.textContent, startTime };
''')
        self.assertEqual(result, {
            "payloadBeforeNextTask": 10,
            "requestStartedAfterSubmit": True,
            "timer": "00:00",
            "startTime": None,
        })


if __name__ == "__main__":
    unittest.main()
