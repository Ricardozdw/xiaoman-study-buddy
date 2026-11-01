# Personal Agent

一个有长期记忆的个人助理：陪你聊、记住你告诉它的事、帮你写草稿（**你确认后才算数**）、设提醒和定时任务、读网页资料。入口：Web + 飞书长连接 + 微信（OpenClaw 桥）。网页会话即账号，飞书/微信通过一次性链接绑定到同一账号；模型经统一 FAST/STRONG 网关。

## 产品边界

| 做 | 不做 |
|----|------|
| 带记忆的对话：姓名、城市、职业、兴趣、偏好、备注，可在记忆卡上查看、修改、遗忘 | 替用户对外发消息、发邮件、提交表单 |
| 写作草稿（邮件 / 消息 / 文章 / 笔记）→ 确认卡 → 定稿；拒绝可带原因自动重写 | 在聊天里收账号密码、手机号、身份证（一律转安全输入区） |
| 一次性提醒、自定义只读定时任务（确认卡后创建） | 登录任何网站、无人值守操作 |
| 读取公开网页 / RSS / 搜索结果作为不可信来源 | 向量检索默认关闭（可选开启） |
| 危机识别与热线兜底、提示词泄露与隐私护栏 | — |

## 已拍板决策

| 项 | 结论 |
|----|------|
| 入口 | 飞书 + 微信（OpenClaw）并行 |
| 账号 | 服务端签发的网页会话；渠道账号绑定到网页会话 |
| 模型 | 任意厂商，统一网关（FAST/STRONG） |
| 向量记忆 | 默认关，`MEMORY_VECTOR_ENABLED=1` 开启 |
| 确认卡 | 不过期；后点覆盖先点 |

## 快速启动

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env 里至少填两项，否则接口 503 / 聊天只回离线占位：
#   AUTH_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
#   KIMI_API_KEY=你的 Moonshot Key（样例默认双档都走 Kimi）
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

| 页面 | URL |
|------|-----|
| 对话 | http://127.0.0.1:8787/ |
| 健康检查 | http://127.0.0.1:8787/health |

只填 `AUTH_SECRET`、不填模型 Key 也能启动：聊天回离线占位、草稿为离线占位稿，便于冒烟。

## 架构一览

| 层 | 实现 |
|----|------|
| 编排 | LangGraph + `app.agent.router` → `app.agent.subgraphs/*`（chat / draft+confirm / profile） |
| 工具 | `app.agent.tool_registry`（统一注册、风险等级、确认门禁；模型只走网关） |
| 记忆 | 工作=checkpoint；档案=SQLite（含对话摘要）；情节=`episodic_events`（关键词/标签）；可选向量事实 |
| 网关 | task→FAST/STRONG→有序模型链（OpenAI 兼容 + Anthropic），失败/超时/429/空内容降级；见 [docs/llm-gateway.md](docs/llm-gateway.md) |
| 通道 | Web / 飞书长连接 / OpenClaw → 统一 `run_action` + 出站渲染 |
| 主动 | 定时任务调度器（默认关）：一次性提醒、自定义只读任务，结果进应用内收件箱并推送到已绑定渠道 |

详情：[docs/agent-stack.md](docs/agent-stack.md) · [docs/技术架构.md](docs/技术架构.md)

## Agent Tools

工具覆盖档案与记忆、写作草稿、定时任务、联网读取、主动提醒；完整清单、风险等级与确认要求见 [工具分类清单](docs/tools.md)。
注册表：`app/agent/tool_registry.py`；工具执行是否强制确认以 `requires_confirm` 为准（`external` 一律需要）。
列表也可查 `GET /api/tools`；机制说明见 [docs/tool-registry.md](docs/tool-registry.md)。

## 通道

所有渠道走同一个网关 `app/channels/gateway.py`：入站归一 → 绑定检查 → 隐私拦截 → 同一个 agent thread → 渲染（飞书卡片 / 微信文本菜单）→ 出站。**两个渠道默认都关**，详见 [docs/channels.md](docs/channels.md)。

- **绑定走对话**：未绑定用户发任何消息，都会收到一次性绑定链接（`/bind`），用常用浏览器打开并点「确认绑定」，渠道账号即绑定到该浏览器的网页会话（与网页共用一份档案和记忆，无需密码）。
- **隐私不进聊天**：手机号、邮箱、身份证、银行卡一律不在渠道里收集，回复网页安全通道链接（`/sandbox`）。
- **草稿**：渠道里只发预览，附「在网页查看完整草稿」链接；确认 / 拒绝在飞书是卡片按钮，微信回数字 `1` / `2`。

| 渠道 | 开关 | 接入方式 |
|------|------|----------|
| 飞书 | `FEISHU_ENABLED=1` + `FEISHU_APP_ID/SECRET` | 官方 SDK 长连接，无需公网地址。见 [docs/feishu-长连接.md](docs/feishu-长连接.md) |
| 微信 | `OPENCLAW_WECHAT_ENABLED=1` + `OPENCLAW_WEBHOOK_TOKEN` | OpenClaw Gateway + [桥接插件](integrations/openclaw-personal-agent-bridge/README.md) |
| QQ 等 | — | 只留了 `ChannelAdapter` 接口（`app/channels/qq.py`），未实现 |

## 部署

- **Docker / Render**：见 [docs/deploy.md](docs/deploy.md)。Blueprint 默认双档走 **Kimi**（`kimi-k2.6` / `kimi-k3`）。

