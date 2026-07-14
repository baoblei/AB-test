# 看板评测结果导出与北京时间统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个看板模型对提供可精细筛选的 XLSX/ZIP 导出，并将全部业务记录时间和展示统一为带 `+08:00` 的北京时间。

**Architecture:** 新增独立的时间工具与导出服务，SQLite 只负责原始记录查询，筛选、汇总、工作簿和图片归档由可单测的纯函数完成。导出接口同步生成临时文件并在响应后清理；前端弹窗只负责收集筛选配置、预览数量和触发下载。

**Tech Stack:** Python 3、FastAPI、SQLite、Pydantic、openpyxl、标准库 `zipfile`/`tempfile`、原生 HTML/CSS/JavaScript、`unittest`。

## Global Constraints

- 规范来源：`docs/superpowers/specs/2026-07-15-dashboard-export-design.md`。
- 业务时间格式固定为 `YYYY-MM-DDTHH:MM:SS+08:00`，精确到秒；JWT 过期时间继续使用 UTC。
- XLSX 始终包含 `Overall`；维度选择只控制美学、合理性、一致性和 TI2I 保真度明细 Sheet。
- ZIP 图片路径固定为 `images/<scene>/<model>/<filename>`，TI2I 参考图为 `images/<scene>/ref/<filename>`。
- 图片缺失只标记，不中断导出；同一图片在 ZIP 内只写一次。
- 保留现有 T2I 旧目录回退行为。
- 保留原有 `GET /api/export` JSON/CSV 接口，新增同路径 `POST /api/export` 文件接口。
- 不提交本地 `database.db`。
- 当前未提交的 `README.md`、`app_core/storage.py`、`main.py`、`templates/dashboard.html` 是上一项已完成的上传功能，执行前先验证并独立提交，禁止丢弃。

---

### Task 0: 固化现有上传功能基线

**Files:**
- Verify: `README.md`
- Verify: `app_core/storage.py`
- Verify: `main.py`
- Verify: `templates/dashboard.html`

**Interfaces:**
- Consumes: 当前工作区已完成的测评集上传、结果图校验和压制比展示。
- Produces: 不包含 `database.db` 的干净 Git 基线，供后续任务精确提交。

- [ ] **Step 1: 检查待提交范围**

Run:

```bash
git diff --check
git diff --stat
git status --short
```

Expected: 仅上述四个文件有修改，`database.db` 保持未跟踪，设计文档和计划文档之外没有未知文件。

- [ ] **Step 2: 重新验证已有功能**

Run:

```bash
python3 -m compileall main.py app_core
node -e "const fs=require('fs'),vm=require('vm'); for (const f of fs.readdirSync('templates').filter(x=>x.endsWith('.html'))) { const s=fs.readFileSync('templates/'+f,'utf8'); for (const m of s.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)) new vm.Script(m[1], {filename:f}); } console.log('templates js ok')"
```

Expected: Python compilation exits 0 and Node prints `templates js ok`.

- [ ] **Step 3: 独立提交已有功能**

```bash
git add README.md app_core/storage.py main.py templates/dashboard.html
git commit -m "feat: 优化看板任务发布和上传校验"
```

Expected: commit contains exactly the four files; `git status --short` still shows only `database.db` and planning artifacts that are intentionally untracked.

---

### Task 1: 北京时间工具与幂等历史迁移

**Files:**
- Create: `app_core/time_utils.py`
- Modify: `app_core/database.py:1-161`
- Create: `tests/__init__.py`
- Create: `tests/test_time_utils.py`

**Interfaces:**
- Consumes: SQLite 文本时间字段。
- Produces: `now_beijing_iso(now: Optional[datetime] = None) -> str`、`legacy_utc_to_beijing_iso(value: Optional[str]) -> Optional[str]`、`beijing_today(now: Optional[datetime] = None) -> str`、`migrate_business_times(conn: sqlite3.Connection) -> dict`。

- [ ] **Step 1: 写时间格式和迁移失败测试**

