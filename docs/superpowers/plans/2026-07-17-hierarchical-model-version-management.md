# Hierarchical Model Version Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organize model names as `class → model → version` in the dashboard while preserving `class_model_version` result directories and null-compatible legacy names.

**Architecture:** Add a focused `model_catalog` module for validation, parsing, database discovery, and catalog merging. Keep storage responsible for filesystem discovery and writes, expose one structured catalog API, submit upload components separately, and let the dashboard derive safe datalist choices and pair filtering from catalog entries.

**Tech Stack:** Python 3, FastAPI, SQLite, filesystem-backed result storage, server-rendered HTML/CSS/vanilla JavaScript, `unittest`, Node.js DOM stubs.

## Global Constraints

- Standard model names are exactly `class_model_version`.
- `class_name`, `model_name`, and `version` are required and may not contain `_`.
- Existing storage-component safety checks still reject path separators, `.`, and `..`.
- Legacy names that are not exactly three non-empty underscore-delimited parts return null class/model and preserve the original full name as version.
- No model metadata database table is added.
- Catalog entries merge result directories, `pair_tasks.v_a/v_b`, and `results_log.v_a/v_b`.
- The frontend submits separate name fields; the backend alone builds the trusted directory name.
- Legacy database rows are not renamed.
- Repository mock models become `test_<original model>_default`.
- Dynamic backend text is inserted with DOM text APIs, never interpolated as HTML.
- Desktop upload blocks use two rows; widths at or below 720px remain single-column.

---

## File Structure

- Create `app_core/model_catalog.py`: model-component validation, full-name composition/parsing, database name discovery, and catalog assembly.
- Modify `app_core/storage.py`: expose filesystem-only model-name discovery and accept structured upload name components.
- Modify `main.py`: add catalog endpoint and change upload form parameters.
- Modify `templates/dashboard.html`: two-row forms, hierarchical upload controls, catalog state, new-name confirmation, and overview class/model filters.
- Create `tests/test_model_catalog.py`: backend unit and integration-style catalog/upload tests.
- Create `tests/test_dashboard_model_hierarchy_ui.py`: Node-backed frontend behavior and layout contract tests.
- Modify `tests/test_task_0_review_fixes.py`: update structured upload calls while retaining path-root and authorization regressions.
- Modify `scripts/generated_dataset.py`, `scripts/rule_perturbations.py`, `tests/test_generated_dataset_tools.py`, `tests/fixtures/generated_dataset_expectations.json`, and `README.md`: migrate repository mock names and paths.
- Move tracked directories under `results/T2I` and `results/TI2I` to three-part names with `git mv`.

---

### Task 1: Model Name Domain Logic

**Files:**
- Create: `app_core/model_catalog.py`
- Create: `tests/test_model_catalog.py`

**Interfaces:**
- Produces: `validate_model_component(value: str, label: str) -> str`
- Produces: `compose_model_name(class_name: str, model_name: str, version: str) -> str`
- Produces: `parse_model_name(full_name: str) -> dict`
- Consumes: `app_core.storage.validate_storage_component`

- [ ] **Step 1: Write failing validation, composition, and parsing tests**

```python
import unittest

from app_core.errors import AppError
from app_core.model_catalog import compose_model_name, parse_model_name, validate_model_component


class ModelNameTests(unittest.TestCase):
    def test_composes_three_valid_components(self):
        self.assertEqual(
            compose_model_name("test", "Atlas", "default"),
            "test_Atlas_default",
        )

    def test_rejects_empty_underscore_and_unsafe_components(self):
        for value in ("", "   ", "foo_bar", ".", "..", "nested/path", "nested\\path"):
            with self.subTest(value=value):
                with self.assertRaises(AppError):
                    validate_model_component(value, "class")

    def test_parses_exactly_three_non_empty_parts(self):
        self.assertEqual(
            parse_model_name("test_Atlas_default"),
            {
                "class_name": "test",
                "model_name": "Atlas",
                "version": "default",
                "full_name": "test_Atlas_default",
            },
        )

    def test_preserves_non_standard_legacy_name(self):
        for full_name in ("Atlas", "too_many_parts_here", "broken__name"):
            with self.subTest(full_name=full_name):
                self.assertEqual(
                    parse_model_name(full_name),
                    {
                        "class_name": None,
                        "model_name": None,
                        "version": full_name,
                        "full_name": full_name,
                    },
                )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_model_catalog.ModelNameTests -v
```

Expected: ERROR because `app_core.model_catalog` does not exist.

- [ ] **Step 3: Implement the minimum domain functions**

