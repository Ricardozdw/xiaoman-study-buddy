import { Button } from "../../components/ui";
import { describe, it, expect, vi, afterEach } from "vitest";
import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { consumeSse, requestJson, loadSource, createSessionInitializer } from "./transport";
import { applyFrame, emptyAnswer, nextCurrentLectureId } from "./state";
import { QaAnswer, QaHandoff, QaSourceText, LecturePicker, CitedText } from "./index";
function response(text: string, byteSize = 1) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({ start(c) {
    for (let i=0;i<bytes.length;i+=byteSize) c.enqueue(bytes.slice(i,i+byteSize));
    c.close();
  }}), { headers: { "Content-Type": "text/event-stream" } });
}
afterEach(() => vi.unstubAllGlobals());
describe("QA stream transport", () => {
  it("decodes byte-split Unicode and CRLF with metadata and DONE", async () => {
    const frames: unknown[]=[];
    await consumeSse(response(': hi\r\n\r\ndata: {"type":"meta","message_id":"m"}\r\n\r\ndata: {"delta":"你好🌱"}\r\n\r\ndata: {"type":"complete","message_id":"m","ok":true}\r\n\r\ndata: [DONE]\r\n\r\n'), f=>frames.push(f));
    expect(frames).toEqual([{type:"meta",message_id:"m"},{delta:"你好🌱"},{type:"complete",message_id:"m",ok:true}]);
  });
  it("rejects truncated streams, invalid JSON and server errors", async () => {
    await expect(consumeSse(response('data: {"delta":"半句"}\n\n'),()=>{})).rejects.toThrow("中断");
    await expect(consumeSse(response('data: nope\n\n'),()=>{})).rejects.toThrow("格式");
    await expect(consumeSse(response('data: {"type":"error","message":"模型失败"}\n\ndata: [DONE]\n\n'),()=>{})).rejects.toThrow("模型失败");
  });
  it("aborts an active reader", async () => {
    const abort=new AbortController();
    const task=consumeSse(new Response(new ReadableStream({start(){}})),()=>{},abort.signal);
    abort.abort();
    await expect(task).rejects.toMatchObject({name:"AbortError"});
  });
  it("never substitutes a success for failed feedback", async () => {
    vi.stubGlobal("fetch",vi.fn(async()=>new Response('{"detail":"failed"}',{status:500})));
    await expect(requestJson('/api/qa/messages/1/feedback',{method:'POST'})).rejects.toThrow("500");
  });
});
describe("QA reducer and rendering",()=>{
  it("preserves metadata and marks incomplete output as failure",()=>{
    let answer=emptyAnswer("local");
    answer=applyFrame(answer,{type:"meta",message_id:"server",thread_id:"thread",intent:"qa",lecture_id:"lec",mock:true,label:"AI 整理，可以改"});
    answer=applyFrame(answer,{delta:"回答"});
    answer=applyFrame(answer,{type:"complete",ok:false});
    expect(answer).toMatchObject({messageId:"server",threadId:"thread",text:"回答",mock:true,status:"error"});
  });
  it("does not fabricate clickable citations from text alone",()=>{
    const answer={...emptyAnswer("a"),text:"没有核验【第 99 页】",status:"done" as const};
    const html=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{}}));
    expect(html).not.toContain("查看第 99 页");
  });
  it("renders escaped source text and highlights exact original quote",()=>{
    const html=renderToStaticMarkup(createElement(QaSourceText,{text:'前面<script>后面',quote:'<script>'}));
    expect(html).toContain('<mark>&lt;script&gt;</mark>');
    expect(html).not.toContain('<script>');
  });
  it("shows mock badge and explicit failure without feedback success",()=>{
    const answer={...emptyAnswer("a"),mock:true,error:"保存失败",status:"error" as const};
    const html=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{}}));
    expect(html).toContain("模拟"); expect(html).toContain("保存失败"); expect(html).not.toContain("已保存");
  });
  it("renders fetched lecture choices and default-current option",()=>{
    const html=renderToStaticMarkup(createElement(LecturePicker,{value:"",onChange:()=>{},lectures:[{id:"real",title:"真实讲义",mock:false}],currentLectureId:"real"}));
    expect(html).toContain('value="real"'); expect(html).toContain("真实讲义"); expect(html).toContain("当前学习");
  });
});

