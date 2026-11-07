import { useState } from "react";
import { Badge, Button, Card } from "../../components/ui";
import type { OutlineView, UnitInput } from "./api";
import { validateUnits } from "./logic";

type DraftUnit = { key: string; title: string; points: string[] };

type Props = {
  outline: OutlineView;
  busy: boolean;
  error?: string;
  onPatch: (units: UnitInput[]) => Promise<boolean>;
  onAccept: () => void;
  onDismiss: () => void;
};

export function OutlineCard({ outline, busy, error, onPatch, onAccept, onDismiss }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DraftUnit[]>([]);
  const [localError, setLocalError] = useState("");
  const message = localError || error || "";

  function startEdit() {
    setDraft(outline.units.map((unit, index) => ({ key: `u-${unit.no ?? index + 1}`, title: unit.title, points: [...unit.points] })));
    setLocalError("");
    setEditing(true);
  }

  function update(key: string, patch: Partial<DraftUnit>) {
    setDraft((list) => list.map((unit) => (unit.key === key ? { ...unit, ...patch } : unit)));
  }

  async function save(): Promise<boolean> {
    const result = validateUnits(draft.map(({ title, points }) => ({ title, points })));
    if (!result.ok) {
      setLocalError(result.message);
      return false;
    }
    setLocalError("");
    const ok = await onPatch(result.units);
    if (ok) setEditing(false);
    return ok;
  }

  async function accept() {
    if (editing) {
      const ok = await save();
      if (!ok) return;
    }
    onAccept();
  }

  return (
    <Card aria-label="学习大纲">
      <header>
        <h3>{outline.title}</h3>
        <Badge sim={outline.label === "模拟"}>{outline.label}</Badge>
        <span className="aux">共 {editing ? draft.length : outline.units.length} 个单元</span>
      </header>
      <p className="aux">通用知识整理，没有资料出处；交了资料后可以排得更准</p>
      {editing ? (
        <div className="v2-edit">
          {draft.map((unit, index) => (
            <div className="v2-unit" key={unit.key}>
              <div className="v2-field">
                <label>
                  第 {index + 1} 个单元
                  <input aria-label={`第 ${index + 1} 个单元的名称`} value={unit.title} disabled={busy} onChange={(event) => update(unit.key, { title: event.target.value })} />
                </label>
                <label>
                  要点，一行一个
                  <textarea aria-label={`第 ${index + 1} 个单元的要点`} value={unit.points.join("\n")} disabled={busy} onChange={(event) => update(unit.key, { points: event.target.value.split("\n") })} />
                </label>
              </div>
              <div className="btns">
                <Button disabled={busy} onClick={() => setDraft((list) => list.filter((item) => item.key !== unit.key))}>删除这个单元</Button>
              </div>
            </div>
          ))}
          <div className="btns">
            <Button
              disabled={busy || draft.length >= 20}
              onClick={() => setDraft((list) => [...list, { key: `new-${list.length}-${Date.now()}`, title: "", points: [""] }])}
            >
              加一个单元
            </Button>
            <Button disabled={busy} onClick={() => void save()}>保存</Button>
            <Button disabled={busy} onClick={() => { setEditing(false); setLocalError(""); }}>取消</Button>
          </div>
        </div>
      ) : (
        <ul className="v2-units">
          {outline.units.map((unit, index) => (
            <li key={unit.no ?? index}>
              <details className="v2-unit" open={index === 0}>
                <summary>第 {unit.no ?? index + 1} 单元 · {unit.title}</summary>
                <ul className="v2-points">{unit.points.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul>
              </details>
            </li>
          ))}
        </ul>
      )}
      {message && <p role="alert">{message}</p>}
      <div className="btns">
        <Button variant="primary" disabled={busy} onClick={() => void accept()}>好</Button>
        {!editing && <Button disabled={busy} onClick={startEdit}>改一改</Button>}
        <Button disabled={busy} onClick={onDismiss}>先不用</Button>
      </div>
    </Card>
  );
}
