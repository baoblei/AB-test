# MLLM A/B 盲测评测平台

一个面向图像生成模型对比评测的 Web 平台，支持 `T2I` 和 `TI2I` 两类任务，提供盲测评测终端、坏例标注、统计看板、个人中心、管理后台，以及结果数据上传与导出能力。

当前实现基于：

- 后端：FastAPI + SQLite
- 前端：原生 HTML / CSS / JavaScript
- 认证：JWT Cookie + bcrypt

## 功能概览

- 支持两类任务：
  - `T2I`：文生图
  - `TI2I`：图像编辑
- 盲测评测：
  - 左右候选图随机展示
  - `TI2I` 额外展示参考图
  - 支持逐张评测、跳过、断点续评
  - 支持只进行整体评价的快速评测模式
- 多维度评测：
  - `T2I`：美学、合理性、一致性
  - `TI2I`：美学、合理性、一致性、保真度
- 严重坏例记录：
  - 按类别展开具体标签
  - 支持一张图多标签记录
- 看板统计：
  - A/B 对战总览
  - 按场景拆分
  - 按评测人统计
  - 坏例占比与坏例详情筛选
  - 明细预览与对比查看
- 用户与管理：
  - 注册、登录、退出
  - 个人历史记录与个人统计
  - 管理后台查看用户、统计和操作日志
- 数据管理：
  - 上传模型结果 zip
  - 上传编辑任务参考图 zip
  - 看板按筛选导出 Excel 或图片归档 ZIP
  - 保留 JSON / CSV 旧版导出接口
  - 旧版 `results/<version>/<scene>` 数据迁移到 `results/T2I/<version>/<scene>`

## 页面说明

- `/`：评测终端
- `/login`：登录页
- `/dashboard`：统计看板
- `/profile`：个人中心
- `/admin`：管理后台

### 图片预览工具

评测页和高清预览支持默认同步的 Ref/A/B 缩放与平移、适应窗口/宽度/高度、1:1、局部放大镜、背景切换和复位。滚轮或触屏双指缩放，拖动平移，空格可临时进入平移模式，`+`/`-` 调整缩放，`Esc` 关闭高清预览；工具栏可折叠，并内置快捷键帮助。

## 目录结构

当前推荐目录结构如下：

```text
ab_test/
├── main.py
├── app_core/
│   ├── config.py
│   ├── database.py
│   ├── auth.py
│   ├── schemas.py
│   ├── storage.py
│   ├── bad_cases.py
│   ├── task_service.py
│   ├── dashboard_service.py
│   ├── export_service.py
│   ├── time_utils.py
│   ├── user_service.py
│   └── admin_service.py
├── database.db
├── requirements.txt
├── README.md
├── scripts/
│   └── migrate_legacy_results_to_t2i.py
├── templates/
│   ├── index.html
│   ├── dashboard.html
│   ├── login.html
│   ├── profile.html
│   └── admin.html
├── results/
│   ├── T2I/
│   │   └── <version>/<scene>/<image>
│   └── TI2I/
│       └── <version>/<scene>/<image>
├── prompt/
│   ├── T2I/
│   │   └── <scene>.txt
│   └── TI2I/
│       └── <scene>.txt
└── ref_images/
    ├── T2I/
    │   └── <scene>/<image>
    └── TI2I/
        └── <scene>/<image>
```

说明：

- `results/T2I` 保存文生图模型输出
- `results/TI2I` 保存编辑模型输出
- `prompt/T2I`、`prompt/TI2I` 分别保存对应任务的 prompt
- `ref_images/TI2I` 保存编辑任务参考图
- `ref_images/T2I` 当前不是必须目录，但系统已预留
- `main.py` 只保留 FastAPI 应用、路由和页面入口
- `app_core/config.py` 维护任务类型、评测维度和坏例标签
- `app_core/database.py` 负责 SQLite 连接、初始化和 schema 兼容迁移
- `app_core/*_service.py` 承载认证、任务、看板、用户和管理后台业务逻辑
- `app_core/export_service.py` 负责导出记录筛选、XLSX 构建、ZIP 打包和图片归档
- `app_core/time_utils.py` 负责北京时间业务时间格式化、校验，以及历史 UTC 时间迁移的转换

## 数据组织规范

### 1. T2I 结果目录

```text
results/T2I/
├── A/
│   └── open/
│       ├── scene1.jpg
│       └── scene2.jpg
└── B/
    └── open/
        ├── scene1.jpg
        └── scene2.jpg
```

### 2. TI2I 结果目录

```text
results/TI2I/
├── D/
│   └── open/
│       ├── scene1.jpg
│       └── scene2.jpg
└── E/
    └── open/
        ├── scene1.jpg
        └── scene2.jpg
```