```python
# app_core/model_catalog.py
from .errors import AppError
from .storage import validate_storage_component


def validate_model_component(value: str, label: str) -> str:
    normalized = validate_storage_component(value, label)
    if "_" in normalized:
        raise AppError(f"{label}不能包含下划线 _")
    return normalized


def compose_model_name(class_name: str, model_name: str, version: str) -> str:
    parts = (
        validate_model_component(class_name, "class"),
        validate_model_component(model_name, "model"),
        validate_model_component(version, "version"),
    )
    return "_".join(parts)


def parse_model_name(full_name: str) -> dict:
    parts = full_name.split("_")
    if len(parts) == 3 and all(parts):
        class_name, model_name, version = parts
        return {
            "class_name": class_name,
            "model_name": model_name,
            "version": version,
            "full_name": full_name,
        }
    return {
        "class_name": None,
        "model_name": None,
        "version": full_name,
        "full_name": full_name,
    }
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
python -m unittest tests.test_model_catalog.ModelNameTests -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit the domain logic**

```bash
git add app_core/model_catalog.py tests/test_model_catalog.py
git commit -m "feat: add hierarchical model name rules"
```

---

### Task 2: Structured Model Catalog API

**Files:**
- Modify: `app_core/model_catalog.py`
- Modify: `app_core/storage.py:45-64`
- Modify: `main.py:15-28,118-120`
- Modify: `tests/test_model_catalog.py`

**Interfaces:**
- Consumes: `parse_model_name(full_name: str) -> dict`
- Produces: `get_filesystem_model_names(task_type: str) -> list[str]`
- Produces: `get_database_model_names(task_type: str) -> list[str]`
- Produces: `get_model_catalog(task_type: str) -> dict`
- Produces: `GET /api/model_catalog?task_type=T2I`
- Preserves: `get_versions_for_type(task_type: str) -> list[str]`

- [ ] **Step 1: Add failing catalog merge tests**

Append:

```python
import os
import sqlite3
import tempfile
from unittest.mock import patch

from app_core import config, model_catalog, storage


class ModelCatalogTests(unittest.TestCase):
    def test_merges_filesystem_and_database_names_with_legacy_compatibility(self):
        with patch.object(
            storage,
            "get_filesystem_model_names",
            return_value=["test_Atlas_default", "legacy-only"],
        ), patch.object(
            model_catalog,
            "get_database_model_names",
            return_value=["test_Atlas_default", "test_Beacon_default", "db-legacy"],
        ):
            self.assertEqual(
                model_catalog.get_model_catalog("T2I"),
                {
                    "task_type": "T2I",
                    "models": [
                        parse_model_name("db-legacy"),
                        parse_model_name("legacy-only"),
                        parse_model_name("test_Atlas_default"),
                        parse_model_name("test_Beacon_default"),
                    ],
                },
            )

    def test_database_discovery_reads_both_model_columns_from_both_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "catalog.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE pair_tasks (task_type TEXT, v_a TEXT, v_b TEXT)"
            )
            conn.execute(
                "CREATE TABLE results_log (task_type TEXT, v_a TEXT, v_b TEXT)"
            )
            conn.execute(
                "INSERT INTO pair_tasks (task_type, v_a, v_b) VALUES ('T2I', 'pair-a', 'shared')"
            )
            conn.execute(
                "INSERT INTO results_log (task_type, v_a, v_b) VALUES ('T2I', 'shared', 'result-b')"
            )
            conn.execute(
                "INSERT INTO results_log (task_type, v_a, v_b) VALUES ('TI2I', 'other-task', 'ignored')"
            )
            conn.commit()
            conn.close()
            with patch.object(
                model_catalog,
                "connect",
                side_effect=lambda: sqlite3.connect(db_path),
            ):
                self.assertEqual(
                    model_catalog.get_database_model_names("T2I"),
                    ["pair-a", "result-b", "shared"],
                )
```

Add an API contract assertion:

```python
class ModelCatalogRouteTests(unittest.TestCase):
    def test_catalog_route_is_registered(self):
        import main

        routes = {route.path: route for route in main.app.routes}
        self.assertIn("/api/model_catalog", routes)
```

- [ ] **Step 2: Run the catalog tests and verify RED**

Run:

```bash
python -m unittest \
  tests.test_model_catalog.ModelCatalogTests \
  tests.test_model_catalog.ModelCatalogRouteTests -v
```

Expected: FAIL because catalog functions and route are missing.

- [ ] **Step 3: Separate filesystem discovery without changing `/api/versions` behavior**

In `app_core/storage.py`, replace the existing function with:

```python
def get_filesystem_model_names(task_type: str) -> List[str]:
    preferred = get_result_root(task_type)
    task_type_names = {normalize_task_type(name) for name in app_config.TASK_CONFIGS}
    task_roots = {
        os.path.normpath(str(config["result_root"]))
        for config in app_config.TASK_CONFIGS.values()
    }
    versions = set()
    for root in get_result_roots(task_type):
        if not os.path.isdir(root):
            continue
        versions.update(
            name
            for name in os.listdir(root)
            if os.path.isdir(os.path.join(root, name))
            and os.path.normpath(os.path.join(root, name)) != os.path.normpath(preferred)
            and os.path.normpath(os.path.join(root, name)) not in task_roots
            and normalize_task_type(name) not in task_type_names
        )
    return sorted(versions)