```python
# tests/test_time_utils.py
import sqlite3
import unittest
from datetime import datetime, timezone

from app_core.database import migrate_business_times
from app_core.time_utils import beijing_today, legacy_utc_to_beijing_iso, now_beijing_iso


class BeijingTimeTests(unittest.TestCase):
    def test_now_beijing_iso_uses_fixed_offset(self):
        value = now_beijing_iso(datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(value, "2026-07-15T09:02:03+08:00")
        self.assertEqual(beijing_today(datetime(2026, 7, 14, 16, 0, 0, tzinfo=timezone.utc)), "2026-07-15")

    def test_legacy_utc_conversion_preserves_new_and_invalid_values(self):
        self.assertEqual(legacy_utc_to_beijing_iso("2026-07-14 16:30:00"), "2026-07-15T00:30:00+08:00")
        self.assertEqual(legacy_utc_to_beijing_iso("2026-07-15T00:30:00+08:00"), "2026-07-15T00:30:00+08:00")
        self.assertEqual(legacy_utc_to_beijing_iso("invalid"), "invalid")
        self.assertIsNone(legacy_utc_to_beijing_iso(None))

    def test_database_migration_runs_once(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, created_at TEXT, last_login TEXT)")
        conn.execute("CREATE TABLE operation_logs (id INTEGER PRIMARY KEY, timestamp TEXT)")
        conn.execute("CREATE TABLE results_log (id INTEGER PRIMARY KEY, timestamp TEXT)")
        conn.execute("INSERT INTO users VALUES (1, '2026-07-14 16:00:00', NULL)")
        conn.execute("INSERT INTO operation_logs VALUES (1, '2026-07-14 16:10:00')")
        conn.execute("INSERT INTO results_log VALUES (1, '2026-07-14 16:20:00')")

        first = migrate_business_times(conn)
        second = migrate_business_times(conn)

        self.assertEqual(first["updated"], 3)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(conn.execute("SELECT timestamp FROM results_log").fetchone()[0], "2026-07-15T00:20:00+08:00")
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_time_utils -v`

Expected: FAIL with import errors for `app_core.time_utils` or `migrate_business_times`.

- [ ] **Step 3: 实现时间纯函数**

```python
# app_core/time_utils.py
from datetime import datetime, timedelta, timezone
from typing import Optional


BEIJING_TZ = timezone(timedelta(hours=8))
LEGACY_UTC_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_beijing_iso(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    value = current.astimezone(BEIJING_TZ).replace(microsecond=0).isoformat()
    return value


def beijing_today(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(BEIJING_TZ).date().isoformat()


def legacy_utc_to_beijing_iso(value: Optional[str]) -> Optional[str]:
    if not value or "T" in value:
        return value
    try:
        parsed = datetime.strptime(value, LEGACY_UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return parsed.astimezone(BEIJING_TZ).replace(microsecond=0).isoformat()
```

- [ ] **Step 4: 实现数据库迁移并更新新库默认值**

In `app_core/database.py`, add `TIME_MIGRATION_KEY = "beijing_time_v1"`, create `app_metadata`, convert the four approved columns in one transaction, then record the migration key. Use this exact migration shape:

```python
BUSINESS_TIME_COLUMNS = {
    "users": ("created_at", "last_login"),
    "operation_logs": ("timestamp",),
    "results_log": ("timestamp",),
}


def migrate_business_times(conn: sqlite3.Connection) -> dict:
    conn.execute("CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if conn.execute("SELECT 1 FROM app_metadata WHERE key=?", (TIME_MIGRATION_KEY,)).fetchone():
        return {"updated": 0, "invalid": 0}

    updated = 0
    invalid = 0
    for table, columns in BUSINESS_TIME_COLUMNS.items():
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not table_exists:
            continue
        for column in columns:
            for row_id, value in conn.execute(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"):
                converted = legacy_utc_to_beijing_iso(value)
                if converted == value:
                    if "T" not in value:
                        invalid += 1
                    continue
                conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (converted, row_id))
                updated += 1
    conn.execute(
        "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
        (TIME_MIGRATION_KEY, now_beijing_iso()),
    )
    conn.commit()
    return {"updated": updated, "invalid": invalid}
```

Call `migrate_business_times(conn)` after the default admin insertion and before closing the connection. Capture the returned `invalid` count and print one concise startup diagnostic when it is non-zero; do not log individual field values.

- [ ] **Step 5: 运行测试并确认 GREEN**

Run: `python3 -m unittest tests.test_time_utils -v`

Expected: 3 tests pass.

- [ ] **Step 6: 提交**

```bash
git add app_core/time_utils.py app_core/database.py tests/__init__.py tests/test_time_utils.py
git commit -m "feat: 统一业务时间为北京时间"
```

---

### Task 2: 所有业务写入与北京时间统计

**Files:**
- Modify: `app_core/database.py:133-161`
- Modify: `app_core/user_service.py:8-48`
- Modify: `app_core/task_service.py:246-352`
- Modify: `app_core/admin_service.py:33-45`
- Create: `tests/test_business_time_writes.py`

**Interfaces:**
- Consumes: `now_beijing_iso()` and `beijing_today()` from Task 1。
- Produces: 用户、日志、评测及跳过记录全部显式写北京时间；`admin_stats()` 按北京时间日期统计。

