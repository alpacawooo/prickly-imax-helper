#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html as html_module
import json
import os
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
ALLOWED_MOTIONS = {"ken-burns", "red-drift", "proof-pan"}
BANNED_COPY = "Prickly AI는 사람이 반복하던 일을 실제로 작동하는 자동화로 바꾼다."


def validate_manifest(cards: list[dict[str, object]]) -> None:
    if [card.get("number") for card in cards] != list(range(1, 9)):
        raise ValueError("video carousel must contain cards 1 through 8 in order")
    if [card.get("duration") for card in cards] != [6, 6, 7, 9, 8, 7, 9, 6]:
        raise ValueError("video carousel durations do not match the approved design")
    for card in cards:
        if not str(card.get("headline", "")).strip():
            raise ValueError(f"card {card.get('number')} has no headline")
        if card.get("motion") not in ALLOWED_MOTIONS:
            raise ValueError(f"card {card.get('number')} has unsupported motion")
        source = str(card.get("source", ""))
        if source and not (ROOT / source).is_file():
            raise FileNotFoundError(ROOT / source)
    raw = json.dumps(cards, ensure_ascii=False)
    if "ScreenRecording_08-14-2026" in raw or "ai_freaks" in raw.lower() or BANNED_COPY in raw:
        raise ValueError("manifest contains benchmark material or banned copy")


def load_carousel_manifest() -> list[dict[str, object]]:
    cards = json.loads(MANIFEST.read_text(encoding="utf-8"))["cards"]
    validate_manifest(cards)
    return cards


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