```bash
docker build -t personal-agent .
docker run --rm -p 8787:8787 -e KIMI_API_KEY=你的key personal-agent
```

## 环境变量

完整键名与注释见 [`.env.example`](.env.example)。**不要提交填好的 `.env`。**

| 分组 | 关键键（示例） |
|------|----------------|
| LLM | `KIMI_API_KEY`；`LLM_FAST_*` / `LLM_STRONG_*`；推荐双档都走 Kimi |
| 会话 | `AUTH_SECRET`（必填，缺失则 `/api` 返回 503） |
| 渠道公共 | `PUBLIC_BASE_URL`（HTTPS，绑定 / 安全通道链接用）、`CHANNEL_ADMIN_TOKEN` |
| 飞书 | `FEISHU_ENABLED`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET` |
| 微信 | `OPENCLAW_WECHAT_ENABLED`、`OPENCLAW_WEBHOOK_TOKEN`、`OPENCLAW_GATEWAY_URL`、`OPENCLAW_GATEWAY_TOKEN` |
| 安全保存 | `SECRETS_FERNET_KEY`（必填才能保存账号/手机号等；逗号分隔可轮换） |
| 主动调度 | `PROACTIVE_ENABLED`、`PROACTIVE_TZ`、`PROACTIVE_TICK_SECONDS` |
| Harness | `HARNESS_ADMIN_TOKENS`、`HARNESS_ID_HMAC_KEY`、`PII_BACKEND`、`PRIVACY_SANDBOX_VALUES`、`TRACE_WRITE_MODE` |
| 可观测性 | `LANGFUSE_ENABLED`、`LANGFUSE_HOST`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`；自托管见 [`docs/langfuse.md`](docs/langfuse.md) |
| 记忆 | `MEMORY_VECTOR_ENABLED`、`SILICONFLOW_API_KEY`（向量 / 混合意图评分） |

## HTTP API 摘要

| 路径 | 说明 |
|------|------|
| `POST /api/session` | 签发 / 刷新网页会话 |
| `GET /health` · `GET /api/capabilities` · `GET /api/tools` | 网关与通道状态、能力清单、工具列表 |
| `POST /api/chat` | 对话；写作请求返回 `awaiting_confirm` + `task_card`（`draft_confirm`） |
| `POST /api/draft` | 直接发起草稿（`request`） |
| `POST /api/confirm/{thread_id}/token` · `POST /api/confirm` | 一次性确认凭证 + 确认 / 拒绝（可带 `edits` / `reason`） |
| `POST /api/continue` | 预算用尽后继续任务 |
| `GET/POST /api/profile` | 通用档案（name / city / tz / occupation / interests / preferences / facts） |
| `GET /api/memory/{user_id}` · `/card` · facts / events · `/forget` | 记忆查看与编辑 |
| `GET/POST/DELETE /api/secrets` | 安全输入区（从不返回明文） |
| `/api/schedules*` | 定时任务 CRUD、确认卡决定、运行历史 |
| `GET /api/proactive/pending` · `POST .../dismiss` | 应用内提醒收件箱 |
| `GET /bind` · `POST /api/channels/bind/complete` · `GET /sandbox` · `POST /api/sandbox/submit` | 渠道绑定与隐私安全通道 |
| `POST /webhooks/feishu` · `POST /webhooks/openclaw/wechat` | 渠道入站 |
| `GET /api/admin/traces` · `/api/admin/audit` · `/api/admin/feedback` | 管理接口（管理员令牌） |

### Harness

- **轨迹日志**：每个图节点一行（`agent_traces`）：输入摘要、工具、参数、结果摘要、耗时、模型档位、token 估算、逐次 LLM 调用、护栏命中；入库前统一脱敏。写入走后台批量队列。
- **防泄露**：所有出站文本过滤密钥、系统提示词原文、他人数据和隐私沙盒值；检查失败 fail closed（`E_GUARD_UNAVAILABLE`），节点异常只返回 `E_NODE_FAILED`。
- **确认门禁**：草稿、定时任务创建 / 修改 / 删除都走确认卡；外部工具需一次性、参数绑定的确认凭证。
- **金标回归**：`tests/golden/`（安慰、危机、泄露、轨迹鉴权）。安全类必须零失败；质量类与 `baseline.json` 比较。

```bash
python tests/golden/run_golden.py                       # mock LLM，CI 默认
python tests/golden/run_golden.py --mode live           # 真实模型（需 key）
python scripts/harness_golden.py                        # CI 门禁入口
python -m pytest -q
```

### 可观测性（Langfuse）

`LANGFUSE_ENABLED=1` 后经 OpenTelemetry 导出分层 span；每个 `/api/*` 响应带 `X-Trace-Id`；对话气泡下的 👍/👎 调 `POST /api/feedback`。评审 rubric（共情 / 危机处理）：`python -m app.evals.cli`。

## 二次开发

想在这个底座上加工具、接新渠道、换记忆实现或改编排，先读 [CONTRIBUTING.md](CONTRIBUTING.md)：它是给新人的地图，按改动深度分五层，标出入口文件、必须同步的契约测试和不能动的安全不变量。

接上真实模型 Key 后，跑一次 `python scripts/live_smoke.py` 可以生成一份真实模型下的主流程记录（`docs/live-smoke-report.md`），作为「正常长什么样」的参照。

## License

[MIT](LICENSE)。