- [ ] **Step 1: 写业务写入失败测试**

Create a temporary database fixture that patches `app_core.database.DB_PATH`, calls `init_db()`, inserts one `pair_tasks` row, and verifies these behaviors:

```python
def test_log_operation_writes_beijing_iso(self):
    log_operation(1, "test", "details")
    value = connect().execute("SELECT timestamp FROM operation_logs ORDER BY id DESC LIMIT 1").fetchone()[0]
    self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$")

def test_submit_and_skip_write_beijing_iso(self):
    submit_vote(self.full_vote, 1)
    skip_task(self.skip_task_id, "T2I", 1, "full")
    values = [row[0] for row in connect().execute("SELECT timestamp FROM results_log ORDER BY id")]
    self.assertTrue(all(value.endswith("+08:00") for value in values))

def test_admin_today_uses_beijing_date(self):
    with patch("app_core.admin_service.beijing_today", return_value="2026-07-15"):
        connect().execute(
            "INSERT INTO results_log (timestamp, skipped) VALUES ('2026-07-15T00:01:00+08:00', 0)"
        ).connection.commit()
        self.assertEqual(admin_stats()["today_eval"], 1)
```

The fixture's `full_vote` is a `SimpleNamespace` with `task_type="T2I"`, `eval_mode="full"`, all three T2I dimensions set to `"tie"`, empty bad-case lists, and `duration_seconds=3`.

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_business_time_writes -v`

Expected: FAIL because current inserts rely on UTC defaults and `admin_stats()` uses `DATE('now')`.

- [ ] **Step 3: 显式写入北京时间**

Apply these exact changes:

```python
# app_core/database.py
timestamp = now_beijing_iso()
cursor.execute(
    "INSERT INTO operation_logs (user_id, action, details, ip_address, timestamp) VALUES (?, ?, ?, ?, ?)",
    (user_id, action, details, ip_address, timestamp),
)
```

```python
# app_core/user_service.py
created_at = now_beijing_iso()
cursor.execute(
    "INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
    (user.username, hash_password(user.password), user.email, created_at),
)

cursor.execute("UPDATE users SET last_login=? WHERE id=?", (now_beijing_iso(), row[0]))
```

Add `timestamp` to both `results_log` insert column lists in `submit_vote()` and `skip_task()`, and pass `now_beijing_iso()` in the corresponding values tuple.

```python
# app_core/admin_service.py
cursor.execute(
    "SELECT COUNT(*) FROM results_log WHERE skipped=0 AND substr(timestamp, 1, 10)=?",
    (beijing_today(),),
)
```

Insert the default admin user with an explicit `created_at=now_beijing_iso()` as well.

For newly created databases, replace each business `CURRENT_TIMESTAMP` default with:

```sql
DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', '+8 hours') || '+08:00')
```

Existing databases keep their original schema default, but every application write path is explicit after this task, so no UTC default is used by the project.

- [ ] **Step 4: 运行时间回归测试**

Run: `python3 -m unittest tests.test_time_utils tests.test_business_time_writes -v`

Expected: all tests pass.

- [ ] **Step 5: 提交**

```bash
git add app_core/database.py app_core/user_service.py app_core/task_service.py app_core/admin_service.py tests/test_business_time_writes.py
git commit -m "fix: 修正业务时间写入和今日统计"
```

---

### Task 3: 导出请求、筛选和预览统计

**Files:**
- Modify: `app_core/schemas.py:1-38`
- Create: `app_core/export_service.py`
- Create: `tests/test_export_filtering.py`

**Interfaces:**
- Consumes: `results_log` rows and `TASK_CONFIGS` dimensions。
- Produces: `ExportRequest`、`get_export_options(task_type, v1, v2) -> dict`、`filter_rows(rows, request, dimension) -> list`、`preview_export(request) -> dict`。

- [ ] **Step 1: 写筛选失败测试**

```python
def test_dimension_filter_excludes_overall_only_rows(self):
    request = ExportRequest(task_type="T2I", v1="A", v2="B", scenes=["open"], dimensions=["aesthetic"])
    self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "aesthetic")], [1])

def test_result_filter_is_applied_per_sheet(self):
    request = ExportRequest(
        task_type="T2I", v1="A", v2="B", scenes=["open"], dimensions=["aesthetic"], result_filter="a"
    )
    self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "overall")], [2])
    self.assertEqual([row["id"] for row in filter_rows(self.rows, request, "aesthetic")], [1])

