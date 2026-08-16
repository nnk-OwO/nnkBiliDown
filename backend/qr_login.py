"""B 站扫码登录。

流程：
1. GET passport.bilibili.com/x/passport-login/web/qrcode/generate 获取二维码
2. 轮询 /x/passport-login/web/qrcode/poll
3. 扫码确认后从 data.url 的 query 中解析 SESSDATA 等字段，保存 Cookie

注意：解析回调 URL 时不能使用 urllib.parse.parse_qs()。
parse_qs 会把字面量 "+" 当成空格，从而破坏 SESSDATA。
"""
from __future__ import annotations

import base64
import io
import threading
import time
import urllib.parse
from typing import Any, Optional

import httpx

from .bilibili import USER_AGENT, BiliError

try:
    import qrcode
except ImportError:  # 允许不装 qrcode 时降级为文本提示
    qrcode = None

COOKIE_NAMES = ("DedeUserID", "DedeUserID__ckMd5", "SESSDATA", "bili_jct", "sid")


def _qr_image_data_uri(url: str) -> str:
    """生成 PNG data URI，浏览器兼容性最好。"""
    if qrcode is None:
        return ""
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class QRLoginManager:
    """全局只允许一个待扫码会话。"""

    def __init__(self, timeout: float = 15.0):
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://www.bilibili.com/",
            },
        )
        self._session: Optional[dict[str, Any]] = None

    def generate(self) -> dict[str, Any]:
        try:
            resp = self._client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BiliError(f"二维码生成失败：{exc.__class__.__name__}") from exc
        if data.get("code") != 0:
            raise BiliError(f"二维码生成失败：{data.get('message') or data.get('msg')}")
        payload = data.get("data") or {}
        key = payload.get("qrcode_key")
        url = payload.get("url")
        if not key or not url:
            raise BiliError("二维码响应缺少关键字段")
        with self._lock:
            self._session = {"key": key, "url": url, "created": time.time()}
        return {
            "qrcode_key": key,
            "url": url,
            "image": _qr_image_data_uri(url),
        }

    def poll(self, key: str) -> dict[str, Any]:
        with self._lock:
            session = self._session
            if not session or session.get("key") != key:
                raise BiliError("二维码会话不存在或已过期，请重新生成")
            if time.time() - float(session.get("created") or 0) > 180:
                raise BiliError("二维码已过期，请重新生成")

        try:
            resp = self._client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": key},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BiliError(f"二维码状态查询失败：{exc.__class__.__name__}") from exc

        if data.get("code") != 0:
            raise BiliError(f"二维码状态查询失败：{data.get('message') or data.get('msg')}")

        payload = data.get("data") or {}
        state = payload.get("code")

        if state == 0:
            return self._handle_success(payload)

        if state == 86090:
            return {"status": "scanned", "message": "已扫码，请在手机上确认"}
        if state == 86101:
            return {"status": "waiting", "message": "等待扫码"}
        if state == 86038:
            with self._lock:
                self._session = None
            return {"status": "expired", "message": "二维码已过期"}

        # 其它未知状态按等待处理，前端继续轮询
        return {"status": "waiting", "message": str(payload.get("message") or "等待扫码")}

    def _handle_success(self, payload: dict[str, Any]) -> dict[str, Any]:
        cookie = self._cookie_from_login_url(str(payload.get("url") or ""))
        # 少数情况下字段通过 Set-Cookie 返回，这里做兜底补齐
        session_cookie = self._cookie_from_session()

        if cookie and session_cookie:
            existing = {
                part.split("=", 1)[0]
                for part in cookie.split("; ")
                if "=" in part
            }
            extra = [
                part
                for part in session_cookie.split("; ")
                if "=" in part and part.split("=", 1)[0] not in existing
            ]
            if extra:
                cookie = "; ".join([cookie, *extra])
        else:
            cookie = cookie or session_cookie

        if not cookie:
            with self._lock:
                self._session = None
            raise BiliError("扫码成功但未获取到登录 Cookie，请重新生成二维码再试")

        with self._lock:
            self._session = None
        return {"status": "success", "cookie": cookie, "message": "登录成功"}

    @staticmethod
    def _cookie_from_login_url(url: str) -> str:
        """从登录回调 URL 的 query 中提取 Cookie 字段。

        B 站回调 URL 形如：
        https://passport.bilibili.com/...crossDomain?DedeUserID=...&SESSDATA=...&bili_jct=...
        这里手动拆分，并对 %XX 做 unquote（unquote 不会把 + 转成空格）。
        """
        query = urllib.parse.urlsplit(url).query
        parts = []
        for item in query.split("&"):
            name, sep, raw_value = item.partition("=")
            if not sep or name not in COOKIE_NAMES:
                continue
            value = urllib.parse.unquote(raw_value)
            if value:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    def _cookie_from_session(self) -> str:
        """从本轮请求的 cookie jar 中兜底提取登录字段。"""
        parts = []
        try:
            cookies = self._client.cookies.jar
        except AttributeError:
            return ""
        for cookie in cookies:
            if cookie.name in COOKIE_NAMES and cookie.value:
                parts.append(f"{cookie.name}={cookie.value}")
        return "; ".join(parts)

    def close(self) -> None:
        self._client.close()
