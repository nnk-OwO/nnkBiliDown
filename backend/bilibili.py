"""Bilibili 网络访问与视频解析。

解析不走 yt-dlp（更快、更可控），下载仍由 yt-dlp 执行。
这里直接调用 B 站 Web API：
- 视频信息:  x/web-interface/view
- 播放流信息: x/player/wbi/playurl（需要 WBI 签名）
- 番剧信息:  pgc/view/web/season
- UP 主投稿:  x/space/wbi/arc/search
- 收藏夹:    x/v3/fav/resource/list
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
from http.cookies import SimpleCookie
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bilibili.com",
}

# 大会员/登录 质量号（B 站经典 quality 编号）
VIP_QUALITIES = {74, 112, 116, 120, 125, 126, 127}
LOGIN_QUALITIES = {64, 80} | VIP_QUALITIES
VIP_HINTS = ("高码率", "HDR", "杜比", "4K", "8K", "大会员", "会员")

_CODEC_LABELS = {
    "avc": ("avc1", "AVC (H.264)"),
    "hevc": ("hev1", "HEVC (H.265)"),
    "av1": ("av01", "AV1"),
}


def mask_cookie(cookie: str) -> str:
    """日志里只显示 Cookie 的少量首尾字符，绝不输出完整值。"""
    c = (cookie or "").strip()
    if not c:
        return "<empty>"
    if len(c) <= 12:
        return "*" * min(len(c), 4)
    return f"{c[:5]}...{c[-4:]}"


def parse_cookie_fields(cookie: str) -> dict[str, str]:
    """把浏览器 Cookie 请求头解析为 name -> value。"""
    fields: dict[str, str] = {}
    for part in (cookie or "").split(";"):
        if "=" not in part:
            continue
        k, _, v = part.strip().partition("=")
        k = k.strip()
        if k:
            fields[k] = v.strip()
    return fields


def cookie_to_netscape(cookie: str) -> str:
    """把原始 Cookie 转成 yt-dlp 可用的 Netscape cookie 文件内容。"""
    lines = ["# Netscape HTTP Cookie File", "# nnkBiliDown - managed cookies"]
    for name, value in parse_cookie_fields(cookie).items():
        # tab 分隔：domain, flag, path, secure, expiry, name, value
        lines.append(f".bilibili.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def extract_url(text: str) -> str:
    """从用户输入（可能混有文字）中提取第一个 URL。"""
    m = re.search(r"https?://[^\s<>'\"]+", text or "")
    return m.group(0).rstrip("，。；、）)]") if m else (text or "").strip()


def canonical_video_url(bvid: str, page: int = 1) -> str:
    base = f"https://www.bilibili.com/video/{bvid}"
    return f"{base}?p={page}" if page > 1 else base


class BiliError(Exception):
    """可安全展示给用户的 B 站相关错误。"""

    def __init__(self, message: str, code: int | None = None):
        self.code = code
        super().__init__(message)


class BiliClient:
    def __init__(self, cookie: str = "", proxy: str = "", timeout: float = 20.0):
        headers = dict(BASE_HEADERS)
        self.cookie = (cookie or "").strip()
        if self.cookie:
            headers["Cookie"] = self.cookie
        self.client = httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            proxy=proxy or None,
        )
        self._wbi_key: str | None = None
        self._wbi_key_ts = 0.0

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "BiliClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------- 基础请求 ----------
    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        raw_nav: bool = False,
        referer: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Referer": referer or BASE_HEADERS["Referer"]} if referer else None
        try:
            resp = self.client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            # 412/风控时给出友好提示
            if exc.response.status_code in (412, 403):
                raise BiliError("B 站风控校验失败（412/403），请稍后重试或先在浏览器中打开一次该页面") from exc
            raise BiliError(f"B 站接口请求失败（HTTP {exc.response.status_code}）") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise BiliError(f"无法连接 B 站：{exc.__class__.__name__}") from exc

        if raw_nav:
            return data
        code = data.get("code")
        if code not in (0, None):
            msg = str(data.get("message") or data.get("msg") or "未知错误")
            if code == -101:
                raise BiliError("登录状态已失效，请重新登录")
            if code in (-352, -412):
                raise BiliError("B 站风控校验失败，请稍后重试或在浏览器中打开一次该页面")
            if code == -404:
                raise BiliError("视频不存在或已失效")
            if code in (62002, 62004):
                raise BiliError("视频不可见或分P失效")
            raise BiliError(f"B 站返回错误（{code}）：{msg}", code=int(code))
        result = data.get("data")
        if result is None:
            return data
        return result

    # ---------- 账号 / WBI ----------
    def account_info(self) -> dict[str, Any]:
        data = self._request_json("https://api.bilibili.com/x/web-interface/nav", raw_nav=True)
        payload = data.get("data") or {}
        self._refresh_wbi_from_nav(payload)
        return payload

    def _refresh_wbi_from_nav(self, nav_data: dict[str, Any]) -> None:
        try:
            wbi = nav_data.get("wbi_img") or {}
            lookup = "".join(
                re.search(r"/([^/]+)\.png", str(wbi.get(k, ""))).group(1)
                for k in ("img_url", "sub_url")
            )
            if len(lookup) < 32:
                return
            mixin = [
                46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
                33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
                61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
                36, 20, 34, 44, 52,
            ]
            self._wbi_key = "".join(lookup[i] for i in mixin)[:32]
            self._wbi_key_ts = time.time()
        except Exception:
            self._wbi_key = None

    def _ensure_wbi_key(self) -> str:
        if not self._wbi_key or time.time() - self._wbi_key_ts > 6 * 3600:
            self.account_info()
        if not self._wbi_key:
            raise BiliError("无法获取 B 站 WBI 签名密钥")
        return self._wbi_key

    def _sign_wbi(self, params: dict[str, Any]) -> dict[str, Any]:
        params = {k: v for k, v in params.items() if v is not None}
        params["wts"] = round(time.time())
        cleaned = {
            k: "".join(ch for ch in str(v) if ch not in "!'()*")
            for k, v in sorted(params.items())
        }
        query = urlencode(cleaned)
        params["w_rid"] = hashlib.md5((query + self._ensure_wbi_key()).encode()).hexdigest()
        return params

    # ---------- 视频 ----------
    def video_info(self, bvid: str | None = None, aid: str | int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if aid:
            params["aid"] = aid
        elif bvid:
            params["bvid"] = bvid
        return self._request_json("https://api.bilibili.com/x/web-interface/view", params=params)

    def video_playurl(self, cid: int, bvid: str | None = None, aid: str | int | None = None) -> dict[str, Any]:
        base: dict[str, Any] = {"cid": cid, "fnval": 4048, "fourk": 1}
        if aid:
            base["aid"] = aid
        elif bvid:
            base["bvid"] = bvid
        params = self._sign_wbi(base)
        return self._request_json(
            "https://api.bilibili.com/x/player/wbi/playurl", params=params
        )

    # ---------- 番剧 / 影视 ----------
    def pgc_season(self, *, season_id: str | None = None, ep_id: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if ep_id:
            params["ep_id"] = ep_id
        elif season_id:
            params["season_id"] = season_id
        else:
            raise BiliError("缺少番剧 season/ep 参数")
        result = self._request_json("https://api.bilibili.com/pgc/view/web/season", params=params)
        return result.get("result") or result

    def pgc_playurl(self, ep_id: str | int, cid: int) -> dict[str, Any]:
        data = self._request_json(
            "https://api.bilibili.com/pgc/player/web/playurl",
            params={"ep_id": ep_id, "cid": cid, "fnval": 4048, "fourk": 1},
        )
        return data.get("result") or data

    # ---------- UP 主空间 / 收藏夹 ----------
    def space_videos(self, mid: str, pn: int = 1, ps: int = 30) -> dict[str, Any]:
        params = self._sign_wbi(
            {
                "mid": mid,
                "ps": ps,
                "pn": pn,
                "order": "pubdate",
                "platform": "web",
                "web_location": "1550101",
            }
        )
        return self._request_json(
            "https://api.bilibili.com/x/space/wbi/arc/search", params=params
        )

    def fav_resources(self, media_id: str, pn: int = 1, ps: int = 20) -> dict[str, Any]:
        return self._request_json(
            "https://api.bilibili.com/x/v3/fav/resource/list",
            params={"media_id": media_id, "pn": pn, "ps": ps, "platform": "web"},
        )

    def danmaku_xml(self, cid: int) -> str:
        try:
            resp = self.client.get(f"https://comment.bilibili.com/{cid}.xml")
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            raise BiliError(f"弹幕下载失败：{exc}") from exc


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------
VIDEO_RE = re.compile(r"bilibili\.com/video/(BV[0-9A-Za-z]+|av\d+)", re.I)
BANGUMI_EP_RE = re.compile(r"bilibili\.com/bangumi/play/ep(\d+)", re.I)
BANGUMI_SS_RE = re.compile(r"bilibili\.com/bangumi/play/ss(\d+)", re.I)
SPACE_RE = re.compile(r"space\.bilibili\.com/(\d+)(?:/(?:video|channel/collectiondetail\?sid=\d+))?", re.I)
FAV_MEDIA_RE = re.compile(r"bilibili\.com/medialist/play/ml(\d+)", re.I)
FAV_LIST_RE = re.compile(r"space\.bilibili\.com/\d+/favlist\?fid=(\d+)", re.I)


def _https(url: str | None) -> str:
    if not url:
        return ""
    return re.sub(r"^https?://", "https://", str(url))


def _fmt_duration(seconds: Any) -> int:
    try:
        return max(0, int(seconds or 0))
    except (TypeError, ValueError):
        return 0


def _codec_from_string(codec: str) -> dict[str, str] | None:
    if not codec:
        return None
    low = codec.lower()
    if low.startswith(("avc1", "avc3")):
        return {"value": "avc", "prefix": "avc1", "label": "AVC (H.264)"}
    if low.startswith(("hev1", "hvc1")):
        return {"value": "hevc", "prefix": "hev1", "label": "HEVC (H.265)"}
    if low.startswith(("av01", "av1")):
        return {"value": "av1", "prefix": "av01", "label": "AV1"}
    if low.startswith("vp9"):
        return {"value": "auto", "prefix": "vp9", "label": "VP9"}
    return {"value": "auto", "prefix": "", "label": "自动"}


def _quality_label(quality: int, support: dict[str, Any] | None) -> tuple[str, str, str]:
    """返回 (主标签, 副标签, 完整说明)。"""
    desc = ""
    superscript = ""
    if support:
        desc = str(
            support.get("new_description")
            or support.get("description")
            or support.get("display_desc")
            or ""
        )
        superscript = str(support.get("superscript") or "")
    base_heights = {
        127: "8K", 126: "杜比视界", 125: "HDR", 120: "4K", 116: "1080P 60帧",
        112: "1080P 高码率", 80: "1080P", 74: "720P 60帧", 64: "720P",
        32: "480P", 16: "360P", 6: "240P",
    }
    main = base_heights.get(quality, f"Q{quality}")
    suffix = ""
    if "高码率" in desc or "高码率" in superscript:
        suffix = " 高码率"
    if "60帧" in desc or "60帧" in superscript or "60FPS" in desc.upper():
        if "60" not in main:
            main += " 60帧"
    if "HDR" in desc or "HDR" in superscript:
        main = "HDR"
        suffix = ""
    if "杜比" in desc or "杜比" in superscript:
        main = "杜比视界"
        suffix = ""
    if "8K" in desc:
        main = "8K"
    if "4K" in desc:
        main = "4K"
    full = f"{main}{suffix}"
    return main, desc or superscript or "", full


def build_quality_options(play_data: dict[str, Any]) -> list[dict[str, Any]]:
    """根据 playurl 响应整理清晰度/编码选项。

    仅出现在 dash.video 中的质量视为“当前账号可下载”；
    support_formats 中的高画质即使不在 dash 里也会展示（灰锁状态），
    方便用户看到登录/大会员后可解锁的档位。
    """
    support_list = play_data.get("support_formats") or []
    dash = play_data.get("dash") or {}
    dash_videos = dash.get("video") or []

    support_by_q: dict[int, dict[str, Any]] = {}
    for item in support_list:
        try:
            q = int(item.get("quality"))
        except (TypeError, ValueError):
            continue
        support_by_q[q] = item

    dash_by_q: dict[int, list[dict[str, Any]]] = {}
    for v in dash_videos:
        try:
            q = int(v.get("id"))
        except (TypeError, ValueError):
            continue
        dash_by_q.setdefault(q, []).append(v)

    ordered_qs: list[int] = []
    for item in support_list:
        q = item.get("quality")
        if q not in ordered_qs:
            ordered_qs.append(int(q))
    for q in sorted(dash_by_q, reverse=True):
        if q not in ordered_qs:
            ordered_qs.append(q)
    ordered_qs.sort(reverse=True)

    options: list[dict[str, Any]] = []
    for q in ordered_qs:
        support = support_by_q.get(q)
        dash_entries = dash_by_q.get(q, [])
        available = bool(dash_entries)
        if not dash_entries and (play_data.get("durl") or not dash_videos):
            available = True

        desc = ""
        superscript = ""
        need_login = False
        need_vip = False
        if support:
            desc = str(support.get("new_description") or support.get("description") or "")
            superscript = str(support.get("superscript") or "")
            need_login = bool(support.get("need_login"))
            need_vip = bool(support.get("need_vip"))
        if q in VIP_QUALITIES or any(k in desc or k in superscript for k in VIP_HINTS):
            need_vip = True
        if q in LOGIN_QUALITIES or need_vip:
            need_login = True

        main, sub, full = _quality_label(q, support)
        height = 0
        fps = 0.0
        for v in dash_entries:
            height = int(v.get("height") or height or 0)
            fps = float(v.get("frameRate") or v.get("frame_rate") or fps or 0)

        codecs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for v in dash_entries:
            c = _codec_from_string(str(v.get("codecs") or ""))
            if not c or c["value"] in seen:
                continue
            seen.add(c["value"])
            codecs.append({**c, "available": True})
        for codec_name in support.get("codecs") or []:
            c = _codec_from_string(str(codec_name))
            if not c or c["value"] in seen:
                continue
            seen.add(c["value"])
            codecs.append({**c, "available": available})
        if not codecs:
            codecs.append({"value": "auto", "prefix": "", "label": "自动", "available": available})

        options.append(
            {
                "quality": q,
                "label": main,
                "sub_label": sub,
                "description": full,
                "height": height,
                "fps": round(fps, 3),
                "available": available,
                "requires_login": need_login,
                "requires_vip": need_vip,
                "codecs": codecs,
            }
        )
    return options


def build_format_selector(quality: int, codec: str = "auto") -> str:
    """生成 yt-dlp format 选择器。

    例如：bestvideo[quality=80][vcodec^=avc1]+bestaudio/bestvideo[quality=80]+bestaudio/best
    优先 DASH 分离流，合并交给 ffmpeg；老视频则回退到整段 mp4/flv。
    """
    codec_filter = ""
    if codec in _CODEC_LABELS:
        prefix = _CODEC_LABELS[codec][0]
        codec_filter = f"[vcodec^={prefix}]"
    video = f"bestvideo[quality={quality}]{codec_filter}"
    return f"{video}+bestaudio/bestvideo[quality={quality}]+bestaudio/best[quality={quality}]/best"


def _clean_html(text: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class BiliResolver:
    """把用户输入的 URL 解析成统一结构，供前端展示和创建任务使用。"""

    def __init__(self, cookie: str = "", proxy: str = ""):
        self.client = BiliClient(cookie=cookie, proxy=proxy)
        self.proxy = proxy

    def close(self) -> None:
        self.client.close()

    def resolve_redirect(self, url: str) -> str:
        current = url
        for _ in range(5):
            if not re.search(r"b23\.tv|bili2233\.cn", current):
                break
            try:
                resp = self.client.client.get(current, follow_redirects=False)
                location = resp.headers.get("location")
                if not location:
                    m = re.search(r"https?://www\.bilibili\.com/[^\s\"'<>]+", resp.text)
                    location = m.group(0) if m else None
                if not location:
                    break
                if not location.startswith("http"):
                    location = urlparse(current)._replace(path=location).geturl()
                current = location
            except httpx.HTTPError as exc:
                raise BiliError("短链接跳转失败，请直接粘贴完整 BV/番剧链接") from exc
        return current

    @staticmethod
    def url_kind(url: str) -> str:
        if VIDEO_RE.search(url):
            return "video"
        if BANGUMI_EP_RE.search(url) or BANGUMI_SS_RE.search(url):
            return "bangumi"
        if SPACE_RE.search(url):
            return "space"
        if FAV_MEDIA_RE.search(url) or FAV_LIST_RE.search(url):
            return "favorite"
        return "unknown"

    def _parse_video(self, url: str) -> dict[str, Any]:
        m = VIDEO_RE.search(url)
        if not m:
            raise BiliError("未识别到 BV/av 视频号")
        video_ref = m.group(1)
        aid: str | int | None = None
        bvid: str | None = None
        if video_ref.lower().startswith("av"):
            aid = video_ref[2:]
        else:
            bvid = video_ref
        info = self.client.video_info(bvid=bvid, aid=aid)
        if aid and not bvid:
            bvid = str(info.get("bvid") or "")
        pages_raw = info.get("pages") or []
        if not pages_raw:
            raise BiliError("视频没有可下载的分P")
        pages = []
        for idx, p in enumerate(pages_raw, start=1):
            pages.append(
                {
                    "index": idx,
                    "cid": int(p.get("cid") or 0),
                    "bvid": bvid or str(info.get("bvid") or ""),
                    "part": str(p.get("part") or f"P{idx}"),
                    "duration": _fmt_duration(p.get("duration")),
                    "url": canonical_video_url(video_ref, idx),
                }
            )
        play_data = self.client.video_playurl(pages[0]["cid"], bvid=bvid)
        account = self.client.account_info()
        return {
            "type": "video",
            "title": str(info.get("title") or "未命名视频"),
            "uploader": str((info.get("owner") or {}).get("name") or "未知 UP 主"),
            "uploader_id": int((info.get("owner") or {}).get("mid") or 0),
            "cover": _https(info.get("pic")),
            "duration": _fmt_duration(info.get("duration")),
            "description": _clean_html(info.get("desc")),
            "pages": pages,
            "quality_options": build_quality_options(play_data),
            "account": {
                "is_login": bool(account.get("isLogin")),
                "uname": account.get("uname") or "",
                "mid": account.get("mid") or 0,
                "vip_status": int(account.get("vipStatus") or 0),
            },
        }

    def _parse_bangumi(self, url: str) -> dict[str, Any]:
        ep_m = BANGUMI_EP_RE.search(url)
        ss_m = BANGUMI_SS_RE.search(url)
        season = self.client.pgc_season(
            season_id=ss_m.group(1) if ss_m else None,
            ep_id=ep_m.group(1) if ep_m else None,
        )
        episodes = season.get("episodes") or []
        if not episodes:
            raise BiliError("该番剧暂无剧集信息（可能需要会员或已下架）")
        pages = []
        for idx, ep in enumerate(episodes, start=1):
            ep_id = int(ep.get("ep_id") or ep.get("id") or 0)
            pages.append(
                {
                    "index": idx,
                    "cid": int(ep.get("cid") or 0),
                    "bvid": str(ep.get("bvid") or ""),
                    "ep_id": ep_id,
                    "part": str(ep.get("long_title") or ep.get("title") or f"第{idx}话"),
                    "duration": _fmt_duration((int(ep.get("duration") or 0)) / 1000),
                    "url": str(ep.get("link") or f"https://www.bilibili.com/bangumi/play/ep{ep_id}"),
                }
            )
        first = episodes[0]
        play_data = self.client.pgc_playurl(
            ep_id=first.get("ep_id") or first.get("id"),
            cid=int(first.get("cid") or 0),
        )
        account = self.client.account_info()
        return {
            "type": "bangumi",
            "title": str(season.get("title") or "未命名番剧"),
            "uploader": "哔哩哔哩番剧",
            "uploader_id": 0,
            "cover": _https(season.get("cover")),
            "duration": _fmt_duration((int(episodes[0].get("duration") or 0)) / 1000),
            "description": str(season.get("evaluate") or ""),
            "pages": pages,
            "quality_options": build_quality_options(play_data),
            "account": {
                "is_login": bool(account.get("isLogin")),
                "uname": account.get("uname") or "",
                "mid": account.get("mid") or 0,
                "vip_status": int(account.get("vipStatus") or 0),
            },
        }

    def _parse_space(self, url: str) -> dict[str, Any]:
        m = SPACE_RE.search(url)
        if not m:
            raise BiliError("无法识别 UP 主空间链接")
        mid = m.group(1)
        collected: list[dict[str, Any]] = []
        page_count = 0
        for pn in range(1, 6):
            data = self.client.space_videos(mid, pn=pn, ps=30)
            vlist = (data.get("list") or {}).get("vlist") or []
            if not vlist:
                break
            for item in vlist:
                bvid = str(item.get("bvid") or "")
                collected.append(
                    {
                        "index": len(collected) + 1,
                        "cid": 0,
                        "bvid": bvid,
                        "part": str(item.get("title") or ""),
                        "duration": _fmt_duration(item.get("length")),
                        "url": canonical_video_url(bvid, 1),
                        "cover": _https(item.get("pic")),
                    }
                )
            page_count = int((data.get("page") or {}).get("count") or 0)
            if pn * 30 >= page_count:
                break
        if not collected:
            raise BiliError("该 UP 主暂无公开视频")
        first = collected[0]
        quality_options = self._quality_options_for_bvid(first["bvid"])
        account = self.client.account_info()
        return {
            "type": "space",
            "title": f"UP 主 {mid} 的投稿",
            "uploader": f"UID:{mid}",
            "uploader_id": int(mid),
            "cover": first.get("cover") or "",
            "duration": sum(p["duration"] for p in collected),
            "description": f"共解析到 {len(collected)} 个视频",
            "pages": collected,
            "quality_options": quality_options,
            "account": {
                "is_login": bool(account.get("isLogin")),
                "uname": account.get("uname") or "",
                "mid": account.get("mid") or 0,
                "vip_status": int(account.get("vipStatus") or 0),
            },
        }

    def _parse_favorite(self, url: str) -> dict[str, Any]:
        m = FAV_MEDIA_RE.search(url) or FAV_LIST_RE.search(url)
        if not m:
            raise BiliError("无法识别收藏夹链接")
        media_id = m.group(1)
        collected: list[dict[str, Any]] = []
        last_data: dict[str, Any] = {}
        for pn in range(1, 6):
            data = self.client.fav_resources(media_id, pn=pn, ps=20)
            last_data = data
            medias = data.get("medias") or []
            if not medias:
                break
            for item in medias:
                bvid = str(item.get("bvid") or "")
                collected.append(
                    {
                        "index": len(collected) + 1,
                        "cid": 0,
                        "bvid": bvid,
                        "part": str(item.get("title") or ""),
                        "duration": _fmt_duration(item.get("duration")),
                        "url": canonical_video_url(bvid, 1),
                        "cover": _https(item.get("cover")),
                    }
                )
            if not data.get("has_more"):
                break
        if not collected:
            raise BiliError("该收藏夹暂无内容或不可见")
        first = collected[0]
        quality_options = self._quality_options_for_bvid(first["bvid"])
        info = last_data.get("info") or {}
        account = self.client.account_info()
        return {
            "type": "favorite",
            "title": str(info.get("title") or f"收藏夹 {media_id}"),
            "uploader": str((info.get("upper") or {}).get("name") or "UP 主"),
            "uploader_id": int((info.get("upper") or {}).get("mid") or 0),
            "cover": _https(info.get("cover")) or first.get("cover") or "",
            "duration": sum(p["duration"] for p in collected),
            "description": f"共解析到 {len(collected)} 个视频",
            "pages": collected,
            "quality_options": quality_options,
            "account": {
                "is_login": bool(account.get("isLogin")),
                "uname": account.get("uname") or "",
                "mid": account.get("mid") or 0,
                "vip_status": int(account.get("vipStatus") or 0),
            },
        }

    def _quality_options_for_bvid(self, bvid: str) -> list[dict[str, Any]]:
        if not bvid:
            return []
        try:
            info = self.client.video_info(bvid)
            pages = info.get("pages") or []
            cid = int((pages[0] if pages else {}).get("cid") or info.get("cid") or 0)
            if not cid:
                return []
            return build_quality_options(self.client.video_playurl(cid, bvid=bvid))
        except BiliError:
            return []

    def parse(self, raw_url: str) -> dict[str, Any]:
        url = extract_url(raw_url)
        if not url:
            raise BiliError("请输入 Bilibili 链接")
        url = self.resolve_redirect(url)
        kind = self.url_kind(url)
        if kind == "video":
            result = self._parse_video(url)
        elif kind == "bangumi":
            result = self._parse_bangumi(url)
        elif kind == "space":
            result = self._parse_space(url)
        elif kind == "favorite":
            result = self._parse_favorite(url)
        else:
            raise BiliError("暂不支持该链接类型。请使用 BV/av 视频、番剧 ep/ss、UP 主空间或收藏夹链接")
        result["url"] = url
        result["normalized_url"] = url
        return result
