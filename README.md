# AI Paper Coach

<p align="center">
  <strong>读论文更快，理解更深，复现更稳。</strong>
</p>

<p align="center">
  <img alt="status" src="https://img.shields.io/badge/status-MVP-2B7FFF">
  <img alt="frontend" src="https://img.shields.io/badge/frontend-Vue%203-42B883">
  <img alt="backend" src="https://img.shields.io/badge/backend-FastAPI-009688">
  <img alt="pdf" src="https://img.shields.io/badge/PDF-pdf.js-EA4335">
  <img alt="runtime" src="https://img.shields.io/badge/runtime-Python%20%2B%20Node-3776AB">
</p>

<p align="center">
  <a href="#zh-cn">简体中文</a> | <a href="#english">English</a>
</p>

---

<a id="zh-cn"></a>
## 简体中文

### 项目简介
AI Paper Coach 是一个面向学生和研究者的论文阅读与复现助手。  
输入 arXiv/PDF 链接或直接上传 PDF，就能自动生成结构化报告，并支持后续问答与历史追踪。

### 为什么值得用
- 一条流完成：`导入 -> 分析 -> 审阅 -> 整理 -> 报告`
- 七问结构化输出：更适合课堂汇报、组会复述、复现实验
- 原文阅读联动：报告和 PDF 原文可对照查看
- 可追踪可回放：保留 trace、历史记录、已保存报告
- 支持删除管理：历史记录和已保存报告都可删除
- 新增 API 连通性验证：一键检查后端是否可达

### 最新界面截图
> 以下图片来自 `caogao/`

#### 整体界面
![整体](./caogao/整体.png)

#### 论文原文阅读区
![论文原文](./caogao/论文原文.png)

#### 摘要面板
![摘要](./caogao/摘要.png)

#### 复现指导
![复现指导](./caogao/复现指导.png)

#### 历史记录
![历史记录](./caogao/历史记录.png)

### 核心功能
- 论文导入：URL / 本地 PDF
- 双模型协作：支持模型校验与配置保存
- 七问阅读框架：横向切换，间距紧凑
- 结果管理：历史记录、已保存报告、删除功能
- 导出能力：Markdown 报告导出
- 诊断信息：运行日志 + trace 记录

### 项目结构
```text
ai-paper-coach/
|- apps/web/          # Vue 3 + Vite 前端
|- services/api/      # FastAPI 后端
|- data/              # 本地数据（报告/历史/缓存）
|- caogao/            # README 截图素材
|- docs/
|- run.py             # 一键启动前后端
`- README.md
```

### 快速开始
#### 1) 安装后端依赖
```bash
cd services/api
pip install -r requirements.txt
```

#### 2) 安装前端依赖
```bash
cd apps/web
npm install
```

#### 3) 配置环境变量
```bash
cp .env.example .env
```
按需填写模型配置；不填也可在 MVP 模式下运行部分流程。

#### 4) 一键启动
```bash
python run.py
```

### 手动启动（可选）
后端：
```bash
cd services/api
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：
```bash
cd apps/web
npm run dev -- --host 127.0.0.1 --port 5500
```

### 主要 API
- `GET /health`（API 连通性检查）
- `POST /validate-models`（模型接口校验）
- `POST /ingest`
- `POST /analyze`
- `POST /review`
- `POST /finalize`
- `GET /report/{paper_id}`
- `GET /export/{paper_id}.md`
- `GET /trace/{paper_id}`
- `GET /history` / `DELETE /history/{record_id}`
- `GET /saved` / `DELETE /saved/{record_id}`

### 适用场景
- 上课/组会前 10 分钟快速吃透论文
- 形成复现实验 TODO 清单
- 比较不同模型配置下的输出质量
- 长期积累论文阅读档案

---

<a id="english"></a>
## English

### Overview
AI Paper Coach helps students and researchers read papers faster and reproduce results with more confidence.
You can ingest a paper from URL/PDF, generate structured reports, and continue with Q&A and traceable history.

### Highlights
- End-to-end pipeline: `ingest -> analyze -> review -> finalize -> report`
- Structured 7-question reading framework
- Side-by-side report + original PDF reading
- History and saved reports with deletion support
- One-click API connectivity check (`/health`)

### Quick Start
```bash
# backend
cd services/api
pip install -r requirements.txt

# frontend
cd apps/web
npm install

# run all
python run.py
```

### Key APIs
- `GET /health`
- `POST /validate-models`
- `POST /ingest`
- `POST /analyze`
- `POST /review`
- `POST /finalize`
- `GET /report/{paper_id}`
- `GET /export/{paper_id}.md`
- `GET /trace/{paper_id}`

---

### Contributing
Issues and PRs are welcome.
Please include:
- clear problem statement
- reproducible steps
- expected vs. actual behavior

