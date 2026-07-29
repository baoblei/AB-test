# Video Loop and Dashboard Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every controlled video preview loop with correct sync semantics and add a new-tab dashboard entry to the post-login evaluation setup card.

**Architecture:** Keep looping inside the shared `VideoPlaybackGroup` so evaluation main preview, evaluation HD preview, and dashboard HD preview inherit one implementation. Keep the setup navigation entirely in `templates/index.html`; it is a normal link and does not enter the evaluation session lifecycle.

**Tech Stack:** Vanilla JavaScript, server-rendered HTML/CSS, Python `unittest`, Node.js runtime probes.

## Global Constraints

- Approved specification: `docs/superpowers/specs/2026-07-30-video-loop-dashboard-entry-design.md`.
- Do not implement previous-task navigation, historical result editing, or any related API/state.
- Do not change FastAPI routes, SQLite schema/data, task claiming, vote submission, skipping, or progress calculation.
- Loop evaluation main video, evaluation HD-preview video, and dashboard HD-preview video through the shared controller.
- In sync mode, one ended video restarts the whole group at 0 seconds; in independent mode, it restarts only itself.
- Preserve existing play/pause, seek, sync toggle, paused-frame tools, source cleanup, and image-task behavior.
- The setup-card dashboard entry must open `/dashboard` in a new tab with `rel="noopener"` and must not call `startTest()`.
- Preserve the user's untracked `database.db` and unrelated worktree changes.

---

### Task 1: Add controller-managed video looping

**Files:**
- Modify: `static/video_media.js:12-25,139-166`
- Test: `tests/test_video_evaluation_ui.py:8-79`

**Interfaces:**
- Consumes: existing `VideoPlaybackGroup.add(id, media)`, `_targets(id)`, `seek(id, seconds)`, and `play(id)` behavior.
- Produces: private `VideoPlaybackGroup._loopFrom(id): void`, registered as the `ended` handler for each added media element.

- [ ] **Step 1: Extend the runtime test with failing sync, independent, and cleanup assertions**

In `VideoPlaybackGroupTests.test_sync_and_independent_playback_and_cleanup`, add these operations after `frameToolsAfterPause` is captured and before `group.destroy()`:

```javascript
    left.currentTime = 4;
    right.currentTime = 2.5;
    left.dispatch("ended");
    await Promise.resolve();
    const independentLoop = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime]
    };

    group.setSync(true);
    left.currentTime = 4;
    right.currentTime = 3.5;
    right.dispatch("ended");
    await Promise.resolve();
    const syncedLoop = {
        plays: [left.playCalls, right.playCalls],
        times: [left.currentTime, right.currentTime]
    };

    group.remove("left", true);
    const playsBeforeRemovedEnded = left.playCalls;
    left.currentTime = 4;
    left.dispatch("ended");
    await Promise.resolve();
    const removedLoop = {
        playsBefore: playsBeforeRemovedEnded,
        playsAfter: left.playCalls,
        listeners: left.listenerCount()
    };
```

Include `independentLoop`, `syncedLoop`, and `removedLoop` in the emitted JSON before the existing `cleanup` object:

```javascript
    console.log(JSON.stringify({
        synced, independent, frameToolsAfterPause,
        independentLoop, syncedLoop, removedLoop,
        cleanup: {
            sources: [left.src, right.src],
            loads: [left.loadCalls, right.loadCalls],
            listeners: [left.listenerCount(), right.listenerCount()]
        }
    }));
```

Add these Python assertions before the existing cleanup assertions:

```python
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
```

Keep the existing cleanup expectations unchanged; `remove("left", true)` still clears the left source once and `destroy()` clears the right source once.

- [ ] **Step 2: Run the controller test to verify RED behavior**

Run:

```bash
python3 -m unittest tests.test_video_evaluation_ui.VideoPlaybackGroupTests.test_sync_and_independent_playback_and_cleanup -v
```

Expected: `FAIL`; `independentLoop` reports no extra play and leaves the ended video at 4 seconds because no `ended` handler exists yet.

- [ ] **Step 3: Implement the minimal shared ended handler**

Add `ended` to the handler map in `VideoPlaybackGroup.add()`:

```javascript
            const handlers = {
                play: () => this._mirrorPlay(id),
                pause: () => this._mirrorPause(id),
                seeking: () => this._mirrorTime(id),
                timeupdate: () => this._correctDrift(id),
                ended: () => this._loopFrom(id),
            };
```

Add this private method after `_correctDrift(id)` and before `_clearSource(media)`:

```javascript
        _loopFrom(id) {
            if (this.propagating || !this.entries.has(id)) return;
            this.seek(id, 0);
            void this.play(id);
        }
```

