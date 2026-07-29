# RAG 完善计划

> 状态：Draft
> 更新时间：2026-07-29
> 目标：把当前“词面检索 + 调试界面”升级为可用于正式论文问答的、可评测、可追溯的混合 RAG。

## 0. 已确认的产品决策

- 产品名称：AI Paper Coach；
- 首发平台：Windows 11 x64；
- 发布范围：面向公众发布；
- 使用方式：普通用户默认使用桌面软件；
- Web 模式：保留给开发和远程部署；
- 模型接入：首版支持通义千问、MiniMax 和 OpenAI-compatible 自定义接口，由用户选择厂商并填写自己的 API Key；
- 云端处理：发送论文内容前明确提示，并由用户授权；
- 本地模式：第一版保证本地数据、历史记录和 lexical 检索可用，后续提供完整的“仅本地处理”模式；
- 数据迁移：首次启动将旧数据复制到系统用户数据目录，原目录保留为备份；
- 品牌资产：当前没有正式图标、发布者信息和签名证书，进入安装包阶段前补齐。

## 1. 当前基线

当前系统已经具备：

- PDF 按页提取与字符窗口切块；
- SQLite chunk 缓存；
- 词面重合 Top-K 检索；
- 中文问题到英文检索词的 LLM 翻译；
- 可选 LLM 回答、fallback 回答和引用列表；
- `/rag/query` API、LangSmith trace 和前端 RAG 调试页；
- 两个 RAG API 契约测试。

主要缺口：

- 没有 embedding、语义检索、混合召回和 reranker；
- 切块不理解章节、句子、表格和公式；
- 跨语言依赖查询翻译，失败后容易零召回；
- 回答中的引用编号没有程序化校验；
- 主聊天链路没有使用原文 RAG；
- 扫描 PDF 没有 OCR；
- 缺少检索质量、引用忠实度、跨语言和性能评测；
- chunk 缓存没有内容指纹和模型版本，无法可靠失效。

## 2. 已确定的技术方向

### 2.1 暂不引入独立向量数据库

第一阶段继续使用 SQLite。单篇论文通常只有数百到数千个 chunk，可以在应用层计算余弦相似度，避免过早引入 Qdrant、Milvus 或 pgvector。

当出现以下任一条件时，再迁移到独立向量存储：

- 单实例超过 10 万个 chunk；
- 需要跨论文库全局检索；
- 多用户并发检索成为主要负载；
- 应用层向量扫描 P95 超过 300 ms。

### 2.2 使用混合检索

目标排序公式：

```text
final_score =
  0.55 * semantic_score
  + 0.35 * lexical_score
  + 0.10 * structure_score
```

- `semantic_score`：多语言 embedding 余弦相似度；
- `lexical_score`：保留词面检索，后续可升级为 SQLite FTS5/BM25；
- `structure_score`：标题命中、同章节、页码邻近等结构信号；
- 各分数必须先归一化到 `[0, 1]`；
- 权重必须通过评测集调整，不能只凭主观决定。

### 2.3 Embedding 接口与默认降级

新增独立的 `EmbeddingProvider`，不要复用聊天生成逻辑。

建议配置：

```text
RAG_EMBEDDING_API_BASE
RAG_EMBEDDING_API_KEY
RAG_EMBEDDING_MODEL
RAG_EMBEDDING_DIMENSIONS
```

要求：

- 兼容 OpenAI-style embeddings API；
- 模型、维度和内容指纹写入索引元数据；
- embedding 不可用时降级为 lexical-only，并在响应 debug 中明确标记；
- 不允许静默把 semantic 模式伪装成成功；
- 中文问题优先直接用多语言 embedding，不再强制经过 LLM 翻译。

### 2.4 原文证据优先

证据来源优先级：

1. PDF 原文页；
2. 解析得到的原文章节；
3. OCR 结果；
4. 已生成报告只能作为补充上下文，不能伪装成原文引用。

来自报告的 chunk 必须标记：

```json
{
  "source_kind": "generated_report",
  "is_primary_evidence": false
}
```

## 3. 目标数据模型

