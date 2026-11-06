# 问答线实现与团队合并说明

## 当前交付边界

按 2026-11-04《分工方案》《交接/2-问答线》实现。2026-11-06 合并版基于真实 Git 历史的 main `a98235774ddc2a591e20992356b21ebc441cab7d`，适配已合入的计划线与湖泊蓝公共界面。

已实现：资料问答、逐段实时输出、原句与页码核对、引用定位、@ 选讲、四类意图分流、反馈与 bad case、token 记录、50 条评测语料与运行器。前后端通过实际本机 HTTP 联调，原文/差评/计划接受撤销/示例题作答均在浏览器验证。

正式课件、主备模型尚未确定，用户已确认先开发和离线测试。因此：**没有真实模型的质量和首字性能验收结果，不把 mock 测试当作 ≥95% / 20条全部诚实 / 5秒首字达标。** 评测讲义是自编 CC0 合成样例，不是正式 PMP 教材或真实课程。

## 文件与所有权

- `app/study/qa/routes.py`：HTTP/SSE 入口，原路径 `/api/chat/stream` 保留。
- `service.py`：NDJSON 逐段解析、出处核对、分流编排及安全输出。
- `storage.py`：现有表上的资料选择、会话归属、回答存档、幂等反馈。
- `intents.py`、`safety.py`：意图分类、统一隐私净化、静态提示词注册。
- `model_stream.py`：重用底座网关配置、模型链、HTTP池、限流和计量的问答流式适配器；没有改动 `app/gateway/` 旧文件。
- `adapters.py`：练习和计划的唯一业务对接位置。
- `app/prompts/qa.answer/v1.md`、`app/prompts/qa.intent/v1.md`：两份新增版本化提示词；后续新增 v2，勿覆盖 v1。
- `web/src/lines/qa/`：自有 hook、组件、SSE client、测试和独立预览；使用已有 CSS/Avatar，无新增项目依赖。
- `app/study/qa/evals/`：8页合成讲义、30条资料内问答、20条资料外问题和 CLI。

**数据库表、共享 API types/client、共享 CSS、其他四条线业务、底座安全规则未修改。** 本次已按用户合并授权，将问答接入新版 `web/src/components/Shell.tsx`；保留湖泊蓝布局、小满形象、字号和滚动交互，问答自有组件复用公共 UI。

## 获取与运行

问答改动通过基于真实 main 历史的功能分支与 PR 集成。合并后在团队正常仓库执行 `git pull --ff-only` 获取，不需要再应用 2026-11-05 交付包中的旧补丁。旧 `02-shell-integration.patch` 对应旧版公共页面，不能覆盖当前湖泊蓝 Shell。

团队其他未合并分支若也改了 Shell，应保留本次的 QA hook、唯一会话初始化、引用工作台和计划刷新回调，在最新 Shell 上逐处合并，勿整文件回退。正式模型与课件验收仍按文末待办执行。

## 接口合同

`POST /api/chat/stream` 保留 `{message,lecture_id?,thread_id?}`，用户身份只来自已签名会话。message 必须非空，最多4000字；不传讲次时，先取该用户最近对话记录中仍有效的讲次，其次最近上传且已有页正文的讲次，再无匹配则取首个可用讲次；没有材料时提供明确标注的两页内置样例。未知讲次返回404，不把资料线的 fallback 当作真实材料。多讲问答应先 @ 选一讲；单讲总文字超过120000字符会明确失败，不能静默截断。

SSE 持续保留旧 `{delta:"..."}` 与 `[DONE]`，新增：

| type | 用途 |
|---|---|
| meta | message_id、thread_id、intent、lecture_id、mock、label |
| references | 累计引用数组；每项 lecture_id/page/quote，按正文标记顺序保存，允许同页和重复原句 |
| handoff | intent=quiz/plan，data 为既有业务数据 |
| error | 稳定错误 code 与安全文案，不暴露原始异常/模型凭证 |
| complete | ok、mock、message_id、in_material、citation_failures、first_text_ms |

新 QA 前端必须得到匹配的 meta/complete.message_id、complete.ok=true 和 [DONE] 才算成功；旧公共 client 仍能读 delta。first_text_ms 是服务器从开始处理到首个可见文本段的耗时；评测另外按客户端接收 delta 计时，不能拿心跳/meta 充数。

`GET /api/qa/lectures` 返回标准 envelope，data 为 `{items:[{id,title,mock}],current_lecture_id}`。

`POST /api/qa/messages/{message_id}/feedback` 接受 `{rating:"up"|"down",reason?:string}`。后端按 user_id 读原始回答和问题，不相信客户端伪造上下文。相同回答重复点踩只保留一个确定性 bad-case ID；后续非空理由可更新。reason 最多1000字。

## 为什么能流式又不先显示假出处

问答模型输出逐行 JSON：先 scope，再每段 sentence。服务端收到一整段后检查原句是否真实出现在对应页、执行现有出站护栏，再把该段发给页面。下一段可以仍在模型生成中。原始模型增量、JSON和未核验页码不会进入页面；删掉的错误出处会记录 bad case 和计数。

主模型在首个原始增量前失败，可以切备模型；已经输出增量后失败会明确中断，不把两个模型答案拼起来。没有 key 时是清楚标出的原文演示，不声称在回答问题。底座原有 `/api/chat` 未修改；闲聊/危机走原有聊天驱动。两份新增提示词登记到现有防泄露护栏，用户隐私 sandbox 同时作用于意图分类、问答、错误库、问题存档和反馈。

