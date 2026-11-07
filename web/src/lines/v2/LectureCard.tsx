import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, Card } from "../../components/ui";

export type Lecture = {
  title: string;
  sections: { heading: string; content: string; example: string }[];
  label: string;
};

export function LectureCard({ unitNo, onDone }: { unitNo: number; onDone: () => void }) {
  const [lecture, setLecture] = useState<Lecture | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError("");
    void api<Lecture>("/api/v2/lecture", { method: "POST", body: JSON.stringify({ unit_no: unitNo }) })
      .then((result) => {
        if (!cancelled && result.source === "api") setLecture(result.envelope.data);
      })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "讲解加载失败，请稍后重试。"); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [unitNo]);

  return (
    <Card aria-label={`第 ${unitNo} 讲`}>
      <Badge>{lecture?.label ?? "通用知识，没有出处"}</Badge>
      <h3>{lecture?.title ?? `第 ${unitNo} 讲`}</h3>
      {busy && <p role="status">小满正在准备这一讲…</p>}
      {error && <p role="alert" className="aux">{error}</p>}
      {lecture && (
        <>
          {lecture.sections.map((section) => (
            <section key={section.heading}>
              <h4>{section.heading}</h4>
              <p>{section.content}</p>
              {section.example && <p className="aux">例：{section.example}</p>}
            </section>
          ))}
          <Button variant="primary" onClick={onDone}>学完了，进入下一件</Button>
        </>
      )}
    </Card>
  );
}