为 `document_chunks` 增加或迁移以下字段：

```text
content_hash
document_hash
source_kind
heading_path_json
token_count
embedding_json / embedding_blob
embedding_model
embedding_dimensions
embedding_created_at
parser_version
chunker_version
```

索引有效性至少由以下组合决定：

```text
paper_id
+ document_hash
+ parser_version
+ chunker_version
+ embedding_model
+ embedding_dimensions
```

禁止只通过 `chunk_size + overlap + strategy` 判断缓存有效。

## 4. 分阶段实施

### Phase 0：建立评测基线

优先级：P0
预计工作量：1–2 天

- [x] 建立 `services/api/tests/fixtures/rag_eval/`；
- [ ] 准备至少 5 篇不同类型的论文样本；
- [ ] 每篇准备中文、英文、无答案问题；
- [ ] 至少包含双栏、表格、公式和扫描 PDF；
- [ ] 建立 40–60 条人工标注问题；
- [ ] 为每个问题标注正确页码、章节和可接受答案要点；
- [x] 编写离线评测命令，不依赖前端。

当前已加入 `synthetic-v1` 小型确定性基线，用于锁定旧检索器行为；它不能替代后续 5 篇真实论文、40–60 条问题的正式评测集。

首批指标：

| 指标 | 基线 | 首阶段目标 |
| --- | ---: | ---: |
| Recall@5 | 0.80（synthetic-v1） | ≥ 0.85 |
| MRR@5 | 0.80（synthetic-v1） | ≥ 0.70 |
| 无答案识别准确率 | 0.50（synthetic-v1） | ≥ 0.85 |
| 引用页码准确率 | 待测 | ≥ 0.90 |
| 跨语言 Recall@5 | 0.00（synthetic-v1） | ≥ 0.80 |
| 检索 P95（已索引） | 待测 | ≤ 500 ms |

验收标准：

- 同一评测命令可以比较旧检索器和新检索器；
- 每次检索逻辑变更都能得到可重复的指标；
- 评测失败必须输出具体问题、预期证据和实际 Top-K。

### Phase 1：重构检索接口与缓存

优先级：P0
预计工作量：2–3 天

- [ ] 将 `rag.py` 拆分为 `chunking.py`、`embedding.py`、`retrieval.py`、`grounding.py`；
- [ ] 定义 `Retriever` 和 `EmbeddingProvider` 协议；
- [ ] 为 chunk 增加来源、哈希、版本和结构字段；
- [ ] 增加数据库迁移，不破坏已有 SQLite 数据；
- [ ] ingest/parse 完成后建立索引，不再把首次查询作为主要索引时机；
- [ ] 加入索引状态：`pending/indexing/ready/failed/stale`；
- [ ] API 返回当前检索模式：`hybrid/semantic/lexical`。

验收标准：

- 原文件变化后旧索引自动失效；
- embedding 模型变化后自动重建向量；
- embedding 服务失败时 lexical 降级可观察；
- 不重复解析和索引未变化的论文。

### Phase 2：章节感知切块

优先级：P0
预计工作量：2–4 天

- [ ] 保留标题层级和页码范围；
- [ ] 优先按段落、句子边界切分；
- [ ] chunk 目标长度改为约 400–700 tokens；
- [ ] overlap 使用完整句子，不从字符中间截断；
- [ ] 标题作为 chunk 的结构字段，不反复污染正文；
- [ ] 合并过短段落；
- [ ] 标记参考文献、附录、表格说明和图注；
- [ ] 为表格和公式保留邻近解释文本。

验收标准：

- chunk 不从单词、句子中间断开；
- 每个原文 chunk 都能回溯到页码和 heading path；
- 相同输入产生稳定 chunk ID；
- chunker 单元测试覆盖空页、超长段落、多栏错序和跨页段落。

### Phase 3：混合召回与重排

优先级：P0
预计工作量：3–5 天

