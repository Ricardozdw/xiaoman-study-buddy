// 通用界面组件：按钮、气泡、卡片容器、图标。
// 视觉基准见 design/approved-lake-blue/。各线直接用这里的组件和 styles.css 的变量，不自己写一套样式。
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** primary：主操作（每张卡最多一个）；secondary：次要操作。两者尺寸完全一样。 */
  variant?: "primary" | "secondary";
};

/** 文字按钮：44px 高、14px 圆角、左右 14px、14px / 500。不带箭头，宽度随文字。 */
export function Button({ variant = "secondary", className, type = "button", ...rest }: ButtonProps) {
  return <button type={type} className={join("btn", variant === "primary" && "primary", className)} {...rest} />;
}

type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  icon: IconName;
  /** 读屏和悬停提示用的文字，必填。 */
  label: string;
  variant?: "primary" | "plain" | "secondary";
};

/** 只有图标的按钮：44×44。需要图标加文字时，另加新变体，不往文字按钮里塞空位。 */
export function IconButton({ icon, label, variant = "plain", className, type = "button", ...rest }: IconButtonProps) {
  return (
    <button type={type} aria-label={label} title={label} className={join("icon-btn", variant, className)} {...rest}>
      <Icon name={icon} />
    </button>
  );
}

type BubbleProps = {
  role: "user" | "xiaoman";
  /** 和上一条是同一个人说的：间距更小。 */
  grouped?: boolean;
  children: ReactNode;
};

/** 聊天气泡：用户在右（浅湖蓝），小满在左（浅灰）。宽度随内容，最大约 76%。 */
export function Bubble({ role, grouped, children }: BubbleProps) {
  const empty = children === "" || children === null || children === undefined;
  return (
    <div className={join("bubble", role, grouped && "grouped")}>
      <p>{empty ? <span className="typing" aria-label="小满在想">…</span> : children}</p>
    </div>
  );
}

type CardProps = HTMLAttributes<HTMLElement> & { as?: "article" | "section" | "div"; collapsed?: boolean };

/** 对话里的卡片容器：很淡的白到浅蓝渐变、细边框、轻阴影。collapsed 是做完后收成的一行。 */
export function Card({ as: Tag = "article", collapsed, className, ...rest }: CardProps) {
  return <Tag className={join("card", collapsed && "collapsed", className)} {...rest} />;
}

/** 标签：默认浅蓝；sim 用于“模拟”。 */
export function Badge({ sim, children }: { sim?: boolean; children: ReactNode }) {
  return <span className={join("badge", sim && "sim")}>{children}</span>;
}

export type IconName = "menu" | "check" | "book" | "file" | "chevron" | "down" | "plus" | "up" | "close";

const PATHS: Record<IconName, string> = {
  menu: "M5 8h14M5 16h14",
  check: "m6 12 4 4 8-9",
  book: "M12 5v15M3 4c4-1 6-1 9 1 3-2 5-2 9-1v15c-4-1-6-1-9 1-3-2-5-2-9-1Z",
  file: "M14 3H5v18h14V8Zm0 0v5h5M8 12h8M8 16h6",
  chevron: "m9 6 6 6-6 6",
  down: "m8 10 4 4 4-4",
  plus: "M12 5v14M5 12h14",
  up: "M12 19V5m-6 6 6-6 6 6",
  close: "M6 6l12 12M18 6 6 18",
};

/** 细线图标，颜色跟随文字。 */
export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={join("icon", className)} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

/** 今天三件的三种图标：学新的（书）、练一练（纸笔）、补一补（复习页）。 */
export function TaskArt({ kind }: { kind: "learn" | "practice" | "repair" | "exam" }) {
  return (
    <span className="task-art" aria-hidden="true">
      <svg viewBox="0 0 40 40">
        {kind === "learn" && (
          <>
            <defs>
              <linearGradient id="xm-cover" x1="0" y1="0" x2="1" y2="1">
                <stop stopColor="#83bdd0" />
                <stop offset="1" stopColor="#4e8fa7" />
              </linearGradient>
            </defs>
            <path d="M10 9h20v25H10z" fill="#395f7320" />
            <path d="M11 7h19v25H11c-3 0-4-2-4-4V11c0-2 1-4 4-4" fill="url(#xm-cover)" />
            <path d="M12 8h16v20H12z" fill="#ffffff25" />
            <path d="M12 31h18v-4H12c-3 0-3 4 0 4" fill="#f4f5f0" />
            <path d="M16 13h8m-8 4h6" fill="none" stroke="#edf8fb" strokeWidth="2" strokeLinecap="round" />
            <path d="M11 8v18" fill="none" stroke="#386f88" strokeWidth="1.5" opacity=".4" />
          </>
        )}
        {kind === "practice" && (
          <>
            <defs>
              <linearGradient id="xm-pencil" x1="0" y1="0" x2="1" y2="1">
                <stop stopColor="#9bc9d6" />
                <stop offset="1" stopColor="#5b9fb6" />
              </linearGradient>
            </defs>
            <rect x="9" y="8" width="22" height="27" rx="4" fill="#36576b18" />
            <rect x="7" y="6" width="22" height="27" rx="4" fill="#f9fcfd" stroke="#c9dfe7" />
            <path d="M12 13h10m-10 5h7m-7 5h5" fill="none" stroke="#98b9c7" strokeWidth="1.5" strokeLinecap="round" />
            <path d="m19 27 3-8 10-10 5 5-10 10-8 3" fill="url(#xm-pencil)" />
            <path d="m19 27 3-8 5 5z" fill="#e5d4b8" />
            <path d="m19 27 1-3 2 2z" fill="#4e6872" />
            <path d="m29 12 5 5" fill="none" stroke="#e5f3f7" strokeWidth="2" />
          </>
        )}
        {kind === "exam" && (
          <>
            <rect x="10" y="8" width="22" height="27" rx="4" fill="#36576b18" />
            <rect x="8" y="6" width="22" height="27" rx="4" fill="#f9fcfd" stroke="#c9dfe7" />
            <path d="M13 13h12m-12 5h8" fill="none" stroke="#98b9c7" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="27" cy="27" r="7" fill="#5b9fb6" />
            <path d="m24 27 2 2 4-4" fill="none" stroke="#f4fafc" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
        {kind === "repair" && (
          <>
            <path d="M10 12h18v22H10z" fill="#36576b16" />
            <rect x="8" y="10" width="18" height="22" rx="4" fill="#f8fbfd" stroke="#c9dfe7" />
            <path d="M13 17h7m-7 5h6" stroke="#9fbcc9" strokeWidth="1.6" strokeLinecap="round" />
            <path d="M22 9a10 10 0 0 1 10 14" fill="none" stroke="#6fa5ba" strokeWidth="3.2" strokeLinecap="round" />
            <path d="m28 21 4 4 4-4" fill="none" stroke="#6fa5ba" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
      </svg>
    </span>
  );
}

function join(...names: (string | false | undefined | null)[]) {
  return names.filter(Boolean).join(" ");
}
