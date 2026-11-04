"""若 .env 里的 AUTH_SECRET 是空的，写进一串本机随机值。不打印这串值。"""

from __future__ import annotations

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def main() -> None:
    if not ENV.exists():
        ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    lines = ENV.read_text(encoding="utf-8").splitlines()
    found = False
    changed = False
    for index, line in enumerate(lines):
        if line.startswith("AUTH_SECRET=") or line.startswith("AUTH_SECRET ="):
            found = True
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not value:
                lines[index] = "AUTH_SECRET=" + secrets.token_hex(32)
                changed = True
            break
    if not found:
        lines.append("AUTH_SECRET=" + secrets.token_hex(32))
        changed = True
    if changed:
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("已在 .env 写入本机 AUTH_SECRET（没有打印内容）。")
    else:
        print("AUTH_SECRET 已有值，没有改动。")


if __name__ == "__main__":
    main()