describe("QA product contracts", () => {
  it("upgrades mock on completion without losing thread or citations",()=>{
    let answer=applyFrame(emptyAnswer("a"),{type:"meta",thread_id:"kept",mock:false});
    answer=applyFrame(answer,{type:"references",references:[{lecture_id:"l",page:1,quote:"原文"},{lecture_id:"l",page:-1,quote:"坏"}]});
    answer=applyFrame(answer,{type:"complete",ok:true,mock:true});
    expect(answer).toMatchObject({threadId:"kept",mock:true,status:"done"});
    expect(answer.references).toHaveLength(1);
  });
  it("does not execute a pending plan while rendering the suggestion",()=>{
    const fetch=vi.fn(); vi.stubGlobal("fetch",fetch);
    const answer={...emptyAnswer("a"),status:"done" as const,handoff:{intent:"plan" as const,data:{id:"action",status:"pending",suggestion:{title:"换成轻松",body:"15分钟",label:"模拟"}}}};
    const html=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{}}));
    expect(html).toContain("就这样"); expect(html).toContain("先不用"); expect(html).not.toContain("已按你的选择调整"); expect(fetch).not.toHaveBeenCalled();
  });
  it("renders only one practice question for one decision at a time",()=>{
    const answer={...emptyAnswer("a"),status:"done" as const,handoff:{intent:"quiz" as const,data:{label:"模拟",questions:[{id:"q1",kind:"single",stem:"第一题",options:[{id:"A",text:"甲"}]},{id:"q2",kind:"single",stem:"第二题",options:[]}]}}};
    const html=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{}}));
    expect(html).toContain("第一题"); expect(html).toContain('<span class="option-key">A</span>甲'); expect(html).not.toContain("第二题");
  });
});

it("trusts page mock flag over the legacy materials envelope default", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ok:true,mock:true,data:{pages:[{page:1,text:"真实原文",mock:false}]}}))));
  await expect(loadSource({lecture_id:"real",page:1,quote:"原文"})).resolves.toEqual({text:"真实原文",mock:false});
});

it("closes the reader on DONE even when the HTTP stream stays open", async () => {
  let cancelled=false;
  const stream=new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('data: {"type":"meta","message_id":"m"}\n\ndata: {"type":"complete","message_id":"m","ok":true}\n\ndata: [DONE]\n\n')); }, cancel() { cancelled=true; } });
  await consumeSse(new Response(stream),()=>{});
  expect(cancelled).toBe(true);
});

it("keeps an accepted plan undo available after a later conversation",()=>{
  const answer={...emptyAnswer("a"),status:"done" as const,handoff:{intent:"plan" as const,data:{id:"x",status:"executed",suggestion:{title:"调整"}}}};
  const html=renderToStaticMarkup(createElement(QaAnswer,{answer,active:false,onReference:()=>{}}));
  expect(html).toContain("撤销");
});

describe("review regressions",()=>{
  it("maps repeated same-page inline markers to quote occurrences including duplicates",()=>{
    const references=[{lecture_id:"l",page:1,quote:"第一原句"},{lecture_id:"l",page:1,quote:"第二原句"},{lecture_id:"l",page:1,quote:"第一原句"}];
    const answer={...emptyAnswer("a"),text:"第一句【第 1 页】第二句【第 1 页】重复句【第 1 页】",references};
    const clicked=vi.fn();
    const element=CitedText({answer,onReference:clicked});
    const children=element.props.children as ReactElement<{onClick?:()=>void}>[];
    const buttons=children.filter(child=>child.type===Button);
    expect(buttons).toHaveLength(3);
    buttons.forEach(button=>button.props.onClick?.());
    expect(clicked.mock.calls.map(call=>call[0])).toEqual(references);
    expect(renderToStaticMarkup(element).match(/查看第 1 页原文/g)).toHaveLength(3);
  });
  it("updates implicit-current lecture label from qa and quiz meta only",()=>{
    const lectures=[{id:"old",title:"旧讲",mock:false},{id:"new",title:"新讲",mock:false}];
    let current="old";
    for (const intent of ["qa","quiz"]) {
      current=nextCurrentLectureId("old",{type:"meta",intent,lecture_id:"new"});
      expect(current).toBe("new");
      const html=renderToStaticMarkup(createElement(LecturePicker,{value:"",onChange:()=>{},lectures,currentLectureId:current}));
      expect(html).toContain("当前学习：新讲");
    }
    expect(nextCurrentLectureId(current,{type:"meta",intent:"plan",lecture_id:"old"})).toBe("new");
    expect(nextCurrentLectureId(current,{type:"meta",intent:"qa",lecture_id:""})).toBe("new");
  });
});

it("requires successful complete for the matching meta message before DONE", async()=>{
  const meta='data: {"type":"meta","message_id":"m"}\n\n';
  for (const text of ['data: [DONE]\n\n',meta+'data: {"delta":"half"}\n\ndata: [DONE]\n\n',meta+'data: {"type":"complete","message_id":"other","ok":true}\n\ndata: [DONE]\n\n']) {
    await expect(consumeSse(response(text),()=>{})).rejects.toThrow("完成");
  }
});

