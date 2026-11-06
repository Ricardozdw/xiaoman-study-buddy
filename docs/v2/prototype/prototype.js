// 小满 V2 可点击原型：定目标 → 交资料（可选）→ 拆解 → 每天三件 → 阶段测验 → 目标完成。
// 纯前端演示，不接后端。规则按 ../V2-方案.md：每天最多三件、改计划先出卡点了才生效、一次只让用户做一个决定。
"use strict";

const $ = (id) => document.getElementById(id);
const stream = $("stream");
const quick = $("quick");
const chat = document.querySelector(".chat");

// ---------- 演示内容 ----------
const TEMPLATES = {
  cert: {
    ask: "哪个证书？",
    picks: ["PMP", "教师资格证", "软考中级"],
    title: (x) => `考过 ${x}`,
    material: ["项目管理概述", "整合管理", "范围管理", "进度管理", "成本管理", "质量管理", "资源与沟通", "风险与采购", "相关方管理"],
    outline: ["项目管理框架与术语", "项目启动与章程", "范围与需求", "进度与关键路径", "成本与挣值", "质量与风险", "团队与沟通", "敏捷与混合方法"],
    file: "PMP 备考指南（第 1–9 章）.pdf",
  },
  course: {
    ask: "哪门课或哪本书？",
    picks: ["《项目管理》网课", "《原则》这本书"],
    title: (x) => `学完${x}`,
    material: ["第 1 章 引言", "第 2 章 基本概念", "第 3 章 方法", "第 4 章 案例一", "第 5 章 案例二", "第 6 章 进阶", "第 7 章 总结"],
    outline: ["整体框架", "核心概念", "关键方法", "典型案例", "常见误区", "综合应用"],
    file: "课程讲义（第 1–7 章）.pdf",
  },
  skill: {
    ask: "想掌握什么技能？",
    picks: ["Excel 数据透视表", "Python 入门"],
    title: (x) => `学会 ${x}`,
    material: ["数据整理规范", "创建透视表", "字段与布局", "值汇总与计算", "筛选与切片器", "透视图", "综合案例"],
    outline: ["数据整理规范", "创建第一张透视表", "字段与布局", "汇总方式与计算字段", "筛选与切片器", "透视图与报表", "综合练习"],
    file: "Excel 透视表教程.pdf",
  },
};

const QUESTIONS = [
  { stem: "项目的关键路径指的是？", opts: ["花钱最多的那条路径", "总工期最长、决定项目最早完成时间的路径", "最先开始的那条路径"], ok: 1, why: "关键路径上任何一项延误，都会推迟整个项目。" },
  { stem: "想多学一点时，小满会怎么做？", opts: ["今天加到五件", "件数不变，每件的分量加大", "把明天的任务挪过来"], ok: 1, why: "每天最多三件，想多学就调强度。" },
  { stem: "范围蔓延最常见的原因是？", opts: ["需求变更没有走变更流程", "团队人数太多", "进度太快"], ok: 0, why: "未经控制的需求变更，会让范围不断变大。" },
  { stem: "挣值管理里，CPI < 1 说明？", opts: ["进度落后", "成本超支", "质量达标"], ok: 1, why: "CPI = EV / AC，小于 1 表示花的钱比完成的价值多。" },
];

const INTENSITY = { light: { label: "轻松", min: 15, q: 3 }, normal: { label: "正常", min: 30, q: 5 }, sprint: { label: "冲刺", min: 50, q: 8 } };

// ---------- 状态 ----------
let S;
function fresh() {
  return {
    step: "q1", type: null, goal: "", deadline: "", days: 60, minutes: 30, hasMaterial: null, progress: "刚开始",
    src: null, units: [], intensity: "normal", day: 1, unit: 0, tasks: [], wrong: [], quizIdx: 0,
    started: false, mastery: [], score: null, pending: null, finished: false,
  };
}