### 3. Prompt 文件

Prompt 文件按场景存储，一个场景一个 `.txt` 文件。

示例：

```text
prompt/T2I/open.txt
prompt/TI2I/open.txt
```

文件内容格式：

```text
scene1    这里是 scene1 对应的 prompt
scene2    这里是 scene2 对应的 prompt
```

要求：

- 第一列为图片文件名去掉扩展名后的 key
- 第二列为 prompt 文本
- 使用制表符 `\t` 分隔

例如图片是 `scene1.jpg`，系统会用 `scene1` 去匹配 prompt。

### 4. TI2I 参考图目录

```text
ref_images/TI2I/
└── open/
    ├── scene1.jpg
    └── scene2.jpg
```

参考图文件名需要和结果图文件名一致，这样评测页和看板才能正确关联展示。

## 评测维度与坏例标签

### T2I 评测维度

- 美学
- 合理性
- 一致性

### TI2I 评测维度

- 美学
- 合理性
- 一致性
- 保真度

### T2I 坏例标签

- 美学缺陷：乱码、色彩异常、明显噪点、网格伪影、模糊失焦
- 结构畸变：物体粘连、透视问题、空间扭曲
- 人像肢体：人脸扭曲、肢体畸变
- 语义问题：关键对象缺失、关键对象错误
- 文本错误：文字乱码、文字缺失、额外文字
- 安全违规：涉黄、暴力、侵权风险

### TI2I 坏例标签

- 美学缺陷：乱码、色彩异常、明显噪点、网格伪影、模糊失焦
- 结构畸变：物体粘连、透视问题、空间扭曲
- 人像肢体：人脸扭曲、肢体畸变
- 语义问题：关键对象缺失、关键对象错误
- 文本错误：文字乱码、文字缺失、额外文字
- 保真：过度编辑、属性污染、保真度差
- 安全违规：涉黄、暴力、侵权风险

## 安装与启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

该命令会安装 Excel 导出所需的 `openpyxl`；不要只安装 Web 服务依赖后再单独运行导出。

### 2. 启动服务

```bash
python main.py
```

默认监听：

- `http://127.0.0.1:8000`
- `http://localhost:8000`

### 3. 默认管理员账号

系统首次启动会自动创建管理员账号：

- 用户名：`admin`
- 密码：`admin123`

建议首次登录后立即修改密码。

## 使用流程

### 评测员流程

1. 登录系统
2. 在评测页选择任务类型：`T2I` 或 `TI2I`
3. 选择需要对比的两个模型版本
4. 选择场景
5. 进入逐张盲测评测
6. 对各维度选择 `左图更好 / 平局 / 右图更好`
7. 如有严重坏例，为左右图分别标记坏例标签
8. 提交并进入下一张

整体快速评测规则：

- 初始化页勾选 `只进行整体评价` 后，每张图只展示 `整体` 一个维度。
- 已完成多维度评测的同一模型对和场景，不能再进行整体快速评测。
- 已完成整体快速评测的同一模型对和场景，可以切换回多维度评测；进入前系统会提示覆盖原整体评测结果。
- 看板中 `整体` 统计会包含整体快速评测结果，其他维度只统计多维度评测结果。

### 管理员流程

1. 登录管理员账号
2. 打开看板页查看整体对战结果
3. 如需新增场景，先上传测评集
4. 按已上传的场景下拉选择并上传模型结果图 zip
5. 在管理后台查看用户、活跃情况和操作日志

## 上传规则

### 上传新测评集

接口对应功能：

- 看板页 `发布新测试任务 / 上传新测评集`
- 后端接口：`POST /api/upload_dataset`

表单字段：

- `task_type`：`T2I` 或 `TI2I`
- `scene`：场景名
- `prompt_file`：prompt txt 文件
- `ref_file`：参考图 zip，仅 `TI2I` 必填

Prompt 格式：

```text
{image_id_without_extension}\t{prompt_text}
```

上传时会检查：

- 每行必须使用 tab 分隔图片名和 prompt
- 图片名不能带路径和扩展名
- 图片名不能重复
- `TI2I` 参考图 zip 中每个图片文件名去掉扩展名后，必须与 prompt 中的图片 ID 完全一致

### 上传/补传参考图

接口对应功能：

- 后端接口：`POST /api/upload_ref`
- 仅管理员可以调用

该接口使用 `multipart/form-data`，表单字段为：

- `task_type`：`T2I` 或 `TI2I`
- `scene`：场景名
- `file`：参考图 zip

该入口用于在已有场景中独立补传参考图；与 `POST /api/upload_dataset` 在上传 `TI2I` 测评集时通过 `ref_file` 一体上传参考图，是两种上传入口。