def test_worker_time_mode_and_bad_case_filters_combine(self):
    request = ExportRequest(
        task_type="TI2I", v1="D", v2="E", scenes=["portrait"], workers=["alice"],
        dimensions=["fidelity"], start_time="2026-07-15T00:00:00+08:00",
        end_time="2026-07-15T23:59:59+08:00", eval_modes=["full"], bad_case_filter="with"
    )
    self.assertEqual(len(filter_rows(self.rows, request, "fidelity")), 1)
```

Use dictionary fixtures containing all `results_log` fields, including JSON strings for bad-case tags.

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_export_filtering -v`

Expected: FAIL because `ExportRequest` and `app_core.export_service` do not exist.

- [ ] **Step 3: 定义请求模型**

```python
# app_core/schemas.py
from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    task_type: str
    v1: str
    v2: str
    scenes: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    workers: List[str] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    eval_modes: List[str] = Field(default_factory=lambda: ["full", "overall"])
    result_filter: str = "all"
    bad_case_filter: str = "all"
    include_images: bool = False
    include_bad_cases: bool = True
    include_duration: bool = True
```

- [ ] **Step 4: 实现规范化和纯筛选函数**

Implement these rules in `app_core/export_service.py`:

```python
VALID_RESULT_FILTERS = {"all", "a", "tie", "b"}
VALID_BAD_CASE_FILTERS = {"all", "with", "without"}
VALID_EVAL_MODES = {"full", "overall"}


def canonical_models(request: ExportRequest) -> tuple[str, str]:
    return tuple(sorted([request.v1, request.v2]))


def expected_result(request: ExportRequest) -> Optional[str]:
    v_a, v_b = canonical_models(request)
    return {"all": None, "a": v_a, "tie": "tie", "b": v_b}[request.result_filter]


def row_has_bad_case(row) -> bool:
    return bool(safe_load_json_list(row["bad_case_tags_a"]) or safe_load_json_list(row["bad_case_tags_b"]))


def filter_rows(rows, request: ExportRequest, dimension: str) -> list:
    result = []
    wanted_result = expected_result(request)
    for row in rows:
        mode = row["eval_mode"] or "full"
        if request.scenes and row["scene"] not in request.scenes:
            continue
        if request.workers and row["worker"] not in request.workers:
            continue
        if request.eval_modes and mode not in request.eval_modes:
            continue
        if request.start_time and row["timestamp"] < request.start_time:
            continue
        if request.end_time and row["timestamp"] > request.end_time:
            continue
        has_bad_case = row_has_bad_case(row)
        if request.bad_case_filter == "with" and not has_bad_case:
            continue
        if request.bad_case_filter == "without" and has_bad_case:
            continue
        if dimension != "overall" and (mode != "full" or not row[dimension]):
            continue
        if wanted_result and row[dimension] != wanted_result:
            continue
        result.append(row)
    return result
```

Validate task type, requested dimensions, filters, eval modes, model names and time ordering before filtering; raise `AppError` with a specific Chinese message for each invalid category.

- [ ] **Step 5: 实现数据库选项和预览**

`get_export_options()` queries non-skipped rows for the canonical model pair and returns sorted unique scenes/workers, `dim_payload(config["eval_dims"])`, min/max timestamp, and total. `preview_export()` fetches the same base rows and returns:

```python
{
    "overall": len(filter_rows(rows, request, "overall")),
    "dimensions": {dim: len(filter_rows(rows, request, dim)) for dim in request.dimensions},
    "unique_images": len({(row["scene"], row["filename"]) for row in selected_union}),
}
```

- [ ] **Step 6: 运行测试并确认 GREEN**

Run: `python3 -m unittest tests.test_export_filtering -v`

Expected: all filtering tests pass.

- [ ] **Step 7: 提交**

```bash
git add app_core/schemas.py app_core/export_service.py tests/test_export_filtering.py
git commit -m "feat: 增加评测导出筛选服务"
```

---

### Task 4: Overall 与维度明细工作簿

**Files:**
- Modify: `requirements.txt`
- Modify: `app_core/export_service.py`
- Create: `tests/test_export_workbook.py`

**Interfaces:**
- Consumes: Task 3 的 `ExportRequest`、筛选结果和现有 `get_prompt_text()`。
- Produces: `build_workbook(request, rows, generated_at=None) -> openpyxl.Workbook`、`workbook_bytes(workbook) -> bytes`。

- [ ] **Step 1: 声明依赖并写工作簿失败测试**

Add `openpyxl` to `requirements.txt`, install project dependencies, then create tests that load generated bytes with `openpyxl.load_workbook()`:

```python
def test_t2i_workbook_has_overall_and_selected_dimension_sheets(self):
    workbook = build_workbook(self.t2i_request, self.t2i_rows, generated_at="2026-07-15T10:00:00+08:00")
    self.assertEqual(workbook.sheetnames, ["Overall", "美学明细", "一致性明细"])
    overall = workbook["Overall"]
    self.assertEqual(overall["A1"].value, "评测结果导出")
    self.assertEqual(overall["A12"].value, "全部场景")

def test_dimension_detail_contains_filename_prompt_worker_and_result(self):
    sheet = build_workbook(self.t2i_request, self.t2i_rows)["美学明细"]
    headers = [cell.value for cell in sheet[1]]
    self.assertIn("图片名", headers)
    self.assertIn("Prompt", headers)
    self.assertIn("评测人", headers)
    self.assertIn("美学判定", headers)
    self.assertEqual(sheet.cell(2, headers.index("Prompt") + 1).value, "a red car")

def test_ti2i_workbook_has_fidelity_and_reference_columns(self):
    sheet = build_workbook(self.ti2i_request, self.ti2i_rows)["保真度明细"]
    headers = [cell.value for cell in sheet[1]]
    self.assertIn("参考图路径", headers)
    self.assertIn("参考图状态", headers)
```

Patch `app_core.export_service.get_prompt_text` to return deterministic prompt values.

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest tests.test_export_workbook -v
```

Expected: dependencies install successfully, then tests FAIL because workbook functions are missing.

- [ ] **Step 3: 实现 Overall 统计**

Create helpers with these exact outputs:

```python
def suppression_ratio(numerator: int, denominator: int):
    if denominator == 0:
        return "∞" if numerator else "-"
    return round(numerator / denominator, 2)


def summarize_overall(rows, v_a: str, v_b: str) -> dict:
    total = len(rows)
    a_wins = sum(row["overall"] == v_a for row in rows)
    ties = sum(row["overall"] == "tie" for row in rows)
    b_wins = sum(row["overall"] == v_b for row in rows)
    bad_a = sum(bool(safe_load_json_list(row["bad_case_tags_a"])) for row in rows)
    bad_b = sum(bool(safe_load_json_list(row["bad_case_tags_b"])) for row in rows)
    return {
        "total": total,
        "a_wins": a_wins,
        "ties": ties,
        "b_wins": b_wins,
        "a_rate": a_wins / total if total else 0,
        "tie_rate": ties / total if total else 0,
        "b_rate": b_wins / total if total else 0,
        "a_suppression": suppression_ratio(a_wins + ties, b_wins + ties),
        "b_suppression": suppression_ratio(b_wins + ties, a_wins + ties),
        "bad_a": bad_a,
        "bad_b": bad_b,
        "bad_a_rate": bad_a / total if total else 0,
        "bad_b_rate": bad_b / total if total else 0,
    }
```

Write metadata rows 1-9, a blank separator, table headers at row 11, total at row 12, then sorted scene rows. Apply percentage number format `0.0%` and freeze the sheet below the table header.

- [ ] **Step 4: 实现维度明细与样式**

Use `DIM_LABELS` for Sheet and result headers. Base columns are task type, model A/B, scene, filename, Prompt, dimension result, worker, eval mode, Beijing timestamp, A/B image paths and statuses. Conditionally append duration and bad-case columns. TI2I appends ref path/status.

Use the exact Sheet mapping `aesthetic -> 美学明细`, `logic -> 合理性明细`, `consistency -> 一致性明细`, and `fidelity -> 保真度明细`; preserve the order from the task configuration after intersecting it with the requested dimensions.

When `include_images=false`, image path cells are empty and status cells contain `未导出`. When image export is enabled, existing files contain the archive-relative path and status `已导出`; missing files have an empty path and status `文件不存在`.

Convert result values with:

```python
def result_label(value: str, v_a: str, v_b: str) -> str:
    if value == "tie":
        return "平局"
    if value == v_a:
        return f"{v_a} 胜"
    if value == v_b:
        return f"{v_b} 胜"
    return value or ""