def get_versions_for_type(task_type: str) -> List[str]:
    return get_filesystem_model_names(task_type)
```

This preserves the evaluation terminal’s existing `/api/versions` contract.

- [ ] **Step 4: Implement database discovery and catalog assembly**

Append to `app_core/model_catalog.py`:

```python
from .config import normalize_task_type
from .database import connect
from . import storage


def get_database_model_names(task_type: str) -> list[str]:
    task_type = normalize_task_type(task_type)
    conn = connect()
    try:
        names = set()
        for table in ("pair_tasks", "results_log"):
            rows = conn.execute(
                f"""
                SELECT v_a FROM {table} WHERE task_type=? AND v_a IS NOT NULL AND v_a<>''
                UNION
                SELECT v_b FROM {table} WHERE task_type=? AND v_b IS NOT NULL AND v_b<>''
                """,
                (task_type, task_type),
            ).fetchall()
            names.update(row[0] for row in rows)
        return sorted(names)
    finally:
        conn.close()


def get_model_catalog(task_type: str) -> dict:
    task_type = normalize_task_type(task_type)
    names = set(storage.get_filesystem_model_names(task_type))
    names.update(get_database_model_names(task_type))
    return {
        "task_type": task_type,
        "models": [parse_model_name(name) for name in sorted(names)],
    }
```

- [ ] **Step 5: Register the API route**

Update imports and add beside `/api/versions`:

```python
from app_core.model_catalog import get_model_catalog


@app.get("/api/model_catalog")
def model_catalog(task_type: str):
    return get_model_catalog(task_type)
```

- [ ] **Step 6: Run focused and existing storage tests**

Run:

```bash
python -m unittest \
  tests.test_model_catalog.ModelCatalogTests \
  tests.test_model_catalog.ModelCatalogRouteTests \
  tests.test_task_0_review_fixes.ResultRootResolutionTests -v
```

Expected: all tests pass, including existing `/api/versions` filesystem behavior.

- [ ] **Step 7: Commit the catalog API**

```bash
git add app_core/model_catalog.py app_core/storage.py main.py tests/test_model_catalog.py
git commit -m "feat: expose structured model catalog"
```

---

### Task 3: Structured Result Upload Contract

**Files:**
- Modify: `app_core/storage.py:680-690`
- Modify: `main.py:318-328`
- Modify: `tests/test_model_catalog.py`
- Modify: `tests/test_task_0_review_fixes.py:99-137`

**Interfaces:**
- Consumes: `compose_model_name(class_name, model_name, version) -> str`
- Produces: `upload_result_zip(task_type, class_name, model_name, version, scene, upload_file, auto_rename=False) -> dict`
- Changes: `POST /api/upload` form fields to `class_name`, `model_name`, and `version`

- [ ] **Step 1: Add failing storage and route-contract tests**

Append:

```python
import io
import zipfile
from types import SimpleNamespace


def image_zip(name: str) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(name, b"image")
    return data.getvalue()


class StructuredUploadTests(unittest.TestCase):
    def test_upload_builds_trusted_full_name_and_returns_it(self):
        upload = SimpleNamespace(file=io.BytesIO(image_zip("img.png")))
        with tempfile.TemporaryDirectory() as temp_dir:
            task_configs = {
                **config.TASK_CONFIGS,
                "T2I": {
                    **config.TASK_CONFIGS["T2I"],
                    "result_root": os.path.join(temp_dir, "results", "T2I"),
                },
            }
            with patch.object(config, "TASK_CONFIGS", task_configs), patch.object(
                storage,
                "validate_result_zip",
                return_value={"status": "exact", "rename_map": {}, "image_count": 1},
            ):
                result = storage.upload_result_zip(
                    "T2I", "test", "Atlas", "default", "scene", upload
                )

            expected = os.path.join(
                task_configs["T2I"]["result_root"],
                "test_Atlas_default",
                "scene",
                "img.png",
            )
            self.assertTrue(os.path.exists(expected))
            self.assertEqual(result["full_name"], "test_Atlas_default")

    def test_upload_rejects_underscore_before_writing(self):
        upload = SimpleNamespace(file=io.BytesIO(image_zip("img.png")))
        with self.assertRaises(AppError):
            storage.upload_result_zip(
                "T2I", "bad_class", "Atlas", "default", "scene", upload
            )
```

Add route field assertions using FastAPI dependency metadata:

```python
class StructuredUploadRouteTests(unittest.TestCase):
    def test_upload_route_accepts_separate_name_components(self):
        import main

        route = next(route for route in main.app.routes if route.path == "/api/upload")
        body_names = {field.name for field in route.dependant.body_params}
        self.assertTrue({"class_name", "model_name", "version"}.issubset(body_names))
        self.assertNotIn("full_name", body_names)
```

- [ ] **Step 2: Run upload tests and verify RED**

Run:

```bash
python -m unittest \
  tests.test_model_catalog.StructuredUploadTests \
  tests.test_model_catalog.StructuredUploadRouteTests -v
