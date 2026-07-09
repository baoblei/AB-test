import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app_core.admin_service import admin_logs as admin_logs_service
from app_core.admin_service import admin_stats as admin_stats_service
from app_core.admin_service import get_users as get_users_service
from app_core.admin_service import update_user_status as update_user_status_service
from app_core.auth import require_admin, require_login
from app_core.config import REF_IMAGE_DIR, RESULT_DIR, TASK_CONFIGS, dim_payload, ensure_data_dirs, get_task_config, normalize_task_type
from app_core.dashboard_service import bad_case_details as bad_case_details_service
from app_core.dashboard_service import dashboard_overview as dashboard_overview_service
from app_core.dashboard_service import detail_results as detail_results_service
from app_core.dashboard_service import export_results
from app_core.dashboard_service import ranking as ranking_service
from app_core.dashboard_service import worker_stats as worker_stats_service
from app_core.database import init_db, reset_working_tasks
from app_core.errors import AppError
from app_core.schemas import PasswordChange, UserLogin, UserRegister, VoteSubmit
from app_core.storage import compare_scene_resolution_stats, get_common_scenes, get_prompt_text, get_ref_root, get_result_root, get_versions_for_type, save_uploaded_zip
from app_core.task_service import get_eval_mode_status as get_eval_mode_status_service
from app_core.task_service import get_next_task, get_progress as get_progress_service
from app_core.task_service import skip_task as skip_task_service
from app_core.task_service import start_eval_session as start_eval_session_service
from app_core.task_service import submit_vote as submit_vote_service
from app_core.user_service import change_user_password, get_my_history as get_my_history_service
from app_core.user_service import get_my_stats as get_my_stats_service
from app_core.user_service import get_user_profile, login_user, register_user


app = FastAPI(title="MLLM Multi-Dim Eval Professional")
ensure_data_dirs()
app.mount("/images", StaticFiles(directory=RESULT_DIR), name="images")
app.mount("/ref-images", StaticFiles(directory=REF_IMAGE_DIR), name="ref_images")

TEMPLATE_DIR = Path("templates")


def render_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.on_event("startup")
def startup():
    init_db()
    reset_working_tasks()


@app.post("/api/auth/register")
def register(user: UserRegister, request: Request):
    return register_user(user, request.client.host if request.client else "")


@app.post("/api/auth/login")
def login(user: UserLogin, request: Request):
    login_result = login_user(user, request.client.host if request.client else "")
    access_token = login_result.pop("access_token")
    response = JSONResponse(login_result)
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=86400)
    return response


@app.post("/api/auth/logout")
def logout(user: dict = Depends(require_login)):
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(key="access_token")
    return response


@app.get("/api/auth/me")
def get_me(user: dict = Depends(require_login)):
    return get_user_profile(user["id"])


@app.put("/api/auth/password")
def change_password(data: PasswordChange, user: dict = Depends(require_login)):
    return change_user_password(data, user["id"])


@app.get("/api/task_types")
def get_task_types():
    return [
        {
            "key": key,
            "label": key,
            "show_ref": config["show_ref"],
            "dims": config["eval_dims"],
        }
        for key, config in TASK_CONFIGS.items()
    ]


@app.get("/api/task_config")
def api_task_config(task_type: str):
    task_type = normalize_task_type(task_type)
    config = get_task_config(task_type)
    return {
        "task_type": task_type,
        "show_ref": config["show_ref"],
        "eval_dims": dim_payload(config["eval_dims"]),
        "dashboard_dims": dim_payload(config["dashboard_dims"]),
        "bad_case_options": config["bad_case_options"],
    }


@app.get("/api/versions")
def get_versions(task_type: str):
    return get_versions_for_type(normalize_task_type(task_type))


@app.get("/api/scenes")
def get_scenes(task_type: str, v1: str, v2: str):
    return get_common_scenes(normalize_task_type(task_type), v1, v2)