## 和各线怎么对接

1. **资料线**：仍只调用 `fetch_lecture_pages(user_id,lecture_id)`，读取既有 `MaterialPage` / `StudyFile`；点击引用仍用 `GET /api/lectures/{id}/pages`。资料线完成真实 PDF 解析后，只要写入同一用户、同一讲次的页码正文，本线直接可用。初始两页样例与8页评测讲义不同，不可混用。
2. **练习线**：只需确认或替换 `adapters.practice_request`。当前转入现有 `quizzes(QuizBody(...),user_id)`，前端用 `/api/attempts` 提交。当前读取已有模拟题；指定讲次没有题时，底座可能回退到该用户其他讲次的示例题，不能视为已基于所选资料出题。现有生成和判分仍为地基模拟，不属于本次真实出题能力验收；如练习线接入自己的卡片，可在 QaHandoff 替换渲染，不改意图协议。
3. **计划线**：直接调用已合入的 `app.study.plan.service.adjust_from_text(user_id,text)`，不再自行创建旧格式 AgentAction。计划 handoff 的 data 为 `{understood,card,reply,mock,label}`，只有 card 非空时发送 handoff；同档位或无法识别时只显示原服务 reply。card 沿用计划线原生 kind/lines/options，接受时把用户实际选择的 option.id（需要时含 exam_date）提交到 `/api/suggestions/{id}/accept`；先不用走 dismiss，撤销走 `/api/actions/{id}/undo`。成功返回 data.plan 后刷新左栏。规则和状态变更为正式计划服务，但按计划线既有约定保留模拟标识，不能将仍为样例的资料与练习当成真实数据。
4. **看板与上线线**：继续用已有 BadCase / LlmCall，不增表。错误来源 qa_backend / qa_intent / user_feedback；用量包含用户、能力、版本、模型和 token，缺厂商用量时 estimated=1。意图用量目前为估算值，不能作为精确账单。主模型失败但备模型成功的尝试也记错例。
5. **A / 后续各线合并者**：问答现已接入新版湖泊蓝 Shell。QA hook 统一初始化会话并暴露 sessionReady，宿主页必须等待它，不能再并发创建会话。QaAnswer 的 onReference 打开现有原文工作台，onPlanChange 更新左栏；active 只给最新回答，避免多张待确认卡同时出现。视觉交给共用组件/CSS，业务组件保持独立。

## 本地验证

按根 README 建立 Python3.12 虚拟环境、安装锁定依赖与前端依赖，使用 scripts/ensure_local_auth.py 配置本地会话。模型密钥仅放本地 .env，不随交付包提供。

```bash
# 两个终端
.venv/bin/uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8787
cd web && npm run dev
```

主页面打开 `http://127.0.0.1:5173/`；问答独立预览仍可打开 `/qa.html`。独立预览的生产构建用 QA 目录的 preview.config.ts；默认 npm run build 构建的主入口已包含问答模块。

```bash
.venv/bin/python -m pytest -q
AUTH_SECRET=local-test PYTHON_DOTENV_DISABLED=1 INTENT_SCORING_MODE=rules .venv/bin/python tests/golden/run_golden.py --mode mock --judge-gate
AUTH_SECRET=local-test PYTHON_DOTENV_DISABLED=1 .venv/bin/python tests/golden/run_hybrid.py --mode mock --judge-gate
cd web && npm test && npm run build
```

QA 专项用例在 tests/test_qa_line.py、test_qa_model_stream.py、test_qa_evals.py、test_qa_plan_integration.py 以及 web/src/lines/qa/qa.test.ts；所有原测试保留。

## 真实验收还需要什么

- 团队选定正式公开课件，资料线解析并写入对应讲次；本次不实现 PDF 上传解析。
- 本地配置主备模型，确认配置中的 qa.answer / qa.intent 任务模型链。支持 OpenAI-compatible 和 Anthropic 流协议，但不同厂商需真实请求验证。
- 按 evals/README.md 运行离线语料检查；导入同一8页讲义后可显式 --live 跑50题。再用正式课程重新标注30+20题验收；要人工复核语义准确性。
- 目标仍是出处核对≥95%、20条资料外问题全部明确说明、真实请求≤5秒开始显示文本。本次没有模型配置，不能宣称这三项已达标。意图分类和按段校验都计入真实首字时间，必要时根据实测调模型或提示词。
- 各线替换剩余地基模拟能力并合并后，团队再走完整8步演示；本次浏览器验证的是问答及当前适配接口，并非整个项目已上线。

## 2026-11-06 合并前验证记录

- 基于 main `a982357`；后端全量 **1858 passed、84 skipped**，119.18秒；原测试未删除或额外跳过。
- 问答与正式计划服务定向回归 **152 passed**。
- 前端 **32 passed**（QA26、计划4、公共卡片2），类型检查和生产构建通过。
- rules/hybrid golden mock 各 **42/42**，hybrid另3个路由探针通过；harness与主动记忆smoke通过。
- 本地真实HTTP及Chrome验证新版主页面的问答、出处高亮、反馈入库、连续提问、计划确认与撤销、示例题作答、窄屏无横向溢出，以及上传提示顺序；不使用真实模型。
- 合并适配审查发现的“撤销上一项后仍能点击已过期子卡”已修复并加入回归；上传通知追加到当前对话末尾。
- 云端检查以PR/Actions页面显示的实际状态为准；真实模型质量、5秒首字和正式课程验收仍未执行。