```

Set autofilter over the used range, freeze `A2`, wrap Prompt/bad-case cells, and cap Prompt width at 60 characters.

- [ ] **Step 5: 实现字节序列化并确认 GREEN**

```python
def workbook_bytes(workbook: Workbook) -> bytes:
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
```

Run: `python3 -m unittest tests.test_export_filtering tests.test_export_workbook -v`

Expected: all export filtering and workbook tests pass.

- [ ] **Step 6: 提交**

```bash
git add requirements.txt app_core/export_service.py tests/test_export_workbook.py
git commit -m "feat: 生成评测导出工作簿"
```

---

### Task 5: 图片归档、临时文件和 FastAPI 接口

**Files:**
- Modify: `app_core/storage.py:32-48,354-373`
- Modify: `app_core/export_service.py`
- Modify: `main.py:1-222`
- Create: `tests/test_export_archive.py`

**Interfaces:**
- Consumes: 工作簿字节、筛选后的记录、任务结果目录和参考图目录。
- Produces: `get_result_image_path()`、`get_ref_image_path()`、`create_export_artifact(request) -> ExportArtifact` 及三个导出 API。

- [ ] **Step 1: 写归档路径和去重失败测试**

```python
def test_archive_uses_scene_model_and_ref_layout(self):
    artifact = build_archive(
        self.request,
        workbook_data=b"xlsx",
        selected_rows=[self.row, dict(self.row, worker="bob")],
        result_path_resolver=self.result_resolver,
        ref_path_resolver=self.ref_resolver,
    )
    with zipfile.ZipFile(artifact, "r") as archive:
        names = sorted(archive.namelist())
    self.assertEqual(names, [
        "images/portrait/D/scene1.jpg",
        "images/portrait/E/scene1.jpg",
        "images/portrait/ref/scene1.jpg",
        "评测结果.xlsx",
    ])

def test_missing_image_is_not_written_and_manifest_marks_it(self):
    manifest = build_image_manifest(self.request, [self.row], lambda *args: None, lambda *args: None)
    self.assertEqual(manifest[("portrait", "scene1.jpg")]["D"]["status"], "文件不存在")
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_export_archive -v`

Expected: FAIL because archive and path helper functions are missing.

- [ ] **Step 3: 增加安全本地路径解析**

```python
# app_core/storage.py
def get_result_image_path(task_type: str, version: str, scene: str, filename: str) -> Optional[str]:
    path = os.path.join(get_scene_path(task_type, version, scene), filename)
    return path if os.path.isfile(path) else None


def get_ref_image_path(task_type: str, scene: str, filename: str) -> Optional[str]:
    roots = [get_ref_root(task_type), REF_IMAGE_DIR]
    for root in roots:
        path = os.path.join(root, scene, filename)
        if os.path.isfile(path):
            return path
    return None
```

Validate every path component with `os.path.basename(value) == value` and reject empty, `.` or `..` values before constructing ZIP names.

- [ ] **Step 4: 构建图片清单和 ZIP**

Deduplicate selected rows by `(scene, filename)`. For each key, resolve A/B and optional TI2I ref source paths and set relative paths exactly as required. Write existing sources with `ZipFile.write()` and always write workbook bytes with:

```python
archive.writestr("评测结果.xlsx", workbook_data)
```

Regenerate the workbook after the manifest is known so detail path/status columns match actual archive contents.

- [ ] **Step 5: 生成临时导出产物**

Define:

```python
@dataclass
class ExportArtifact:
    path: str
    filename: str
    media_type: str
    cleanup_dir: str
```

`create_export_artifact()` validates the request, fetches rows, rejects an empty Overall selection, creates `tempfile.mkdtemp(prefix="ab-test-export-")`, writes XLSX or ZIP, and removes the directory inside an exception handler before re-raising.

- [ ] **Step 6: 接入 FastAPI**

Keep the legacy GET route and add:

```python
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse


@app.get("/api/export_options")
def export_options(task_type: str, v1: str, v2: str):
    return get_export_options(task_type, v1, v2)


@app.post("/api/export/preview")
def export_preview(payload: ExportRequest):
    return preview_export(payload)


@app.post("/api/export")
def export_file(payload: ExportRequest):
    artifact = create_export_artifact(payload)
    return FileResponse(
        artifact.path,
        media_type=artifact.media_type,
        filename=artifact.filename,
        background=BackgroundTask(shutil.rmtree, artifact.cleanup_dir, ignore_errors=True),
    )
```

- [ ] **Step 7: 运行归档和回归测试**

Run: `python3 -m unittest tests.test_export_filtering tests.test_export_workbook tests.test_export_archive -v`

Expected: all export tests pass.

- [ ] **Step 8: 提交**

```bash
git add app_core/storage.py app_core/export_service.py main.py tests/test_export_archive.py
git commit -m "feat: 导出评测图片归档和接口"
```

---

### Task 6: 看板导出配置弹窗和下载交互

**Files:**
- Modify: `templates/dashboard.html:1-1170`
- Create: `tests/test_dashboard_export_ui.py`

**Interfaces:**
- Consumes: `/api/export_options`、`/api/export/preview`、`POST /api/export`。
- Produces: 每个模型对标题栏导出按钮、筛选弹窗、预计数量和 XLSX/ZIP 浏览器下载。

- [ ] **Step 1: 写模板契约失败测试**

```python
from pathlib import Path
import unittest


class DashboardExportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def test_export_modal_and_pair_button_exist(self):
        for marker in ('id="export-modal"', 'id="export-form"', 'openExportModal(', '>导出<'):
            self.assertIn(marker, self.html)

    def test_export_filters_and_download_functions_exist(self):
        for marker in (
            'id="export-scenes"', 'id="export-dimensions"', 'id="export-workers"',
            'id="export-start-time"', 'id="export-end-time"', 'id="export-images"',
            'function collectExportRequest', 'async function previewExport', 'async function downloadExport'
        ):
            self.assertIn(marker, self.html)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_dashboard_export_ui -v`

Expected: FAIL because the modal and handlers are absent.

- [ ] **Step 3: 增加导出按钮和弹窗结构**

In each pair header action group, add:

```html
<button class="btn btn-export" onclick='openExportModal(${JSON.stringify(pair.v_a)}, ${JSON.stringify(pair.v_b)})'>导出</button>
```

Add one reusable modal containing fixed pair labels; checkbox groups for scenes, dimensions and workers; `datetime-local` start/end inputs; mode/result/bad-case selects; include-images/include-bad-cases/include-duration checkboxes; preview count; cancel and export buttons.

Use horizontal wrapping checkbox chips so long scene and worker lists do not create a tall single-column form. On mobile, switch the fixed two-column form sections to one column.

- [ ] **Step 4: 加载选项并收集请求**

Store current export state as:

```javascript
state.exportPair = { v1: "", v2: "", options: null, previewTimer: null };
```

`openExportModal(v1, v2)` fetches options, selects every scene/worker/dimension, fills min/max Beijing times into `datetime-local`, opens the modal, then calls `previewExport()`.

`collectExportRequest()` returns API-ready ISO values by appending seconds and `+08:00` to `datetime-local` values without timezone conversion:

```javascript
function localInputToBeijingIso(value, endOfMinute = false) {
    if (!value) return null;
    return `${value}:${endOfMinute ? "59" : "00"}+08:00`;
}
```

- [ ] **Step 5: 实现预览和二进制下载**

`previewExport()` posts JSON after a 200 ms debounce and displays Overall count, each dimension count and unique image count. Disable export when Overall count is zero.

`downloadExport()` posts the same JSON, reads the blob, extracts the UTF-8 filename from `Content-Disposition`, clicks a temporary `<a download>`, revokes the blob URL, and restores the button in `finally`. For non-2xx responses, parse the JSON `detail` and show it in the modal.

- [ ] **Step 6: 运行模板测试和 JavaScript 语法检查**

Run:

```bash
python3 -m unittest tests.test_dashboard_export_ui -v
node -e "const fs=require('fs'),vm=require('vm'); const s=fs.readFileSync('templates/dashboard.html','utf8'); for (const m of s.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)) new vm.Script(m[1]); console.log('dashboard js ok')"
```

Expected: tests pass and Node prints `dashboard js ok`.

- [ ] **Step 7: 提交**

```bash
git add templates/dashboard.html tests/test_dashboard_export_ui.py
git commit -m "feat: 增加看板导出配置交互"
```

---

### Task 7: 业务时间展示与评测计时起点

**Files:**
- Modify: `templates/index.html:960-1004`
- Modify: `templates/dashboard.html:619-1065`
- Modify: `templates/profile.html:280-350`
- Modify: `templates/admin.html:330-367`
- Create: `tests/test_frontend_time_contract.py`

**Interfaces:**
- Consumes: API 返回的 `+08:00` 北京时间字符串和当前任务图片节点。
- Produces: `formatBusinessTime(value)` 和 `waitForTaskImages(timeoutMs=15000)`；评测计时不再包含接口或图片加载等待。

- [ ] **Step 1: 写前端时间契约失败测试**

```python
def test_all_business_time_pages_use_shared_format_contract(self):
    for template in ("dashboard.html", "profile.html", "admin.html"):
        html = Path("templates", template).read_text(encoding="utf-8")
        self.assertIn("function formatBusinessTime", html)
        self.assertIn("formatBusinessTime(", html)

