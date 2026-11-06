"""验证构建产物、鉴权和看板 API；只适用于明确启动的测试实例。"""
import argparse
from http.cookiejar import CookieJar
from http.client import HTTPException
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    args=parser.parse_args()
    base=args.base_url.rstrip("/")
    opener=build_opener(ProxyHandler({}),HTTPCookieProcessor(CookieJar()))
    for attempt in range(20):
        try:
            with opener.open(base+"/health",timeout=2) as response:
                assert response.status == 200
            break
        except (URLError, TimeoutError, ConnectionError, HTTPException):
            if attempt == 19:
                raise
            time.sleep(1)
    with opener.open(base+"/study/",timeout=5) as response:
        source=response.read().decode()
    assets=re.findall(r'(?:src|href)="(/study/assets/[^\"]+)"',source)
    assert assets, "前端不是 /study/ 构建"
    for asset in assets:
        with opener.open(base+asset,timeout=5) as response:
            assert response.status == 200
    try:
        opener.open(base+"/api/dashboard",timeout=5)
        raise AssertionError("无登录态也能读看板")
    except HTTPError as exc:
        assert exc.code == 401
    with opener.open(Request(base+"/api/session",method="POST"),timeout=5) as response:
        assert response.status == 200
    with opener.open(base+"/api/dashboard",timeout=5) as response:
        payload=json.load(response)
        assert payload["ok"] is True and payload["data"]["range"] == "week"
    print("PASS: health, React assets, authentication, dashboard")


if __name__ == "__main__":
    main()
