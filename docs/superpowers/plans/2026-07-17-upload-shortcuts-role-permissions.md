# Upload Status, Evaluation Shortcuts, and Role Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add consistent upload feedback, reliable first-empty-dimension shortcuts, and enforced three-level user roles.

**Architecture:** Keep `users.role` as the single authorization source and add focused FastAPI dependencies for admin-only and data-transfer permissions. Preserve the existing dashboard controls while rendering server authorization errors in their existing status areas, and derive shortcut targets directly from current radio state instead of a mutable index.

**Tech Stack:** Python 3, FastAPI, SQLite, Pydantic, vanilla HTML/CSS/JavaScript, unittest/pytest-compatible tests.

## Global Constraints

- Valid roles are exactly `admin`, `manager`, and `evaluator`.
- New registrations default explicitly to `evaluator`.
- Upload and export controls remain visible to every logged-in role.
- Unauthorized upload and export feedback is exactly `当前用户没有权限，请联系管理员`.
- An admin cannot change their own role, and the system must retain at least one active admin.
- Permission checks must run before upload writes, export generation, or user mutation.
- Existing task assignment and evaluation behavior remain unchanged except for shortcut targeting.

---

### Task 1: Role Authorization and Account Safety

**Files:**
- Modify: `app_core/auth.py`
- Modify: `app_core/user_service.py`
- Modify: `app_core/admin_service.py`
- Modify: `main.py`
- Create: `tests/test_role_permissions.py`

**Interfaces:**
- Produces: `require_data_manager(user: dict = Depends(get_current_user)) -> dict`
- Produces: `update_user_role(user_id: int, role: str, admin_id: int) -> dict`
- Preserves: `update_user_status(user_id: int, is_active: int, admin_id: int) -> dict`

- [ ] **Step 1: Write failing authorization and registration tests**

Create `tests/test_role_permissions.py` with temporary-database tests that patch each module's `connect`, assert registration writes `evaluator`, call `require_data_manager` for all three roles, inspect every upload/export route dependency, and verify admin routes still require `require_admin`.

```python
def test_data_manager_accepts_admin_and_manager_and_rejects_evaluator(self):
    self.assertEqual(asyncio.run(auth.require_data_manager({"role": "admin"}))["role"], "admin")
    self.assertEqual(asyncio.run(auth.require_data_manager({"role": "manager"}))["role"], "manager")
    with self.assertRaises(HTTPException) as context:
        asyncio.run(auth.require_data_manager({"role": "evaluator"}))
    self.assertEqual(context.exception.status_code, 403)
    self.assertEqual(context.exception.detail, "当前用户没有权限，请联系管理员")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_role_permissions -v`

Expected: FAIL because `require_data_manager` and role update behavior do not exist and export routes still use weaker dependencies.

- [ ] **Step 3: Implement the shared permission dependency and explicit registration role**

Add to `app_core/auth.py`:

```python
DATA_MANAGER_ROLES = {"admin", "manager"}

async def require_data_manager(user: dict = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if user["role"] not in DATA_MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="当前用户没有权限，请联系管理员")
    return user
```

Change registration insert columns and values to include `role="evaluator"`. In `main.py`, use `require_data_manager` for `/api/upload_dataset`, `/api/upload`, `/api/upload_ref`, `GET /api/export`, `GET /api/export_options`, `POST /api/export/preview`, and `POST /api/export`.

- [ ] **Step 4: Add failing role-change and last-admin tests**

Cover valid changes, invalid roles, self-role changes, demoting the last active admin, disabling the last active admin, and operation-log creation. Assert rejected operations leave the database unchanged.

```python
def test_admin_cannot_change_own_role(self):
    with self.assertRaises(AppError):
        admin_service.update_user_role(self.admin_id, "manager", self.admin_id)

def test_last_active_admin_cannot_be_disabled(self):
    with self.assertRaises(AppError):
        admin_service.update_user_status(self.admin_id, 0, self.other_admin_id)
```

- [ ] **Step 5: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_role_permissions.RoleMutationTests -v`

Expected: FAIL because role updates and last-admin protection are absent.

- [ ] **Step 6: Implement minimal role mutation rules and route**

Add a transaction-based `update_user_role`, validate against `{"admin", "manager", "evaluator"}`, reject `user_id == admin_id`, and count active admins before demotion. Extend `update_user_status` to reject disabling the last active admin. Add:

```python
@app.put("/api/admin/users/{user_id}/role")
def update_user_role(user_id: int, role: str, admin: dict = Depends(require_admin)):
    return update_user_role_service(user_id, role, admin["id"])
```

- [ ] **Step 7: Run authorization tests and commit**

Run: `python -m unittest tests.test_role_permissions -v`

Expected: all tests PASS.

```bash
git add app_core/auth.py app_core/user_service.py app_core/admin_service.py main.py tests/test_role_permissions.py
git commit -m "feat: enforce three-level role permissions"
```

### Task 2: Admin Role Controls

**Files:**
- Modify: `templates/admin.html`
- Create: `tests/test_admin_role_ui.py`

**Interfaces:**
- Consumes: `PUT /api/admin/users/{user_id}/role?role=<role>`
- Produces: `updateUserRole(userId, role)` browser function

- [ ] **Step 1: Write failing admin UI contract tests**

Test that the page renders a select with all three exact values, labels roles as 超级管理员/管理员/评测员, calls the role endpoint, restores the user list after success, and displays the server error after failure.

```python
def test_role_selector_contains_all_three_roles(self):
    for value in ('value="admin"', 'value="manager"', 'value="evaluator"'):
        self.assertIn(value, self.html)