```

Expected: FAIL because the old function accepts one `version` directory name.

- [ ] **Step 3: Implement structured upload composition**

Update `app_core/storage.py`:

```python
def upload_result_zip(
    task_type: str,
    class_name: str,
    model_name: str,
    version: str,
    scene: str,
    upload_file,
    auto_rename: bool = False,
) -> dict:
    from .model_catalog import compose_model_name

    task_type = normalize_task_type(task_type)
    full_name = compose_model_name(class_name, model_name, version)
    scene = validate_storage_component(scene, "场景")
    zip_bytes = read_upload_bytes(upload_file)
    validation = validate_result_zip(task_type, scene, zip_bytes, auto_rename=auto_rename)
    if validation["status"] == "requires_rename_confirmation":
        return validation
    result_root = get_task_config(task_type)["result_root"]
    save_zip_images(
        os.path.join(result_root, full_name, scene),
        zip_bytes,
        validation.get("rename_map"),
    )
    return {
        "message": "Success",
        "status": validation["status"],
        "image_count": validation["image_count"],
        "full_name": full_name,
    }
```

The local import avoids a module-import cycle because `model_catalog` reuses the storage validator.

- [ ] **Step 4: Change FastAPI form parameters**

```python
@app.post("/api/upload")
async def upload_data(
    task_type: str = Form(...),
    class_name: str = Form(...),
    model_name: str = Form(...),
    version: str = Form(...),
    scene: str = Form(...),
    file: UploadFile = File(...),
    auto_rename: bool = Form(False),
    admin: dict = Depends(require_admin),
):
    return upload_result_zip(
        task_type,
        class_name,
        model_name,
        version,
        scene,
        file,
        auto_rename=auto_rename,
    )
```

- [ ] **Step 5: Update existing upload regressions to pass three fields**

Replace calls such as:

```python
storage.upload_result_zip("T2I", "new-version", "new-scene", upload)
```

with:

```python
storage.upload_result_zip("T2I", "new", "model", "version", "new-scene", upload)
```

Update expected paths to `new_model_version`. For unsafe path tests, place the unsafe value in one component:

```python
storage.upload_result_zip("T2I", "../escape", "model", "v1", "scene", result_upload)
```

- [ ] **Step 6: Run upload and authorization regressions**

Run:

```bash
python -m unittest \
  tests.test_model_catalog.StructuredUploadTests \
  tests.test_model_catalog.StructuredUploadRouteTests \
  tests.test_task_0_review_fixes.ResultRootResolutionTests \
  tests.test_task_0_review_fixes.UploadValidationTests \
  tests.test_task_0_review_fixes.UploadRouteAuthorizationTests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit the upload contract**

```bash
git add app_core/storage.py main.py tests/test_model_catalog.py tests/test_task_0_review_fixes.py
git commit -m "feat: upload structured model versions"
```

---

### Task 4: Dashboard Hierarchical Controls and Filtering

**Files:**
- Create: `tests/test_dashboard_model_hierarchy_ui.py`
- Modify: `templates/dashboard.html:63-92,440-466,490-530,738-840,980-1025,1920-1980`

**Interfaces:**
- Consumes: `GET /api/model_catalog`
- Produces frontend functions:
  - `loadModelCatalog(taskType) -> Promise<void>`
  - `handleResultTaskTypeChange() -> Promise<void>`
  - `syncResultModelChoices() -> void`
  - `syncOverviewModelFilters() -> void`
  - `validateModelInput(value, label) -> string`
  - `confirmNewModelHierarchy() -> boolean`
  - `pairMatchesHierarchy(pair, className, modelName) -> boolean`

- [ ] **Step 1: Create failing HTML contract tests**

```python
import json
import subprocess
import unittest
from pathlib import Path


class DashboardModelHierarchyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("templates/dashboard.html").read_text(encoding="utf-8")

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

    def test_upload_and_filter_controls_exist(self):
        for marker in (
            'id="result-class"',
            'id="result-model"',
            'id="result-version"',
            'id="result-class-options"',
            'id="result-model-options"',
            'id="result-version-options"',
            'id="filter-class"',
            'id="filter-model"',
        ):
            self.assertIn(marker, self.html)

    def test_form_data_submits_components_not_full_name(self):
        source = self.function_source("uploadResultZip")
        self.assertIn('formData.append("class_name"', source)
        self.assertIn('formData.append("model_name"', source)
        self.assertIn('formData.append("version"', source)
        self.assertNotIn('formData.append("full_name"', source)
```

- [ ] **Step 2: Add failing pure-function filtering tests**

Append:

