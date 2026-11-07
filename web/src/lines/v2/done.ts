// 完成状态只在 V2 卡片和左栏之间传。Shell 不另打一遍完成接口。

type Listener = (done: boolean) => void;

let current = false;
const listeners = new Set<Listener>();

export function publishGoalDone(done: boolean) {
  current = done;
  listeners.forEach((listener) => listener(done));
}

export function subscribeGoalDone(listener: Listener) {
  listener(current);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
