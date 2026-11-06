"""验证构建产物、鉴权和看板 API；只适用于明确启动的测试实例。"""
import argparse
from http.cookiejar import CookieJar
from http.client import HTTPException
import json
import math
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request


class SmokeFailure(RuntimeError):
    """测试实例未达到部署要求，错误信息不包含响应正文或会话。"""


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("等待时间必须是正的有限秒数")
    return seconds


def wait_for_health(opener, base, timeout=60):
    """只重试启动阶段的暂时性故障；应用检查失败不靠重试掩盖。"""
    timeout = positive_seconds(timeout)
    deadline = time.monotonic() + timeout
    attempts = 0
    last_error = "尚未响应"
    while (remaining := deadline - time.monotonic()) > 0:
        attempts += 1
        try:
            with opener.open(base + "/health", timeout=min(2, remaining)) as response:
                if response.status != 200:
                    raise SmokeFailure(f"health: HTTP {response.status}")
                try:
                    payload = json.load(response)
                except (ValueError, UnicodeError) as exc:
                    raise SmokeFailure("health: 返回的不是有效 JSON") from exc
                if not isinstance(payload, dict) or payload.get("ok") is not True:
                    raise SmokeFailure("health: 未报告 ok=true")
            print(f"PASS: health ({attempts} 次请求)", flush=True)
            return
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status not in (502, 503, 504):
                raise SmokeFailure(f"health: HTTP {status}，停止等待") from exc
            last_error = f"HTTP {status}"
        except (URLError, TimeoutError, ConnectionError, HTTPException) as exc:
            last_error = type(exc).__name__
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))
    raise SmokeFailure(f"health: {timeout:g} 秒内未就绪（{attempts} 次请求，最后为 {last_error}）")


def run_smoke(base, startup_timeout=60):
    base = base.rstrip("/")
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    wait_for_health(opener, base, startup_timeout)

    def fetch(path, *, method="GET", content_type=None):
        try:
            with opener.open(Request(base + path, method=method), timeout=5) as response:
                if response.status != 200:
                    raise SmokeFailure(f"{path}: HTTP {response.status}")
                if content_type and response.headers.get_content_type() not in content_type:
                    raise SmokeFailure(f"{path}: 资源类型不符，可能返回了错误页")
                return response.read()
        except (URLError, TimeoutError, ConnectionError, HTTPException) as exc:
            reason = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
            if isinstance(exc, HTTPError):
                exc.close()
            raise SmokeFailure(f"{path}: {reason}") from exc

    source = fetch("/study/", content_type={"text/html"}).decode()
    assets = sorted(set(re.findall(r'(?:src|href)="(/study/assets/[^\"]+)"', source)))
    if not any(asset.endswith(".js") for asset in assets) or not any(asset.endswith(".css") for asset in assets):
        raise SmokeFailure("/study/: 缺少 /study/assets/ 下的 JS 或 CSS 构建产物")
    for asset in assets:
        expected = {"text/css"} if asset.endswith(".css") else {"application/javascript", "text/javascript"}
        if not fetch(asset, content_type=expected):
            raise SmokeFailure(f"{asset}: 文件为空")
    avatar = fetch("/study/xiaoman-lake-blue.png", content_type={"image/png"})
    if not avatar.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SmokeFailure("/study/xiaoman-lake-blue.png: 不是有效 PNG 文件")
    print("PASS: React JS, CSS, 小满原图", flush=True)

    try:
        with opener.open(base + "/api/dashboard", timeout=5):
            raise SmokeFailure("/api/dashboard: 无登录态也能读取看板")
    except HTTPError as exc:
        status = exc.code
        exc.close()
        if status != 401:
            raise SmokeFailure(f"/api/dashboard: 匿名请求应为 401，实际为 {status}") from exc
    print("PASS: anonymous dashboard denied", flush=True)
    fetch("/api/session", method="POST")
    try:
        payload = json.loads(fetch("/api/dashboard", content_type={"application/json"}))
    except (ValueError, UnicodeError) as exc:
        raise SmokeFailure("/api/dashboard: 返回的不是有效 JSON") from exc
    if (not isinstance(payload, dict) or payload.get("ok") is not True
            or not isinstance(payload.get("data"), dict) or payload["data"].get("range") != "week"):
        raise SmokeFailure("/api/dashboard: 登录后的看板数据不符合约定")
    print("PASS: signed session and dashboard", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--startup-timeout", type=positive_seconds, default=60)
    args = parser.parse_args()
    try:
        run_smoke(args.base_url, args.startup_timeout)
    except (SmokeFailure, URLError, TimeoutError, ConnectionError, HTTPException, UnicodeError) as exc:
        # 不打印请求/响应正文、Cookie 或健康检查中的运行配置。
        detail = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
        print(f"FAIL: {detail}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
