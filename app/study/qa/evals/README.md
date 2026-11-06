# 问答评测：自编公开演示资料

`corpus.json` 包含 8 页合成讲义、30 条资料内问题和 20 条资料外问题，均为本项目自编，可按 CC0-1.0 使用。不是正式 PMP 教材、官方试题或真实课程。`build_sample.py` 是明确手写的讲义与标注源，可显式运行重建 JSON，导入模块不写文件或数据库。

先在仓库根目录执行：

```bash
.venv/bin/python -m app.study.qa.evals.runner
.venv/bin/python -m pytest tests/test_qa_evals.py -q
.venv/bin/python -m app.study.qa.evals.runner --export-lecture work/synthetic-lecture.json
```

默认只校验语料结构、30/20 数量、页码、原句和非空答案关键词，不请求 HTTP 或模型，不生成虚假的质量分数或延迟。导出的 JSON 需通过资料线显式导入为同一用户的 8 页资料。不要把资料线原有两页 `lec-6` 模拟内容当成本讲义。资料导入及用户会话应使用本地隔离演示环境，真实课件或正式模型尚未选定时停留在离线检查即可。

资料已导入并获得 lecture_id、模型已配置后，才显式执行（会发送 50 次真实模型请求并产生费用）：

```bash
.venv/bin/python -m app.study.qa.evals.runner --live \
  --base-url http://127.0.0.1:8787 \
  --cookie-file work/local-session-cookie.json \
  --lecture-id YOUR_IMPORTED_LECTURE_ID \
  --output work/qa-live-results.json
```

cookie 文件格式为 `{"cookie":"session_cookie_name=value"}`，使用服务实际的 cookie 名称。文件仅在本地保存，不提交到 Git；凭证不放在命令行参数、评测结果或文档中。HTTP 重定向一律拒绝；非本地服务要求 HTTPS；base URL 只能为无凭证、路径和查询参数的 origin。

live 在首次模型请求之前，通过同会话 GET `/api/lectures/{id}/pages` 验证 8 页正文严格一致；随后只调用 `/api/chat/stream`。每个 case 独立发起会话、不复用 thread。它消费真实 SSE `meta`、兼容 `{delta}`、`references`、`complete`、`[DONE]`；完整 UTF-8 和事件完成后才计入 delta。心跳、meta、空字符串、服务器自报的 `first_text_ms` 均不作为客户端首字时间。

每条结果记录文本、引用、失败原因和客户端首字毫秒；不保存 cookie、base URL、输入 headers 或异常全文。输出在每条完成后刷新，即使中途停止也保留之前结果。mock 或未知 provenance、缺失帧、错误 scope、`ok=false`、断流、无实际 delta、引用为空/原句不匹配/lecture 不匹配都失败。服务器删掉的错误引用也计入失败。资料外必须明确说明本讲义没有依据，且不得返回任何引用或页码。答案关键词和标注原句的匹配刻意保守，允许人工复核同义表达造成的假阴性。

汇总展示资料内引用通过率（目标 ≥95%）、资料外完整通过率（目标 100%）、首字 p50/p95 和是否所有请求 ≤5000ms。只有完整 50 条、所有严格 case 检查通过且全部首字 ≤5秒时，总 `passed` 才为 true；这是比单独引用率更严格的自动门槛。空集、仅提供引用帧、删错引后表面无误，均不能获得通过。

这组自编材料的自动评测只能证明针对当前合成案例的表现，不能代替真实课程质量验证和人工语义评审。当前交付仅进行了离线校验和传输字节 fixture 测试，没有进行真实模型质量或延迟测量。