- [ ] 实现多语言 embedding；
- [ ] 实现 lexical + semantic 候选合并；
- [ ] 候选池先取 20–40 个，再重排到 Top-K；
- [ ] 增加最低相关性阈值；
- [ ] 去除高度重复 chunk；
- [ ] 对相邻页和同章节证据做适度扩展；
- [ ] debug 中分别输出 lexical、semantic、structure 和 final score；
- [ ] 用 Phase 0 评测集调权重。

第二阶段可选：

- cross-encoder reranker；
- LLM rerank，仅用于离线对比或低频高质量模式；
- 跨论文库检索。

验收标准：

- 常见停用词不能让无关 chunk 获得高分；
- 中文问题不依赖查询翻译也能召回英文证据；
- 无答案问题不会因为一个常见词被强行回答；
- 新方案的 Recall@5 和 MRR@5 均优于当前实现。

### Phase 4：可信回答与引用校验

优先级：P0
预计工作量：2–3 天

- [ ] 给每个上下文块分配不可伪造的 citation ID；
- [ ] 解析回答中的引用；
- [ ] 拒绝或修复不存在的引用编号；
- [ ] 检查关键句是否至少有一个引用；
- [ ] 明确区分原文证据与生成报告；
- [ ] 证据不足时返回结构化 `insufficient_evidence`；
- [ ] citations 返回稳定 chunk ID、页码、标题路径和原文；
- [ ] 前端点击引用可跳到 PDF 对应页。

推荐响应结构：

```json
{
  "answer": "...",
  "answer_mode": "grounded_llm",
  "evidence_status": "sufficient",
  "citations": [],
  "warnings": [],
  "debug": {}
}
```

验收标准：

- 回答不能引用未进入上下文的编号；
- 原文证据不足时不生成确定性结论；
- 每条 citation 都能定位到真实原文；
- 自动引用检查和人工评测结果都进入测试报告。

### Phase 5：接入正式聊天

优先级：P0
预计工作量：2–3 天

- [ ] `ReportChatRequest` 增加 `paper_id`；
- [ ] 每轮使用最新用户问题执行 RAG；
- [ ] 报告摘要作为辅助上下文，原文 chunk 作为事实证据；
- [ ] 流式回答结束后返回结构化 citations；
- [ ] 主聊天显示引用卡片和 PDF 跳转；
- [ ] “带入论文库”改为真实检索，不只传论文元数据；
- [ ] 保留独立 RAG 调试页用于观察召回。

验收标准：

- 主聊天和 `/rag/query` 使用同一 Retriever；
- 用户无需进入调试页也能获得原文引用；
- 流式和非流式回答具有一致的引用结果；
- 关闭论文上下文后不触发检索。

### Phase 6：OCR、性能和运维

优先级：P1
预计工作量：3–6 天

- [ ] 检测文本密度过低的扫描页；
- [ ] 为 OCR 定义可插拔 provider；
- [ ] OCR 结果保留页码、置信度和来源；
- [ ] 索引任务异步化并提供进度；
- [ ] 对 embedding 请求批处理；
- [ ] 增加超时、重试、限流和失败恢复；
- [ ] 记录索引耗时、检索耗时、生成耗时和降级次数；
- [ ] 增加大论文和并发性能测试。

验收标准：

- 扫描 PDF 能建立可检索索引；
- 索引失败不影响报告查看；
- 用户能看到索引状态和失败原因；
- 已索引查询不会重新解析整个 PDF。

## 5. 必须补齐的测试

### 单元测试

- tokenizer 与停用词；
- 章节感知 chunker；
- embedding 序列化和维度校验；
- 分数归一化与混合排序；
- 重复 chunk 去除；
- 引用编号解析与校验；
- 索引版本和失效判断。

### API 测试

- `use_llm=true`；
- embedding 成功、超时和失败降级；
- 中文问英文论文；
- 无答案问题；
- 无效引用修复；
- 扫描 PDF；
- 缓存命中、失效和重建；
- 流式聊天引用。

### 质量回归

- Recall@K；
- MRR；
- 无答案识别；
- 引用页码准确率；
- 回答忠实度；
- 跨语言召回；
- 延迟和成本。

## 6. 建议的第一批直接落地内容

后续直接在当前 `main` 分批修改和验证。第一批只做以下内容：

