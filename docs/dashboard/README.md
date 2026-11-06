# 5 号线交付：看板、质量与上线准备

本目录是 5 号线实现与合并交接。产品范围以 `docs/分工方案.md`、`docs/交接/5-看板与上线线.md` 和当前 PRD 为准。旧技术主文档中 Dify、旧角色分工、较宽松的评测线均不覆盖这三份约定。

## 代码范围

- 业务后端：`app/study/dashboard/`。
- 业务前端：`web/src/lines/dashboard/`；复用现有 `.card`、`.btn`、`.badge` 等样式，没有改颜色、组件库或其他线。
- 共用文件仅 `web/src/components/Shell.tsx`：导入看板组件、识别明确的看板请求、插入摘要卡、替换原工作台看板占位。此处是提交给 A 的接线提案，请 A review 后随 PR 合并。
- 统一评测：`evals/`；提示词初稿：`app/prompts/dashboard.eval/v1.md`。看板数值由规则统计，不需要模型生成。
- 上线准备：`deploy/xiaoman/` 和独立 CI。原 Dockerfile、底座安全规则、原金标、共用数据模型均保持原样。

## 本地运行与验收

Python 3.12；依赖安装沿用根 README。前端开发仍是原有 `npm run dev`。

```bash
# 后端（本机 .env 配置 AUTH_SECRET；不需要真实模型）
uvicorn app.main:app --host 127.0.0.1 --port 8787

# 前端，另开终端
cd web
npm ci
npm run dev
```

在对话里输入“这周学得怎么样”，摘要卡点“打开完整看板”。也可点原收工卡的“看看板”。完成任务或做题后，重新打开或点“刷新看板”。网络/登录失败会显示错误，保留旧记录并说明，不用本地假数覆盖错误。

```bash
python -m pytest -q
AUTH_SECRET=x INTENT_SCORING_MODE=rules python tests/golden/run_golden.py --mode mock --judge-gate
AUTH_SECRET=x python tests/golden/run_hybrid.py --mode mock --judge-gate
python scripts/harness_golden.py
AUTH_SECRET=x python scripts/smoke_proactive_memory.py
cd web && npm test && npm run build
```

## 统计口径与对接口

`GET /api/dashboard?range=week` 保留原字段，增加 `period`、`goal`、`mastery_note` 和每讲的 `assessed` / `mistakes_due`。只支持 `week`；其他范围返回 422。`GET /api/dashboard/summary` 返回同一快照及摘要卡。身份始终来自服务端会话，不接受客户端指定别人。

| 指标 | 数据来源与口径 |
| --- | --- |
| 这周学了几天 | 北京时间周一至今天，有作答或实际学习/任务完成的日期去重。打开页面、上传占位和 foundation_seed 不算学习。完成后撤销勾选，已有完成事件仍保留。 |
| 本周做题 | 本周所有作答次数，包含重做。未来日期不计入。 |
| 待重做错题 | 每道题按最新作答判断；重复答错只算一道，后续答对即退出。历史作答不删除。当前表尚无重出题的 parent id，换问法跨题关联由练习线提供后再对齐。 |
| 每讲掌握度 | 同一讲的 `knowledge_points.mastery` 平均值；不把第一知识点当整讲。练习线拥有计算与更新算法；看板只读取，不另算正确率覆盖它。没有知识点则“还未评估”。 |
| 目标进度 | 已有计划时复用计划线 `progress.progress` / 保存的 `learned_up_to`，不重算计划线规则；独立统计样例兼容按已完成 learn 的讲次去重。最多 100%。 |
| 模拟标记 | 存在地基 foundation_seed 的账户整张看板继续标“模拟”，不将地基样例伪装为真实资料。新空账户读看板不自动造数据。 |

已对齐主分支合并的计划线：复用其进度接口和演示时钟，“跳到明天”后看板按同一天统计，并明确标“演示用”。任务完成事件优先按任务 day 归属，避免演示日期和真实服务器时间不同而算错。`task_status` 的 props 含 task_id、status；历史已完成任务没有事件时，兼容读取任务 day。计划线旧样例的 phases 是字符串、而进度接口期望对象；5 号线对旧样例只读计划线保存的进度，阶段信息标不可用，不修改计划线或旧数据。

**当前地基的练习接口不更新掌握度，问答/资料仍有占位。** 计划线已合并。5 号线测试验证了知识点更新后看板立即变化，但不替其他线完成其算法、按钮和 8 步演示。各线合并后由 A 联调。

## 各线统一记录 AI 用量和错误

已有 `llm_calls`、`bad_cases` 表可复用，没有另建平行的表。各线二选一，避免重复记账：