// ---------- 渲染小工具 ----------
function el(tag, cls, html) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
}
function scrollDown() {
  requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; });
}
function say(text) {
  const m = el("div", "msg x");
  m.appendChild(el("p", "", text));
  stream.appendChild(m);
  scrollDown();
}
function me(text) {
  const m = el("div", "msg u");
  m.appendChild(el("p", "", text));
  stream.appendChild(m);
  scrollDown();
}
function dayLine(text) {
  stream.appendChild(el("p", "day", text));
}
function card(html, opts = {}) {
  const c = el("article", "card" + (opts.wide ? " wide" : ""), html);
  stream.appendChild(c);
  scrollDown();
  return c;
}
function btn(label, primary, onClick) {
  const b = el("button", "btn" + (primary ? " primary" : ""), label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}
function actions(c, buttons) {
  const row = el("div", "btns");
  buttons.forEach((b) => row.appendChild(b));
  c.appendChild(row);
}
// 一次只让用户做一个决定：出新卡前，把还没处理的那张收起。
function decisionCard(html, buttons, opts) {
  if (S.pending) settle(S.pending, "先放着了，之后还能再找小满。");
  const c = card(html, opts);
  actions(c, buttons);
  c.appendChild(el("p", "decided-note"));
  S.pending = c;
  return c;
}
function settle(c, note) {
  c.classList.add("decided");
  const n = c.querySelector(".decided-note");
  if (n) n.innerHTML = note;
  if (S.pending === c) S.pending = null;
}
function replies(list) {
  quick.innerHTML = "";
  list.forEach(([label, fn, ghost]) => {
    const b = el("button", ghost ? "ghost" : "", label);
    b.type = "button";
    b.addEventListener("click", () => { quick.innerHTML = ""; fn(label); });
    quick.appendChild(b);
  });
}

// ---------- 定目标：一次一题 ----------
function start() {
  S = fresh();
  stream.innerHTML = "";
  quick.innerHTML = "";
  dayLine("第 1 天 · 第一次见面");
  say("你好，我是小满。先说说你想学成什么样？\n我帮你拆成每天三件事，陪你走到完成。");
  replies([["考过一个证书", () => pickType("cert")], ["学完一门课或一本书", () => pickType("course")], ["掌握一项技能", () => pickType("skill")]]);
  renderRail();
}
function pickType(type) {
  S.type = type;
  const t = TEMPLATES[type];
  me({ cert: "考过一个证书", course: "学完一门课或一本书", skill: "掌握一项技能" }[type]);
  S.step = "q1b";
  say(t.ask);
  replies(t.picks.map((p) => [p, () => setGoal(p)]));
}
function setGoal(x) {
  me(x);
  S.goal = TEMPLATES[S.type].title(x);
  S.step = "q2";
  say(`好，目标是「${S.goal}」。什么时候想完成？`);
  replies([
    ["12 月 20 日", () => setDeadline("12 月 20 日", 44)],
    ["一个月内", () => setDeadline("一个月内", 30)],
    ["三个月内", () => setDeadline("三个月内", 90)],
    ["不急，先学着", () => setDeadline("不急，先学着", 60)],
  ]);
}
function setDeadline(label, days) {
  me(label);
  S.deadline = label;
  S.days = days;
  S.step = "q3";
  say("每天大概有多少时间？下班后十几分钟也行。");
  replies([["15 分钟", () => setMinutes(15)], ["30 分钟", () => setMinutes(30)], ["50 分钟", () => setMinutes(50)]]);
}
function setMinutes(m) {
  me(`${m} 分钟`);
  S.minutes = m;
  S.intensity = m <= 20 ? "light" : m <= 40 ? "normal" : "sprint";
  S.step = "q4";
  say("手上有课件、教材或考纲吗？\n有就交给我，排得更准；没有也可以先开始。");
  replies([["有，现在交", () => material("now")], ["有，晚点交", () => material("later")], ["没有", () => material("no")]]);
}
function material(choice) {
  S.hasMaterial = choice;
  me({ now: "有，现在交", later: "有，晚点交", no: "没有" }[choice]);
  if (choice === "now") {
    readFile(() => { S.src = "material"; S.units = TEMPLATES[S.type].material.slice(); askProgress(); });
  } else {
    showOutline();
  }
}
function readFile(done) {
  const t = TEMPLATES[S.type];
  me(`📎 ${t.file}`);
  const c = card(`<div class="meta-row"><span>交资料</span><span class="badge">读取中</span></div>
    <h3>正在读你的资料</h3><p class="sub" id="readTxt">按页读文字…</p><div class="progress"><i id="readBar"></i></div>`);
  let page = 0;
  const total = 120;
  const timer = setInterval(() => {
    page = Math.min(total, page + 20);
    c.querySelector("#readBar").style.width = `${(page / total) * 100}%`;
    c.querySelector("#readTxt").textContent = `按页读文字… 第 ${page} / ${total} 页`;
    if (page >= total) {
      clearInterval(timer);
      c.querySelector("#readTxt").textContent = `读完了：共 ${total} 页，识别出 ${t.material.length} 个章节，学习文档也整理好了。`;
      c.querySelector(".badge").textContent = "好了";
      c.querySelector("#readBar").removeAttribute("id");
      c.querySelector("#readTxt").removeAttribute("id");
      done();
    }
  }, 260);
}
function showOutline() {
  const t = TEMPLATES[S.type];
  S.src = "outline";
  S.units = t.outline.slice();
  say(S.hasMaterial === "later" ? "好，资料什么时候交都行。我先按通用知识列一份学习大纲，你看看。" : "没关系。我先按通用知识列一份学习大纲，你看看合不合适。");
  const html = () => `<div class="meta-row"><span>学习大纲</span><span class="badge">AI 整理，可以改</span><span class="badge nosrc">通用知识，没有出处</span></div>
    <h3>「${S.goal}」大概分 ${S.units.length} 个单元</h3>
    <ol class="units">${S.units.map((u) => `<li>${u}</li>`).join("")}</ol>
    <p class="aux" style="margin-top:8px">之后交了资料，我可以按资料重新排。</p>`;
  const c = decisionCard(html(), [
    btn("说说怎么改", false, () => {
      settle(c, "你说说想怎么改，我改完再给你看。");
      S.step = "reviseOutline";
      say("想怎么改？比如“把第 6 个放到前面”“去掉第 2 个”。");
      replies([["把最后一个放到前面", () => reviseOutline("把最后一个放到前面")], ["就按原来的", () => { me("就按原来的"); askProgress(); }, true]]);
    }),
    btn("就按这个", true, () => { settle(c, "大纲定下了。"); askProgress(); }),
  ]);
}
function reviseOutline(text) {
  me(text);
  S.units.unshift(S.units.pop());
  say("改好了，第一个单元换成了「" + S.units[0] + "」。");
  showOutlineAgain();
}
function showOutlineAgain() {
  const c = decisionCard(`<div class="meta-row"><span>学习大纲 · 改过</span><span class="badge">AI 整理，可以改</span></div>
    <h3>新的单元顺序</h3><ol class="units">${S.units.map((u) => `<li>${u}</li>`).join("")}</ol>`,
  [btn("就按这个", true, () => { settle(c, "大纲定下了。"); askProgress(); })]);
}
function askProgress() {
  if (S.type === "skill") return showPlan();
  S.step = "q5";
  say("最后一题：现在学到哪了？");
  replies([["刚开始", () => { me("刚开始"); showPlan(); }], ["已经学了一部分", () => { me("已经学了一部分"); S.unit = 1; S.progress = "已学一部分"; showPlan(); }], ["跳过", () => { me("跳过"); showPlan(); }, true]]);
}

// ---------- 拆解卡 ----------
function phases() {
  const n = S.units.length;
  const a = Math.ceil(n * 0.5);
  const b = Math.max(a + 1, n - 1);
  const sprintDays = Math.max(3, Math.round(S.days * 0.12));
  const perUnit = Math.max(1, Math.floor((S.days - sprintDays) / n));
  const span = (x, y) => (x === y ? `单元 ${x}` : `单元 ${x}–${y}`);
  return [
    { name: "基础", range: span(1, a), days: perUnit * a, end: a },
    { name: "强化", range: span(a + 1, b), days: perUnit * (b - a), end: b },
    { name: "冲刺", range: b < n ? `${span(b + 1, n)} + 总复习` : "总复习 + 模拟测验", days: S.days - perUnit * b, end: n },
  ];
}
function showPlan() {
  S.step = "plan";
  const ps = phases();
  const iv = INTENSITY[S.intensity];
  const srcNote = S.src === "material" ? `按你的资料（${S.units.length} 个章节）` : `按学习大纲（${S.units.length} 个单元，通用知识）`;
  const c = decisionCard(`<div class="meta-row"><span>目标拆解</span><span class="badge sim">模拟</span></div>
    <h3>「${S.goal}」这样安排</h3>
    <p class="sub">${srcNote}，${S.deadline}，默认强度「${iv.label}」约 ${iv.min} 分钟。</p>
    <div class="phases">${ps.map((p) => `<div class="phase"><b>${p.name}</b>${p.range}<br>约 ${p.days} 天 · 学完考一次</div>`).join("")}</div>
    <ul><li>每天最多三件：学新的 / 练一练 / 补一补</li><li>每个阶段学完（最长 7 天）做一次阶段测验</li>${S.src === "outline" ? "<li>没有资料时，通用题每天最多 3 道</li>" : ""}<li>点「好」才生效，也可以撤销</li></ul>`,
  [
    btn("说说怎么改", false, () => { settle(c, "原型里先不展开“说说怎么改”，正式版会用一句话重排。"); setTimeout(showPlan, 300); }),
    btn("好", true, () => {
      settle(c, "已生效。左边出现了今天三件。<button type='button' class='btn' id='undoPlan' style='height:32px;min-height:32px;margin-left:8px'>撤销</button>");
      c.querySelector("#undoPlan").addEventListener("click", undoPlan);
      S.started = true;
      S.mastery = S.units.map((_, i) => (i < S.unit ? 45 : 0));
      makeTasks();
      say(`好，今天就从「${S.units[S.unit]}」开始。左边第一件，点一下就能开始。`);
    }),
  ]);
}
function undoPlan() {
  S.started = false;
  S.tasks = [];
  renderRail();
  say("已撤销，今天三件先清空了。想重新定的话跟我说。");
  replies([["重新定目标", () => start()]]);
}

// ---------- 每天三件 ----------
function makeTasks() {
  const n = S.units.length;
  const u = Math.min(S.unit, n - 1);
  const q = S.src === "outline" ? Math.min(3, INTENSITY[S.intensity].q) : INTENSITY[S.intensity].q;
  const learn = { kind: "学新的", icon: "📘", title: `单元 ${u + 1} · ${S.units[u]}`, meta: S.src === "material" ? "看学习文档 · 带页码" : "看小满讲的要点 · 通用知识", type: "learn" };
  const learned = Math.max(0, u - 1);
  const practice = S.day === 1 && S.unit === 0
    ? { kind: "练一练", icon: "✏️", title: `单元 1 · ${q} 道题`, meta: "学完第一件再做", type: "practice", unit: 0 }
    : { kind: "练一练", icon: "✏️", title: `单元 ${learned + 1} · ${q} 道题`, meta: S.src === "material" ? "从资料出题" : "通用题，没有出处", type: "practice", unit: learned };
  let repair;
  if (S.wrong.length) repair = { kind: "补一补", icon: "🔁", title: `重做错题 ${S.wrong.length} 道`, meta: "换个问法再考你", type: "repair" };
  else repair = { kind: "学新的", icon: "📘", title: `单元 ${Math.min(u + 2, n)} · 先看个开头`, meta: "还没有错题，由学新的顶上", type: "learn2" };
  S.tasks = [learn, practice, repair].map((t) => ({ ...t, done: false }));
  if (S.stageTest) S.tasks[1] = { kind: "阶段测验", icon: "🧭", title: `${S.stageTest.name}阶段测验 · 12 道`, meta: "约 15 分钟 · 占今天一件", type: "test", done: false };
  renderRail();
}
function renderRail() {
  const box = $("goalBox");
  box.hidden = !S.started && !S.finished;
  if (S.goal) {
    $("goalTitle").textContent = S.goal;
    const total = S.units.length || 1;
    const pct = S.finished ? 100 : Math.round((S.unit / total) * 100);
    $("goalMeta").textContent = `${S.deadline} · 已学 ${S.unit} / ${total} 个单元 · ${pct}%`;
    $("goalBar").style.width = `${pct}%`;
    const ps = phases();
    const cur = ps.find((p) => S.unit < p.end) || ps[2];
    $("goalPhase").textContent = S.finished ? "目标已完成 🎉" : `当前阶段：${cur.name}（${cur.range}）· 资料：${S.src === "material" ? "已交" : "还没交"}`;
  }
  document.querySelectorAll("#seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.intensity)));
  const iv = INTENSITY[S.intensity];
  $("caption").textContent = S.started ? `约 ${iv.min} 分钟 · 按自己的节奏来` : S.finished ? "目标完成了，休息一下也很好" : "还没定目标";
  $("dayLabel").textContent = `第 ${S.day} 天`;
  const list = $("tasks");
  list.innerHTML = "";
  if (!S.started || !S.tasks.length) {
    list.appendChild(el("li", "empty", S.finished ? "这个目标走完了。定下一个目标后，这里会出现新的三件事。" : "定好目标后，这里会出现今天的三件事。"));
  } else {
    const firstOpen = S.tasks.findIndex((t) => !t.done);
    S.tasks.forEach((t, i) => {
      const li = el("li");
      const b = el("button", "task" + (t.done ? " done" : i === firstOpen ? " current" : ""));
      b.type = "button";
      b.innerHTML = `<span class="art">${t.icon}</span><span class="copy"><span class="kind">${t.kind}${i === firstOpen ? " · 先做这件" : ""}</span><strong>${t.title}</strong><span class="meta">${t.done ? "已完成" : t.meta}</span></span><span class="mark">${t.done ? "✓" : ""}</span>`;
      b.addEventListener("click", () => !t.done && runTask(i));
      li.appendChild(b);
      list.appendChild(li);
    });
  }
  $("count").textContent = `${S.tasks.filter((t) => t.done).length} / ${S.started ? S.tasks.length : 3}`;
}

function runTask(i) {
  const t = S.tasks[i];
  if (S.busy) return;
  me(`开始：${t.title}`);
  if (t.type === "learn" || t.type === "learn2") return learnCard(i);
  if (t.type === "practice") return quizCard(i, 3, "练一练");
  if (t.type === "repair") return quizCard(i, Math.min(2, S.wrong.length), "补一补", true);
  if (t.type === "test") return stageTest(i);
}
function learnCard(i) {
  const t = S.tasks[i];
  const unit = t.title.split(" · ")[1];
  const src = S.src === "material" ? '<span class="badge">第 12–28 页</span>' : '<span class="badge nosrc">通用知识，没有出处</span>';
  S.busy = true;
  const c = card(`<div class="meta-row"><span>学新的</span>${src}<span class="badge">AI 整理，可以改</span></div>
    <h3>${unit}：三个要点</h3>
    <ol><li>先弄清这一块要解决什么问题，以及它和上一单元的关系。</li><li>记住 2–3 个关键术语，下面的题会用到。</li><li>用一个工作里的例子把它说一遍，说得出来就算懂了。</li></ol>
    <p class="aux" style="margin-top:8px">有不懂的，直接在下面问我${S.src === "material" ? "，回答会标出原文页码" : ""}。</p>`);
  actions(c, [btn("学完了", true, () => { c.querySelector(".btns").remove(); S.busy = false; complete(i); })]);
}
function quizCard(i, count, label, repair) {
  S.busy = true;
  let k = 0;
  let right = 0;
  const wrongNow = [];
  const c = card("", { wide: false });
  const draw = () => {
    const q = QUESTIONS[(S.quizIdx + k) % QUESTIONS.length];
    const srcBadge = S.src === "material" ? '<span class="badge">出处 第 41 页</span>' : '<span class="badge nosrc">通用题，没有出处</span>';
    c.innerHTML = `<div class="meta-row"><span>${label}${repair ? " · 换了个问法" : ""}</span>${srcBadge}<span>第 ${k + 1} / ${count} 题</span></div>
      <h3>${q.stem}</h3><div class="q-opts">${q.opts.map((o, j) => `<button type="button" class="q-opt" data-j="${j}">${"ABC"[j]}. ${o}</button>`).join("")}</div>`;
    c.querySelectorAll(".q-opt").forEach((b) => b.addEventListener("click", () => {
      const j = Number(b.dataset.j);
      c.querySelectorAll(".q-opt").forEach((x) => { x.disabled = true; });
      c.querySelector(`[data-j="${q.ok}"]`).classList.add("right");
      if (j === q.ok) right += 1; else { b.classList.add("wrong"); wrongNow.push(q.stem); }
      c.appendChild(el("div", "explain", (j === q.ok ? "答对了。" : "这道先记下，过几天换个问法再考你。") + q.why));
      actions(c, [btn(k + 1 < count ? "下一题" : "做完了", true, () => {
        k += 1;
        if (k < count) return draw();
        S.quizIdx += count;
        if (repair) S.wrong = wrongNow;
        else S.wrong = S.wrong.concat(wrongNow);
        c.innerHTML = `<div class="meta-row"><span>${label} · 已做完</span></div><p class="sub">做了 ${count} 道，对 ${right} 道。${wrongNow.length ? "错的放进了之后的补一补。" : "全对。"}做了就算完成，对错只影响掌握度。</p>`;
        const u = S.tasks[i].unit ?? Math.max(0, S.unit - 1);
        S.mastery[u] = Math.min(100, (S.mastery[u] || 0) + 20 + right * 10);
        S.busy = false;
        complete(i);
      })]);
      scrollDown();
    }));
    scrollDown();
  };
  draw();
}
function complete(i) {
  S.tasks[i].done = true;
  if (S.tasks[i].type === "learn") S.unit = Math.min(S.units.length, S.unit + 1);
  if (S.tasks[i].type === "test") S.stageTest = null;
  renderRail();
  const next = S.tasks.findIndex((t) => !t.done);
  if (next >= 0) {
    say(`第 ${i + 1} 件做完了。下一件：${S.tasks[next].title}`);
    replies([["开始", () => runTask(next)], ["晚点再做", () => { me("晚点再做"); say("好，想做的时候点左边就行。"); }, true]]);
  } else {
    doneCard();
  }
}
function doneCard() {
  const nextUnit = S.units[Math.min(S.unit, S.units.length - 1)];
  card(`<div class="meta-row"><span>收工</span><span class="badge sim">模拟</span></div>
    <h3>今天三件都做完了 🎉</h3>
    <p class="sub">明天的三件：学「${nextUnit}」、练一练刚学的单元${S.wrong.length ? `、重做今天错的 ${S.wrong.length} 道` : ""}。</p>
    <p class="aux" style="margin-top:8px">演示：点左下“跳到明天”，看小满第二天怎么接上。</p>`);
}

// ---------- 演示开关 ----------
function nextDay(silent) {
  if (!S.started) return say("先定个目标吧，定好之后这些演示开关才有意义。");
  S.day += 1;
  if (S.pending) settle(S.pending, "先放着了。");
  quick.innerHTML = "";
  dayLine(`第 ${S.day} 天`);
  makeTasks();
  if (!silent) {
    const first = S.tasks[0];
    say(S.wrong.length
      ? `早，接着昨天来。昨天错的那 ${S.wrong.length} 道我记着呢，今天放在补一补里，换个问法再考你。\n先从「${first.title}」开始？`
      : `早，接着昨天来。今天先学「${first.title}」。`);
  }
}
function toStageEnd() {
  if (!S.started) return say("先定个目标吧。");
  const ps = phases();
  const cur = ps.find((p) => S.unit < p.end) || ps[0];
  S.unit = cur.end;
  S.mastery = S.units.map((_, i) => (i < S.unit ? 40 + ((i * 13) % 30) : 0));
  S.day += 6;
  dayLine(`第 ${S.day} 天 · ${cur.name}阶段学完了`);
  S.stageTest = cur;
  makeTasks();
  const c = decisionCard(`<div class="meta-row"><span>阶段测验</span><span class="badge sim">模拟</span></div>
    <h3>${cur.name}阶段学完了，考考这一阶段？</h3>
    <p class="sub">${cur.range}，一共 12 道单选题，约 15 分钟。测验占今天三件中的一件，不加件数。</p>`,
  [
    btn("晚点再考", false, () => { settle(c, "好，测验先留在今天三件里，想考的时候点左边。"); }),
    btn("开始测验", true, () => { settle(c, "开始了。"); stageTest(1); }),
  ]);
}
function stageTest(i) {
  const cur = S.stageTest || phases()[0];
  S.busy = true;
  let k = 0;
  let right = 0;
  const count = 4;
  const c = card("", { wide: true });
  const draw = () => {
    const q = QUESTIONS[k % QUESTIONS.length];
    c.innerHTML = `<div class="meta-row"><span>${cur.name}阶段测验</span><span>第 ${k + 1} / ${count} 题</span><span class="aux">（原型只放 4 道，正式是 10–15 道）</span></div>
      <h3>${q.stem}</h3><div class="q-opts">${q.opts.map((o, j) => `<button type="button" class="q-opt" data-j="${j}">${"ABC"[j]}. ${o}</button>`).join("")}</div>`;
    c.querySelectorAll(".q-opt").forEach((b) => b.addEventListener("click", () => {
      if (Number(b.dataset.j) === q.ok) right += 1;
      k += 1;
      if (k < count) return draw();
      report(c, cur, right, count, i);
    }));
    scrollDown();
  };
  draw();
}
function report(c, cur, right, count, i) {
  const score = Math.round(55 + (right / count) * 40);
  S.score = score;
  const units = S.units.slice(0, cur.end);
  const from = Math.max(0, units.length - 4);
  const rows = units.slice(from).map((u, idx) => {
    const ui = from + idx;
    const before = Math.max(20, S.mastery[ui] || 40);
    const after = Math.min(96, before + 10 + ((idx * 7) % 18));
    S.mastery[ui] = after;
    return `<div class="report-row"><span>${u}</span><span class="delta">${before}→${after}</span><span class="mini-bar"><i style="width:${after}%"></i></span></div>`;
  }).join("");
  let weakIdx = from;
  for (let ui = from; ui < units.length; ui += 1) if ((S.mastery[ui] || 0) < (S.mastery[weakIdx] || 0)) weakIdx = ui;
  const weak = units[weakIdx];
  c.innerHTML = `<div class="meta-row"><span>${cur.name}阶段测验 · 成绩报告</span><span class="badge sim">模拟</span></div>
    <div style="display:flex;align-items:baseline;gap:10px"><span class="big-score">${score}</span><span class="aux">分 · 答对 ${right} / ${count}（原型）</span></div>
    <p class="sub" style="margin-top:6px">每个单元的掌握度：</p>${rows}
    <p class="sub" style="margin-top:10px">最需要再看的是「${weak}」，已经放进之后几天的补一补。分数只用来调整安排，不用来评判你。</p>`;
  S.wrong = S.wrong.length ? S.wrong : ["阶段测验错题"];
  S.busy = false;
  if (S.tasks[i] && S.tasks[i].type === "test") complete(i);
  else { S.stageTest = null; makeTasks(); }
}
function uploadLater() {
  if (!S.started) return say("先定个目标吧，资料可以在定目标时交，也可以之后随时交。");
  if (S.src === "material") return say("你已经交过资料了。原型里再交一份的效果一样，就不重复演示了。");
  readFile(() => {
    const t = TEMPLATES[S.type];
    const c = decisionCard(`<div class="meta-row"><span>建议</span><span class="badge sim">模拟</span></div>
      <h3>按你的资料重新排一下？</h3>
      <p class="sub">单元从学习大纲（${S.units.length} 个，通用知识）换成资料的 ${t.material.length} 个章节；之后的讲解和题目都会带页码。已经学过的保留，做过的题记录不变。</p>`,
    [
      btn("先不用", false, () => settle(c, "好，继续按学习大纲来。想换的时候跟我说。")),
      btn("按资料重排", true, () => {
        const done = S.unit;
        S.src = "material";
        S.units = t.material.slice();
        S.unit = Math.min(done, S.units.length - 1);
        S.mastery = S.units.map((_, i) => S.mastery[i] || 0);
        makeTasks();
        settle(c, "已按资料重排，左边的三件也换了。<button type='button' class='btn' style='height:32px;min-height:32px;margin-left:8px' disabled>撤销（原型不演示）</button>");
        say("换好了。之后的讲解和题目都从你的资料里来，会标出页码。");
      }),
    ]);
  });
}
function toFinish() {
  if (!S.started) return say("先定个目标吧。");
  S.unit = S.units.length;
  S.day = Math.max(S.day, S.days - 2);
  S.mastery = S.units.map((_, i) => 72 + ((i * 11) % 22));
  S.stageTest = null;
  S.tasks.forEach((t) => { t.done = true; });
  renderRail();
  dayLine(`第 ${S.day} 天 · 所有单元学完了`);
  const c = decisionCard(`<div class="meta-row"><span>建议</span><span class="badge sim">模拟</span></div>
    <h3>看起来可以收尾了</h3><p class="sub">${S.units.length} 个单元都学完了，最后一次阶段测验 82 分，超过了 70 分的线。要把「${S.goal}」标成完成吗？</p>`,
  [
    btn("还想再练练", false, () => { settle(c, "好，接下来几天以练一练和补一补为主，想收尾了随时说。"); nextDay(true); say("那接下来几天多练练薄弱的地方。"); }),
    btn("我完成了", true, () => { settle(c, "已标成完成。"); finishCard(); }),
  ]);
}
function finishCard() {
  S.finished = true;
  S.started = false;
  S.tasks = [];
  renderRail();
  const avg = Math.round(S.mastery.reduce((a, b) => a + b, 0) / S.mastery.length);
  const hard = S.units[Math.min(3, S.units.length - 1)];
  card(`<div class="meta-row"><span>目标完成</span><span class="badge">AI 整理，可以改</span><span class="badge sim">模拟</span></div>
    <h3>「${S.goal}」完成了 🎉</h3>
    <div class="stats"><div class="stat"><b>${S.day}</b><span>天里学了 ${Math.round(S.day * 0.8)} 天</span></div><div class="stat"><b>${S.day * 4}</b><span>道题</span></div><div class="stat"><b>${avg}%</b><span>平均掌握度（从 0% 起）</span></div></div>
    <p class="sub" style="margin-top:12px">最难的一块是「${hard}」：第一次阶段测验只有 60 分，后来在补一补里换着问法练了 4 次，最后一次全对。中间也停过几天，回来后照样接上了。</p>
    <p class="aux" style="margin-top:8px">学习记录都留着，随时可以回来翻。</p>`, { wide: true });
  say("恭喜你，这一程走完了。接下来想做什么？");
  replies([["定下一个目标", () => { me("定下一个目标"); start(); }], ["先休息一阵", () => { me("先休息一阵"); say("好，好好休息。想学的时候跟我说一声就行，我都在。"); }, true]]);
}

// ---------- 输入框、强度、滚动 ----------
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("input").value.trim();
  if (!v) return;
  $("input").value = "";
  if (S.step === "q1b") return setGoal(v);
  if (S.step === "reviseOutline") { quick.innerHTML = ""; S.step = "plan"; return reviseOutline(v); }
  me(v);
  if (/只有|15 ?分钟|忙/.test(v) && S.started) {
    const c = decisionCard(`<div class="meta-row"><span>建议</span><span class="badge sim">模拟</span></div><h3>今天轻松一点？</h3><p class="sub">还是三件，每件的分量减一些，约 15 分钟。</p>`,
      [btn("先不用", false, () => settle(c, "好，按原来的来。")), btn("就这样", true, () => { S.intensity = "light"; makeTasks(); settle(c, "已改成轻松。"); })]);
    return;
  }
  say(S.src === "material" ? "（原型）这里会接问答线：对着你的资料回答，并标出【第 N 页】。" : "（原型）这里会用通用知识回答，并标“通用知识，没有出处”。交了资料就能带页码。");
});
document.querySelectorAll("#seg button").forEach((b) => b.addEventListener("click", () => {
  if (!S.started) return;
  S.intensity = b.dataset.v;
  makeTasks();
}));
stream.addEventListener("scroll", () => {
  if (!chat.classList.contains("compact") && stream.scrollTop > 40 && stream.scrollHeight - stream.clientHeight > 200) chat.classList.add("compact");
  else if (chat.classList.contains("compact") && stream.scrollTop < 8) chat.classList.remove("compact");
});
$("dTomorrow").addEventListener("click", () => nextDay(false));
$("dStage").addEventListener("click", toStageEnd);
$("dUpload").addEventListener("click", uploadLater);
$("dFinish").addEventListener("click", toFinish);
$("dReset").addEventListener("click", start);

start();
