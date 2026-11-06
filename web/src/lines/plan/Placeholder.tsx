import { useEffect, useState } from "react";
import { api } from "../../api/client";

// 计划线 · 演示开关。只有后端打开 XIAOMAN_DEMO_CLOCK 时才显示，界面标“演示用”。
// 跳完刷新整页，左栏按新的一天重排（不改共用的 Shell）。

type DemoClock = {
  enabled: boolean;
  offset_days: number;
  today: string;
  real_today: string;
  label: string;
};

const STEPS: { days: number; label: string }[] = [
  { days: 1, label: "跳到明天" },
  { days: 2, label: "跳过两天" },
  { days: 8, label: "跳过 8 天" },
];

export function PlanLine() {
  const [clock, setClock] = useState<DemoClock | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void api<DemoClock>("/api/demo/clock").then((result) => {
      if (!cancelled && result.source === "api") setClock(result.envelope.data);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!clock?.enabled) {
    return <p className="line-placeholder">计划线：今天三件按规则排。演示开关没打开。</p>;
  }

  async function go(path: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    const result = await api<DemoClock>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
    if (result.source === "api") {
      window.location.reload();
      return;
    }
    setBusy(false);
  }

  return (
    <section className="line-placeholder" aria-label="演示开关">
      <p>
        <span className="badge sim">{clock.label}</span>{" "}
        {clock.offset_days === 0 ? `现在是真实的今天（${clock.today}）` : `现在按 ${clock.today} 排，比真实日期晚 ${clock.offset_days} 天`}
      </p>
      <div className="btns">
        {STEPS.map((step) => (
          <button key={step.days} type="button" className="btn" disabled={busy} onClick={() => void go("/api/demo/clock", { days: step.days })}>
            {step.label}
          </button>
        ))}
        {clock.offset_days > 0 && (
          <button type="button" className="btn" disabled={busy} onClick={() => void go("/api/demo/clock/reset")}>
            回到今天
          </button>
        )}
      </div>
    </section>
  );
}