def test_evaluation_timer_waits_for_images(self):
    html = Path("templates/index.html").read_text(encoding="utf-8")
    self.assertIn("function waitForTaskImages", html)
    self.assertIn("await waitForTaskImages()", html)
    self.assertLess(html.index("await waitForTaskImages()"), html.index("startTimer();", html.index("async function loadNextTask")))
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_frontend_time_contract -v`

Expected: FAIL because format and wait helpers are missing.

- [ ] **Step 3: 统一页面时间显示**

Add the same small formatter to dashboard, profile and admin scripts:

```javascript
function formatBusinessTime(value) {
    if (!value) return "-";
    return value.replace("T", " ").replace("+08:00", "");
}
```

Wrap dashboard detail/bad-case `row.time`, profile history and account timestamps, and admin user/log timestamps with this function. No `Date` constructor is used for stored business timestamps.

- [ ] **Step 4: 等待任务图片后启动计时**

```javascript
function waitForTaskImages(timeoutMs = 15000) {
    const images = [...document.querySelectorAll("#compare-grid img")];
    return Promise.all(images.map(img => new Promise(resolve => {
        if (img.complete) return resolve();
        const finish = () => {
            clearTimeout(timeout);
            img.removeEventListener("load", finish);
            img.removeEventListener("error", finish);
            resolve();
        };
        const timeout = setTimeout(finish, timeoutMs);
        img.addEventListener("load", finish, { once: true });
        img.addEventListener("error", finish, { once: true });
    })));
}
```

At the start of `loadNextTask()`, call `stopTimer()`, set `startTime = null`, and reset the timer text to `00:00`. Remove the existing first-line `startTimer()`. After task state, compare grid, prompt and bad-case panels are rendered, call `await waitForTaskImages(); startTimer();`.

- [ ] **Step 5: 运行前端契约和语法检查**

Run:

```bash
python3 -m unittest tests.test_frontend_time_contract tests.test_dashboard_export_ui -v
node -e "const fs=require('fs'),vm=require('vm'); for (const f of fs.readdirSync('templates').filter(x=>x.endsWith('.html'))) { const s=fs.readFileSync('templates/'+f,'utf8'); for (const m of s.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)) new vm.Script(m[1], {filename:f}); } console.log('templates js ok')"
```

Expected: all tests pass and Node prints `templates js ok`.

- [ ] **Step 6: 提交**

```bash
git add templates/index.html templates/dashboard.html templates/profile.html templates/admin.html tests/test_frontend_time_contract.py
git commit -m "fix: 统一北京时间展示并修正评测计时"
```

---

### Task 8: 文档、全量验证与代码审查

**Files:**
- Modify: `README.md`
- Verify: all changed production and test files

**Interfaces:**
- Consumes: Tasks 1-7 的完整实现。
- Produces: 可复现的安装、导出、迁移说明和经审查的最终实现。

- [ ] **Step 1: 更新 README**

Document `openpyxl` installation via `pip install -r requirements.txt`, dashboard export filters, XLSX/ZIP behavior, exact image paths, Beijing time storage format, one-time migration, and the fact that `database.db` should be backed up before first startup after upgrade.

- [ ] **Step 2: 运行完整自动化验证**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall main.py app_core tests
node -e "const fs=require('fs'),vm=require('vm'); for (const f of fs.readdirSync('templates').filter(x=>x.endsWith('.html'))) { const s=fs.readFileSync('templates/'+f,'utf8'); for (const m of s.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)) new vm.Script(m[1], {filename:f}); } console.log('templates js ok')"
git diff --check
```

Expected: all tests pass with 0 failures, compileall exits 0, Node prints `templates js ok`, and `git diff --check` produces no output.

- [ ] **Step 3: 在数据库副本上验证迁移**

Run a test helper that copies `database.db` into a temporary directory, patches `app_core.database.DB_PATH`, runs `init_db()` twice, and prints counts of business timestamps ending in `+08:00` after each run.

Expected: first and second runs have identical row counts and identical timestamp values; no source `database.db` write occurs.

- [ ] **Step 4: 本地浏览器验证**

Start `uvicorn main:app --host 127.0.0.1 --port 8000`, then verify in the in-app browser:

1. T2I model pair opens an export modal with three detail dimensions.
2. TI2I model pair opens an export modal with four detail dimensions.
3. Scene/worker/mode/result/bad-case/time changes update preview counts.
4. No-image export downloads a readable XLSX with `Overall` and selected detail sheets.
5. Image export downloads a ZIP with `images/<scene>/<model>/<filename>` and TI2I `images/<scene>/ref/<filename>`.
6. Dashboard, profile and admin display Beijing time without an 8-hour offset.
7. Index timer remains `00:00` while task images load and begins afterward.

- [ ] **Step 5: 请求独立代码审查并修复问题**

Use `superpowers:requesting-code-review` with the approved design, this plan, base SHA, and current HEAD. Fix every Critical and Important finding, then rerun Step 2 in full.

- [ ] **Step 6: 最终提交**

```bash
git add README.md
git commit -m "docs: 补充评测导出和北京时间说明"
git status --short
```

Expected: only intentionally untracked `database.db` and local `.planning` files remain; no production or test changes are unstaged.
