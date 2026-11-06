# 小满学习搭子

一个以对话为主的学习网页：你只管上课和交资料，小满记得你学到哪，每天告诉你该学的三件事，让你看得见自己在进步。

这是 6 人小组两周 MVP 的协作仓库。后端以开源项目 [Personal-Agent](https://github.com/hubooooooo/Personal-Agent)（MIT）为底座，不用 Dify；前端另建 React 项目。

## 先读这些

| 文档 | 在线版（以它为准） | 仓库里的快照（2026-11-04） |
| --- | --- | --- |
| **分工方案**（6 个角色、协作方式、共同约定） | —（以仓库为准） | [docs/分工方案.md](docs/分工方案.md) |
| **每人的交接文档**（负责什么、目标、和谁对接） | —（以仓库为准） | [docs/交接/](docs/交接/) |
| MVP PRD（功能、验收、产品规则） | [链接](https://claude.ai/artifact/NvuYb5wf2gi39FR7Mujmk7) | [docs/xiaoman/MVP-PRD.md](docs/xiaoman/MVP-PRD.md) |
| 技术实现主文档（数据表、接口、模块） | [链接](https://claude.ai/artifact/FwzuAyM7n8Foi1xbG9BuDd) | [docs/xiaoman/技术实现主文档.md](docs/xiaoman/技术实现主文档.md) |
| 可点击 demo | [链接](https://claude.ai/artifact/QNQPNJgPJin1rsqk4HqLvM) | [demo/index.html](demo/index.html) |

快照里的图（架构图、路线图、流程图）只留了标题，看图请打开在线版。在线版更新后，快照由 A 定期同步。

## 仓库结构

| 位置 | 是什么 | 谁负责 |
| --- | --- | --- |
| `app/`、`tests/`、`scripts/`、`config/`、`intents/`、`static/` 等 | Personal-Agent 底座原有的后端代码和测试 | 底座本身尽量不改，新功能放各线自己的模块 |
| `app/prompts/<名字>/vN.md` | 版本化提示词文件，每个 AI 能力一个 | 各能力所属的线 |
| `web/` | React 前端：对话页骨架、卡片组件、各线自己的文件夹 | 骨架和组件共用，改动由 A 拍板 |
| `app/study/` | 学习搭子的后端（五条线 + 共用表和假接口） | 各线只改自己的文件夹；`common/` 要改先找 A |
| `docs/地基给各线.md` | 代码放哪、怎么接 AI、怎么测 | 地基写好后给五条线 |
| `demo/` | 可点击 demo（单个 HTML，数据都是预设的） | A |
| `docs/分工方案.md`、`docs/交接/` | 分工和每人的交接文档 | A |
| `docs/xiaoman/` | PRD 和技术主文档的快照 | A |
| `docs/` 其余文件、`CONTRIBUTING.md`、`DESIGN.md` | 底座自带的文档 | — |

## 本地跑起来

**demo**：用浏览器直接打开 `demo/index.html`。

**后端底座**（需要 Python 3.12）：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -c requirements.lock
cp .env.example .env
```

打开 `.env`，至少填 `AUTH_SECRET`（生成：`python -c "import secrets; print(secrets.token_hex(32))"`）。不填模型 key 也能启动，聊天走离线占位。然后：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

打开 http://127.0.0.1:8787/health 看到正常返回就是跑起来了。测试：

```bash
pip install -r requirements-dev.txt -c requirements.lock
python -m pytest -q
```

更多见 [docs/personal-agent-README.md](docs/personal-agent-README.md)（底座原 README）。

**地基（后端 + 对话页）**：不需要模型 key，也不需要 Supabase。在上面的虚拟环境里：

```bash
cp .env.example .env
python scripts/ensure_local_auth.py
```

这条脚本只在 `AUTH_SECRET` 为空时，写进一串本机随机值，用来给网页会话签名。它不是模型密钥，也不会打印出来。`.env.example` 里 `XIAOMAN_MVP=1` 会藏起飞书、微信、写草稿、安全输入区和记忆卡这些两周用不到的入口。危机识别和出站护栏还在。

两个终端分别跑：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

```bash
cd web && npm install && npm run dev
```

浏览器打开 http://127.0.0.1:5173 。中间是对话，左边是今天三件，右边工作台可以打开。接口说明在 http://127.0.0.1:8787/docs 。

前端构建和测试：`cd web && npm test && npm run build`。

五条线从哪写起，见 [docs/地基给各线.md](docs/地基给各线.md)。A 已经定过的几件事（表分开、强度算在今天、三个授权开关、对话用切块 SSE、临时配色、学习表不进底座的权限迁移、MVP 里停用抓网页和写草稿）也写在那一页。界面视觉已定为湖泊蓝（2026-11-06），见 [design/approved-lake-blue/](design/approved-lake-blue/README.md)；各线用 `web/src/components/ui.tsx` 的组件和 `web/src/styles.css` 的变量，不自己写样式。

## 怎么协作

详见 [docs/分工方案.md](docs/分工方案.md)。简单说：

1. `git clone` 本仓库，在自己的分支上做自己那条线，不直接改 `main`。
2. 做完后一次性提一个 PR 给 A。提之前，自己的模块要在浏览器里完整跑通，自动测试通过。
3. 共用的东西（对话页骨架、卡片组件、数据表、接口约定）要改，先在群里说，由 A 拍板。
4. 改提示词要新建下一版文件，评测分数不降才算改好。
5. 密钥只放 `.env`，不提交、不发群、不截图。`.env` 已在 `.gitignore` 里。
6. 让 AI 写代码前，先让它读 `CLAUDE.md` / `AGENTS.md`（两份内容一致）。

## 来源与许可

后端代码来自 [hubooooooo/Personal-Agent](https://github.com/hubooooooo/Personal-Agent)，按 MIT 许可使用，原作者的版权声明保留在 [LICENSE](LICENSE)，原提交记录也保留在本仓库历史里。
