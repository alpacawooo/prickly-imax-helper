#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html as html_module
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
BUILD = HERE / "build"
HTML = BUILD / "html"
CAROUSEL = HERE / "carousel"
REEL = HERE / "reel"
FRAMES = REEL / "frames"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
PRODUCT_PYTHON = Path("/Users/woojinyoung/.prickly-imax-helper/venv/bin/python")
MANIFEST = HERE / "carousel_manifest.json"
VIDEO_CAROUSEL = HERE / "video-carousel"
VIDEO_COVERS = VIDEO_CAROUSEL / "covers"
VIDEO_CARDS = VIDEO_CAROUSEL / "cards"
SCENE_FRAMES = BUILD / "scene-frames"
ALLOWED_MOTIONS = {
    "none",
    "setup-scroll",
    "workflow-sequence",
    "outcome-sequence",
}
ALLOWED_ANCHORS = {"bottom-left", "top-left", "bottom", "right", "center-left"}
FORBIDDEN_SOURCE_TYPES = {"fake-browser", "fake-terminal", "phone-mockup", "fake-ticket"}
BANNED_COPY = "Prickly AI는 사람이 반복하던 일을 실제로 작동하는 자동화로 바꾼다."


def validate_manifest(cards: list[dict[str, object]]) -> None:
    if [card.get("number") for card in cards] != list(range(1, 9)):
        raise ValueError("video carousel must contain cards 1 through 8 in order")
    expected_media = ["png", "png", "png", "mp4", "mp4", "png", "mp4", "png"]
    if [card.get("media_type") for card in cards] != expected_media:
        raise ValueError("publishable sequence must contain five PNGs and MP4 cards 4, 5, and 7")
    if [card.get("duration") for card in cards] != [None, None, None, 7, 8, None, 8, None]:
        raise ValueError("card 4 must be seven seconds and cards 5 and 7 eight seconds")
    required = {
        "number", "media_type", "duration", "source_type", "source", "headline", "supporting",
        "footer", "composition", "text_anchor", "motion",
    }
    for card in cards:
        number = card.get("number")
        missing = sorted(required - set(card))
        if missing:
            raise ValueError(f"card {number} is missing {', '.join(missing)}")
        if not str(card.get("headline", "")).strip():
            raise ValueError(f"card {number} has no headline")
        if card.get("motion") not in ALLOWED_MOTIONS:
            raise ValueError(f"card {number} has unsupported motion")
        expected_motion = {
            4: "setup-scroll",
            5: "workflow-sequence",
            7: "outcome-sequence",
        }.get(int(number), "none")
        if card.get("motion") != expected_motion:
            raise ValueError(f"card {number} has motion that does not match its media type")
        if card.get("text_anchor") not in ALLOWED_ANCHORS:
            raise ValueError(f"card {number} has unsupported text anchor")
        if card.get("source_type") in FORBIDDEN_SOURCE_TYPES:
            raise ValueError(f"card {number} uses forbidden fake UI")
        source = str(card.get("source", ""))
        if source and not (ROOT / source).is_file():
            raise FileNotFoundError(ROOT / source)
    if len({str(card["composition"]) for card in cards}) < 6:
        raise ValueError("video carousel requires at least six distinct compositions")
    raw = json.dumps(cards, ensure_ascii=False)
    if "ScreenRecording_08-14-2026" in raw or "ai_freaks" in raw.lower() or BANNED_COPY in raw:
        raise ValueError("manifest contains benchmark material or banned copy")


def load_carousel_manifest() -> list[dict[str, object]]:
    cards = json.loads(MANIFEST.read_text(encoding="utf-8"))["cards"]
    validate_manifest(cards)
    return cards


def motion_recipes() -> dict[str, dict[str, float | int]]:
    return {
        "setup-scroll": {"duration": 7, "fps": 30, "viewport_height": 900},
        "workflow-sequence": {"transition_ms": 180},
        "outcome-sequence": {"transition_ms": 180},
    }


def card_four_scroll_offsets(
    *, source_height: int, viewport_height: int, frame_count: int
) -> list[int]:
    if source_height <= 0 or viewport_height <= 0 or frame_count < 2:
        raise ValueError("scroll dimensions must be positive and require at least two frames")
    maximum = max(source_height - viewport_height, 0)
    return [round(maximum * index / (frame_count - 1)) for index in range(frame_count)]