```python
    def run_js(self, body):
        return json.loads(subprocess.check_output(["node", "-e", body], text=True))

    def test_pair_hierarchy_must_match_on_the_same_side(self):
        source = self.function_source("pairMatchesHierarchy")
        payload = self.run_js(f"""
            {source}
            const pair = {{
                v_a_meta: {{ class_name: "alpha", model_name: "one" }},
                v_b_meta: {{ class_name: "beta", model_name: "two" }}
            }};
            console.log(JSON.stringify([
                pairMatchesHierarchy(pair, "alpha", "one"),
                pairMatchesHierarchy(pair, "alpha", "two"),
                pairMatchesHierarchy(pair, "", ""),
            ]));
        """)
        self.assertEqual(payload, [True, False, True])

    def test_legacy_null_model_only_matches_all(self):
        source = self.function_source("pairMatchesHierarchy")
        payload = self.run_js(f"""
            {source}
            const pair = {{
                v_a_meta: {{ class_name: null, model_name: null }},
                v_b_meta: {{ class_name: null, model_name: null }}
            }};
            console.log(JSON.stringify([
                pairMatchesHierarchy(pair, "", ""),
                pairMatchesHierarchy(pair, "test", ""),
            ]));
        """)
        self.assertEqual(payload, [True, False])
```

- [ ] **Step 3: Run frontend tests and verify RED**

Run:

```bash
python -m unittest tests.test_dashboard_model_hierarchy_ui -v
```

Expected: FAIL because controls and functions are missing.

- [ ] **Step 4: Add upload datalist controls and overview selects**

Replace the single model-version input with:

```html
<div class="input-group">
    <label>Class</label>
    <input id="result-class" list="result-class-options" required
           oninput="syncResultModelChoices()">
    <datalist id="result-class-options"></datalist>
</div>
<div class="input-group">
    <label>Model</label>
    <input id="result-model" list="result-model-options" required
           oninput="syncResultModelChoices()">
    <datalist id="result-model-options"></datalist>
</div>
<div class="input-group">
    <label>Version</label>
    <input id="result-version" list="result-version-options" required>
    <datalist id="result-version-options"></datalist>
</div>
```

Add to overview filters:

```html
<div class="input-group">
    <label>Class</label>
    <select id="filter-class" onchange="syncOverviewModelFilters(); applyFilters()">
        <option value="">全部 class</option>
    </select>
</div>
<div class="input-group">
    <label>Model</label>
    <select id="filter-model" onchange="applyFilters()">
        <option value="">全部 model</option>
    </select>
</div>
```

- [ ] **Step 5: Add catalog state and safe option helpers**

Extend state:

```javascript
modelCatalogs: {},
modelCatalogErrors: {}
```

Add safe datalist replacement:

```javascript
function replaceDatalistOptions(list, values) {
    const nodes = values.map(value => {
        const option = document.createElement("option");
        option.value = value;
        return option;
    });
    list.replaceChildren(...nodes);
}
```

Add catalog loading:

```javascript
async function loadModelCatalog(taskType) {
    try {
        const catalog = await api(
            `/api/model_catalog?task_type=${encodeURIComponent(taskType)}`
        ).then(response => response.json());
        state.modelCatalogs[taskType] = catalog.models;
        state.modelCatalogErrors[taskType] = "";
    } catch (error) {
        state.modelCatalogs[taskType] = [];
        state.modelCatalogErrors[taskType] = error.message;
    }
}
```

- [ ] **Step 6: Implement upload hierarchy choices and validation**

```javascript
function currentResultCatalog() {
    const taskType = document.getElementById("result-task-type").value;
    return state.modelCatalogs[taskType] || [];
}

function uniqueSorted(values) {
    return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function syncResultModelChoices() {
    const className = document.getElementById("result-class").value.trim();
    const modelName = document.getElementById("result-model").value.trim();
    const standard = currentResultCatalog().filter(item => item.class_name && item.model_name);
    replaceDatalistOptions(
        document.getElementById("result-class-options"),
        uniqueSorted(standard.map(item => item.class_name))
    );
    const classModels = standard.filter(item => item.class_name === className);
    replaceDatalistOptions(
        document.getElementById("result-model-options"),
        uniqueSorted(classModels.map(item => item.model_name))
    );
    replaceDatalistOptions(
        document.getElementById("result-version-options"),
        uniqueSorted(
            classModels
                .filter(item => item.model_name === modelName)
                .map(item => item.version)
        )
    );
}

function validateModelInput(value, label) {
    const normalized = value.trim();
    if (!normalized) throw new Error(`请输入 ${label}`);
    if (normalized.includes("_")) throw new Error(`${label} 不能包含下划线 _`);
    if (normalized === "." || normalized === ".." || /[\\/]/.test(normalized)) {
        throw new Error(`${label} 包含不安全字符`);
    }
    return normalized;
}

function confirmNewModelHierarchy() {
    const classInput = document.getElementById("result-class");
    const modelInput = document.getElementById("result-model");
    const className = validateModelInput(classInput.value, "class");
    const modelName = validateModelInput(modelInput.value, "model");
    validateModelInput(document.getElementById("result-version").value, "version");
    const standard = currentResultCatalog().filter(item => item.class_name && item.model_name);
    const classExists = standard.some(item => item.class_name === className);
    if (!classExists && !confirm(`class “${className}” 尚不存在，是否新建？`)) {
        classInput.focus();
        return false;
    }
    const modelExists = standard.some(
        item => item.class_name === className && item.model_name === modelName
    );
    if (!modelExists && !confirm(`model “${modelName}” 尚不存在，是否在 class “${className}” 下新建？`)) {
        modelInput.focus();
        return false;
    }
    return true;
}
```

