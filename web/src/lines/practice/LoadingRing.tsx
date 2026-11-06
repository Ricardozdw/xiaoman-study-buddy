import "./practice.css";

export function LoadingRing({ text }: { text: string }) {
  return <div className="practice-loading-overlay"><div className="card practice-loading" role="status" aria-live="polite">
    <svg className="practice-ring" width="36" height="36" viewBox="0 0 36 36" aria-hidden="true">
      <circle cx="18" cy="18" r="14" fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray="60 28" strokeLinecap="round" />
    </svg>
    <div><strong>{text}</strong></div>
  </div></div>;
}
