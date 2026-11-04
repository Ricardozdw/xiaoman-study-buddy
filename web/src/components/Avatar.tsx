type Mood = "idle" | "wave";

export function Avatar({ mood = "idle" }: { mood?: Mood }) {
  return (
    <span className="avatar" role="img" aria-label={mood === "wave" ? "小满在打招呼" : "小满"}>
      <svg viewBox="0 0 64 64" width="36" height="36" aria-hidden="true">
        <circle cx="32" cy="32" r="30" fill="currentColor" opacity="0.15" />
        <circle cx="24" cy="28" r="3" fill="currentColor" />
        <circle cx="40" cy="28" r="3" fill="currentColor" />
        <path d={mood === "wave" ? "M22 40c4 6 16 6 20 0" : "M24 42h16"} stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
      </svg>
    </span>
  );
}
