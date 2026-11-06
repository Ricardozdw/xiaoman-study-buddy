# 资料线：PDF → 带出处的学习笔记

已实现真实 PDF 上传、按物理页序提取文字、AI 整理、出处核验、摘要卡、笔记全文、编辑保存、引用高亮、失败重试、重复文件复用，以及笔记完成后与今日计划联动。

资料功能接入最新主界面的上传入口、资料列表和学习文档工作台，复用 `components/ui.tsx`，保留问答对话流、计划与看板。业务代码在本目录和 `web/src/lines/materials/`，共享 Shell 只负责入口、回调和工作台装配。

默认在本机使用文件目录和 SQLite。Supabase 私有桶适配已经实现并通过模拟 HTTP 测试；当前没有项目连接配置，因此没有实际接通云端，也没有把本机已有文件迁移上云。

## 本地运行

使用 Python 3.12，安装根目录锁定依赖。先运行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt -c requirements.lock
python scripts/ensure_local_auth.py
```

AI 整理使用现有模型网关。可在本机 `.env` 配置模型密钥；示例配置 `config/materials-models.example.json` 将 **materials.summary 这一项能力** 路由到 DeepSeek Flash / V4 Pro 主备链，不改变其他聊天或计划能力。

```dotenv
# 真实值仅在本机填写，不提交、不截图、不发聊天。
DEEPSEEK_API_KEY=
LLM_CONFIG_FILE=config/materials-models.example.json
```

未配可用模型时，系统仍能读 PDF 和看原文，但会明确提示“模型未配置”，不生成占位笔记。配好后点“重试整理笔记”，不必重传 PDF。

后端：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

前端另开终端：

```bash
cd web
npm ci
npm run dev
```

打开 http://127.0.0.1:5173/ 。选讲次，点“＋ 交资料”或拖入 PDF，完成后点“打开学习笔记”。现有已读取 PDF 可直接点“整理成笔记”。

支持文字版 PDF，最大 20 MB、200 页；AI 整理最多接收 10 万字符，超限明确要求按讲拆分，不静默截掉内容。损坏、加密或没有可提取文字的文件会报错。

## 准备样例并验收

可使用以下公开原件，下载后从主界面“交资料”选择文件：

- [《AI产品经理手册》中文公开节选，45 页，约 1.5 MB](https://www.tup.tsinghua.edu.cn/upload/books/yz/103768-01.pdf)。含前言、目录和第一章正文，PDF 第 23 页为“构建 AI 产品所需要的基础设施和工具”章节开头。
- [MIT 预算与成本控制公开课，35 页，约 0.76 MB](https://ocw.mit.edu/courses/esd-36-system-project-management-fall-2012/cc2e35aeec27d3f5ee43e43ebda5201f_MITESD_36F12_Lec10.pdf)。英文原件，用于完整计时。

先验证抽文字无需模型密钥：上传成功后，读取 `/api/files/{id}/status`，当 `parse_status=parsed` 时，`GET /api/lectures/{lecture_id}/pages?file_id={id}` 应返回真实逐页正文、`mock:false`；`/api/qa/lectures` 应能列出该讲，问答使用同一份正文。缺少笔记模型只影响整理笔记，不影响已读取的文字供问答/练习调用。

配置可用模型后，再检查：生成三条重点、知识点、术语 → 打开页码看到原文高亮 → 修改标题/解释并保存 → 刷新后重新打开 → 同讲重复上传复用，修改仍保留。测试新生成耗时应使用新讲次或新会话，避免复用缓存。损坏 PDF、非 PDF 和其他用户的文件访问应明确报错。

最新 main 的练习接口仍是显式模拟。本线提供它可调用的真实正文入口，不把原练习占位题算作由课件生成的真实题目。

## 用户能做什么

- 看三条重点、知识点和术语，逐条带原文页码。
- 点页码打开对应原文件的那一页，连续原句高亮；同讲替换 PDF 后，旧笔记仍指向旧文件。
- 修改标题、摘要、知识点名称/解释、术语/解释，保存后刷新仍在。
- 修改笔记时保留知识点顺序和出处，不增删、重排知识点，以免学习历史被归到别的概念上。
- 重复上传同一用户、同一讲、相同文件时复用正文和笔记；已有笔记不会被重新生成覆盖，用户修改也不会丢。
- 解析失败可以重试读取；AI 出错可以只重试整理，已提取正文保留。

## 接口

身份仍来自底座签名会话，前端不传用户 ID。成功外壳沿用 `{ok,status,mock,data}`；真实资料和笔记为 `mock:false`，错误通过 HTTP 状态与 `detail:{code,message}` 表示，不降级为模拟成功。

| 接口 | 用途 |
| --- | --- |
| POST `/api/files/upload-url` | `{filename,mime}` → `{file_id,upload_url,method}` |
| PUT `/api/files/{id}/raw` | 直接发送 PDF 字节，Content-Type 为 application/pdf |
| POST `/api/files/{id}/complete` | `{lecture_id:"lec-N"}`，后台读取并自动整理 |
| POST `/api/files/{id}/summarize` | 对已有正文生成或重试笔记，已保存的直接复用 |
| GET `/api/files/{id}/status` | 页数、进度、解析/整理状态、错误、note_id |
| GET `/api/files` | 当前用户真实上传记录 |
| GET `/api/lectures/{id}/pages` | 当前讲一个成功版本的逐页正文 |
| GET `/api/lectures/{id}/pages?file_id=...` | 精确读取某个归属该用户/讲次的原文件版本 |
| GET `/api/notes` | 有真实笔记时只返回真实笔记；未生成时保留显式模拟外壳 |
| GET `/api/notes/{id}` | 完整结构化笔记 |
| PATCH `/api/notes/{id}` | `{content,title?}`，校验并保存用户修改 |

状态：

- `parse_status`: awaiting_upload → uploaded → reading → parsed → ready；读取失败为 failed。
- `summary_status`: not_started → pending → generating → ready；模型缺配置为 unavailable；整理失败为 failed。
- `parsed` 表示正文可用，`ready` 才表示笔记真实保存完成，`notes_ready:true` 同时返回 note_id。
- `pending` 是解析交给 AI 的过渡状态，前端继续轮询，避免在两步之间停止观察。
- 计划线仍按 files.parse_status == ready 自动完成“交课件”，因此不会把单纯读出文字算成整个整理过程完成。

问答/练习统一从 `fetch_lecture_pages(user_id, lecture_id, *, file_id=None)` 取正文。原来的两个位置参数保持兼容，新增可选的 `file_id` 固定原文件版本。返回按物理页码排序的 `lecture_id/file_id/page/text/mock`；上传记录已有正文时，即使 `summary_status=unavailable/failed/generating` 也可读取。调用方使用后端可信会话身份，并拒绝 `mock:true` 作为真实课件。

笔记 content 含 schema_version、file_id、summaries、knowledge_points、terms、generation。每条摘要/知识点/术语都有 page 和 quote；知识点还有稳定 id。保留 points:string[] 作为旧壳兼容字段。数据库沿用 notes、knowledge_points 等已有表，没有改共享表结构。

## AI 与数据可靠性

- 能力提示词在 `app/prompts/materials.summary/vN.md`。v1/v2 保留不动，生产固定使用 v3。
- 后端为完整原文逐页标记片段编号，模型选择编号，后端填入对应页码和逐字原文，避免模型漏抄数学符号。所有片段拼接后与原页完全一致，没有检索、删减或跨页拼接。短片段保留正文但不作为引用。
- 通过现有网关调模型；Pydantic 检查编号格式和所属资料，填入原句后仍核对引用是否确实存在于标注物理页，再经过原有出站护栏。模型不能自行覆盖 page/quote，公开接口格式保持不变。
- 不合格最多修复一次，仍失败记录 bad case，保留正文。缺模型、模型返回占位或出站护栏不可用都不会形成“成功笔记”。
- 调用记录写入 llm_calls，带用户、能力、模型和提示词版本；优先保存实际输入/输出 token，没有报告值时明确标估算。
- PDF 原件以服务端生成 ID 和用户哈希寻址。笔记和正文按用户隔离；读取、修改均通过原有护栏。
- 生成结果只保存一次；重复请求复用。编辑保留知识点掌握度和下次复习日期，禁止通过更换 ID 或重排把历史归到其他概念。
- 当前任务与进度保存在本机，支持识别已退出的后台进程并重试；面向单进程开发，并发首次上传同一文件仍可能各解析一次。

## Supabase 原件存储

需团队事先准备 **私有桶**，然后仅在后端配置：

```dotenv
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=
```

全留空使用本机；填写 URL 和服务端密钥后启用，桶名省略时使用 study-materials。桶必须已存在且为 private。部分配置、误用公开桶或网络错误都会明确失败；服务端密钥不会返回前端。新上传原件先镜像到云端，再保存本地缓存；缓存缺失时可以从云端恢复。状态 sidecar 仍在本机。已有本地原件不会自动迁移。

当前没有真实 Supabase 凭据，云端只做了模拟接口验证。Supabase 数据库的公共表迁移仍需 A/上线线统一安排；本次没有执行远程建表、修改权限或部署。

## 合并范围

资料线后端在本目录，前端在 `web/src/lines/materials/`。唯一共享界面文件 Shell.tsx 用于上传入口、资料卡、笔记/出处工作台和计划刷新，需 A 合并时 review。其他共享改动仅为 `.env.example` 配置说明、根 README 和测试环境对真实云凭据的隔离。

没有修改其他模块业务、公用样式、旧版提示词或底座安全规则。

## 验证记录

```bash
python -m pytest -q tests/test_materials*.py
python -m pytest -q
cd web
npm test
npm run build
```

已实测：33 页中文 PDF 经真实 DeepSeek Flash 调用生成 **3 条重点、12 个知识点、11 个术语，共 26 条出处核验通过**；编辑后刷新保留；重复上传没有新增模型调用；引用页原句在浏览器高亮。

2026-11-06 完整计时：35 页 MIT 公开课 PDF 在全新本地数据目录、空会话中首次上传，从申请上传到笔记保存并读取 JSON 共 **7.384 秒**；真实 DeepSeek Flash 一次调用，3 条摘要、12 个知识点、12 个术语，27 条引用通过核验，未使用缓存或手动重试。计时包含上传、读取全部页面、AI 生成、出处校验和保存；独立复核不计入。该结果只代表这份样本及本次环境，不保证所有 PDF 均在两分钟内完成。

本次 v3 修复前，同一 PDF 因模型漏抄第 24 页的 U+F0B3 特殊字形而失败。首次失败记录保留；v3 从后端原文片段填入出处，仍拒绝缺符号或改符号的手写引用。

最新 main 整合后：后端全量 **2029 passed、84 skipped、0 failed**；资料、问答与计划自动完成联合测试 **155 passed**；前端 **74 项测试与构建通过**。Rules/Hybrid 金标各 **42/42**，旧 harness 通过。新增 6 项跨线测试覆盖真实 PDF → 按页正文 → 问答的完整数据链路、缺笔记模型、历史正文兼容和用户隔离；问答模型输出使用离线桩。

浏览器在最新湖泊蓝主界面实际上传 45 页中文《AI产品经理手册》公开节选，经真实 DeepSeek Flash 一次生成 3 条摘要、11 个知识点、10 个术语。上传后 `@` 讲次列表更新为这份真实课件，学习文档入口和第 23 页原句高亮通过；问答原文面板也读取这份上传文件。开发机未配置问答所需模型时，问答仍按 main 的既有约定明确标为模拟。本轮为功能验收，35 页样例的完整计时记录单独保留。