1. 采用 `app.study.dashboard.telemetry.tracked_json(...)`：输入服务端 user_id、能力、提示词名称/版本、公开样例 payload、Pydantic 输出模型；经原模型网关校验、重试、切备用。每次物理上游尝试按实际模型独立记录 token、延迟、成功与否；失败写 bad case。
2. 已经封装能力的线继续原流程，每次调用后用 `record_call(...)`，出错用原 `app.study.common.bad_cases.write_bad_case(...)`。不要再套 tracked_json 造成双记账。

```python
record_call(
    user_id=authenticated_user_id, capability="问答", prompt_name="qa.answer", prompt_version="v1",
    model=actual_model, prompt_tokens=reported_input, completion_tokens=reported_output,
    latency_ms=elapsed_ms, ok=output_valid,
)
```

未知 token 传 `None`；按字符估算必须 `estimated=True`。不将未知当作零费用。底座内存 ring 的用量不混入用户账本。各线还没接这个入口的调用不会自动计入；本 PR 不改其他线或全局 monkey patch 网关。

`GET /api/study/usage` 给当前用户按能力、模型分组，保留原 `by_capability` / `items`，并给出币种分开的费用小计。没有单价或只有估算 token 时计入 `unpriced_calls`，费用为空，不冒充免费。费用按随代码版本保存的价格表估算，**不是历史账单**；缓存折扣、时段、价格变更需按实际账单复核。

`POST /api/study/feedback` 输入 `target_type: message|question`、`target_id`、可选 reason。服务端只读取本人的消息/题目，保存原输出、资料引用及来源信息；重复点同一对象只生成一条 bad case。其他线的 👎 / “这道题有问题”按钮应接此入口。当前地基没有这些真实按钮，本 PR 不在其他线代做。

问答线保存消息时，请在 `messages.refs_json` 中保留 `{model, prompt_version, input, refs}`；`input` 需要保存当时公开样例问题及实际带入的页。旧记录未保存来源时明确写 `not_recorded`，不根据最近一次模型调用猜来源。题目生成错误应在产生时 `write_bad_case`，保留实际输入、输出、模型、提示词版本；已有 questions 表没有模型/提示词字段，用户反馈旧题时来源会显示缺失，需 A 统一决定后续共用字段。

团队直接在 Supabase 表格中分诊 `bad_cases`，不提供管理页。原表所有 PRD 字段已经存在。

## 统一评测与回归

```bash
# 默认只用隔离临时数据库，不调用模型、不读取 .env
python evals/run.py --output data/evals/first
python evals/run.py --baseline data/evals/first.json --output data/evals/repeat

# 上线门禁：缺任何必需能力/真实模型评测时返回非零
python evals/run.py --release-gate
```

输出 JSON、可独立打开的 HTML 和失败案例 JSON。同一数据集比较每一条已通过用例，曾通过现在失败就报退步；数据集或模式变化会拒绝比较，不拿总分抵消退步。离线分数不能作为模型质量分数。JSON 报告保留 AI 的真实输出、延迟和供应商 token；失败案例可以分诊后回归。

各线将公开用例放 `evals/cases/<线名>.json`，评测器自动发现：

```json
[
  {
    "id": "qa-public-example-001",
    "capability": "qa_citation",
    "kind": "ai",
    "prompt": {"name": "qa.answer", "version": "v1"},
    "payload": {"question": "公开样例里的问题", "pages": [{"page": 1, "text": "公开原文"}]},
    "checks": {"citations.0.page": 1, "citations.0.quote": "公开原文"}
  }
]
```

这是接入格式说明，**没有把这条占位示例放入正式用例**。字段需对齐各线真实提示词输出；checks 是确定性路径断言。看板已有 8 条实际聚合用例。`manifest.json` 规定 QA 出处至少 30 条且 ≥95%，资料外至少 20 条且全部通过，练习至少 20 条且 ≥95%；其他线初始用例缺失会在 coverage 中显示。

自动断言不替代人工抽查答案正确、原文依据、题目重复和语气。`dashboard.eval/v1.md` 是复核提示词初稿，缺证据必须给 insufficient，尚未接真实 judge。资料线、问答线、练习线、计划线的提示词与标准答案由它们各自交付。

已修复 bad case 在 `input_json` 中增加 `public_sample: true`、`evaluation: {capability, prompt, payload, checks}`（prompt 指向**修复后的**版本），然后：

```bash
python evals/export_bad_cases.py --user-id <服务端用户ID> --output evals/cases/fixed.json
python evals/run.py --mode live --model deepseek-flash --output data/evals/flash
```