@app.get("/api/scene_resolution_stats")
def scene_resolution_stats(task_type: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    return compare_scene_resolution_stats(normalize_task_type(task_type), v1, v2, scene)


@app.get("/api/eval_mode_status")
def get_eval_mode_status(task_type: str, worker: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    return get_eval_mode_status_service(task_type, worker, v1, v2, scene)


@app.post("/api/start_eval_session")
def start_eval_session(
    task_type: str,
    worker: str,
    v1: str,
    v2: str,
    scene: str,
    eval_mode: str = "full",
    overwrite_overall: bool = False,
    user: dict = Depends(require_login),
):
    return start_eval_session_service(task_type, worker, v1, v2, scene, eval_mode, user["id"], overwrite_overall)


@app.get("/api/get_prompt")
def get_prompt(task_type: str, scene: str, filename: str):
    return get_prompt_text(normalize_task_type(task_type), scene, filename)


@app.get("/api/get_task")
def get_task(task_type: str, worker: str, v1: str, v2: str, scene: str, user: dict = Depends(require_login)):
    return get_next_task(task_type, worker, v1, v2, scene, user["id"])


@app.get("/api/progress")
def get_progress(task_type: str, worker: str, v1: str, v2: str, scene: str, eval_mode: str = "full", user: dict = Depends(require_login)):
    return get_progress_service(task_type, worker, v1, v2, scene, eval_mode)


@app.post("/api/submit")
def submit_vote(vote: VoteSubmit, user: dict = Depends(require_login)):
    return submit_vote_service(vote, user["id"])


@app.post("/api/skip_task")
def skip_task(task_id: int, task_type: str, eval_mode: str = "full", user: dict = Depends(require_login)):
    return skip_task_service(task_id, task_type, user["id"], eval_mode)


@app.get("/api/my_history")
def get_my_history(user: dict = Depends(require_login)):
    return get_my_history_service(user["id"])


@app.get("/api/my_stats")
def get_my_stats(user: dict = Depends(require_login)):
    return get_my_stats_service(user["id"])


@app.get("/api/dashboard_overview")
def dashboard_overview(task_type: str):
    return dashboard_overview_service(task_type)


@app.get("/api/worker_stats")
def worker_stats(task_type: str, v1: str, v2: str, scene: Optional[str] = None):
    return worker_stats_service(task_type, v1, v2, scene)


@app.get("/api/detail_results")
def detail_results(task_type: str, v1: str, v2: str, scene: str):
    return detail_results_service(task_type, v1, v2, scene)


@app.get("/api/bad_case_details")
def bad_case_details(
    task_type: str,
    v1: str,
    v2: str,
    scene: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
):
    return bad_case_details_service(task_type, v1, v2, scene, model, category, tag)


@app.get("/api/export")
def export_data(format: str = "json", task_type: str = "T2I", v1: Optional[str] = None, v2: Optional[str] = None, scene: Optional[str] = None):
    return export_results(format, task_type, v1, v2, scene)


@app.get("/api/ranking")
def ranking(task_type: str = "T2I", scene: Optional[str] = None, dimension: str = "overall"):
    return ranking_service(task_type, scene, dimension)


@app.get("/api/admin/users")
def get_users(admin: dict = Depends(require_admin)):
    return get_users_service()


@app.put("/api/admin/users/{user_id}")
def update_user_status(user_id: int, is_active: int, admin: dict = Depends(require_admin)):
    return update_user_status_service(user_id, is_active, admin["id"])


@app.get("/api/admin/stats")
def admin_stats(admin: dict = Depends(require_admin)):
    return admin_stats_service()


@app.get("/api/admin/logs")
def admin_logs(limit: int = 100, admin: dict = Depends(require_admin)):
    return admin_logs_service(limit)


@app.post("/api/upload")
async def upload_data(task_type: str = Form(...), version: str = Form(...), scene: str = Form(...), file: UploadFile = File(...)):
    task_type = normalize_task_type(task_type)
    save_uploaded_zip(os.path.join(get_result_root(task_type), version, scene), file)
    return {"message": "Success"}


@app.post("/api/upload_ref")
async def upload_ref(task_type: str = Form(...), scene: str = Form(...), file: UploadFile = File(...)):
    task_type = normalize_task_type(task_type)
    save_uploaded_zip(os.path.join(get_ref_root(task_type), scene), file)
    return {"message": "Success"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return render_template("index.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return render_template("login.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return render_template("dashboard.html")


@app.get("/profile", response_class=HTMLResponse)
async def profile():
    return render_template("profile.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return render_template("admin.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
