# 小满上线记录（腾讯云开发 + Supabase）

> 不含任何密钥。密钥 / 数据库密码只在本机 `.env`（模型 Key）和 `.env.deploy`（数据库与会话密钥），两者都已 gitignore。

## 线上资源

| 项 | 值 |
| --- | --- |
| 访问地址 | https://xiaoman-api-341891-6-1317663597.sh.run.tcloudbase.com （根路径自动跳到 `/study/`） |
| 云开发环境 | `xhs-demo-d0gj034jw4870181f`（体验版，到期 2027-05-05；与 xhs、gic 两个产品共用每月 3000 资源点） |
| 服务 | `xiaoman-api`（容器型，0.25 核 / 0.5 GB，实例 0–1，闲置会缩到 0） |
| 数据库 | Supabase 项目 `xiaoman`（ref `kliozyikhjjhiglqfbge`，东京 ap-northeast-1，免费版） |
| 连接方式 | 连接池会话模式 `aws-0-ap-northeast-1.pooler.supabase.com:5432`，用户名 `角色.kliozyikhjjhiglqfbge`（直连地址只有 IPv6，云托管连不上） |
| 数据库角色 | `xm_owner` 只用于建表；运行时 `xm_app`（DATABASE_URL）/ `xm_system`（SYSTEM_DATABASE_URL），都不能绕过 RLS |

## 线上环境变量（名字；值见本机文件）

密钥（从 `.env` / `.env.deploy` 读）：`DEEPSEEK_API_KEY` `DASHSCOPE_API_KEY` `KIMI_API_KEY` `AUTH_SECRET` `HARNESS_ID_HMAC_KEY` `SECRETS_FERNET_KEY` `DATABASE_URL` `SYSTEM_DATABASE_URL`

固定值：`PORT=8080` `XIAOMAN_MVP=1` `XIAOMAN_V2=1` `XIAOMAN_DEMO_CLOCK=0` `PROACTIVE_ENABLED=0` `FEISHU_ENABLED=0` `FEISHU_WS_ENABLED=0` `OPENCLAW_WECHAT_ENABLED=0` `DATA_DIR=/app/data` `CORS_ALLOW_ORIGINS=<访问地址>` `LLM_CONFIG_JSON=<deploy/xiaoman/models.example.json 压成一行>`

**每次写环境变量都是整组覆盖**，要把上面全部列上（见工具包 `docs/手册/参考代码/腾讯云开发/set_cloudrun_env.py`）。

## 更新上线（代码改完后）

1. 用 git 导出干净源码，并把小满的 Dockerfile 放到根目录：
   `git archive HEAD | tar -x -C <临时目录> && cp deploy/xiaoman/Dockerfile <临时目录>/Dockerfile`
2. 用工具包脚本部署（会检查包里没有密钥）：
   `python3 docs/手册/参考代码/腾讯云开发/deploy_cloudrun.py --env-id xhs-demo-d0gj034jw4870181f --service xiaoman-api --source <临时目录> --port 8080 --secret-file <仓库>/.env --secret-file <仓库>/.env.deploy`
3. 环境变量会沿用；要改时用 `set_cloudrun_env.py` 整组重写。

## 数据库变更

表结构改了（新增表 / 列）时，用管理员账号重跑一键建库脚本（可重复执行）：
`OWNER_DATABASE_URL=postgresql://xm_owner.kliozyikhjjhiglqfbge:<XM_OWNER_PASSWORD>@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require XM_APP_PASSWORD=… XM_SYSTEM_PASSWORD=… python deploy/xiaoman/provision_pg.py`
注意：脚本只补“没有的表”，已有表加列需要另写迁移。

## 上线验收（2026-11-08，Claude 实测）

- 新用户：定目标 → 大纲 → 讲解 → 练习 → 考试 → 今天完成；手机 390px 无横向滚动
- 用户隔离：第二个用户看不到第一个用户的大纲 / 错题 / 成绩；应用账号不带身份查库 0 行
- 重启后：环境变量重写 ×2、代码重新部署 ×1，同一浏览器仍是同一用户，进度还在
- Supabase 安全检查 0 项问题；匿名角色对所有表 0 权限

## 已知限制

- **测试域名提示页**：浏览器第一次打开（及约 15 分钟后）会先看到腾讯云“页面访问提示”，点「确定访问」即可。只有绑定已备案的自有域名才能去掉。
- **慢**：库在东京、服务在上海，每次查库约 80–100ms；首屏约 6 秒，完成卡等要 10 秒左右才出来。闲置后第一次访问还要等服务冷启动。
- **重启会丢的**：调用轨迹 / 费用台账（audit.db）、闲聊的短期上下文（checkpoints.db）。学习数据、对话消息都在数据库里。
- **谁拿到链接都能用**：没有邀请码，每个浏览器自动是一个新用户，会消耗模型额度。先只发给信任的试用者。
- 曾出现 1 次“服务重启后浏览器被当成新用户”，之后 3 次重启都没复现，原因未查明，请试用时留意。
