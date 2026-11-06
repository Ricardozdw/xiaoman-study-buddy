export function PracticeLine() {
  return <p className="line-placeholder">练习线：{import.meta.env.DEV ? <a href="/src/lines/practice/preview.html" target="_blank" rel="noreferrer">打开本地独立验收页</a> : "独立模块已准备"}。共用对话页接入等待 A 确认。</p>;
}
