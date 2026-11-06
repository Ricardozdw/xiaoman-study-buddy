import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "../../styles.css";
import { Button } from "../../components/ui";
import { Avatar } from "../../components/Avatar";
import { LecturePicker, QaAnswer, QaSourcePanel, useQaConversation } from "./index";
import type { Reference } from "./types";
function Preview() {
  const qa = useQaConversation();
  const [draft, setDraft] = useState("");
  const [reference, setReference] = useState<Reference | null>(null);
  const [error, setError] = useState("");
  return <div className="app"><header className="top"><Avatar mood="wave" /><strong>小满 · 问答线预览</strong><span className="aux">按真实接口连接，示范内容会标“模拟”</span></header>
    <div className="shell"><aside className="rail"><h2>资料</h2><p className="aux">@ 可指定一讲；不选时问当前在学的一讲。</p>{qa.lectures.map(item => <Button key={item.id} className="task" onClick={() => qa.setLectureId(item.id)}>{item.title}{item.mock ? "（模拟）" : ""}</Button>)}{qa.lectureError && <p role="alert">{qa.lectureError}</p>}</aside>
    <main className="chat"><div className="stream"><p>我是小满。可以问这一讲讲了什么，也可以说“出几道题”或“今天只有 15 分钟”。</p>{qa.messages.map(item => <QaAnswer key={item.id} answer={item} active={item.id === qa.messages.at(-1)?.id} onReference={setReference} />)}{error && <p role="alert">{error}</p>}</div>
    <form className="composer" onSubmit={event => { event.preventDefault(); const text = draft.trim(); if (!text || qa.busy) return; setDraft(""); setError(""); void qa.send(text).catch(error => setError(error.message)); }}>
      <LecturePicker value={qa.lectureId} onChange={qa.setLectureId} lectures={qa.lectures} currentLectureId={qa.currentLectureId} disabled={qa.busy} /><input aria-label="跟小满说一句" placeholder="跟小满说一句" value={draft} maxLength={4000} onChange={event => setDraft(event.target.value)} />{qa.busy ? <Button type="button" onClick={qa.stop}>停止</Button> : <Button type="submit" variant="primary" disabled={!qa.sessionReady}>发送</Button>}
    </form></main>{reference && <aside className="workbench"><header><h2>引用原文</h2><Button type="button" onClick={() => setReference(null)}>关闭</Button></header><QaSourcePanel reference={reference} /></aside>}</div></div>;
}
createRoot(document.getElementById("root")!).render(<StrictMode><Preview /></StrictMode>);