it("coalesces session initialization across concurrent consumers and StrictMode remount",async()=>{
  let resolve!: (value: Response)=>void;
  const request=vi.fn(()=>new Promise<Response>(done=>{resolve=done;}));
  const initialize=createSessionInitializer(request);
  const first=initialize(), remount=initialize(), shell=initialize();
  expect(request).toHaveBeenCalledTimes(1);
  resolve(new Response("{}",{status:200}));
  await Promise.all([first,remount,shell]);
  await initialize();
  expect(request).toHaveBeenCalledTimes(1);
  expect(request.mock.calls[0]).toEqual(["/api/session",{method:"POST",credentials:"include"}]);
});

it("renders QA using lake blue shared assistant and user bubbles",()=>{
  const user=renderToStaticMarkup(createElement(QaAnswer,{answer:{...emptyAnswer('u'),role:'user',text:'用户问题'},onReference:()=>{}}));
  const assistant=renderToStaticMarkup(createElement(QaAnswer,{answer:{...emptyAnswer('a'),text:'资料回答'},onReference:()=>{}}));
  expect(user).toContain('bubble user'); expect(assistant).toContain('bubble xiaoman');
  expect(assistant).not.toContain('<svg');
});
it("renders native plan option labels rather than a fabricated generic choice",()=>{
  const handoff={intent:'plan' as const,data:{card:{id:'native',kind:'adjust',type:'suggestion' as const,title:'正式安排建议',lines:['三件不变'],badge:'模拟',status:'pending',collapsed_text:'已确认',options:[{id:'light',label:'轻松一点'}]}}};
  const html=renderToStaticMarkup(createElement(QaAnswer,{answer:{...emptyAnswer('a'),status:'done',handoff},onReference:()=>{}}));
  expect(html).toContain('正式安排建议');expect(html).toContain('轻松一点');expect(html).not.toContain('就这样');
});

it("keeps lake-blue Shell navigation while using QA current lecture selection",async()=>{
  const { Shell }=await import('../../components/Shell');
  const html=renderToStaticMarkup(createElement(Shell));
  expect(html).toContain('companion');expect(html).toContain('/xiaoman-lake-blue.png');expect(html).toContain('今天三件');
  // 只有一份资料时不放讲次选择；字号和授权收进“设置”；不出现开发用语。
  expect(html).not.toContain('当前学习（暂无资料）');expect(html).toContain('maxLength="4000"');
  // 学习文档 / 学习路径 / 错题本 / 交课件 收进右上角“更多”；首屏是“月/日 + 一句话状态”。
  expect(html).toContain('aria-label="更多"');expect(html).toContain('aria-label="设置"');
  expect(html).toContain('<b>11</b>/04');expect(html).toContain('今天还有 3 件事');
  expect(html).not.toContain('已连接');expect(html).not.toContain('占位');expect(html).not.toContain('今天的三件在左边');
});

it("submits native plan option/date and keeps dismiss and undo on official routes",async()=>{
  const { submitPlanDecision }=await import('./transport');
  const request=vi.fn(async(_url: RequestInfo | URL, _init?: RequestInit)=>new Response(JSON.stringify({ok:true,mock:true,data:{status:'executed',plan:{minutes:15}}})));
  vi.stubGlobal('fetch',request);
  const result=await submitPlanDecision('card/id','accept','exam_date','2026-12-20');
  expect(result.data.plan?.minutes).toBe(15);
  expect(request.mock.calls[0][0]).toBe('/api/suggestions/card%2Fid/accept');
  expect(JSON.parse(request.mock.calls[0][1]?.body as string)).toEqual({option:'exam_date',exam_date:'2026-12-20'});
  await submitPlanDecision('card/id','dismiss');expect(request.mock.calls[1][0]).toBe('/api/suggestions/card%2Fid/dismiss');
  await submitPlanDecision('card/id','undo');expect(request.mock.calls[2][0]).toBe('/api/actions/card%2Fid/undo');
});
it("retains the executed action for undo when plan returns a follow-up card",async()=>{
  const { advancePlanCard }=await import('./state');
  const first={id:'one',kind:'return',type:'reschedule' as const,title:'第一张',lines:[],badge:'模拟',collapsed_text:'已执行',status:'pending',options:[]};
  const next={...first,id:'two',title:'下一张'};
  const result=advancePlanCard(first,{...first,status:'executed',next_card:next});
  expect(result.card.id).toBe('two');expect(result.previous).toMatchObject({id:'one',status:'executed'});
});
it("keeps upload notices after existing conversation without fabricating server feedback ids",async()=>{
 const { appendLocalNotice }=await import('./state');
 const result=appendLocalNotice([{...emptyAnswer('existing'),text:'已有回答'}],'（模拟）资料已记下');
 expect(result.map(item=>item.text)).toEqual(['已有回答','（模拟）资料已记下']);
 expect(result[1].messageId).toBe('');expect(result[1].mock).toBe(true);
});
it("replaces the expired follow-up with the server parent after undo previous",async()=>{
 const { restorePlanAfterUndo }=await import('./state');
 const child={id:'child',kind:'return',type:'reschedule' as const,title:'过期后续',lines:[],badge:'模拟',collapsed_text:'',status:'pending',options:[{id:'continue',label:'过期选项'}]};
 const parent={...child,id:'parent',title:'已撤销建议',status:'undone',options:[]};
 const state=restorePlanAfterUndo(parent);
 expect(state.card).toEqual(parent);expect(state.previous).toBeNull();
 const html=renderToStaticMarkup(createElement(QaAnswer,{answer:{...emptyAnswer('a'),status:'done',handoff:{intent:'plan',data:{card:state.card}}},onReference:()=>{}}));
 expect(html).toContain('已撤销调整');expect(html).not.toContain('过期选项');
});