缺公开标记或回归说明会阻止导出，不静默漏过。导出为用例后，默认评测命令会自动包含全部 fixed.json。不要把期望输出当成模型输出回放。真实输入进入版本库前必须确认是公开样例。

## 两个候选模型与价格

2026-11-06 已读取 [DeepSeek 官方价格表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。当前模型名称是 `deepseek-flash` 和 `deepseek-v4-pro`；不用旧别名假设型号。

| 候选 | 输入未命中缓存 / 百万 token | 输入缓存命中 / 百万 token | 输出 / 百万 token | 本项目质量/延迟 |
| --- | --- | --- | --- | --- |
| deepseek-flash | 高峰 ¥2 / 空闲 ¥1 | 高峰 ¥0.04 / 空闲 ¥0.02 | 高峰 ¥8 / 空闲 ¥4 | 待真实评测 |
| deepseek-v4-pro | 高峰 ¥9 / 空闲 ¥4.5 | 高峰 ¥0.30 / 空闲 ¥0.15 | 高峰 ¥27 / 空闲 ¥13.5 | 待真实评测 |

费用汇总采用高峰、未命中缓存的保守口径，不在代码里猜节假日或缓存比例。价格表固定在 `prices.json`；调整时更新核验日期和来源。

**初步建议先将 deepseek-flash 作为待验证主候选，v4-pro 作为备用候选；最终主模型由真实评测决定。** 这个顺序仅基于已核对价格，不代表质量或速度已经达线。同厂商两模型不能覆盖该厂商整体不可用或共享账户额度耗尽，需要更强可用性时由 A 决定是否改成跨厂商候选。

模型配置示例在 `deploy/xiaoman/models.example.json`。只有收到实际模型凭据并明确评测费用后才运行：

```bash
# 显式从安全环境提供 DEEPSEEK_API_KEY。评测脚本不会读取 .env。
python evals/run.py --mode live --model deepseek-flash --output data/evals/flash
python evals/run.py --mode live --model deepseek-v4-pro --output data/evals/pro
python evals/compare.py data/evals/flash.json data/evals/pro.json
```

同一评测集、同一模式，逐模型单独调用，禁用混入备用输出。比较报告给准确率、延迟中位数/P95、token、费用和建议；覆盖不完整或无真实结果时明确“暂不确定主模型”。

## 交给 A 的上线准备

```bash
cd web && npm run build -- --base=/study/
cd ..
uvicorn app.study.dashboard.release:app --host 127.0.0.1 --port 8787
```

访问根路径会跳到 `/study/`，API、健康检查、原底座安全中间件仍经原 app。React 资源和 API 同源，不把模型密钥发给浏览器。镜像：

```bash
docker build -f deploy/xiaoman/Dockerfile -t xiaoman-study .
```

`deploy/xiaoman/render.yaml` 是**手动部署提案**，自动部署关闭。包含付费磁盘配置；A 决定预算与目标后才创建。仅用 Supabase 不足以保存本机 audit、checkpoint 和尚未迁移的上传文件，因此仍需持久磁盘。原免费蓝图没有这个保障。

数据库准备：原学习表只有 SQLite 自动创建，原 schema.sql 只是权限意图。`study_schema.py` 依据现有模型生成 18 张学习表与独立 RLS SQL 草案，不连接数据库、不执行权限变更，不并入底座 RLS 迁移。A 先审阅表名、现有策略、app/system 运行角色和 Supabase Data API 设置，在隔离测试库验证后再决定应用。基础角色初始化见 `docs/postgres-rls.md`，运行连接不能使用 owner/service_role 或绕过 RLS 的角色。

```bash
python deploy/xiaoman/study_schema.py > data/study-schema.sql
python deploy/xiaoman/preflight.py data/release-evidence.json
```

前者只输出 SQL；后者只读检查，不部署。SQL 采用 `app.user_id` 与 `WITH CHECK`，限制为 personal_agent_app，撤销 anon/authenticated 的表权限；不套用 Supabase Auth 的 auth.uid()。官方依据：[RLS 文档](https://supabase.com/docs/guides/database/postgres/row-level-security)。Supabase 近期 [CLI v3 改变默认目标及远端确认](https://supabase.com/changelog/supabase-cli-v3)，后续操作必须先核对本机版本，本交付没有调用 CLI 或改远端数据库。

`release-evidence.json` 是 A 的逐项验收记录，只能对已经有实际证据的项目填 true。键名见 preflight.py。当前未完成项见 [验证记录](验证记录.md)，不能为了通过预检补勾。