参考图 zip 会按目标 `task_type` 和 `scene` 的现有 prompt 校验：

- 文件必须为有效 zip，且至少包含一张系统支持的图片扩展名文件
- 隐藏文件、`__MACOSX` 条目和非图片扩展名文件会被忽略
- zip 内不能出现重复的图片文件名；目录路径不参与匹配，系统只使用文件基名
- 每个 prompt 图片 ID 必须且只能对应一张图片；去扩展名后的图片 ID 不得重复，例如 `scene1.jpg` 与 `scene1.png` 会被拒绝
- 每张图片文件名去掉扩展名后，必须与 prompt 中的图片 ID 完全一致，不能缺少或多出

上传成功后，该场景现有的参考图目录会被本次 zip 内容替换。

### 上传新结果图

接口对应功能：

- 看板页 `发布新测试任务 / 上传新结果图`
- 后端接口：`POST /api/upload`

表单字段：

- `task_type`：`T2I` 或 `TI2I`
- `version`：模型版本名
- `scene`：从已上传测评集场景中下拉选择
- `file`：结果图 zip
- `auto_rename`：是否允许按 prompt 图片名前缀自动格式化文件名

上传时会检查结果图 zip 的图片名：

- 图片名和 prompt 图片名完全一致时直接上传
- 图片名前缀能唯一匹配 prompt 图片名时，前端会弹窗提示可自动格式化名称
- 用户确认后，后端会按 prompt 图片名重命名并继续上传
- 无法匹配、缺图或多图对应同一 prompt 图片名时会阻止上传

## 统计看板能力

看板支持：

- 按任务类型切换 `T2I / TI2I`
- 查看模型对战汇总
- 按维度查看 A 胜 / 平局 / B 胜占比
- 同时显示百分比和具体数量
- 展示场景级拆分结果
- 查看评测明细
- 查看坏例明细
- 按坏例类别或具体标签筛选
- 在坏例明细中显示 prompt
- 查看按评测人拆分的统计
- 预览图片对比结果

预览逻辑：

- 对战明细：显示对比图
- 坏例明细：显示单图预览
- `TI2I` 明细中可带参考图一起查看

### 评测结果导出

在每个模型对总览标题栏点击“导出”，模型对和任务类型会固定为当前总览。弹窗提供以下筛选与选项：

- 场景、明细维度、评测人（均可多选）
- 开始和结束时间（北京时间）
- 评测模式：多维度评测、整体快速评测
- 判定结果：A 胜、平局、B 胜
- 坏例范围：全部、存在坏例、不存在坏例；“存在坏例”表示 A 或 B 至少一侧有坏例标签
- 导出图片、包含坏例字段、包含评测耗时

筛选变化会调用预览并显示 Overall、每个维度和去重图片的预计数量；没有 Overall 记录时不能下载。场景、评测人、时间、评测模式和坏例范围筛选评测记录；判定结果在 Overall 中按 `overall` 判定，在场景明细中按各维度独立判定。整体快速评测仅进入 Overall；场景明细只包含多维度评测且至少一个已选维度命中的记录。

每次导出固定生成 `Overall` 汇总 Sheet，其余 Sheet 按场景生成。场景明细使用两级横向表头：第一行合并显示样本信息、各评测维度、图片信息和坏例信息，第二行显示具体字段；每个维度分为“模型 A 胜 / 平局 / 模型 B 胜”三列，命中结果写入 `1`。`T2I` 可选美学、合理性、一致性 3 个维度，`TI2I` 还可选保真度。明细字段包括图片名、Prompt、评测人、评测时间（北京时间）、评测模式、A/B 图片路径和图片状态；启用相应选项后还包括坏例标签/类别和评测耗时。`TI2I` 明细额外包含参考图路径和状态。

- 不勾选“导出图片”时，下载 `.xlsx` 文件。
- 勾选“导出图片”时，下载 ZIP，内部结构严格为：

```text
评测结果.xlsx
images/<scene>/<model>/<filename>
images/<scene>/ref/<filename>  # 仅 TI2I
```

`TI2I` 打包图片时，`ref` 是参考图保留目录，模型版本名大小写无关不能为 `ref`；不勾选“导出图片”的纯 XLSX 导出不受此限制。

同一图片被多次评测时，每条评测仍保留在明细中，但 ZIP 中图片按场景和图片名去重。图片缺失不会中断导出，明细会标记 `文件不存在`，缺失文件不会写入 ZIP。

## 北京时间与升级迁移

升级到包含北京时间统一的版本前，先备份 `database.db`，再首次启动服务。`init_db()` 会在首次初始化时自动执行一次历史业务时间迁移：将旧的无时区 UTC 值 `YYYY-MM-DD HH:MM:SS` 加 8 小时并写为北京时间；迁移标记保证重复启动幂等，不会再次偏移。无法解析的异常时间会保留原值，并在启动时输出诊断信息。