1. 增加 RAG 离线评测 fixture 和评测脚本；
2. 为当前 lexical retriever 建立基线指标；
3. 定义 `Retriever` 接口；
4. 将现有检索逻辑迁入 `LexicalRetriever`，保持 API 行为不变；
5. 补齐无答案、停用词误召回和中文问英文失败测试。

暂时不在第一批修改中加入 embedding、OCR 或前端改版。

这样可以先建立可比较的基线，再逐步替换检索器，避免一次大改后无法判断质量是否真的提升。

直接修改 `main` 时，每一批都必须满足：

- 开始前确认工作区状态，保留用户已有改动；
- 只修改当前阶段需要的文件，不夹带无关重构；
- 后端相关测试、前端构建和新增质量评测全部通过；
- 检查 `git diff`，确认没有生成物、密钥或运行数据进入版本控制；
- 当前批次验证完成后，再开始下一批。

## 7. 桌面软件打包

产品形态确定为：

```text
Tauri 2 桌面壳
  ├── Vue/Vite 前端（复用 apps/web）
  ├── FastAPI sidecar（复用 services/api）
  └── OS 用户数据目录
      ├── SQLite
      ├── uploads
      ├── indexes
      ├── cache
      └── logs
```

### 7.1 技术选择

- 桌面壳使用 Tauri 2；
- Vue 生产构建作为桌面静态资源；
- FastAPI 使用 PyInstaller 打包为 sidecar；
- 第一版使用 PyInstaller `onefile`，并通过父进程监视器确保桌面退出后不残留服务进程；
- Windows x64 作为首个正式发布目标；
- macOS 和 Linux 必须在对应操作系统分别构建，不能复用 Windows sidecar；
- 浏览器开发模式继续保留，但不作为最终用户的主要入口。

暂不选择 Electron。当前应用不依赖 Node 原生桌面能力，Electron 会额外携带 Chromium；Tauri 可以直接复用系统 WebView，并且原生支持外部 sidecar。

### 7.2 桌面运行模型

启动流程：

1. Tauri 主进程选择空闲本地端口；
2. 生成单次启动 token；
3. 启动 FastAPI sidecar，并传入端口、token 和用户数据目录；
4. 轮询 `/health`，确认后再显示主窗口；
5. Vue 只访问本次启动的本地 API 地址；
6. 应用退出时先请求 sidecar 优雅关闭，超时后再终止进程。

安全要求：

- FastAPI 只能监听 `127.0.0.1`，禁止默认监听局域网；
- 所有桌面 API 请求携带单次启动 token；
- 端口不得写死，避免冲突和被其他本地进程抢占；
- API key 不再存放于前端 `localStorage` 或明文 `.env`；
- 模型密钥写入操作系统凭据存储；
- 上传文件、数据库、向量索引和日志不能写入安装目录；
- Tauri sidecar 权限只允许启动指定二进制和固定参数；
- 前端启用严格 CSP，不允许任意远程脚本。

### 7.3 需要新增的目录

```text
apps/
  desktop/
    src-tauri/
      capabilities/
      binaries/
      icons/
      src/
      tauri.conf.json
    package.json
scripts/
  build-api-sidecar.ps1
  build-desktop.ps1
  verify-desktop-package.ps1
services/
  api/
    desktop_entry.py
    api-sidecar.spec
```

`desktop_entry.py` 只负责：

- 读取桌面启动参数；
- 设置数据目录和安全 token；
- 启动 Uvicorn；
- 输出机器可解析的 ready/error 信息；
- 响应优雅关闭。

业务逻辑仍保留在现有 FastAPI app 中，不为桌面版复制一套 API。

### 7.4 实施阶段

#### Desktop Phase 0：最小桌面壳

- [x] 初始化 `apps/desktop`；
- [x] 加载现有 Vue 构建产物；
- [ ] 开发模式连接现有 FastAPI；
- [ ] 实现单实例窗口；
- [ ] 增加原生文件选择和应用日志入口。

验收标准：

- `npm run desktop:dev` 能打开原生窗口；
- 页面功能与浏览器模式一致；
- 重复启动时聚焦已有窗口。

