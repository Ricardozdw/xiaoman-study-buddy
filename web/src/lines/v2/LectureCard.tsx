import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Button, Card } from "../../components/ui";

export type Lecture = {
  title: string;
  sections: { heading: string; content: string; example: string }[];
  label: string;
};

// 同一讲同时只发一次请求（开发模式下组件会挂载两次；连点也不重复生成）。
const inflight = new Map<number, ReturnType<typeof api<Lecture>>>();
function loadLecture(unitNo: number) {
  const running = inflight.get(unitNo);
  if (running) return running;
  const request = api<Lecture>("/api/v2/lecture", { method: "POST", body: JSON.stringify({ unit_no: unitNo }) })
    .finally(() => inflight.delete(unitNo));
  inflight.set(unitNo, request);
  return request;
}

export function LectureCard({ unitNo, onDone, doneLabel = "学完了，去练一练" }: { unitNo: number; onDone: () => void; doneLabel?: string }) {
  const [lecture, setLecture] = useState<Lecture | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError("");
    void loadLecture(unitNo)
      .then((result) => {
        if (!cancelled && result.source === "api") setLecture(result.envelope.data);
      })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "讲解加载失败，请稍后重试。"); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [unitNo]);

  // 一节一节往下看（像多邻国的小步子），不一次铺一大段；重看时直接全部展开。
  const total = lecture?.sections.length ?? 0;
  const [shown, setShown] = useState(1);
  const review = doneLabel === "看完了";
  const visible = review ? total : Math.min(shown, total);
  const last = visible >= total;
  const tag = lecture?.label && lecture.label !== "AI 整理，可以改" ? lecture.label : "";

  return (
    <Card aria-label={`第 ${unitNo} 讲`} className="lecture-card card-read">
      <header className="lecture-head">
        <span className="aux">第 {unitNo} 讲{tag ? ` · ${tag}` : ""}</span>
        <h3>{lecture?.title ?? "小满正在准备这一讲…"}</h3>
        {total > 0 && !review && (
          <div className="quiz-progress" aria-label={`第 ${visible} / ${total} 节`}><span style={{ width: `${(visible / total) * 100}%` }} /></div>
        )}
      </header>
      {busy && <p role="status" className="aux">大概要十几秒，稍等一下。</p>}
      {error && <p role="alert" className="aux">{error}</p>}
      {lecture && (
        <>
          {lecture.sections.slice(0, visible).map((section) => (
            <section key={section.heading} className="lecture-section">
              <h4>{section.heading}</h4>
              <p>{section.content}</p>
              {section.example && <p className="lecture-example"><strong>例</strong>{section.example}</p>}
            </section>
          ))}
          <div className="btns">
            {last
              ? <Button variant="primary" onClick={onDone}>{doneLabel}</Button>
              : <Button variant="primary" onClick={() => setShown((n) => n + 1)}>下一节（{visible + 1} / {total}）</Button>}
          </div>
        </>
      )}
    </Card>
  );
}
