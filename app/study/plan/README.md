# 计划线（4 号线）

负责 PRD 的 F1 目标拆解、F5 今天三件事与强度、F6 中断后回来、F7 里小满开场与建议，以及“跳到明天”演示开关。演示 8 步里的第 1、5、6、7 步。

排程、强度、中断后回来都用后端规则算，不用 AI。只有“小满开场”一个 AI 能力。

## 文件

| 文件 | 做什么 |
| --- | --- |
| `scheduler.py` | 排程规则（只做计算）：三处来源各取一件，某处没有由另外两处顶上，最多三件；有之前的错题时补一补排第一；强度只改分量 |
| `service.py` | 读学习记录、生成并保存当天计划、勾任务、出卡 / 接受 / 撤销 / 先不用、调强度建议 |
| `goal.py` | 目标拆解：问题、拆解卡、说说怎么改、生效 / 撤销 |
| `parse.py` | 把一句话解析成日期、讲数、学到第几讲、每天时间、强度 |
| `returning.py` | 中断后回来：判断情况、算空余天、生成卡片（只做计算） |
| `daily.py` | 收工卡、引导下一件、调强度卡、快捷回复（只做计算） |
| `opening.py` + `app/prompts/plan.opening/v1.md` | AI 能力“开场与建议” |
| `progress.py` | 给看板线的计划数据 |
| `demo.py` | 演示开关（`XIAOMAN_DEMO_CLOCK=1` 才开） |
| `routes.py` | 接口 |

前端在 `web/src/lines/plan/`。

## 接口

都在 `/api` 下，返回外层是 `{ok, status, mock, data}`。在 http://127.0.0.1:8787/docs 里能点。

| 接口 | 说明 |
| --- | --- |
| `GET /plan/today` | 今天三件。字段：<br>`tasks`：每件带 `reason`、`amount`、`minutes`<br>`first_task_id`：先做这件<br>`card`：当前唯一待选的卡<br>`undoable`：今天最近一张能撤销的卡<br>`done_card`：收工卡<br>`needs_setup`：还没定目标<br>`mood`：小满状态<br>`quick_replies`：快捷回复 |
| `PATCH /plan/today` | 用户自己切强度，直接生效 |
| `PATCH /tasks/{id}` | 勾选 / 取消。返回 `next`（下一件：开始 / 晚点再做）、`all_done`、`done_card` |
| `POST /tasks/{id}/later` | 晚点再做：这件挪到最后 |
| `GET /goals/questions` | 定目标的五道题，带快捷回复和“先按……安排” |
| `POST /goals/draft` | 按回答出目标拆解卡（不生效） |
| `POST /goals/draft/{id}/revise` | 说说怎么改：`{"text": "考试改到 12 月 20 日"}`，出新卡替换旧卡 |
| `POST /goals` · `GET /goals/current` | 用户直接改目标（直接生效）/ 读目标（带 `needs_setup`、`chosen`、`phases`） |
| `POST /suggestions/{id}/accept` | 点卡上的选项，才生效。正文可带 `{"option": "...", "exam_date": "YYYY-MM-DD"}`；只有一个选项时可以不带 |
| `POST /suggestions/{id}/dismiss` | 先不用 |
| `POST /actions/{id}/undo` | 撤销：恢复改之前的状态，今天没做的重排，做完的保留 |
| `POST /plan/adjust` | “今天只有 15 分钟”这类话 → 调强度建议卡 |
| `GET /plan/quick-replies` | 只给当下说得通的快捷回复 |
| `GET /plan/opening` | 小满开场白，同一天只生成一次 |
| `GET /plan/progress` | 给看板：这周学了几天、目标进度、离考试几天、当前阶段 |
| `GET /demo/clock` · `POST /demo/clock` · `POST /demo/clock/reset` | 演示开关：查看 / 往后跳 `{"days": 1}` / 回到今天 |

卡片的种类（`card.kind`）：

| kind | 什么时候出 |
| --- | --- |
| `goal_setup` | 目标拆解 |
| `return_light` | 回来时落后不多 |
| `return_reschedule` | 回来时落后较多 |
| `return_goal` | 超过 7 天没打开，或考试日期已过 |
| `adjust_intensity` | 用户说“今天只有 15 分钟”这类话 |

同一时间最多一张待选。

## 规则怎么算

- **今天三件**：当天第一次打开时算一次，存起来，同一天不重排。没做的不搬到新的一天。新的一天回到目标定的默认强度。
- **学新的**：已学到的那一讲的下一讲。课件没交就是“交第 N 讲课件”。勾完推进到下一讲。
- **练一练**：学过、有资料的讲里，掌握度低、隔得久的先练。
- **补一补**：先是之前做错、之后没做对的题（按讲合成一件，今天刚错的明天才排），再是到期且掌握度低于 80 的知识点。
- **中断后回来**：
  - 隔 2–7 天：看空余天（离考试天数 − 没学的讲数）。空余天 ≥ 复习底线（默认 7 天，定目标时按实际情况定）出建议卡，否则出重排卡。
  - 隔 8 天及以上：先出目标卡。
- **目标拆解**：按一天一讲排“学新讲”，剩下的时间是“刷题”，考前 3 天“冲刺”。每天时间 ≤20 分钟默认轻松，≤40 分钟默认正常，更多默认冲刺。

## 和别的线怎么接

- **问答线**：识别到“调安排”时，调 `service.adjust_from_text(user_id, text)`。它会返回一张卡，或一句回复（已经是那一档 / 没听懂）。
- **资料线**：讲次编号先按“第 N 讲 = `lec-N`”。`files.parse_status == "ready"` 就算这一讲资料交了。**这个约定待资料线确认。**
- **练习线**：错题按“这道题最后一次作答是错的”算，掌握度读 `knowledge_points.mastery` 和 `next_review_on`，都是只读。**口径以练习线的实现为准。**
- **看板线**：读 `GET /api/plan/progress`。不要显示“连续 N 天”。

## 需要 A 定的事

1. **卡片挂进对话流**：现在计划线面板挂在右侧工作台底部（Shell 里的 `<PlanLine />`）。正式应该出现在对话流里，要改 `Shell.tsx`。改到左栏的操作现在靠刷新整页；挂进去后可以改成回调刷新左栏。
2. **卡片和开场的文案**：都是占位。改文案只动 `returning.py`、`daily.py`、`goal.py`、`opening.py` 里的字。测试会扫禁用词。
3. **地基写死的样例计划和目标**：新用户一开始就有一份样例目标（没确认过），所以左栏先有三件，同时 `needs_setup` 为 true。计划线会在一件没勾时替换样例计划。建议以后不写死，新用户左栏就是空的，等定完目标再出三件。
4. **“模拟”标记**：计划线的规则是真的，但上游资料、练习现在还是假数据，所以暂时都标“模拟”。等各线接通后再去掉。
5. **上线环境**：把 `XIAOMAN_DEMO_CLOCK` 设成 0。
6. **只有计划线跟着演示开关跳日期**：看板线的“这周”自己算的话，还按真实日期算。

## 测试

```bash
python -m pytest -q tests/test_plan_scheduler.py tests/test_plan_demo_clock.py tests/test_plan_returning.py tests/test_plan_goal.py tests/test_plan_daily.py tests/test_plan_opening.py
cd web && npm test
```