Change the result task selector to:

```html
<select id="result-task-type" onchange="handleResultTaskTypeChange()">
```

Add:

```javascript
async function handleResultTaskTypeChange() {
    const taskType = document.getElementById("result-task-type").value;
    await Promise.all([loadModelCatalog(taskType), syncResultScenes()]);
    syncResultModelChoices();
    const error = state.modelCatalogErrors[taskType];
    if (error) {
        document.getElementById("upload-msg").textContent =
            `模型目录加载失败，仍可手动输入：${error}`;
    }
}
```

Update `init()`:

```javascript
async function init() {
    await loadModelCatalog(state.taskType);
    await handleTaskTypeChange();
    syncDatasetUploadMode();
    await handleResultTaskTypeChange();
    bindUploadForms();
    bindExportEvents();
}
```

A catalog load error does not disable free input.

- [ ] **Step 7: Implement same-side overview filtering**

When loading the dashboard, attach metadata without changing backend aggregate payloads:

```javascript
function catalogEntryFor(fullName) {
    const catalog = state.modelCatalogs[state.taskType] || [];
    return catalog.find(item => item.full_name === fullName) || {
        class_name: null,
        model_name: null,
        version: fullName,
        full_name: fullName
    };
}

function pairMatchesHierarchy(pair, className, modelName) {
    if (!className && !modelName) return true;
    return [pair.v_a_meta, pair.v_b_meta].some(meta => {
        if (className && meta.class_name !== className) return false;
        if (modelName && meta.model_name !== modelName) return false;
        return true;
    });
}
```

In `loadDashboard()`:

```javascript
state.pairs = data.pairs.map(pair => ({
    ...pair,
    v_a_meta: catalogEntryFor(pair.v_a),
    v_b_meta: catalogEntryFor(pair.v_b),
}));
syncOverviewModelFilters();
```

In the existing `handleTaskTypeChange()`, insert this line immediately after the `/api/task_config` response is assigned:

```javascript
await loadModelCatalog(state.taskType);
```

This guarantees metadata exists before the unchanged later `loadDashboard()` call.

Implement cascading filter options:

```javascript
function syncOverviewModelFilters() {
    const classSelect = document.getElementById("filter-class");
    const modelSelect = document.getElementById("filter-model");
    const selectedClass = classSelect.value;
    const selectedModel = modelSelect.value;
    const standard = (state.modelCatalogs[state.taskType] || [])
        .filter(item => item.class_name && item.model_name);
    replaceSelectOptions(
        classSelect,
        [["", "全部 class"], ...uniqueSorted(standard.map(item => item.class_name))
            .map(value => [value, value])]
    );
    classSelect.value = selectedClass;
    const models = standard
        .filter(item => !classSelect.value || item.class_name === classSelect.value)
        .map(item => item.model_name);
    replaceSelectOptions(
        modelSelect,
        [["", "全部 model"], ...uniqueSorted(models).map(value => [value, value])]
    );
    if (models.includes(selectedModel)) modelSelect.value = selectedModel;
}
```

Add to `applyFilters()`:

```javascript
const className = document.getElementById("filter-class").value;
const modelName = document.getElementById("filter-model").value;
if (!pairMatchesHierarchy(pair, className, modelName)) return false;
```

Extend the existing `resetFilters()` assignments:

```javascript
document.getElementById("filter-class").value = "";
syncOverviewModelFilters();
document.getElementById("filter-model").value = "";
```

- [ ] **Step 8: Submit structured fields and preserve confirmation through ZIP rename retry**

At the start of the initial submit only:

```javascript
if (!autoRename && !confirmNewModelHierarchy()) {
    msg.textContent = "已取消上传";
    return;
}
```

Build FormData:

```javascript
formData.append("class_name", validateModelInput(
    document.getElementById("result-class").value, "class"
));
formData.append("model_name", validateModelInput(
    document.getElementById("result-model").value, "model"
));
formData.append("version", validateModelInput(
    document.getElementById("result-version").value, "version"
));
```

After success, report `result.full_name`, reload the current task type’s catalog, resync controls, and then refresh the dashboard. Catch validation errors before `fetch`.

- [ ] **Step 9: Add confirmation-order tests**

Add Node stubs proving:

- New class confirmation happens before new model confirmation.
- Cancelling class focuses class and makes no request.
- Existing class plus new model asks only the model question.
- `autoRename=true` does not repeat new-name confirmations.
- `validateModelInput("bad_name", "class")` throws before API invocation.

Use an event log array:

```javascript
const events = [];
const confirm = message => { events.push(message); return true; };
```

Assert exact event ordering and `focus()` calls.

- [ ] **Step 10: Run frontend hierarchy and existing XSS regressions**

