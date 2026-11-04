# 小满学习搭子

一个以对话为主的学习网页：你只管上课和交资料，小满记得你学到哪，每天告诉你该学的三件事，让你看得见自己在进步。

这是 6 人小组两周 MVP 的协作仓库。后端以开源项目 [Personal-Agent](https://github.com/hubooooooo/Personal-Agent)（MIT）为底座，不用 Dify；前端另建 React 项目。

## 先读这些

| 文档 | 在线版（以它为准） | 仓库里的快照（2026-11-04） |
| --- | --- | --- |
| 两周分工方案 v2（每人一节，可直接复制给自己的 AI） | [链接](https://claude.ai/artifact/NEi85sxozNCLQYHdPbG681) | [docs/xiaoman/两周分工方案-v2.md](docs/xiaoman/两周分工方案-v2.md) |
| MVP PRD（功能、验收、产品规则） | [链接](https://claude.ai/artifact/NvuYb5wf2gi39FR7Mujmk7) | [docs/xiaoman/MVP-PRD.md](docs/xiaoman/MVP-PRD.md) |
| 技术实现主文档（数据表、接口、模块） | [链接](https://claude.ai/artifact/FwzuAyM7n8Foi1xbG9BuDd) | [docs/xiaoman/技术实现主文档.md](docs/xiaoman/技术实现主文档.md) |
| 可点击 demo | [链接](https://claude.ai/artifact/QNQPNJgPJin1rsqk4HqLvM) | [demo/index.html](demo/index.html) |

快照里的图（架构图、路线图、流程图）只留了标题，看图请打开在线版。在线版更新后，快照由 A 定期同步。

## 仓库结构

| 位置 | 是什么 | 谁负责 |
| --- | --- | --- |
| `app/`、`tests/`、`scripts/`、`config/`、`intents/`、`static/` 等 | Personal-Agent 底座原有的后端代码和测试 | D（底座本身尽量不改，新功能放单独模块） |
| `app/prompts/<名字>/vN.md` | 版本化提示词文件，每个 AI 能力一个 | E、F |
| `demo/` | 可点击 demo（单个 HTML，数据都是预设的） | A |
| `docs/xiaoman/` | 我们的需求和分工文档快照 | A |
| `docs/` 其余文件、`CONTRIBUTING.md`、`DESIGN.md` | 底座自带的文档 | — |
| `web/`（待建） | React 前端 | B、C |
| `evals/`（待建） | 评测用例和评测脚本 | F |

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

## 怎么协作

1. `git clone` 本仓库后，每个功能开一个分支，不直接改 `main`。
2. 提 PR，至少一位同学在本地跑过、点过才合并；底座的测试要保持全绿。
3. 接口、卡片、数据表的格式要改，先在群里说，前端确认了再改。
4. 改提示词一次只改一处，新建下一版文件，评测分数不降才合并。
5. 密钥只放 `.env`，不提交、不发群、不截图。`.env` 已在 `.gitignore` 里。
6. 让 AI 写代码前，先让它读 `CLAUDE.md` / `AGENTS.md`（两份内容一致）。

## 来源与许可

后端代码来自 [hubooooooo/Personal-Agent](https://github.com/hubooooooo/Personal-Agent)，按 MIT 许可使用，原作者的版权声明保留在 [LICENSE](LICENSE)，原提交记录也保留在本仓库历史里。