it("keeps long quiz choices in the wrapping option variant without changing their labels",()=>{
  const text="学习资料中的一个很长的选项".repeat(30);
  const answer={...emptyAnswer("long-options"),status:"done" as const,handoff:{intent:"quiz" as const,data:{label:"模拟",questions:[{id:"q-long",kind:"single",stem:"长选项",options:[{id:"A",text},{id:"B",text:"短选项"}]}]}}};
  const html=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{}}));
  expect(html.match(/class="btn option ?"/g)).toHaveLength(2);
  expect(html).toContain(text); expect(html).toContain('<span class="option-key">B</span>短选项');
});

it("keeps file selection mounted but does not show an idle materials card in a fresh chat",async()=>{
  const {Shell}=await import('../../components/Shell');
  const html=renderToStaticMarkup(createElement(Shell));
  expect(html).toContain('aria-label="选择 PDF 文件"');
  expect(html).not.toContain('aria-label="资料读取"');
});

it("goal follow-up questions show option chips only while current, without AI tag or feedback buttons",()=>{
  const answer={...emptyAnswer("g"),text:"每天大概有多少时间？",messageId:"m1",intent:"goal",status:"done" as const,handoff:{intent:"goal" as const,data:{question:"每天大概有多少时间？",options:["15 分钟","30 分钟"]}}};
  const live=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{},onQuickReply:()=>{}}));
  expect(live).toContain("30 分钟");expect(live).not.toContain("AI 整理");expect(live).not.toContain("赞同回答");
  const old=renderToStaticMarkup(createElement(QaAnswer,{answer,active:false,onReference:()=>{},onQuickReply:()=>{}}));
  expect(old).not.toContain("30 分钟");
});

it("real answers keep the AI tag and feedback buttons",()=>{
  const answer={...emptyAnswer("q"),text:"关键路径是最长的那条",messageId:"m2",intent:"qa",status:"done" as const};
  const html=renderToStaticMarkup(createElement(QaAnswer,{answer,onReference:()=>{}}));
  expect(html).toContain("AI 整理");expect(html).toContain("赞同回答");
});

it("remembers today's open quiz and resumes at the first unanswered question",async()=>{
  const store=new Map<string,string>();
  vi.stubGlobal('localStorage',{getItem:(k:string)=>store.get(k)??null,setItem:(k:string,v:string)=>{store.set(k,v);},removeItem:(k:string)=>{store.delete(k);}});
  const { rememberQuiz, openQuizId, forgetQuiz }=await import('./index');
  rememberQuiz('quiz-1');expect(openQuizId()).toBe('quiz-1');
  forgetQuiz('other');expect(openQuizId()).toBe('quiz-1');
  forgetQuiz('quiz-1');expect(openQuizId()).toBeNull();
  store.set('xm-open-quiz',JSON.stringify({quizId:'old',day:'2000-01-01'}));expect(openQuizId()).toBeNull();
  const data={quiz_id:'quiz-2',questions:[{id:'q1',kind:'single',stem:'第一题',options:['甲']},{id:'q2',kind:'single',stem:'第二题',options:['乙']}],results:{q1:{correct:true}}};
  const html=renderToStaticMarkup(createElement(QaHandoff,{handoff:{intent:'quiz',data}}));
  expect(html).toContain('第二题');expect(html).not.toContain('第一题');expect(html).toContain('第 2 / 2 题');
  vi.unstubAllGlobals();
});