Run:

```bash
python -m unittest \
  tests.test_dashboard_model_hierarchy_ui \
  tests.test_dashboard_export_ui.DashboardExportUiTests.test_result_scene_selector_treats_uploaded_scene_names_as_text \
  tests.test_dashboard_export_ui.DashboardExportUiTests.test_dynamic_dashboard_renderers_do_not_interpolate_backend_html -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit hierarchy controls**

```bash
git add templates/dashboard.html tests/test_dashboard_model_hierarchy_ui.py
git commit -m "feat: add dashboard model hierarchy controls"
```

---

### Task 5: Two-Row Upload Layout

**Files:**
- Modify: `templates/dashboard.html:63-92,376-386,413-466`
- Modify: `tests/test_dashboard_model_hierarchy_ui.py`

**Interfaces:**
- Produces CSS classes: `.upload-form`, `.upload-row`, `.dataset-upload-primary`, `.dataset-upload-files`, `.result-upload-primary`, `.result-upload-files`
- Preserves single-column behavior at `max-width: 720px`

- [ ] **Step 1: Add failing layout-contract tests**

```python
    def test_each_upload_block_has_two_rows(self):
        for marker in (
            'class="upload-row dataset-upload-primary"',
            'class="upload-row dataset-upload-files"',
            'class="upload-row result-upload-primary"',
            'class="upload-row result-upload-files"',
        ):
            self.assertIn(marker, self.html)

    def test_mobile_upload_rows_collapse_to_one_column(self):
        mobile = self.html[self.html.index("@media (max-width: 720px)"):]
        self.assertIn(".upload-row", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)
```

- [ ] **Step 2: Run layout tests and verify RED**

Run:

```bash
python -m unittest \
  tests.test_dashboard_model_hierarchy_ui.DashboardModelHierarchyUiTests.test_each_upload_block_has_two_rows \
  tests.test_dashboard_model_hierarchy_ui.DashboardModelHierarchyUiTests.test_mobile_upload_rows_collapse_to_one_column -v
```

Expected: FAIL because forms are currently one grid each.

- [ ] **Step 3: Introduce explicit row wrappers**

Use:

```html
<form id="dataset-form" class="upload-form">
    <div class="upload-row dataset-upload-primary">
        <!-- task type, scene -->
    </div>
    <div class="upload-row dataset-upload-files">
        <!-- prompt, optional ref, button -->
    </div>
</form>
```

and:

```html
<form id="result-form" class="upload-form">
    <div class="upload-row result-upload-primary">
        <!-- task type, class, model, version -->
    </div>
    <div class="upload-row result-upload-files">
        <!-- scene, result zip, button -->
    </div>
</form>
```

- [ ] **Step 4: Add desktop and responsive grid rules**

```css
.upload-form { display: grid; gap: 14px; }
.upload-row {
    display: grid;
    gap: 14px;
    align-items: end;
}
.dataset-upload-primary { grid-template-columns: 160px minmax(0, 1fr); }
.dataset-upload-files {
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1.4fr) auto;
}
.result-upload-primary {
    grid-template-columns: 140px repeat(3, minmax(0, 1fr));
}
.result-upload-files {
    grid-template-columns: minmax(180px, 1fr) minmax(0, 1.4fr) auto;
}
```

At `max-width: 1180px`, use two columns for `.upload-row`. At `max-width: 720px`:

```css
.upload-row { grid-template-columns: 1fr; }
```

Keep `dataset-ref-group` using `display:none/flex` because an input group already lays out as a vertical flex container; CSS grid automatically closes the hidden gap.

- [ ] **Step 5: Run layout and dataset-upload regression tests**

Run:

```bash
python -m unittest \
  tests.test_dashboard_model_hierarchy_ui \
  tests.test_dashboard_dataset_download_ui -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the upload layout**

```bash
git add templates/dashboard.html tests/test_dashboard_model_hierarchy_ui.py
git commit -m "style: split dashboard uploads into two rows"
```

---

### Task 6: Mock Model Migration and Full Verification

**Files:**
- Move: `results/T2I/Atlas` → `results/T2I/test_Atlas_default`
- Move: `results/T2I/Beacon` → `results/T2I/test_Beacon_default`
- Move: `results/T2I/Cipher` → `results/T2I/test_Cipher_default`
- Move: `results/TI2I/Mosaic` → `results/TI2I/test_Mosaic_default`
- Move: `results/TI2I/Prism` → `results/TI2I/test_Prism_default`
- Modify: `scripts/generated_dataset.py`
- Modify: `scripts/rule_perturbations.py`
- Modify: `tests/test_generated_dataset_tools.py`
- Modify: `tests/fixtures/generated_dataset_expectations.json`
- Modify: `README.md`
- Modify only if executable assertions require it: generated-dataset design/plan docs are historical records and should retain their original names.

**Interfaces:**
- Repository mock full names become:
  - `test_Atlas_default`
  - `test_Beacon_default`
  - `test_Cipher_default`
  - `test_Mosaic_default`
  - `test_Prism_default`
