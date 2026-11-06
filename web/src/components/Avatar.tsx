// 小满形象：湖泊蓝短耳绒毛原图（design/approved-lake-blue/），不重画、不换色。
// mood 先保留给以后的动作和表情；现在只有一张静态图，读屏文字随 mood 变化。
type Mood = "idle" | "wave";

export function Avatar({ mood = "idle", size }: { mood?: Mood; size?: number }) {
  return (
    <span className="avatar" role="img" aria-label={mood === "wave" ? "小满在打招呼" : "小满"} style={size ? { width: size, height: size } : undefined}>
      <img src={`${import.meta.env.BASE_URL}xiaoman-lake-blue.png`} alt="" draggable={false} />
    </span>
  );
}