#### Desktop Phase 1：Python sidecar

- [x] 新增独立桌面启动入口；
- [x] 使用隔离环境和 PyInstaller `onefile` 打包；
- [x] Tauri 启动和监控 sidecar；
- [ ] 实现随机端口、启动 token、health check 和优雅退出；
- [ ] 将数据库及上传目录迁移到 OS 用户数据目录；
- [ ] sidecar 崩溃时向用户展示可理解的错误和日志位置。

验收标准：

- 未安装 Python、Node.js 的干净 Windows 环境可以运行；
- 启动后不会弹出命令行窗口；
- 退出桌面应用后没有残留 Python 进程；
- 多次启动不会产生端口冲突或多个后端实例。

#### Desktop Phase 2：安装包与升级

- [x] 生成 Windows NSIS 安装包；
- [ ] 设置应用图标、版本、发布者和卸载信息；
- [ ] 验证覆盖安装、卸载和重新安装；
- [ ] 升级时保留用户数据库、论文、索引和配置；
- [ ] 增加安装包 smoke test；
- [ ] 代码签名和自动更新放在基础安装包稳定之后。

验收标准：

- 安装、启动、上传论文、分析、RAG、导出和卸载全链路通过；
- 安装目录只包含程序文件；
- 用户数据升级后仍可读取；
- 卸载行为明确区分“删除程序”和“删除个人数据”。

### 7.5 桌面版本测试矩阵

至少覆盖：

| 场景 | 要求 |
| --- | --- |
| Windows 10/11 x64 | 安装、启动、更新和卸载 |
| 无 Python/Node 环境 | 所有核心功能可运行 |
| 路径包含中文和空格 | 上传、数据库和导出正常 |
| 端口被占用 | 自动选择其他端口 |
| sidecar 启动失败 | 显示错误和日志路径 |
| sidecar 运行中崩溃 | 前端可检测并提示重启 |
| 无网络 | 本地论文、历史记录和 lexical 检索可用 |
| 模型服务不可用 | 明确降级，不丢失本地数据 |
| 覆盖安装 | 用户数据和索引不丢失 |
| 应用退出 | 无残留进程和未提交数据库事务 |

### 7.6 打包顺序

桌面壳不需要等所有 RAG 阶段完成后才开始，但应按以下顺序推进：

1. 先完成 Desktop Phase 0，验证 Vue 能在桌面壳运行；
2. 完成 RAG Phase 0 和 Phase 1，稳定数据目录与后端边界；
3. 再完成 Desktop Phase 1，冻结 Python sidecar；
4. RAG 核心能力达到正式可用标准后，制作安装包；
5. 最后增加签名、更新和跨平台构建。

## 8. 完成定义

RAG 只有同时满足以下条件，才可以从“调试 MVP”标记为“正式可用”：

- [ ] 主聊天默认使用原文检索；
- [ ] 跨语言检索不依赖 LLM 查询翻译；
- [ ] 达到约定 Recall@5、MRR 和引用准确率；
- [ ] 无答案问题能够拒答；
- [ ] 回答引用经过程序化校验；
- [ ] 每条证据可跳转到原文页；
- [ ] 索引具有内容指纹、版本和失效机制；
- [ ] embedding 故障时存在可观察的降级；
- [ ] 文本 PDF 与扫描 PDF 都有明确处理路径；
- [ ] 自动测试覆盖检索、生成、引用、缓存和聊天集成。

产品只有同时满足以下条件，才可以标记为“桌面软件正式可发布”：

- [ ] 用户无需安装 Python、Node.js 或手动启动后端；
- [ ] FastAPI 仅监听本机并使用单次启动 token；
- [ ] 模型密钥不保存在前端明文存储；
- [ ] 数据目录与安装目录彻底分离；
- [ ] 安装、升级和卸载不会意外删除用户数据；
- [ ] 应用退出后没有残留 sidecar；
- [ ] Windows 安装包通过干净环境 smoke test；
- [ ] 浏览器开发模式和桌面模式复用同一业务代码。