- Quality labels remain keyed by the same semantic models but use full model names wherever the key represents a result directory.

- [ ] **Step 1: Change generated-dataset tests first**

Update expected model tuples:

```python
MODELS = {
    "T2I": (
        "test_Atlas_default",
        "test_Beacon_default",
        "test_Cipher_default",
    ),
    "TI2I": (
        "test_Mosaic_default",
        "test_Prism_default",
    ),
}
```

Update all test paths and manifest dictionary keys. Keep human-readable quality descriptions if they are not used as directory keys; otherwise update them to full names.

Add one explicit hierarchy assertion:

```python
def test_repository_mock_models_use_three_part_names(self):
    for task_type, models in self.MODELS.items():
        for model in models:
            self.assertEqual(model.split("_"), ["test", model.split("_")[1], "default"])
```

- [ ] **Step 2: Run generated-dataset tests and verify RED**

Run:

```bash
python -m unittest tests.test_generated_dataset_tools -v
```

Expected: FAIL because scripts, fixture keys, and directories still use old names.

- [ ] **Step 3: Move tracked result directories**

Run:

```bash
git mv results/T2I/Atlas results/T2I/test_Atlas_default
git mv results/T2I/Beacon results/T2I/test_Beacon_default
git mv results/T2I/Cipher results/T2I/test_Cipher_default
git mv results/TI2I/Mosaic results/TI2I/test_Mosaic_default
git mv results/TI2I/Prism results/TI2I/test_Prism_default
```

- [ ] **Step 4: Update scripts and fixture keys mechanically**

Replace result-directory model keys and paths:

```text
Atlas  -> test_Atlas_default
Beacon -> test_Beacon_default
Cipher -> test_Cipher_default
Mosaic -> test_Mosaic_default
Prism  -> test_Prism_default
```

Apply this to:

- `scripts/generated_dataset.py`
- `scripts/rule_perturbations.py`
- `tests/fixtures/generated_dataset_expectations.json`
- executable assertions in `tests/test_generated_dataset_tools.py`

Do not rename prompt scenes or reference-image directories.

- [ ] **Step 5: Update current README examples**

Document:

```text
results/T2I/test_Atlas_default/<scene>/
results/TI2I/test_Mosaic_default/<scene>/
```

Explain that the UI displays these as:

```text
class=test, model=Atlas, version=default
```

Update the upload API parameter list from one `version` directory value to separate `class_name`, `model_name`, and `version`.

- [ ] **Step 6: Run mock-data tests and repair only migration-related failures**

Run:

```bash
python -m unittest \
  tests.test_generated_dataset \
  tests.test_generated_dataset_tools \
  tests.test_rule_perturbations -v
```

Expected: all tests pass.

- [ ] **Step 7: Run focused feature verification**

Run:

```bash
python -m unittest \
  tests.test_model_catalog \
  tests.test_dashboard_model_hierarchy_ui \
  tests.test_task_0_review_fixes \
  tests.test_dashboard_export_ui \
  tests.test_dashboard_dataset_download_ui -v
```

Expected: all tests pass with no errors or warnings.

- [ ] **Step 8: Run the complete regression suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 9: Run repository integrity checks**

Run:

```bash
git diff --check
rg -n 'results/(T2I|TI2I)/(Atlas|Beacon|Cipher|Mosaic|Prism)(/|")' \
  README.md scripts tests app_core templates
```

Expected:

- `git diff --check` produces no output.
- The `rg` command produces no current-code/test/README references to old mock result paths.
- Historical design and plan documents are intentionally outside the search scope.

- [ ] **Step 10: Commit the mock migration**

```bash
git add results scripts tests/fixtures tests/test_generated_dataset_tools.py README.md
git commit -m "chore: migrate mock models to hierarchical names"
```

- [ ] **Step 11: Review the final change set**

Run:

```bash
git status --short
git log --oneline -7
git diff HEAD~6..HEAD --stat
```

Expected:

- Only pre-existing untracked `.planning/`, `.superpowers/`, and `database.db` remain outside commits.
- Six feature commits follow the implementation plan.
- No runtime database file is staged.

## Final Manual Acceptance

Run the application using the repository’s normal command, log in as an administrator, and verify:

1. The result upload first row is task type, class, model, version.
2. The result upload second row is scene, result ZIP, upload button.
3. The dataset upload block has its required two rows.
4. Selecting `test` suggests Atlas/Beacon/Cipher for T2I and Mosaic/Prism for TI2I.
5. Entering a new class asks for class creation, then model creation.
6. Entering `_` in any component is blocked before upload and rejected by the backend if submitted directly.
7. A successful upload writes to `<result_root>/<class>_<model>_<version>/<scene>`.
8. Overview class/model filtering matches either side of a pair, but both selected values must match the same side.
9. Legacy single-part names still appear with null class/model behavior when present in database history.
10. At mobile width, upload rows collapse without horizontal overflow.