def setup_preview() -> Path:
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
    out = ASSETS / "helper-setup-preview.png"
    capture(path, out, 1440, 1100)
    return out


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
    guide_png: Path,
    cards: list[dict[str, object]],
) -> list[str]:
    orange = img_uri(ROOT / str(cards[0]["source"]))
    giants = img_uri(ROOT / str(cards[1]["source"]))
    setup = img_uri(setup_png)
    guide = img_uri(guide_png)
    common = """
    .content{top:170px}.photo-scrim{position:absolute;inset:0;background:linear-gradient(180deg,rgba(5,6,8,.10),rgba(5,6,8,.58) 50%,rgba(5,6,8,.95) 100%)}
    .proof-window{margin-top:38px;overflow:hidden;border:1px solid rgba(255,255,255,.15);border-radius:28px;background:#fff;box-shadow:0 26px 80px rgba(0,0,0,.42)}
    .proof-window img{display:block;width:100%}.browserbar{height:54px;background:#202329;border-bottom:1px solid #343840;display:flex;align-items:center;gap:9px;padding:0 18px}.browserbar i{width:11px;height:11px;border-radius:50%;background:#59606a}.browserbar i:first-child{background:#ef5f57}.browserbar span{margin-left:10px;color:#9da2aa;font:600 13px ui-monospace,monospace}
    .loop{display:grid;gap:16px;margin-top:58px}.loop .card{display:flex;align-items:center;gap:20px;padding:25px 28px}.loop strong{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;background:#24272d;color:#ef382f;font-size:21px}.loop b{font-size:30px}.loop span{margin-left:auto;color:#8f949c;font-size:19px}
    .status{margin-top:45px;padding:36px}.status-head{display:flex;align-items:center;gap:18px}.status-head b{font:800 36px ui-monospace,monospace;color:#66db98}.status-head em{margin-left:auto;color:#777;font:600 15px ui-monospace,monospace}.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:17px;margin-top:31px}.status-grid div{padding:25px;background:#111319;border:1px solid #2a2d34;border-radius:18px}.status-grid span{display:block;color:#8f949d;font:600 16px ui-monospace,monospace}.status-grid strong{display:block;margin-top:9px;font:800 40px ui-monospace,monospace}.status p{font-size:22px;color:#aaa;margin:28px 0 0}
    .safety{display:grid;grid-template-columns:1fr 1fr;gap:17px;margin-top:45px}.safety .card{padding:28px}.safety b{display:block;margin-top:18px;font-size:26px}.safety p{font-size:18px;line-height:1.45;color:#aeb2b8}
    .guide-window{height:620px}.guide-window img{width:100%;transform:translateY(-40px)}
    .mini-foot{position:absolute;left:72px;right:72px;bottom:92px;color:#aaa;font-size:18px;line-height:1.45}
    """
    safe = lambda value: html_module.escape(str(value))
    result: list[str] = []
    result.append(page(f"""<div class="bg-photo" style="background-image:url('{orange}');background-position:center"></div><div class="photo-scrim"></div>{header(1,8)}
      <div class="content" style="top:250px"><div class="eyebrow">{safe(cards[0]['eyebrow'])}</div><h1>용아맥 한 자리 보는데<br><span class="red">30만 원?</span></h1><p class="sub">{safe(cards[0]['supporting'])}</p></div><div class="mini-foot">{safe(cards[0]['footer'])}</div>{footer('THE PROBLEM')}""",width=1080,height=1350,extra_css=common))
    result.append(page(f"""<div class="bg-photo" style="background-image:url('{giants}');background-position:center"></div><div class="photo-scrim"></div>{header(2,8)}
      <div class="content" style="top:685px"><div class="eyebrow">{safe(cards[1]['eyebrow'])}</div><h2 style="font-size:57px">보고 싶은 사람은 많은데<br>원하는 날짜는 이미<br><span class="red">매진.</span></h2><p class="sub">{safe(cards[1]['supporting'])}</p></div>{footer('AUDIENCE SIGNAL')}""",width=1080,height=1350,extra_css=common))
    result.append(page(f"""{header(3,8)}<div class="content"><div class="eyebrow">{safe(cards[2]['eyebrow'])}</div><h2>취소표를 기다리는 동안<br>남는 선택은 세 가지였다.</h2><div class="loop"><div class="card"><strong>01</strong><b>새로고침</b><span>계속 앱 확인</span></div><div class="card"><strong>02</strong><b>포기</b><span>다음 기회로</span></div><div class="card" style="border-color:#68302e"><strong>03</strong><b>비싼 리셀</b><span>정가보다 비싸게</span></div></div><p class="sub">{safe(cards[2]['supporting'])}</p></div>{footer('THE LOOP')}""",width=1080,height=1350,extra_css=common))
    result.append(page(f"""{header(4,8)}<div class="content"><div class="eyebrow">{safe(cards[3]['eyebrow'])}</div><h2 style="font-size:54px">설치 → 직접 로그인 →<br><span class="red">원하는 조건 설정</span></h2><div class="proof-window"><div class="browserbar"><i></i><i></i><i></i><span>localhost · Prickly IMAX Helper</span></div><div style="height:590px;overflow:hidden"><img src="{setup}" style="transform:translateY(-30px)"></div></div><p class="small" style="margin-top:22px">{safe(cards[3]['footer'])}</p></div>{footer('YOUR ACCOUNT · YOUR RULES')}""",width=1080,height=1350,extra_css=common))
    result.append(page(f"""{header(5,8)}<div class="content"><div class="eyebrow">{safe(cards[4]['eyebrow'])}</div><h2 style="font-size:55px">지금 열린 날짜부터<br><span class="red">새로 열릴 날짜까지.</span></h2>{status_card()}<p class="sub" style="font-size:25px">{safe(cards[4]['supporting'])}</p></div>{footer('WAITING · NOT FAILED')}""",width=1080,height=1350,extra_css=common))
    safety_items = [("중복 예매 차단","이미 잡아둔 표가 있으면 멈춤"),("관람권 수 확인","인원수와 같은 수량만 허용"),("남은 금액 0원","추가 결제금액이 남으면 중단"),("최종 제출 1회","결과 불명 시 자동 재시도 금지")]
    safety_html = "".join(f'<div class="card"><span class="check">✓</span><b>{a}</b><p>{b}</p></div>' for a,b in safety_items)
    result.append(page(f"""{header(6,8)}<div class="content"><div class="eyebrow">{safe(cards[5]['eyebrow'])}</div><h2>빠르기 전에<br><span class="red">틀리지 않는 게 먼저.</span></h2><div class="safety">{safety_html}</div><p class="small" style="margin-top:24px">{safe(cards[5]['footer'])}</p></div>{footer('VERIFY · THEN SUBMIT')}""",width=1080,height=1350,extra_css=common))
    result.append(page(f"""{header(7,8)}<div class="content"><div class="eyebrow">{safe(cards[6]['eyebrow'])}</div><h2 style="font-size:52px">댓글을 남기면<br><span class="red">이 설치 안내</span>를 보낸다.</h2><div class="proof-window guide-window"><img src="{guide}"></div><p class="small" style="margin-top:20px">{safe(cards[6]['footer'])}</p></div>{footer('INSTALL GUIDE PREVIEW')}""",width=1080,height=1350,extra_css=common))
    result.append(page(f"""{header(8,8)}<div class="content" style="top:315px"><div class="eyebrow">{safe(cards[7]['eyebrow'])}</div><h1 style="font-size:66px;max-width:880px;line-height:1.18">댓글에 <span class="red">‘아이맥스’</span>라고 남기면<br>설치 방법을 보내줄게.</h1><p class="sub" style="margin-top:68px">Mac · Windows<br>내 컴퓨터 · 내 CGV 계정 · 내 IMAX 관람권</p><div class="rule" style="margin-top:235px"></div><div style="margin-top:34px;font-size:38px;font-weight:850">prickly.ai</div></div>{footer('COMMENT → DM')}""",width=1080,height=1350,extra_css=common))
    return result


