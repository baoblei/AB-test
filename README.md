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
  - 导出 JSON / CSV
  - 旧版 `results/<version>/<scene>` 数据迁移到 `results/T2I/<version>/<scene>`

## 页面说明

- `/`：评测终端
- `/login`：登录页
- `/dashboard`：统计看板
- `/profile`：个人中心
- `/admin`：管理后台

## 目录结构

当前推荐目录结构如下：

```text
ab_test/
├── main.py
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
- 人像：人脸扭曲、肢体畸变
- 语义问题：语义丢失、对象错误
- 文本错误：文字乱码、文字缺失、额外文字
- 安全违规：涉黄、暴力、侵权风险

### TI2I 坏例标签

- 美学缺陷：乱码、色彩异常、明显噪点、网格伪影、模糊失焦
- 结构畸变：物体粘连、透视问题、空间扭曲
- 人像：人脸扭曲、肢体畸变
- 语义问题：语义丢失、对象错误
- 文本错误：文字乱码、文字缺失、额外文字
- 保真：过度编辑、属性污染、保真度差
- 安全违规：涉黄、暴力、侵权风险

## 安装与启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

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

### 管理员流程

1. 登录管理员账号
2. 打开看板页查看整体对战结果
3. 如需新增结果数据，在看板页上传 zip 数据包
4. 如为 `TI2I` 任务，可额外上传参考图 zip
5. 在管理后台查看用户、活跃情况和操作日志

## 上传规则

### 上传模型结果

接口对应功能：

- 看板页上传模型结果
- 后端接口：`POST /api/upload`

表单字段：

- `task_type`：`T2I` 或 `TI2I`
- `version`：模型版本名
- `scene`：场景名
- `file`：zip 文件

压缩包建议直接包含图片文件，不要再多包一层无关目录。  
系统会在解压后自动尝试剥离单层嵌套目录。

### 上传参考图

接口对应功能：

- 看板页上传参考图
- 后端接口：`POST /api/upload_ref`

表单字段：

- `task_type`
- `scene`
- `file`

当前主要用于 `TI2I`。

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

数据库初始化和字段补齐逻辑在 [main.py](/Users/baobinglei/code/ab_test/main.py) 的 `init_db()` 中完成，旧表结构会自动做兼容迁移。

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
- `GET /api/export`
- `GET /api/ranking`

### 管理后台

- `GET /api/admin/users`
- `PUT /api/admin/users/{user_id}`
- `GET /api/admin/stats`
- `GET /api/admin/logs`

### 数据上传

- `POST /api/upload`
- `POST /api/upload_ref`

## 已知约束

- `prompt` 和 `ref_images` 的匹配依赖文件名一致
- 评测任务按 `(task_type, v_a, v_b, scene, filename, worker)` 唯一分配
- `overall` 为后端根据各评测维度自动推导，不需要前端单独提交
- 当前认证依赖 `bcrypt`，部署环境需要正确安装对应依赖

## 开发建议

- 新增任务类型时，优先在 [main.py](/Users/baobinglei/code/ab_test/main.py) 的 `TASK_CONFIGS` 中扩展
- 新增坏例标签时，需要同步更新前端展示和看板筛选
- 若调整目录规范，优先保证 `results`、`prompt`、`ref_images` 三套路径的一致性

