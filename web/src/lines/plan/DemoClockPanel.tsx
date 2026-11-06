import type { DemoClock } from "./types";

// 演示开关：只在后端打开 XIAOMAN_DEMO_CLOCK 时显示，界面标“演示用”。

const STEPS: { days: number; label: string }[] = [
  { days: 1, label: "跳到明天" },
  { days: 2, label: "跳过两天" },
  { days: 8, label: "跳过 8 天" },
];

type Props = { clock: DemoClock; busy: boolean; onStep: (days: number) => void; onReset: () => void };

export function DemoClockPanel({ clock, busy, onStep, onReset }: Props) {
  return (
    <section className="line-placeholder" aria-label="演示开关">
      <p>
        <span className="badge sim">{clock.label}</span>{" "}
        {clock.offset_days === 0 ? `现在是真实的今天（${clock.today}）` : `现在按 ${clock.today} 排，比真实日期晚 ${clock.offset_days} 天`}
      </p>
      <div className="btns">
        {STEPS.map((step) => (
          <button key={step.days} type="button" className="btn" disabled={busy} onClick={() => onStep(step.days)}>
            {step.label}
          </button>
        ))}
        {clock.offset_days > 0 && (
          <button type="button" className="btn" disabled={busy} onClick={onReset}>
            回到今天
          </button>
        )}
      </div>
    </section>
  );
}