def render_video_carousel_covers(cards: list[dict[str, object]]) -> list[Path]:
    for directory in (ASSETS, BUILD, HTML, VIDEO_CAROUSEL, VIDEO_COVERS, VIDEO_CARDS):
        directory.mkdir(parents=True, exist_ok=True)
    setup_png = ASSETS / "helper-setup-preview.png"
    if not setup_png.is_file():
        setup_png = setup_preview()
    guide_png = install_guide_preview()
    paths: list[Path] = []
    for idx, source in enumerate(video_carousel_covers(setup_png, guide_png, cards), 1):
        html = HTML / f"video-carousel-{idx:02d}.html"
        png = VIDEO_COVERS / f"{idx:02d}.png"
        html.write_text(source, encoding="utf-8")
        capture(html, png, 1080, 1350)
        paths.append(png)
    contact_sheet(paths, VIDEO_CAROUSEL / "contact-sheet.png", 4, (216, 270))
    return paths


def render_video_carousel_cards(
    cards: list[dict[str, object]],
    covers: list[Path],
) -> list[Path]:
    if len(cards) != len(covers):
        raise ValueError("every video card requires one cover")
    VIDEO_CARDS.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for card, cover in zip(cards, covers):
        number = int(card["number"])
        duration = int(card["duration"])
        frame_count = duration * 30
        motion = str(card["motion"])
        if motion == "ken-burns":
            zoom = "min(zoom+0.00014,1.025)"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif motion == "proof-pan":
            zoom = "1.010"
            x = "iw/2-(iw/zoom/2)"
            y = f"(ih-ih/zoom)*on/{frame_count}"
        else:
            zoom = "min(zoom+0.000035,1.007)"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        output = VIDEO_CARDS / f"{number:02d}.mp4"
        run(
            FFMPEG,
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            str(cover),
            "-t",
            str(duration),
            "-vf",
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frame_count}:s=1080x1350:fps=30,format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(output),
        )
        outputs.append(output)
    return outputs


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_video_carousel(
    cards: list[dict[str, object]],
    covers: list[Path],
    videos: list[Path],
) -> Path:
    if len(cards) != 8 or len(covers) != 8 or len(videos) != 8:
        raise ValueError("publishable package requires eight cards and eight covers")
    contact = VIDEO_CAROUSEL / "contact-sheet.png"
    checksummed = [*covers, *videos, contact]
    sums = "".join(f"{sha256(path)}  {path.relative_to(VIDEO_CAROUSEL)}\n" for path in checksummed)
    (VIDEO_CAROUSEL / "SHA256SUMS").write_text(sums, encoding="utf-8")
    readme = """# Prickly IMAX Helper 영상 캐러셀

- 업로드 순서: `cards/01.mp4`부터 `cards/08.mp4`
- 표지 확인: `covers/01.png`부터 `covers/08.png`
- 모든 카드는 1080×1350, H.264, yuv420p, 30fps, 무음입니다.
- 댓글 키워드: `아이맥스`
- 음악은 인스타그램 게시 단계에서 별도로 추가하세요.
- Card 7은 공개 Notion을 캡처한 것이 아니라 개인정보 없는 로컬 설치 안내 미리보기입니다.
"""
    (VIDEO_CAROUSEL / "README.md").write_text(readme, encoding="utf-8")
    qa = """# 영상 캐러셀 최종 QA

- 카드 MP4: 8개
- PNG 표지: 8개
- 해상도: 전부 1080×1350
- 비디오: H.264 · yuv420p · 30fps · 무음
- 길이: 6 / 6 / 7 / 9 / 8 / 7 / 9 / 6초
- 오디세이 스틸: 사용자 사용 허용 게시물의 UI 없는 원본 2장
- 제품 설정 화면: 실제 로컬 Helper UI를 오프라인 렌더링
- 설치 안내: 개인정보 없는 로컬 미리보기
- 벤치마킹 계정 화면 녹화: 최종 결과물에서 제외
- CGV 접속·회차·좌석·관람권·결제 조작: 없음
- 예매 완료·좌석 보장·CGV 제휴 주장: 없음
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
        shutil.copytree(VIDEO_COVERS, package / "covers")
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