Do not add per-template `ended` listeners or native `loop` attributes. Existing generic handler cleanup in `remove()` and `destroy()` will remove the new listener.

- [ ] **Step 4: Run the video controller test file to verify GREEN behavior**

Run:

```bash
python3 -m unittest tests/test_video_evaluation_ui.py -v
```

Expected: all 6 existing tests pass, including the extended loop and listener-cleanup assertions.

- [ ] **Step 5: Commit the controller loop**

```bash
git add static/video_media.js tests/test_video_evaluation_ui.py
git commit -m "feat: loop controlled video playback"
```

---

### Task 2: Add the setup-card dashboard entry and loop copy

**Files:**
- Modify: `templates/index.html:74-82,983-992,1369-1376`
- Test: `tests/test_video_evaluation_ui.py:92-137`

**Interfaces:**
- Consumes: existing setup-card `.stack`, `startTest()`, `/dashboard`, and `handleTaskTypeChange()` task hint projection.
- Produces: `.setup-actions` layout, `.setup-dashboard-link` style, and an anchor whose navigation is independent of `startTest()`.

- [ ] **Step 1: Add a failing setup-entry and video-copy contract test**

Add this method to `VideoEvaluationTemplateTests` after `test_static_controller_and_video_dimension_selector_are_wired`:

```python
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
```

- [ ] **Step 2: Run the new template test to verify RED behavior**

Run:

```bash
python3 -m unittest tests.test_video_evaluation_ui.VideoEvaluationTemplateTests.test_setup_card_exposes_dashboard_entry_and_video_loop_copy -v
```

Expected: `FAIL`; `class="setup-actions"` and the dashboard link are absent.

- [ ] **Step 3: Implement the setup action row, dashboard link, and loop hint**

Add these styles immediately after `.stack { display: grid; gap: 12px; }`:

```css
        .setup-actions {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }
        .setup-dashboard-link {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 9px 14px;
            border: 1px solid rgba(72, 55, 37, 0.1);
            border-radius: 999px;
            color: var(--muted);
            background: rgba(118, 103, 88, 0.08);
            font-weight: 700;
            text-decoration: none;
        }
```

Replace the single setup submit button with this action row:

```html
                <div class="setup-actions">
                    <button class="submit-btn" onclick="startTest()">进入评测</button>
                    <a class="setup-dashboard-link" href="/dashboard" target="_blank" rel="noopener">进入看板</a>
                </div>
```

Change only the video branch of the task hint in `handleTaskTypeChange()`:

```javascript
            document.getElementById("task-hint").textContent = isVideoTask()
                ? "视频底部可播放、暂停和拖动进度，播放结束后自动循环；侧边栏同步按钮控制 A/B 联动，暂停后可使用画面对照工具。"
                : (state.taskType === "TI2I"
                    ? "参考图 + A/B 编辑结果会同步展示，点击图片可打开高清三图预览。"
                    : "点击图片可打开高清对比预览。");
```

Do not add click handlers to the dashboard anchor and do not alter `startTest()`.

- [ ] **Step 4: Run the focused video evaluation tests to verify GREEN behavior**

Run:

```bash
python3 -m unittest tests/test_video_evaluation_ui.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit the setup navigation**

```bash
git add templates/index.html tests/test_video_evaluation_ui.py
git commit -m "feat: link evaluation setup to dashboard"
```

---

### Task 3: Verify scope and regressions

**Files:**
- Verify only: `static/video_media.js`
- Verify only: `templates/index.html`
- Verify only: `tests/test_video_evaluation_ui.py`

**Interfaces:**
- Consumes: committed outputs from Tasks 1 and 2.
- Produces: fresh evidence that focused behavior, the complete application suite, and the approved file scope are clean.

- [ ] **Step 1: Run the focused video and dashboard preview suites**

Run:

```bash
python3 -m unittest \
  tests/test_video_evaluation_ui.py \
  tests/test_video_dashboard_ui.py \
  tests/test_dashboard_image_preview_ui.py \
  -v
```

Expected: all tests pass; this covers the shared controller consumers in both evaluation and dashboard previews.

- [ ] **Step 2: Run the complete regression suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: 434 tests pass with `OK` and no failures or errors.

- [ ] **Step 3: Audit the final diff and worktree**

Run:

```bash
git diff --check HEAD~2..HEAD
git status --short --branch
git diff --stat HEAD~2..HEAD
git diff --name-only HEAD~2..HEAD
```

Expected:

- `git diff --check HEAD~2..HEAD` prints nothing.
- The feature worktree has no uncommitted changes.
- The two implementation commits modify only `static/video_media.js`, `templates/index.html`, and `tests/test_video_evaluation_ui.py`.
- No backend, database, task service, result history, or dashboard template file is changed.