业务时间统一使用秒级 canonical ISO 北京时间格式：

```text
YYYY-MM-DDTHH:MM:SS+08:00
```

该规则适用于评测结果、操作日志、用户创建和最后登录时间。页面和导出只格式化该业务时间显示，不进行额外时区转换。JWT 的过期时间继续使用 UTC/Unix 时间戳，不属于业务时间迁移范围。

评测耗时不会包含当前任务的接口和图片加载等待：当前任务的所有所需图片加载成功、加载失败或等待超时结算后，计时器才从 `00:00` 开始。评测范围始终使用登录用户名，不信任客户端传入的评测人名称。提交或跳过期间两个操作按钮会同时禁用，后端在单个事务中校验任务仍为当前用户持有的 `working` 状态；重复提交、提交/跳过竞态或篡改任务字段会返回 `409`，不会重复写入结果。

历史 NULL 或无法解析的异常时间不会阻塞无时间范围的导出，并会按原值/空值写入明细；设置任一导出时间边界时，这些非规范时间记录会被排除，导出选项中的最早/最晚时间也只统计规范北京时间。

## 数据库说明

系统使用 SQLite，数据库文件默认是：

```text
database.db
```

主要表：

- `users`：用户表
- `operation_logs`：操作日志
- `pair_tasks`：评测任务分发表
- `results_log`：评测结果表

数据库初始化、字段补齐和北京时间迁移逻辑在 [app_core/database.py](app_core/database.py) 的 `init_db()` 中完成，旧表结构会自动做兼容迁移。

## 旧数据迁移

如果你之前的数据还是旧结构：

```text
results/
├── A/open/...
├── B/open/...
└── C/open/...
```

可以使用迁移脚本移动到新结构：

```bash
python3 scripts/migrate_legacy_results_to_t2i.py --dry-run
python3 scripts/migrate_legacy_results_to_t2i.py
```

迁移规则：

- 只迁移 `results` 根目录下的旧版本目录
- 自动跳过 `results/T2I` 和 `results/TI2I`
- 如果目标目录已存在，不会覆盖

迁移后会变成：

```text
results/
└── T2I/
    ├── A/open/...
    ├── B/open/...
    └── C/open/...
```

## 主要接口

### 认证

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PUT /api/auth/password`

### 评测配置

- `GET /api/task_types`
- `GET /api/task_config?task_type=...`
- `GET /api/versions?task_type=...`
- `GET /api/scenes?task_type=...&v1=...&v2=...`
- `GET /api/get_prompt?task_type=...&scene=...&filename=...`

### 评测过程

- `GET /api/get_task`
- `GET /api/progress`
- `POST /api/submit`
- `POST /api/skip_task`

### 个人统计

- `GET /api/my_history`
- `GET /api/my_stats`

### 看板与导出

- `GET /api/dashboard_overview`
- `GET /api/worker_stats`
- `GET /api/detail_results`
- `GET /api/bad_case_details`
- `GET /api/export_options`：登录后获取当前任务类型和模型对的场景、评测人、维度与北京时间范围
- `POST /api/export/preview`：登录后按完整筛选返回 Overall、各维度和去重图片的预计数量
- `POST /api/export`：登录后按完整筛选下载 XLSX 或包含图片的 ZIP；导出语义校验错误返回 `422`
- `GET /api/export`：保留的旧 JSON / CSV 导出接口
- `GET /api/ranking`

### 管理后台

- `GET /api/admin/users`
- `PUT /api/admin/users/{user_id}`
- `GET /api/admin/stats`
- `GET /api/admin/logs`

### 数据上传

- `POST /api/upload_dataset`
- `POST /api/upload`
- `POST /api/upload_ref`

## 已知约束

- `prompt` 和 `ref_images` 的匹配依赖文件名一致
- 评测任务按 `(task_type, v_a, v_b, scene, filename, worker)` 唯一分配
- 多维度评测会由后端根据各维度结果推导 `overall`；整体快速评测由前端提交 `overall`，两种模式都会产生 Overall 评价
- 当前认证依赖 `bcrypt`，部署环境需要正确安装对应依赖

## 开发建议

- 新增任务类型时，优先在 [app_core/config.py](app_core/config.py) 的 `TASK_CONFIGS` 中扩展
- 新增坏例标签时，优先更新 [app_core/config.py](app_core/config.py)，前端会通过 `/api/task_config` 读取配置
- 若调整目录规范，优先在 [app_core/storage.py](app_core/storage.py) 中维护 `results`、`prompt`、`ref_images` 三套路径的一致性