```

- [ ] **Step 2: Run the UI test and verify RED**

Run: `python -m unittest tests.test_admin_role_ui -v`

Expected: FAIL because the admin page only renders role badges.

- [ ] **Step 3: Implement the role selector**

Render a `<select>` in the role column with the current value selected and `onchange="updateUserRole(...)"`. Implement the fetch call, parse JSON errors, alert the returned `detail`, and call `loadUsers()` after both success and failure so rejected changes restore the displayed role.

- [ ] **Step 4: Run UI and permission tests and commit**

Run: `python -m unittest tests.test_admin_role_ui tests.test_role_permissions -v`

Expected: all tests PASS.

```bash
git add templates/admin.html tests/test_admin_role_ui.py
git commit -m "feat: manage user roles in admin console"
```

### Task 3: Upload and Export Feedback

**Files:**
- Modify: `templates/dashboard.html`
- Create: `tests/test_dashboard_permission_feedback.py`

**Interfaces:**
- Consumes: FastAPI JSON errors shaped as `{ "detail": string }`
- Produces: `setUploadMessage(message, status)` and `setExportMessage(message, status)`

- [ ] **Step 1: Write failing feedback contract tests**

Assert success/error CSS classes exist, upload handlers mark successful messages green and all caught errors red, new requests clear semantic state, and export option/preview/download failures render the server `detail` through the red error class.

```python
def test_upload_feedback_has_success_and_error_states(self):
    self.assertIn(".status-success", self.html)
    self.assertIn(".status-error", self.html)
    self.assertIn('setUploadMessage(data.message || "上传成功", "success")', self.html)
```

- [ ] **Step 2: Run the feedback tests and verify RED**

Run: `python -m unittest tests.test_dashboard_permission_feedback -v`

Expected: FAIL because upload feedback currently changes only text and export errors are not consistently styled.

- [ ] **Step 3: Implement semantic status helpers and normalized API errors**

Add CSS:

```css
.status-success { color: var(--success) !important; }
.status-error { color: var(--danger) !important; }
```

Add helpers that remove both classes before setting one. Ensure the shared `api` function extracts FastAPI `detail` on non-OK responses. Route every upload completion/catch and export option/preview/download catch through the helpers. Do not hide controls.

- [ ] **Step 4: Run dashboard UI tests and commit**

Run: `python -m unittest tests.test_dashboard_permission_feedback tests.test_dashboard_export_ui tests.test_dashboard_model_hierarchy_ui -v`

Expected: all tests PASS.

```bash
git add templates/dashboard.html tests/test_dashboard_permission_feedback.py
git commit -m "fix: color upload and export status feedback"
```

### Task 4: First-Empty-Dimension Keyboard Shortcuts

**Files:**
- Modify: `templates/index.html`
- Create: `tests/test_evaluation_shortcuts_ui.py`

**Interfaces:**
- Produces: `firstUnselectedDimension(dims) -> dimension | null`
- Consumes: existing radio ids `opt-<dimension>-left|tie|right`

- [ ] **Step 1: Write failing JavaScript behavior tests**

Extract the helper and shortcut handler in a Node VM test fixture. Simulate dimensions where the first is selected and the second is blank, then assert `1/2/3` clicks only the second dimension. Simulate all dimensions selected and assert no radio is clicked or overwritten.

```python
def test_shortcut_uses_first_unselected_dimension(self):
    result = self.run_shortcut(selected={"overall": "left"}, key="2")
    self.assertEqual(result["clicked"], "opt-aesthetic-tie")
```

- [ ] **Step 2: Run the shortcut tests and verify RED**

Run: `python -m unittest tests.test_evaluation_shortcuts_ui -v`

Expected: FAIL because shortcut targeting uses `currentDimIndex` rather than current selections.

- [ ] **Step 3: Implement first-empty selection**

Add:

```javascript
function firstUnselectedDimension(dims) {
    return dims.find(dim => !document.querySelector(`input[name="${dim.key}"]:checked`)) || null;
}
```

For keys `1`, `2`, and `3`, compute the helper result at keydown time, map the key to `left`, `tie`, or `right`, and click only when a blank dimension exists. Remove `currentDimIndex` reads and increments from shortcut handling while leaving Enter unchanged.

- [ ] **Step 4: Run shortcut and existing evaluation tests and commit**

Run: `python -m unittest tests.test_evaluation_shortcuts_ui tests.test_evaluation_preview_ui tests.test_task_mode_integrity -v`

Expected: all tests PASS.

```bash
git add templates/index.html tests/test_evaluation_shortcuts_ui.py
git commit -m "fix: keep evaluation shortcuts on first blank dimension"
```

### Task 5: Full Regression Verification

**Files:**
- Modify: `README.md`
- Test: all files under `tests/`

**Interfaces:**
- Documents: role matrix and permission-denied behavior

- [ ] **Step 1: Update user and API documentation**

Document the three role names, role matrix, default evaluator registration, admin self/last-admin safeguards, and upload/export authorization requirements in `README.md`.

- [ ] **Step 2: Run syntax and diff checks**

Run: `python -m compileall app_core main.py tests && git diff --check`

Expected: exit code 0 with no syntax or whitespace errors.

- [ ] **Step 3: Run the full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS with zero failures and errors.

- [ ] **Step 4: Review the requirement checklist and commit docs**

Confirm every global constraint has a corresponding passing test and inspect `git diff --stat` for unrelated changes.

```bash
git add README.md
git commit -m "docs: describe role permissions"
```
