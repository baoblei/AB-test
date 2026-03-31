# MLLM A/B Testing Platform

多模态大语言模型（MLLM）多维度盲测评测系统。支持多版本模型对比、多人独立评测、多维度评分与可视化统计看板。

## ✨ 特性

- **A/B 盲测**：两版本模型左右随机排列，消除位置偏好
- **多维度评分**：整体体验、美学质量、逻辑合理性、指令一致性四个维度
- **多人独立评测**：不同评测人可独立完成相同场景的测试，互不干扰
- **按评测人统计**：支持查看每个评测人各维度的 A/B 胜率分布
- **可视化看板**：维度胜率条形图、全员汇总、case-by-case 明细
- **数据包管理**：通过 zip 包上传模型输出结果，自动解压建立索引

## 📁 项目结构

```
ab_test/
├── main.py                 # FastAPI 后端服务
├── templates/
│   ├── index.html          # 盲测评测终端页面
│   └── dashboard.html      # 统计看板页面
├── results/                # 模型输出图片（按版本/场景组织）
│   └── {version}/{scene}/  # 如 results/A/open/scene1.jpg
├── prompt/                 # 评测 prompt 文件（每场景一个 .txt）
│   └── open.txt            # 格式: {image_id}\t{prompt_text}
├── database.db             # SQLite 数据库（自动生成）
├── requirements.txt
└── README.md
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备数据

将模型输出图片按以下目录结构放置：

```
results/
├── ModelA/
│   ├── scene1/
│   │   ├── img001.png
│   │   └── img002.png
│   └── scene2/
│       ├── img001.png
│       └── img002.png
└── ModelB/
    ├── scene1/
    │   ├── img001.png
    │   └── img002.png
    └── scene2/
        ├── img001.png
        └── img002.png
```

或在看板页面通过上传 zip 包自动部署（zip 内结构与上述一致）。

### 3. 配置 Prompt（可选）

在 `prompt/` 目录下为每个场景创建一个 `.txt` 文件，格式为：

```
{image_id_without_extension}\t{对应的 prompt 文本}
```

评测时会自动匹配显示。

### 4. 启动服务

```bash
python main.py
```

服务启动后访问：

- **盲测终端**：http://localhost:8000
- **统计看板**：http://localhost:8000/dashboard

## 📊 使用流程

### 评测员

1. 在盲测终端输入姓名、选择两个模型版本和评测场景
2. 系统逐张展示左右对比图片 + prompt
3. 对四个维度分别打分（A 更好 / 平局 / B 更好）
4. 提交后自动加载下一组，直到完成该场景所有图片

### 管理员

1. 在看板页面上传新版本数据包（zip）
2. 查看多维度对战总览（A/B 胜率分布）
3. 点击「明细」查看逐条评分记录
4. 点击「👤 统计」按评测人分组查看各人评分偏好

## 🔧 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/versions` | GET | 获取所有模型版本列表 |
| `/api/scenes?v1=&v2=` | GET | 获取两个版本共有的场景列表 |
| `/api/get_task?worker=&v1=&v2=&scene=` | GET | 获取评测任务（自动断点续评） |
| `/api/submit` | POST | 提交评分结果 |
| `/api/dashboard_v2` | GET | 多维度汇总统计 |
| `/api/worker_stats?v1=&v2=&scene=` | GET | 按评测人分组统计 |
| `/api/detail_results?v1=&v2=&scene=` | GET | 逐条明细结果 |
| `/api/upload` | POST | 上传模型输出 zip 包 |

## 🗄️ 数据库

使用 SQLite，包含两张表：

- **pair_tasks**：评测任务分配表，唯一约束 `(v_a, v_b, scene, filename, worker)`，支持多人独立评测
- **results_log**：评分结果表，记录每个维度判定、评测人和时间戳

首次启动时自动创建，如遇旧 schema 会自动迁移。

## 📋 技术栈

- **后端**：Python + FastAPI + SQLite
- **前端**：原生 HTML/CSS/JS（无框架依赖）
- **部署**：uvicorn 内置服务器

<!-- nohup uvicorn main:app --host 0.0.0.0 --port 8000 > 111.log 2>&1 -->