def redact_visual_evidence(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+", "[redacted-email]", value)
    value = re.sub(r"(?i)(cookie|voucher|profile)\s*[=:]\s*\S+", r"\1=[redacted]", value)
    value = re.sub(r"/Users/[^\s]+", "[redacted-path]", value)
    return value


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def capture(html: Path, output: Path, width: int, height: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    script = """
import sys
from playwright.sync_api import sync_playwright
uri, output, chrome, width, height = sys.argv[1:]
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=chrome,
        headless=True,
        args=['--disable-background-networking', '--disable-gpu', '--hide-scrollbars'],
    )
    page = browser.new_page(viewport={'width': int(width), 'height': int(height)}, device_scale_factor=1)
    page.goto(uri, wait_until='load')
    page.wait_for_timeout(250)
    page.screenshot(path=output, full_page=False)
    browser.close()
"""
    run(
        str(PRODUCT_PYTHON),
        "-c",
        script,
        html.as_uri(),
        str(output),
        str(CHROME),
        str(width),
        str(height),
    )


def capture_full_page(html: Path, output: Path, width: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    script = """
import sys
from playwright.sync_api import sync_playwright
uri, output, chrome, width = sys.argv[1:]
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=chrome,
        headless=True,
        args=['--disable-background-networking', '--disable-gpu', '--hide-scrollbars'],
    )
    page = browser.new_page(viewport={'width': int(width), 'height': 1100}, device_scale_factor=1)
    page.goto(uri, wait_until='load')
    page.wait_for_timeout(250)
    page.screenshot(path=output, full_page=True)
    browser.close()
"""
    run(
        str(PRODUCT_PYTHON),
        "-c",
        script,
        html.as_uri(),
        str(output),
        str(CHROME),
        str(width),
    )


def base_css(width: int, height: int) -> str:
    return f"""
    :root {{ --red:#ef382f; --white:#f7f7f3; --muted:#a8abb0; --panel:#171a20; --line:#2b2e34; }}
    * {{ box-sizing:border-box; }}
    html,body {{ margin:0; width:{width}px; height:{height}px; overflow:hidden; background:#0b0d10; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Noto Sans KR',sans-serif; color:var(--white); }}
    .canvas {{ position:relative; width:{width}px; height:{height}px; overflow:hidden; background:
      radial-gradient(circle at 78% 14%, rgba(239,56,47,.10), transparent 34%),
      linear-gradient(145deg,#16191e 0%,#0b0d10 58%,#08090b 100%); }}
    .topline {{ position:absolute; z-index:20; inset:0 0 auto 0; height:7px; background:var(--red); }}
    .brand {{ position:absolute; z-index:20; top:42px; left:0; right:0; text-align:center; font-size:25px; font-weight:800; letter-spacing:-.8px; }}
    .pager {{ position:absolute; z-index:20; right:54px; top:49px; font:600 14px/1 ui-monospace,SFMono-Regular,Menlo,monospace; color:#8f939b; }}
    .content {{ position:absolute; z-index:5; left:72px; right:72px; top:154px; bottom:72px; }}
    .eyebrow {{ display:flex; align-items:center; gap:14px; color:#d1d3d7; font-size:22px; font-weight:700; letter-spacing:.02em; }}
    .eyebrow:before {{ content:''; display:block; width:38px; height:5px; background:var(--red); }}
    h1 {{ margin:34px 0 0; font-size:76px; line-height:1.12; letter-spacing:-4.8px; font-weight:850; }}
    h2 {{ margin:32px 0 0; font-size:61px; line-height:1.18; letter-spacing:-3.3px; font-weight:840; }}
    .red {{ color:var(--red); }}
    .sub {{ margin-top:34px; max-width:810px; font-size:29px; line-height:1.55; letter-spacing:-1.1px; color:#d5d7da; font-weight:600; }}
    .small {{ font-size:20px; line-height:1.5; color:#999da4; }}
    .foot {{ position:absolute; left:72px; right:72px; bottom:46px; z-index:12; display:flex; justify-content:space-between; align-items:center; color:#747880; font-size:14px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    .rule {{ height:1px; background:#30333a; margin-top:34px; }}
    .card {{ border:1px solid #292d34; background:rgba(22,25,30,.90); border-radius:24px; box-shadow:0 22px 55px rgba(0,0,0,.28); }}
    .glass {{ border:1px solid rgba(255,255,255,.12); background:rgba(15,17,21,.78); border-radius:28px; box-shadow:0 30px 90px rgba(0,0,0,.42); }}
    .pill {{ display:inline-flex; align-items:center; min-height:50px; padding:0 22px; border:1px solid #3a3e45; border-radius:99px; background:#181b20; color:#e9eaec; font-size:20px; font-weight:700; }}
    .check {{ width:38px; height:38px; border-radius:50%; display:grid; place-items:center; background:rgba(239,56,47,.16); border:1px solid rgba(239,56,47,.55); color:var(--red); font-size:24px; font-weight:900; }}
    .status-dot {{ width:13px; height:13px; border-radius:50%; background:#58d68d; box-shadow:0 0 0 7px rgba(88,214,141,.12); }}
    .bg-photo {{ position:absolute; inset:0; background-size:cover; background-position:center; }}
    .scrim {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(6,7,9,.20),rgba(6,7,9,.76) 54%,rgba(6,7,9,.96)); }}
    """


def page(body: str, *, width: int, height: int, extra_css: str = "") -> str:
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
    <meta name="viewport" content="width={width},initial-scale=1"><style>{base_css(width,height)}{extra_css}</style></head>
    <body><div class="canvas">{body}</div></body></html>"""


def header(n: int, total: int) -> str:
    return f'<div class="topline"></div><div class="brand">prickly.ai</div><div class="pager">{n:02d} / {total:02d}</div>'


def footer(label: str) -> str:
    return f'<div class="foot"><span>{label}</span><span>PRICKLY IMAX HELPER</span></div>'


def img_uri(path: Path) -> str:
    return path.resolve().as_uri()


def install_guide_preview() -> Path:
    path = HTML / "install-guide-preview.html"
    source = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}html,body{margin:0;width:900px;height:1600px;overflow:hidden;background:#f7f7f5}
    body{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#191919}
    main{padding:72px 70px 100px}.mark{font-size:18px;font-weight:850;letter-spacing:-.4px;color:#ef382f}
    h1{font-size:48px;line-height:1.16;letter-spacing:-2.5px;margin:22px 0 18px}p{font-size:21px;line-height:1.58;color:#555;margin:0}
    .callout{margin-top:32px;padding:24px 26px;background:#fff3f2;border-left:5px solid #ef382f;border-radius:10px;font-size:20px;line-height:1.5}
    h2{font-size:29px;letter-spacing:-1px;margin:45px 0 18px}.os{display:grid;grid-template-columns:1fr 1fr;gap:16px}.os div{background:white;border:1px solid #dfdfdc;border-radius:14px;padding:22px;font-size:22px;font-weight:800}.os small{display:block;margin-top:8px;color:#777;font-size:15px;font-weight:650}
    .steps{display:grid;gap:14px}.step{display:grid;grid-template-columns:42px 1fr;gap:14px;align-items:start;background:white;border:1px solid #e0e0dd;border-radius:14px;padding:20px}.num{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:#ef382f;color:white;font-weight:900}.step b{display:block;font-size:21px}.step span{display:block;margin-top:6px;color:#666;font-size:17px;line-height:1.45}
    .toggle{margin-top:14px;padding:18px 20px;background:#ececea;border-radius:10px;font-size:18px;font-weight:760}.footer{margin-top:34px;padding-top:26px;border-top:1px solid #d8d8d4;color:#777;font-size:16px;line-height:1.55}
    </style></head><body><main><div class="mark">prickly.ai</div><h1>Prickly IMAX Helper<br>3분 설치 안내</h1><p>개발 지식 없이 내 컴퓨터에서 설치하고, 전용 Chrome에서 본인이 직접 CGV에 로그인합니다.</p>
    <div class="callout"><b>비밀번호와 결제정보는 입력하지 않습니다.</b><br>카드 결제는 자동화하지 않으며, 등록된 IMAX 영화관람권과 잔액 0원 조건만 사용합니다.</div>
    <h2>내 운영체제 선택</h2><div class="os"><div>🍎 macOS 전용<small>설치 파일 1개 · 체크섬 검증</small></div><div>🪟 Windows 전용<small>설치 파일 1개 · 관리자 권한 불필요</small></div></div>
    <h2>설치 후 세 단계</h2><div class="steps"><div class="step"><i class="num">1</i><div><b>전용 Chrome 열기</b><span>새 창에서 본인의 CGV 계정으로 직접 로그인</span></div></div><div class="step"><i class="num">2</i><div><b>원하는 조건 설정</b><span>영화 · 극장 · 시간 · 인원 · 허용 열 · 중앙 우선</span></div></div><div class="step"><i class="num">3</i><div><b>감시 시작</b><span>지금 열린 날짜와 앞으로 열리는 날짜를 내 컴퓨터에서 확인</span></div></div></div>
    <h2>더 알아보기</h2><div class="toggle">▸ IMAX 영화관람권 구매·등록 방법</div><div class="toggle">▸ 조건 다시 설정하기</div><div class="toggle">▸ 업데이트·삭제 방법</div>
    <div class="footer">설치 안내 미리보기 · 개인정보 없는 로컬 재현<br>Mac · Windows / 내 컴퓨터 · 내 CGV 계정 · 내 IMAX 관람권</div></main></body></html>"""
    path.write_text(source, encoding="utf-8")
    out = ASSETS / "install-guide-preview.png"
    capture(path, out, 900, 1600)
    return out


def setup_preview_html() -> Path:
    path = HTML / "setup-preview.html"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "runtime")
    script = (
        "from pathlib import Path; "
        "from prickly_imax_helper.setup_server import _default_form_values, _render_page; "
        "rendered = _render_page('preview-token', '로그인은 전용 Chrome에서 직접 진행합니다.', _default_form_values()); "
        f"Path({str(path)!r}).write_text(rendered, encoding='utf-8')"
    )
    subprocess.run([str(PRODUCT_PYTHON), "-c", script], check=True, env=env)
    return path


def setup_preview() -> Path:
    path = setup_preview_html()
    out = ASSETS / "helper-setup-preview.png"
    capture(path, out, 1440, 1100)
    return out


def setup_scroll_preview() -> Path:
    path = setup_preview_html()
    out = ASSETS / "helper-setup-scroll.png"
    capture_full_page(path, out, 1440)
    return out


def redacted_monitor_preview() -> Path:
    command = Path("/Users/woojinyoung/.local/bin/prickly-imax")
    data: dict[str, object] = {}
    if command.exists():
        completed = subprocess.run(
            [str(command), "diagnose"], capture_output=True, text=True, check=True, timeout=20
        )
        payload = json.loads(redact_visual_evidence(completed.stdout))
        status = payload.get("status", {})
        if isinstance(status, dict):
            for key in ("status", "detail", "open_dates", "eligible_shows", "match", "errors", "last_scan_lane"):
                data[key] = status.get(key)
    rows = "".join(
        f"<div><span>{html_module.escape(str(key))}</span><b>{html_module.escape(json.dumps(value, ensure_ascii=False))}</b></div>"
        for key, value in data.items()
    )
    source = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1350px;overflow:hidden;background:#0a0a0a}}
    body{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#efefea;padding:110px 86px}}
    h1{{font:750 42px/1.2 -apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;margin:0 0 64px}}
    p{{color:#777;font-size:17px;margin:0 0 70px}}.rows{{border-top:1px solid #333}}
    .rows div{{display:grid;grid-template-columns:320px 1fr;padding:27px 0;border-bottom:1px solid #252525}}
    span{{color:#8b8b88;font-size:22px}}b{{font-size:27px;font-weight:650}}.armed{{color:#55d78b}}
    </style></head><body><h1>Prickly IMAX Helper · redacted diagnose</h1><p>로컬 상태에서 개인정보 필드를 제외한 실제 값</p><section class="rows">{rows}</section></body></html>"""
    path = HTML / "monitor-preview.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    out = ASSETS / "helper-monitor-preview.png"
    capture(path, out, 1080, 1350)
    return out


def cinematic_page(body: str, composition: str) -> str:
    css = """
    :root{--red:#ef382f;--paper:#f4f2ed}*{box-sizing:border-box}html,body{margin:0;width:1080px;height:1350px;overflow:hidden;background:#080808}
    body{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#f7f7f4}
    .scene{position:relative;width:1080px;height:1350px;overflow:hidden;background:#080808}.media{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
    .shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.08) 20%,rgba(0,0,0,.18) 46%,rgba(0,0,0,.92) 100%)}
    .copy{position:absolute;z-index:3;left:66px;right:66px}.copy h1{white-space:pre-line;margin:0;font-size:68px;line-height:1.13;letter-spacing:-4.4px;font-weight:850}
    .copy p{white-space:pre-line;margin:24px 0 0;font-size:27px;line-height:1.42;letter-spacing:-1px;color:#d4d4d0;font-weight:620}.meta{position:absolute;z-index:4;left:66px;bottom:38px;color:#858580;font-size:15px;letter-spacing:.03em}
    .page-no{position:absolute;z-index:4;right:48px;top:42px;font-size:17px;color:#d7d7d2}.red{color:var(--red)}
    .full .copy{bottom:105px}.top .copy{top:80px;max-width:830px}.top .shade{background:linear-gradient(180deg,rgba(0,0,0,.82),rgba(0,0,0,.10) 50%,rgba(0,0,0,.82))}
    .evidence .media{object-fit:cover;object-position:50% 44%}.evidence:after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(0,0,0,.18) 65%,rgba(0,0,0,.96))}.evidence .copy{bottom:88px}.evidence .copy h1{font-size:58px}
    .screenfill{background:#eee}.screenfill .media{object-fit:cover;object-position:50% 20%;filter:saturate(.82)}.screenfill .shade{background:linear-gradient(180deg,rgba(0,0,0,.08),rgba(0,0,0,.02) 54%,rgba(0,0,0,.94))}.screenfill .copy{bottom:82px}
    .screenfill .copy h1{font-size:61px}.monitor .media{object-position:center}.monitor .shade{background:linear-gradient(180deg,rgba(0,0,0,0),rgba(0,0,0,.15) 56%,rgba(0,0,0,.93))}.monitor .copy{bottom:80px}.monitor .copy h1{font-size:57px}
    .setup-scroll{background:#0a0a0a}.setup-scroll .copy{left:54px;right:54px;top:66px}.setup-scroll .copy h1{font-size:52px;line-height:1.12;letter-spacing:-3.2px}.setup-scroll .copy p{margin-top:12px;font-size:21px;color:#a7a7a2}.setup-scroll .scroll-window{position:absolute;left:54px;top:320px;width:972px;height:900px;overflow:hidden;background:#fff;border:1px solid #2c2c2c}.setup-scroll .scroll-window img{display:block;width:972px;height:auto}.setup-scroll .meta{left:54px;bottom:58px}
    .condition-focus{background:#090909;color:#f7f7f4}.condition-focus .copy{left:58px;right:58px;top:72px}.condition-focus .copy h1{font-size:56px;line-height:1.12;letter-spacing:-3.6px}.condition-focus .form-focus{position:absolute;left:58px;right:58px;top:320px;height:620px;overflow:hidden;background:#fff;border-top:1px solid #2c2c2c;border-bottom:1px solid #2c2c2c}.condition-focus .form-focus img{display:block;width:972px;height:auto;transform:translateY(-390px)}.condition-focus .condition-list{position:absolute;left:58px;right:58px;bottom:92px;display:grid;grid-template-columns:1fr 1fr;gap:0 42px;border-top:2px solid #353535}.condition-focus .condition-list div{padding:22px 0;border-bottom:1px solid #353535;font-size:27px;font-weight:820}.condition-focus .condition-list span{display:block;margin-bottom:7px;color:#92928d;font-size:16px;font-weight:700}.condition-focus .meta{display:none}
    .guide{background:#111}.guide .media{left:360px;width:720px;object-fit:cover;object-position:50% 10%;filter:saturate(.8)}.guide .shade{background:linear-gradient(90deg,rgba(0,0,0,.98) 0%,rgba(0,0,0,.92) 30%,rgba(0,0,0,.12) 78%)}.guide .copy{left:64px;right:430px;top:170px}.guide .copy h1{font-size:55px}.guide .copy p{font-size:23px;margin-top:40px}
    .compare{background:#020202}.compare .media{inset:105px 34px auto;width:1012px;height:570px;object-fit:contain;filter:saturate(.82) contrast(1.04)}.compare .shade{background:linear-gradient(180deg,rgba(0,0,0,.04),rgba(0,0,0,.12) 48%,#050505 73%)}.compare .copy{left:64px;right:64px;bottom:118px}.compare .copy h1{font-size:58px}.compare .copy p{font-size:25px;max-width:850px}
    .flowstage{background:linear-gradient(150deg,#151515,#070707 70%)}.flowstage .ghost{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.24;filter:blur(4px) grayscale(.72)}.flowstage .stage-index{position:absolute;z-index:2;left:66px;top:96px;color:var(--red);font:800 20px/1 ui-monospace,monospace}.flowstage .copy{z-index:2;left:66px;right:66px;top:250px;text-shadow:0 2px 22px #000}.flowstage .copy h1{font-size:65px}.flowstage .copy p{font-size:28px;max-width:760px}.flowstage .rail{position:absolute;z-index:2;left:66px;right:66px;bottom:90px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.flowstage .rail i{height:5px;background:#333}.flowstage .rail i.on{background:var(--red)}
    .outcome{background:#090909}.outcome .copy{top:185px}.outcome-list{position:absolute;left:66px;right:66px;top:560px;display:grid;gap:20px}.outcome-list div{padding:22px 0;border-top:1px solid #353535;font-size:27px;color:#aaa}.outcome-list b{display:inline-block;width:48px;color:var(--red);font:800 18px ui-monospace,monospace}
    .note{background:#090909}.note .copy{left:74px;right:74px;top:240px}.note .copy h1{font-size:60px;line-height:1.22}.note .copy p{margin-top:150px;font-size:42px;line-height:1.38;color:#f1f1ec}.note .meta{bottom:72px;font-size:21px;color:#aaa}
    """
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{css}</style></head><body><main class="scene" data-composition="{html_module.escape(composition)}">{body}</main></body></html>'


def card_three_scene_htmls(evidence_png: Path, headline: str) -> list[str]:
    source = img_uri(evidence_png)
    safe_headline = html_module.escape(headline).replace("\n", "<br>")
    stages = [
        ("top", "1석/624석 회차 발견", ""),
        ("bottom", "좌석표에는 외딴 한 자리", ""),
        ("bottom", safe_headline, "final"),
    ]
    pages: list[str] = []
    for position, label, state in stages:
        final = state == "final"
        body = (
            f'<img class="media" src="{source}" style="object-position:50% {"18%" if position == "top" else "82%"}">'
            f'<div class="shade" style="opacity:{1 if final else .35}"></div>'
            '<span class="page-no">3/8</span>'
            f'<section class="copy"><h1 style="font-size:{58 if final else 40}px">{label}</h1></section>'
        )
        pages.append(cinematic_page(body, "single-seat-evidence-stage").replace('class="scene"', 'class="scene evidence"'))
    return pages


def flow_stage_html(
    *, number: int, index: int, title: str, detail: str, ghost: Path | None = None
) -> str:
    ghost_html = f'<img class="ghost" src="{img_uri(ghost)}">' if ghost else ""
    rail = "".join(f'<i class="{"on" if step <= index else ""}"></i>' for step in range(1, 5))
    body = (
        f'{ghost_html}<span class="stage-index">0{index} / 04</span>'
        f'<span class="page-no">{number}/8</span>'
        f'<section class="copy"><h1>{html_module.escape(title)}</h1>'
        f'<p>{html_module.escape(detail)}</p></section><div class="rail">{rail}</div>'
    )
    return cinematic_page(body, f"card-{number}-stage-{index}").replace(
        'class="scene"', 'class="scene flowstage"'
    )


def card_five_scene_htmls(setup_png: Path, monitor_png: Path) -> list[str]:
    stages = [
        ("조건 설정", "영화 · 극장 · 시간 · 붙어 있는 좌석", setup_png),
        ("감시 시작", "새 날짜와 취소표를 로컬에서 확인", monitor_png),
        ("연속 좌석 후보 발견", "설정한 인원수만큼 같은 행에 붙은 자리", None),
        ("중복·관람권·잔액 검증", "조건이 하나라도 맞지 않으면 제출하지 않음", None),
    ]
    return [
        flow_stage_html(number=5, index=index, title=title, detail=detail, ghost=ghost)
        for index, (title, detail, ghost) in enumerate(stages, 1)
    ]


def card_seven_scene_htmls(_monitor_png: Path) -> list[str]:
    stages = [
        ("조건 일치", "설정한 회차와 연속 좌석 후보 확인", None),
        ("안전검증 통과", "중복 예매 없음 · 관람권 수량 일치 · 잔액 0원", None),
        ("최종 제출 1회", "결과가 불명확하면 자동으로 다시 제출하지 않음", None),
        ("결과 이메일 전송", "완료 · 결과 확인 필요 · 안전 차단 상태를 알림", None),
    ]
    pages: list[str] = []
    for index, (title, detail, ghost) in enumerate(stages, 1):
        pages.append(
            flow_stage_html(number=7, index=index, title=title, detail=detail, ghost=ghost)
        )
    return pages


def comment_cards() -> str:
    comments = [
        ("아직 IMAX로 못 봤어요", "원하는 날짜는 늘 매진"),
        ("용아맥은 그냥 포기했어요", "열어볼 때마다 남은 좌석 0"),
        ("오늘도 앱부터 확인", "취소표는 보이면 금방 사라짐"),
    ]
    return "".join(
        f'<div class="comment card"><div class="avatar"></div><div><b>{a}</b><span>{b}</span></div></div>'
        for a, b in comments
    )


def setup_mock(setup_png: Path) -> str:
    return f"""
    <div class="browser glass">
      <div class="browserbar"><i></i><i></i><i></i><span>localhost · Prickly IMAX Helper</span></div>
      <div class="browsercrop"><img src="{img_uri(setup_png)}"></div>
    </div>"""


def status_card() -> str:
    return """
    <div class="status glass">
      <div class="status-head"><span class="status-dot"></span><b>armed</b><em>LOCAL MONITOR</em></div>
      <div class="status-grid">
        <div><span>open dates</span><strong>12</strong></div>
        <div><span>eligible shows</span><strong>37</strong></div>
        <div><span>match</span><strong>null</strong></div>
        <div><span>errors</span><strong>0</strong></div>
      </div>
      <p>match:null = 조건에 맞는 좌석을 기다리는 중</p>
    </div>"""


def seat_diagram() -> str:
    rows = []
    for r in "DEFGHIJ":
        seats = "".join(f'<i class="seat {"target" if r=="G" and n in (6,7) else ""}"></i>' for n in range(1,13))
        rows.append(f'<div class="seatrow"><b>{r}</b>{seats}</div>')
    return '<div class="screen">SCREEN</div><div class="seats">' + "".join(rows) + '</div>'


def video_carousel_covers(
    setup_png: Path,
    monitor_png: Path,
    guide_png: Path,
    cards: list[dict[str, object]],
    setup_scroll_png: Path | None = None,
) -> list[str]:
    safe = lambda value: html_module.escape(str(value)).replace("\n", "<br>")
    sources = [img_uri(ROOT / str(card["source"])) if str(card["source"]) else "" for card in cards]
    scroll_source = setup_scroll_png or setup_png
    sources[3], sources[4], sources[5], sources[6] = map(
        img_uri, (scroll_source, monitor_png, scroll_source, monitor_png)
    )
    result: list[str] = []
    media = lambda src: f'<img class="media" src="{src}">'
    number = lambda n: f'<span class="page-no">{n}/8</span>'
    result.append(cinematic_page(f'{media(sources[0])}<div class="shade"></div>{number(1)}<section class="copy"><h1>{safe(cards[0]["headline"])}</h1><p>{safe(cards[0]["supporting"])}</p></section><small class="meta">{safe(cards[0]["footer"])}</small>', str(cards[0]["composition"])).replace('class="scene"','class="scene full"'))
    result.append(cinematic_page(f'{media(sources[1])}<div class="shade"></div>{number(2)}<section class="copy"><h1>{safe(cards[1]["headline"])}</h1><p>{safe(cards[1]["supporting"])}</p></section><small class="meta">{safe(cards[1]["footer"])}</small>', str(cards[1]["composition"])).replace('class="scene"','class="scene compare"'))
    result.append(cinematic_page(f'{media(sources[2])}{number(3)}<section class="copy"><h1>{safe(cards[2]["headline"])}</h1><p>{safe(cards[2]["supporting"])}</p></section><small class="meta">{safe(cards[2]["footer"])}</small>', str(cards[2]["composition"])).replace('class="scene"','class="scene evidence"'))
    result.append(cinematic_page(
        f'{number(4)}<section class="copy"><h1>{safe(cards[3]["headline"])}</h1>'
        f'<p>{safe(cards[3]["supporting"])}</p></section>'
        f'<div class="scroll-window"><img src="{sources[3]}"></div>'
        f'<small class="meta">{safe(cards[3]["footer"])}</small>',
        str(cards[3]["composition"]),
    ).replace('class="scene"','class="scene setup-scroll"'))
    result.append(cinematic_page(f'{media(sources[4])}<div class="shade"></div>{number(5)}<section class="copy"><h1>{safe(cards[4]["headline"])}</h1><p>{safe(cards[4]["supporting"])}</p></section><small class="meta">{safe(cards[4]["footer"])}</small>', str(cards[4]["composition"])).replace('class="scene"','class="scene monitor"'))
    condition_rows = "".join(
        f'<div><span>{label}</span>{value}</div>'
        for label, value in (
            ("같은 행 좌석", "연속 2석"),
            ("허용 열", "D–J열"),
            ("좌석 위치", "양끝 20% 제외"),
            ("당일 회차", "3시간 이상"),
        )
    )
    result.append(cinematic_page(
        f'{number(6)}<section class="copy"><h1>{safe(cards[5]["headline"])}</h1></section>'
        f'<div class="form-focus"><img src="{sources[5]}"></div>'
        f'<div class="condition-list">{condition_rows}</div>'
        f'<small class="meta">{safe(cards[5]["footer"])}</small>',
        str(cards[5]["composition"]),
    ).replace('class="scene"','class="scene condition-focus"'))
    outcome_rows = "".join(
        f'<div><b>0{idx}</b>{label}</div>'
        for idx, label in enumerate(("조건 일치", "안전검증", "최종 제출 1회", "결과 이메일"), 1)
    )
    result.append(cinematic_page(f'{number(7)}<section class="copy"><h1>{safe(cards[6]["headline"])}</h1><p>{safe(cards[6]["supporting"])}</p></section><div class="outcome-list">{outcome_rows}</div><small class="meta">{safe(cards[6]["footer"])}</small>', str(cards[6]["composition"])).replace('class="scene"','class="scene outcome"'))
    result.append(cinematic_page(f'{number(8)}<section class="copy"><h1>{safe(cards[7]["headline"])}</h1><p>{safe(cards[7]["supporting"])}</p></section><small class="meta">{safe(cards[7]["footer"])}</small>', str(cards[7]["composition"])).replace('class="scene"','class="scene note"'))
    return result


def render_video_carousel_covers(cards: list[dict[str, object]]) -> list[Path]:
    for directory in (ASSETS, BUILD, HTML, SCENE_FRAMES, VIDEO_CAROUSEL, VIDEO_COVERS, VIDEO_CARDS):
        directory.mkdir(parents=True, exist_ok=True)
    setup_png = ASSETS / "helper-setup-preview.png"
    if not setup_png.is_file():
        setup_png = setup_preview()
    setup_scroll_png = setup_scroll_preview()
    monitor_png = redacted_monitor_preview()
    guide_png = install_guide_preview()
    paths: list[Path] = []
    for idx, source in enumerate(
        video_carousel_covers(setup_png, monitor_png, guide_png, cards, setup_scroll_png), 1
    ):
        html = HTML / f"video-carousel-{idx:02d}.html"
        png = VIDEO_COVERS / f"{idx:02d}.png"
        html.write_text(source, encoding="utf-8")
        capture(html, png, 1080, 1350)
        paths.append(png)
    for idx, source in enumerate(card_five_scene_htmls(setup_png, monitor_png), 1):
        html = HTML / f"video-carousel-05-stage-{idx}.html"
        png = SCENE_FRAMES / f"card05-{idx}.png"
        html.write_text(source, encoding="utf-8")
        capture(html, png, 1080, 1350)
    for idx, source in enumerate(card_seven_scene_htmls(monitor_png), 1):
        html = HTML / f"video-carousel-07-stage-{idx}.html"
        png = SCENE_FRAMES / f"card07-{idx}.png"
        html.write_text(source, encoding="utf-8")
        capture(html, png, 1080, 1350)
    contact_sheet(paths, VIDEO_CAROUSEL / "contact-sheet.png", 4, (216, 270))
    return paths


def render_card_four_scroll_video(
    cover: Path,
    setup_scroll_png: Path,
    output: Path,
    *,
    duration: int,
    fps: int = 30,
) -> None:
    frame_count = duration * fps
    viewport_x, viewport_y = 54, 320
    viewport_width, viewport_height = 972, 900
    with Image.open(cover) as cover_image, Image.open(setup_scroll_png) as source_image:
        base = cover_image.convert("RGB")
        source = source_image.convert("RGB")
        scaled_height = max(round(source.height * viewport_width / source.width), viewport_height)
        source = source.resize((viewport_width, scaled_height), Image.Resampling.LANCZOS)
        offsets = card_four_scroll_offsets(
            source_height=source.height,
            viewport_height=viewport_height,
            frame_count=frame_count,
        )
        with tempfile.TemporaryDirectory(prefix="prickly-card-four-scroll-") as tmp:
            frame_dir = Path(tmp)
            for index, offset in enumerate(offsets):
                frame = base.copy()
                crop = source.crop((0, offset, viewport_width, offset + viewport_height))
                frame.paste(crop, (viewport_x, viewport_y))
                frame.save(frame_dir / f"frame-{index:04d}.jpg", quality=94, subsampling=0)
            run(
                FFMPEG,
                "-loglevel", "error", "-y",
                "-framerate", str(fps),
                "-i", str(frame_dir / "frame-%04d.jpg"),
                "-t", str(duration),
                "-vf", "scale=iw:ih:in_range=full:out_range=tv,format=yuv420p",
                "-an", "-c:v", "libx264",
                "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-color_range", "tv", "-movflags", "+faststart",
                str(output),
            )


def render_video_carousel_cards(
    cards: list[dict[str, object]],
    covers: list[Path],
) -> list[Path]:
    if len(cards) != len(covers):
        raise ValueError("every publishable card requires one cover")
    VIDEO_CARDS.mkdir(parents=True, exist_ok=True)
    for stale in VIDEO_CARDS.iterdir():
        if stale.is_file() and stale.suffix.lower() in {".png", ".mp4"}:
            stale.unlink()
    outputs: list[Path] = []
    for card, cover in zip(cards, covers):
        number = int(card["number"])
        if card["media_type"] == "png":
            output = VIDEO_CARDS / f"{number:02d}.png"
            shutil.copy2(cover, output)
            outputs.append(output)
            continue
        duration = int(card["duration"])
        output = VIDEO_CARDS / f"{number:02d}.mp4"
        if number == 4:
            setup_scroll_png = ASSETS / "helper-setup-scroll.png"
            if not setup_scroll_png.is_file():
                raise FileNotFoundError("card 4 setup scroll source is missing")
            render_card_four_scroll_video(
                cover,
                setup_scroll_png,
                output,
                duration=duration,
            )
            outputs.append(output)
            continue
        frames = [SCENE_FRAMES / f"card{number:02d}-{idx}.png" for idx in range(1, 5)]
        if not all(frame.is_file() for frame in frames):
            raise FileNotFoundError(f"card {number} scene frames are missing")
        run(
            FFMPEG, "-loglevel", "error", "-y",
            "-loop", "1", "-t", "2.18", "-i", str(frames[0]),
            "-loop", "1", "-t", "2.18", "-i", str(frames[1]),
            "-loop", "1", "-t", "2.18", "-i", str(frames[2]),
            "-loop", "1", "-t", "2.18", "-i", str(frames[3]),
            "-filter_complex",
            "[0:v][1:v]xfade=transition=fade:duration=0.18:offset=2.0[x1];"
            "[x1][2:v]xfade=transition=fade:duration=0.18:offset=4.0[x2];"
            "[x2][3:v]xfade=transition=fade:duration=0.18:offset=6.0,"
            "fps=30,format=yuv420p[v]",
            "-map", "[v]", "-t", str(duration), "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-movflags", "+faststart", str(output),
        )
        outputs.append(output)
    return outputs


def verify_video_carousel(
    cards: list[dict[str, object]], covers: list[Path], media: list[Path]
) -> dict[str, object]:
    if len(cards) != 8 or len(covers) != 8 or len(media) != 8:
        raise ValueError("eight cards, eight covers, and eight publishable media files are required")
    for expected, (card, cover, published) in enumerate(zip(cards, covers, media), 1):
        suffix = ".mp4" if card["media_type"] == "mp4" else ".png"
        if cover.name != f"{expected:02d}.png" or published.name != f"{expected:02d}{suffix}":
            raise ValueError(f"card {expected} filenames are out of order")
        with Image.open(cover) as image:
            if image.size != (1080, 1350):
                raise ValueError(f"card {expected} cover has wrong dimensions")
        if card["media_type"] == "png":
            with Image.open(published) as image:
                if image.size != (1080, 1350):
                    raise ValueError(f"card {expected} PNG has wrong dimensions")
            continue
        probe = json.loads(
            subprocess.check_output(
                [
                    FFPROBE, "-v", "error", "-show_entries",
                    "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt:format=duration",
                    "-of", "json", str(published),
                ],
                text=True,
            )
        )
        video_streams = [s for s in probe["streams"] if s.get("codec_type") == "video"]
        audio_streams = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
        if len(video_streams) != 1 or audio_streams:
            raise ValueError(f"card {expected} must contain one muted video stream")
        stream = video_streams[0]
        expected_fields = {
            "codec_name": "h264", "width": 1080, "height": 1350,
            "r_frame_rate": "30/1", "pix_fmt": "yuv420p",
        }
        if any(stream.get(key) != value for key, value in expected_fields.items()):
            raise ValueError(f"card {expected} media contract mismatch")
        if abs(float(probe["format"]["duration"]) - float(card["duration"])) > 0.1:
            raise ValueError(f"card {expected} duration mismatch")
    return {
        "covers": 8,
        "png_cards": sum(card["media_type"] == "png" for card in cards),
        "video_cards": sum(card["media_type"] == "mp4" for card in cards),
        "verified": True,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_video_carousel(
    cards: list[dict[str, object]],
    covers: list[Path],
    media: list[Path],
) -> Path:
    if len(cards) != 8 or len(covers) != 8 or len(media) != 8:
        raise ValueError("publishable package requires eight ordered media files and eight review covers")
    contact = VIDEO_CAROUSEL / "contact-sheet.png"
    checksummed = [*covers, *media, contact]
    sums = "".join(f"{sha256(path)}  {path.relative_to(VIDEO_CAROUSEL)}\n" for path in checksummed)
    (VIDEO_CAROUSEL / "SHA256SUMS").write_text(sums, encoding="utf-8")
    readme = """# Prickly IMAX Helper 혼합 캐러셀

- 업로드 순서: `01.png` · `02.png` · `03.png` · `04.mp4` · `05.mp4` · `06.png` · `07.mp4` · `08.png`
- PNG 5개와 MP4 3개는 모두 1080×1350입니다.
- Card 4는 실제 설정 화면을 아래로 스크롤하는 7초 영상입니다.
- Card 5와 Card 7은 H.264, yuv420p, 30fps, 무음, 각 8초입니다.
- 댓글 키워드: `아이맥스`
- 음악은 인스타그램 게시 단계에서 별도로 추가하세요.
- Card 7은 Prickly 결과 흐름이며 CGV 모바일티켓·예매번호·완료 거래 화면을 만들지 않습니다.

체크섬 확인: `shasum -a 256 -c SHA256SUMS`
"""
    (VIDEO_CAROUSEL / "README.md").write_text(readme, encoding="utf-8")
    qa = """# 혼합 캐러셀 최종 QA

- 게시용 PNG: 5개
- 게시용 MP4: 3개 (Card 4, Card 5, Card 7)
- 검수용 PNG 표지: 8개
- 해상도: 전부 1080×1350
- 비디오: H.264 · yuv420p · 30fps · 무음 · Card 4는 7초, Card 5·7은 8초
- 오디세이 스틸: 사용자 사용 허용 게시물의 UI 없는 원본 2장
- Card 2: 사용자 제공 The Direct 비교 자료 · 워터마크 유지 · IMAX 70mm와 용산 IMAX LASER 2D 형식 차이 표기
- Card 3: 사용자 제공 실제 CGV 한 자리 화면, `연속 2석 없음` 범위로만 표현
- 제품 설정 화면: 실제 로컬 Helper UI를 오프라인 렌더링
- Card 4: 실제 설정 화면을 한눈에 이해하도록 위에서 아래로 연속 스크롤
- 감시 화면: 개인정보를 제외한 실제 로컬 diagnose 값
- Card 5: 조건 설정부터 안전검증까지의 작동 과정
- Card 6: 실제 설정 화면 중 좌석 조건을 크게 보여주는 필드 중심 구도
- Card 7: 조건 일치부터 결과 이메일까지의 제품 흐름
- 반복 템플릿·가짜 브라우저·가짜 터미널·휴대폰 목업: 없음
- 벤치마킹 계정 화면 녹화: 최종 결과물에서 제외
- CGV 접속·회차·좌석·관람권·결제 조작: 없음
- 가짜 모바일티켓·예매번호·QR·바코드·완료 거래 화면: 없음
- 좌석 보장·CGV 제휴 주장: 없음
- 카드 결제 자동화 주장: 없음
- 금지 문구: 미사용
"""
    (VIDEO_CAROUSEL / "qa-report.md").write_text(qa, encoding="utf-8")
    archive_base = HERE / "prickly-imax-helper-video-carousel"
    archive = archive_base.with_suffix(".zip")
    if archive.exists():
        archive.unlink()
    with tempfile.TemporaryDirectory(prefix="prickly-video-carousel-") as tmp:
        package = Path(tmp) / "prickly-imax-helper-video-carousel"
        shutil.copytree(VIDEO_CARDS, package / "cards")
        shutil.copy2(contact, package / "contact-sheet.png")
        shutil.copy2(VIDEO_CAROUSEL / "README.md", package / "README.md")
        shutil.copy2(VIDEO_CAROUSEL / "qa-report.md", package / "qa-report.md")
        shutil.copy2(VIDEO_CAROUSEL / "SHA256SUMS", package / "SHA256SUMS")
        shutil.copy2(HERE / "sources-and-claim-notes.md", package / "sources-and-claim-notes.md")
        shutil.copy2(MANIFEST, package / "carousel_manifest.json")
        shutil.make_archive(str(archive_base), "zip", package)
    return archive


def carousel_slides(setup_png: Path) -> list[str]:
    bg = img_uri(ASSETS / "cinema-background.png")
    common = """
    .comment-stack{display:grid;gap:22px;margin-top:52px}.comment{display:flex;gap:20px;align-items:center;padding:25px 28px}.comment:nth-child(2){transform:translateX(46px)}
    .avatar{width:56px;height:56px;border-radius:50%;background:linear-gradient(145deg,#353a43,#16181d);border:1px solid #4a4f58}.comment b{display:block;font-size:27px}.comment span{display:block;margin-top:7px;color:#999ea6;font-size:20px}
    .browser{overflow:hidden}.browserbar{height:58px;display:flex;align-items:center;gap:10px;padding:0 20px;background:#202329;border-bottom:1px solid #333740}.browserbar i{width:12px;height:12px;border-radius:50%;background:#5a5f68}.browserbar i:first-child{background:#ef5f57}.browserbar span{margin-left:12px;color:#9da2aa;font:600 14px ui-monospace,monospace}.browsercrop{height:620px;overflow:hidden;background:white}.browsercrop img{width:100%;display:block}
    .safety{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:52px}.safety .card{padding:30px}.safety b{display:block;margin-top:18px;font-size:27px}.safety p{font-size:19px;line-height:1.45;color:#aeb2b8}
    .screen{width:560px;height:26px;margin:38px auto 48px;border-radius:50%;background:linear-gradient(90deg,transparent,#f1f2f2,transparent);box-shadow:0 15px 35px rgba(255,255,255,.20);color:#777;text-align:center;font:600 13px/1 ui-monospace,monospace;letter-spacing:.25em}.seats{display:grid;gap:13px}.seatrow{display:flex;align-items:center;gap:10px}.seatrow b{width:26px;color:#7e838b}.seat{width:48px;height:39px;border-radius:9px 9px 5px 5px;background:#2a2e35;border:1px solid #424750}.seat.target{background:#ef382f;border-color:#ff756d;box-shadow:0 0 22px rgba(239,56,47,.45)}
    """
    slides: list[str] = []
    slides.append(page(f"""
      <div class="bg-photo" style="background-image:url('{bg}');background-position:50% 53%"></div><div class="scrim"></div>{header(1,9)}
      <div class="content" style="top:244px"><div class="eyebrow">ODYSSEY · YONGSAN IMAX</div>
      <h1>용아맥 한 자리 보는데<br><span class="red">30만 원?</span></h1>
      <p class="sub">정가를 훌쩍 넘긴 리셀 게시물까지 나왔다.</p>
      <p class="small" style="margin-top:330px">* 일부 리셀 게시물 사례이며 일반적인 거래 가격을 뜻하지 않습니다.</p></div>{footer('THE PROBLEM')}</div>""", width=1080,height=1350,extra_css=common))
    slides.append(page(f"""{header(2,9)}<div class="content"><div class="eyebrow">SOLD OUT</div>
      <h2>보고 싶은 사람은 많은데<br>원하는 날짜는 이미<br><span class="red">전석 매진.</span></h2>
      <div class="comment-stack">{comment_cards()}</div></div>{footer('AUDIENCE SIGNAL')}</div>""",width=1080,height=1350,extra_css=common))
    slides.append(page(f"""{header(3,9)}<div class="content"><div class="eyebrow">THE LOOP</div>
      <h2>하루 종일 새로고침하거나,<br>포기하거나,<br><span class="red">비싼 리셀표를 보거나.</span></h2>
      <div class="loop" style="margin-top:70px;display:grid;grid-template-columns:repeat(3,1fr);gap:18px">
        <div class="card" style="padding:34px"><b style="font-size:26px">01</b><p class="sub" style="font-size:27px">새로고침</p><span class="small">CGV 앱을<br>계속 확인</span></div>
        <div class="card" style="padding:34px"><b style="font-size:26px">02</b><p class="sub" style="font-size:27px">포기</p><span class="small">용아맥은<br>다음 기회로</span></div>
        <div class="card" style="padding:34px;border-color:#67302e"><b class="red" style="font-size:26px">03</b><p class="sub" style="font-size:27px">리셀표</p><span class="small">정가보다<br>훨씬 비싸게</span></div>
      </div><p class="sub" style="margin-top:58px">취소표는 잠깐 나타났다 사라진다.<br>사람이 계속 보고 있기엔 너무 빠르다.</p></div>{footer('REFRESH FATIGUE')}</div>""",width=1080,height=1350,extra_css=common))
    slides.append(page(f"""{header(4,9)}<div class="content"><div class="eyebrow">THE ALTERNATIVE</div>
      <h2>그래서 사람 대신<br><span class="red">내 컴퓨터가</span><br>취소표를 기다리게 했다.</h2>
      <div style="margin-top:52px">{setup_mock(setup_png)}</div>
      <p class="sub" style="font-size:25px;margin-top:30px">하루 종일 새로고침하지 않아도,<br>내 조건에 맞는 취소표를 내 컴퓨터가 기다린다.</p></div>{footer('LOCAL FIRST')}</div>""",width=1080,height=1350,extra_css=common))
    slides.append(page(f"""{header(5,9)}<div class="content"><div class="eyebrow">SETUP</div>
      <h2>로그인도, 조건도<br><span class="red">내가 직접 정한다.</span></h2>
      <div style="margin-top:42px">{setup_mock(setup_png)}</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:26px"><span class="pill">영화</span><span class="pill">극장</span><span class="pill">시간</span><span class="pill">인원</span><span class="pill">허용 열</span><span class="pill">중앙 우선</span></div>
      <p class="small" style="margin-top:22px">전용 Chrome에서 본인 CGV 계정으로 직접 로그인합니다.</p></div>{footer('YOUR ACCOUNT · YOUR RULES')}</div>""",width=1080,height=1350,extra_css=common))
    slides.append(page(f"""{header(6,9)}<div class="content"><div class="eyebrow">MONITORING</div>
      <h2>오늘 좌석만<br>보는 게 아니다.</h2>
      <p class="sub">지금 열린 날짜와 새로 열리는 날짜까지.<br>설정한 수만큼 같은 행에 붙은 좌석만 찾는다.</p>
      <div class="card" style="margin-top:42px;padding:38px 42px">{seat_diagram()}</div>
      <p class="small" style="margin-top:24px">예: 2명이면 같은 행 연속 2석</p></div>{footer('ALL OPEN DATES')}</div>""",width=1080,height=1350,extra_css=common))
    safety = [
        ("중복 예매 차단", "이미 잡아둔 표가 있으면 멈춥니다."),
        ("관람권 수 확인", "인원수와 같은 수의 IMAX 관람권을 확인합니다."),
        ("남은 금액 0원", "추가 결제금액이 남으면 제출하지 않습니다."),
        ("최종 제출 1회", "결과가 불명확하면 자동으로 다시 누르지 않습니다."),
    ]
    safety_html = "".join(f'<div class="card"><span class="check">✓</span><b>{a}</b><p>{b}</p></div>' for a,b in safety)
    slides.append(page(f"""{header(7,9)}<div class="content"><div class="eyebrow">SAFETY BEFORE SPEED</div>
      <h2>빠르기 전에<br><span class="red">틀리지 않는 게 먼저다.</span></h2>
      <div class="safety">{safety_html}</div><p class="small" style="margin-top:28px">조건이 모두 맞을 때만 한 번 제출 · 카드 결제는 자동화하지 않음</p></div>{footer('VERIFY · THEN SUBMIT')}</div>""",width=1080,height=1350,extra_css=common))
    slides.append(page(f"""
      <div class="bg-photo" style="background-image:url('{bg}');background-position:50% 68%;filter:grayscale(.35)"></div><div class="scrim" style="background:linear-gradient(180deg,rgba(6,7,9,.52),rgba(6,7,9,.95))"></div>{header(8,9)}
      <div class="content" style="top:285px"><div class="eyebrow">THE CHOICE</div>
      <h1 style="font-size:70px">암표를 사는 대신,<br><span class="red">정가 취소표를</span><br>기다릴 수 있는 선택지.</h1>
      <div class="rule" style="margin-top:70px"></div><p class="sub">표가 생긴다고 약속할 수는 없다.<br>대신 사람이 화면에 붙어 있어야 했던 시간을 줄인다.</p></div>{footer('NO GUARANTEE · LESS REFRESH')}</div>""",width=1080,height=1350,extra_css=common))
    slides.append(page(f"""{header(9,9)}<div class="content" style="top:300px">
      <div class="eyebrow">TRY IT YOURSELF</div>
      <h1 style="font-size:68px;max-width:860px">댓글에 <span class="red">“아이맥스”</span>라고 남기면<br>설치 방법을 보내줄게.</h1>
      <p class="sub" style="margin-top:70px">Mac · Windows<br>내 컴퓨터 · 내 CGV 계정 · 내 IMAX 관람권</p>
      <div class="rule" style="margin-top:230px"></div><div style="margin-top:34px;font-size:42px;font-weight:850">prickly.ai</div>
      <p class="small" style="margin-top:20px">공개 설치 안내가 준비된 뒤 순서대로 전달합니다.</p></div>{footer('COMMENT → DM')}</div>""",width=1080,height=1350,extra_css=common))
    return slides


def reel_frames(setup_png: Path) -> list[tuple[str, int]]:
    bg = img_uri(ASSETS / "cinema-background.png")
    extra = """
    .content{left:76px;right:76px;top:240px;bottom:150px}.brand{top:80px;font-size:28px}.pager{top:88px}
    h1{font-size:92px;line-height:1.08}.sub{font-size:35px}.comment-stack{display:grid;gap:24px;margin-top:58px}.comment{display:flex;gap:20px;align-items:center;padding:28px}.comment b{display:block;font-size:29px}.comment span{display:block;margin-top:8px;color:#999;font-size:22px}.avatar{width:58px;height:58px;border-radius:50%;background:#30343b}
    .browser{overflow:hidden;margin-top:54px}.browserbar{height:58px;background:#22262b;border-bottom:1px solid #373b42;padding:0 20px;display:flex;align-items:center;gap:9px}.browserbar i{width:12px;height:12px;border-radius:50%;background:#5a5f68}.browserbar i:first-child{background:#ef5f57}.browserbar span{margin-left:12px;color:#9da2aa;font:600 14px ui-monospace,monospace}.browsercrop{height:720px;overflow:hidden;background:white}.browsercrop img{width:100%;display:block}
    .status{margin-top:72px;padding:40px}.status-head{display:flex;align-items:center;gap:18px}.status-head b{font:800 36px ui-monospace,monospace;color:#66db98}.status-head em{margin-left:auto;color:#777;font:600 16px ui-monospace,monospace}.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:35px}.status-grid div{padding:26px;background:#111319;border:1px solid #2a2d34;border-radius:18px}.status-grid span{display:block;color:#8f949d;font:600 17px ui-monospace,monospace}.status-grid strong{display:block;margin-top:10px;font:800 42px ui-monospace,monospace}.status p{font-size:24px;color:#aaa;margin:30px 0 0}
    .safety{display:grid;gap:18px;margin-top:70px}.safety .card{display:flex;align-items:center;gap:20px;padding:28px}.safety b{font-size:29px}
    """
    frames: list[tuple[str,int]] = []
    frames.append((page(f"""<div class="bg-photo" style="background-image:url('{bg}');background-position:50% 55%"></div><div class="scrim"></div>{header(1,7)}<div class="content" style="top:370px"><div class="eyebrow">일부 리셀 게시물 사례</div><h1>용아맥 한 자리 보는데<br><span class="red">30만 원?</span></h1><p class="small" style="margin-top:520px">일반적인 거래 가격을 뜻하지 않습니다.</p></div></div>""",width=1080,height=1920,extra_css=extra),3))
    frames.append((page(f"""{header(2,7)}<div class="content"><div class="eyebrow">전석 매진</div><h1 style="font-size:78px">앱을 열 때마다 매진.<br>취소표는 보여도<br><span class="red">금방 사라진다.</span></h1><div class="comment-stack">{comment_cards()}</div></div></div>""",width=1080,height=1920,extra_css=extra),4))
    frames.append((page(f"""{header(3,7)}<div class="content" style="top:360px"><div class="eyebrow">PRICKLY IMAX HELPER</div><h1>사람 대신<br><span class="red">내 컴퓨터가</span><br>기다리게 했다.</h1><div style="margin-top:100px">{status_card()}</div></div></div>""",width=1080,height=1920,extra_css=extra),4))
    frames.append((page(f"""{header(4,7)}<div class="content"><div class="eyebrow">3 STEPS</div><h1 style="font-size:72px">설치 → 직접 로그인 →<br><span class="red">원하는 조건 설정</span></h1>{setup_mock(setup_png)}<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:30px"><span class="pill">영화</span><span class="pill">시간</span><span class="pill">인원</span><span class="pill">허용 열</span></div><p class="small" style="margin-top:22px">비밀번호와 결제정보를 Helper에 입력하지 않습니다.</p></div></div>""",width=1080,height=1920,extra_css=extra),7))
    frames.append((page(f"""{header(5,7)}<div class="content" style="top:320px"><div class="eyebrow">LOCAL MONITOR</div><h1 style="font-size:75px">지금 열린 날짜부터<br><span class="red">새로 열릴 날짜까지.</span></h1>{status_card()}<p class="sub">match:null은 실패가 아니라<br>조건에 맞는 좌석을 기다리는 중.</p></div></div>""",width=1080,height=1920,extra_css=extra),5))
    safety = "".join(f'<div class="card"><span class="check">✓</span><b>{x}</b></div>' for x in ["중복 예매 차단","관람권 수 확인","남은 금액 0원","최종 제출 1회"])
    frames.append((page(f"""{header(6,7)}<div class="content" style="top:300px"><div class="eyebrow">SAFETY</div><h1 style="font-size:76px">빠르기 전에<br><span class="red">틀리지 않는 게 먼저.</span></h1><div class="safety">{safety}</div><p class="sub">조건이 맞지 않으면 누르지 않는다.<br>카드 결제는 자동화하지 않는다.</p></div></div>""",width=1080,height=1920,extra_css=extra),4))
    frames.append((page(f"""<div class="bg-photo" style="background-image:url('{bg}');background-position:50% 58%"></div><div class="scrim"></div>{header(7,7)}<div class="content" style="top:470px"><div class="eyebrow">COMMENT → DM</div><h1 style="font-size:80px">써보고 싶다면<br>댓글에 <span class="red">“아이맥스”</span></h1><p class="sub" style="margin-top:70px">설치 방법을 보내줄게.</p><div class="rule" style="margin-top:360px"></div><div style="margin-top:38px;font-size:46px;font-weight:850">prickly.ai</div></div></div>""",width=1080,height=1920,extra_css=extra),3))
    return frames


def contact_sheet(paths: list[Path], output: Path, cols: int, thumb: tuple[int,int]) -> None:
    tw, th = thumb
    gap = 24
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (gap + cols*(tw+gap), gap + rows*(th+gap)), "#08090b")
    for idx, path in enumerate(paths):
        im = Image.open(path).convert("RGB")
        im = ImageOps.fit(im, (tw, th), method=Image.Resampling.LANCZOS)
        x = gap + (idx % cols)*(tw+gap)
        y = gap + (idx // cols)*(th+gap)
        sheet.paste(im, (x,y))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((x+10,y+10,x+58,y+42), fill="#ef382f")
        draw.text((x+24,y+17), str(idx+1), fill="white")
    output.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(output, quality=92)


def build_video(frame_paths: list[Path], durations: list[int]) -> Path:
    clips = BUILD / "reel-clips"
    clips.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []
    for idx, (frame, duration) in enumerate(zip(frame_paths,durations),1):
        clip = clips / f"{idx:02d}.mp4"
        frames = duration * 30
        run(
            FFMPEG, "-loglevel", "error", "-y", "-loop", "1", "-i", str(frame), "-t", str(duration),
            "-vf", f"zoompan=z='min(zoom+0.00022,1.025)':d={frames}:s=1080x1920:fps=30,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-movflags", "+faststart", str(clip),
        )
        clip_paths.append(clip)
    concat = BUILD / "reel-concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clip_paths), encoding="utf-8")
    out = REEL / "prickly-imax-helper-reel-visual-master.mp4"
    run(FFMPEG,"-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",str(out))
    return out


def verify(carousel: list[Path], frames: list[Path], video: Path) -> dict[str, object]:
    assert len(carousel) == 9
    assert len(frames) == 7
    for path in carousel:
        assert Image.open(path).size == (1080,1350), path
    for path in frames:
        assert Image.open(path).size == (1080,1920), path
    probe = subprocess.check_output([
        FFPROBE,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(video)
    ],text=True).strip()
    duration = float(probe)
    assert 29.8 <= duration <= 30.2, duration
    return {"carousel_count":9,"carousel_size":"1080x1350","reel_frame_count":7,"reel_size":"1080x1920","reel_duration_seconds":duration}


def build_legacy_assets() -> None:
    for directory in (ASSETS,BUILD,HTML,CAROUSEL,REEL,FRAMES):
        directory.mkdir(parents=True,exist_ok=True)
    setup_png = setup_preview()

    slide_paths: list[Path] = []
    for idx, source in enumerate(carousel_slides(setup_png),1):
        html = HTML / f"carousel-{idx:02d}.html"
        png = CAROUSEL / f"{idx:02d}.png"
        html.write_text(source,encoding="utf-8")
        capture(html,png,1080,1350)
        slide_paths.append(png)

    frame_paths: list[Path] = []
    durations: list[int] = []
    for idx, (source,duration) in enumerate(reel_frames(setup_png),1):
        html = HTML / f"reel-{idx:02d}.html"
        png = FRAMES / f"{idx:02d}.png"
        html.write_text(source,encoding="utf-8")
        capture(html,png,1080,1920)
        frame_paths.append(png)
        durations.append(duration)

    contact_sheet(slide_paths,CAROUSEL / "contact-sheet.png",3,(270,338))
    contact_sheet(frame_paths,REEL / "contact-sheet.png",4,(216,384))
    video = build_video(frame_paths,durations)
    report = verify(slide_paths,frame_paths,video)
    (HERE / "qa-metrics.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    archive_base = HERE / "prickly-imax-helper-social-assets"
    if archive_base.with_suffix(".zip").exists():
        archive_base.with_suffix(".zip").unlink()
    with tempfile.TemporaryDirectory(prefix="prickly-package-") as tmp:
        package = Path(tmp) / "prickly-imax-helper-social-assets"
        shutil.copytree(CAROUSEL,package / "carousel")
        shutil.copytree(REEL,package / "reel")
        shutil.copy2(HERE / "qa-metrics.json",package / "qa-metrics.json")
        for note in ("README.md", "sources-and-claim-notes.md", "qa-report.md"):
            shutil.copy2(HERE / note, package / note)
        shutil.make_archive(str(archive_base),"zip",Path(tmp),package.name)
    print(json.dumps(report,ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--video-carousel",
        action="store_true",
        help="build the approved eight-card Instagram video carousel",
    )
    args = parser.parse_args()
    if args.video_carousel:
        cards = load_carousel_manifest()
        covers = render_video_carousel_covers(cards)
        videos = render_video_carousel_cards(cards, covers)
        verify_video_carousel(cards, covers, videos)
        archive = package_video_carousel(cards, covers, videos)
        print(
            json.dumps(
                {
                    "video_carousel_covers": len(covers),
                    "video_carousel_cards": len(videos),
                    "archive": str(archive),
                },
                ensure_ascii=False,
            )
        )
        return
    build_legacy_assets()


if __name__ == "__main__":
    main()
