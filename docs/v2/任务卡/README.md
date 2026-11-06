# 任务卡 · 给接手的 AI（Codex / Grok + Cursor / Claude）

> 维护：A（项目负责人）· 2026-11-06 · 方案依据：`docs/v2/V2-方案.md` 第 11 节（V2.0 最小版，已确认）

## 开工前必读（按顺序）
1. 仓库根目录 `AGENTS.md`（= `CLAUDE.md`）：产品规则 8 条、视觉基准、禁止事项。**违反任何一条，PR 不收。**
2. `docs/v2/V2-方案.md`，重点第 6 节（规则 9–11）和第 11 节（最小版技术方案）。
3. 你要做的那张卡。**只做卡里写的事**；卡外的问题写进 PR 的“发现的其他问题”，不要顺手改。

## ⚠️ 工作目录
A 本机的仓库在 iCloud“文稿”里，git 和 `.venv` 已被 iCloud 损坏（`git show-ref` 崩溃）。**不要在那个文件夹里工作。** 请在 iCloud 以外重新克隆：
```bash
git clone https://github.com/Ricardozdw/xiaoman-study-buddy-demo.git ~/code/xiaoman-study-buddy-demo
cd ~/code/xiaoman-study-buddy-demo
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cd web && npm ci
```
`.env` 找 A 要（里面是本机 `AUTH_SECRET`；**密钥不进仓库、不贴对话**）。

## 每张卡的流程
1. 从最新 `main` 开分支，分支名写在卡里。
2. 写代码 + 测试。后端 `pytest` 全绿（跳过数不变），前端 `npm test`、`npm run build` 通过。
3. 浏览器里按卡上的“验收”逐条点过（本机 8787、8788 常被占用，后端换空闲端口，vite 代理 `/api` 过去）。
4. 开 PR 到 `main`：标题写卡号；正文逐条贴验收结果（截图 / 数值 / 命令输出），写“改了哪些文件”“没做的”“发现的其他问题”。
5. **不要自己合并。** 开好告诉 A；Claude 按卡验收，A 合并。

## 通用约定
- V2 代码只放 `app/study/v2/`、`web/src/lines/v2/`、`app/prompts/goal.outline/`、`tests/test_v2_*.py`、`web/src/lines/v2/*.test.ts`。要碰别的文件，卡里会写明哪几行；卡里没写的不碰。
- 开关：`XIAOMAN_V2=1`。**开关关掉时，现有全部测试必须照旧通过，页面和原来完全一样。**
- 每个 AI 能力 = 版本化提示词 `app/prompts/<名字>/vN.md` + 后端函数，经 `app/gateway/` 调用（参考 `app/study/plan/opening.py` 和 `app/study/practice/capabilities.py`）；没配模型时有确定性的模拟结果，并标“模拟”。
- 数据库：新表在 `app/study/v2/models.py`，同时登记到 `app/study/common/schema.sql`（Postgres 行级安全：只能读写自己 `user_id` 的行），CI 的 `postgres-rls` 必须通过。
- 界面：颜色、字号、圆角只用 `web/src/styles.css` 的变量；按钮、气泡、卡片、标签只用 `web/src/components/ui.tsx`（`Button`、`Bubble`、`Card`、`Badge`）。不写暗色样式。
- 文案：中文、温和、不追责；不说“你断了几天”“不及格”。

## 卡片一览
| 卡 | 内容 | 建议执行 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| T01 | 对话区样式与文案小修 | Codex | — | 卡在 PR #9 |
| T02 | V2 地基：开关、两张表、路由骨架 | Codex | — | 待开工 |
| T03 | 学习大纲 `goal.outline` + 写成讲次 | Codex | T02 | 待开工 |
| T04 | 阶段测验 + 成绩报告（后端） | Codex | T03 | 待开工 |
| T05 | V2 前端：定目标 5 问 + 大纲卡 | Grok（Cursor） | T03、PR #9 | 待开工 |
| T06 | 目标完成（后端） | Codex | T04 | 待开工 |
| T07 | V2 前端：测验卡、成绩报告卡、完成卡 | Grok（Cursor） | T04、T06 | 待开工 |
| T08 | 统一模型配置 | Grok（Cursor） | A 定主备模型 | 等 A |

可以并行：T01、T02 现在就能开工；T03 合并后 T04、T05 可以并行；T06 合并后做 T07。

## 给 AI 的开工话术（A 复制粘贴用）
> 你在仓库 `Ricardozdw/xiaoman-study-buddy-demo` 工作。先完整读 `docs/v2/任务卡/README.md`，再读任务卡 `docs/v2/任务卡/<卡号>-….md`，按卡执行。只做卡里写的事；按 README 的流程开分支、写测试、在浏览器里逐条验收，开 PR 到 main，PR 正文逐条贴验收结果。不要合并，不要改卡里没写的文件，不要把任何密钥写进代码或对话。有疑问先停下来问我。

## 验收（Claude）
A 把 PR 链接发给 Claude：“按任务卡 Txx 验收 PR #N”。Claude 读卡 → 拉分支 → 跑测试 → 浏览器逐条核对 → 列出不通过项，或者告诉 A 可以合并。
