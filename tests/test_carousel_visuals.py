from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("prickly_visual_builder", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_locks_eight_distinct_compositions() -> None:
    cards = load_builder().load_carousel_manifest()
    assert [card["number"] for card in cards] == list(range(1, 9))
    assert [card["media_type"] for card in cards] == [
        "png", "png", "png", "mp4", "mp4", "png", "mp4", "png"
    ]
    assert [card["duration"] for card in cards] == [None, None, None, 7, 8, None, 8, None]
    assert len({card["composition"] for card in cards}) >= 6
    assert all(
        card["text_anchor"] in {"bottom-left", "top-left", "bottom", "right", "center-left"}
        for card in cards
    )


def test_manifest_uses_real_single_seat_evidence_for_card_three() -> None:
    card = load_builder().load_carousel_manifest()[2]
    assert card["source_type"] == "cgv-user-evidence"
    assert card["composition"] == "single-seat-evidence"
    assert "붙어 있는 2석" in card["headline"]
    assert (ROOT / str(card["source"])).is_file()


def test_manifest_rejects_fake_ui_sources() -> None:
    cards = load_builder().load_carousel_manifest()
    banned = {"fake-browser", "fake-terminal", "phone-mockup", "fake-ticket"}
    assert not ({card["source_type"] for card in cards} & banned)


def test_cover_html_has_eight_distinct_compositions_and_no_fake_chrome(tmp_path: Path) -> None:
    builder = load_builder()
    cards = builder.load_carousel_manifest()
    placeholders = [tmp_path / name for name in ("setup.png", "monitor.png", "guide.png")]
    html = builder.video_carousel_covers(*placeholders, cards)
    assert len(html) == 8
    joined = "\n".join(html)
    for banned in ("browserbar", "status-grid", "phone-mockup", "class=\"pill", "eyebrow"):
        assert banned not in joined
    for composition in {card["composition"] for card in cards}:
        assert any(f'data-composition="{composition}"' in page for page in html)


def test_motion_recipes_are_restrained() -> None:
    recipes = load_builder().motion_recipes()
    assert set(recipes) == {"setup-scroll", "workflow-sequence", "outcome-sequence"}
    assert recipes["setup-scroll"]["duration"] == 7
    assert all(
        recipe.get("transition_ms", 0) <= 220
        for recipe in recipes.values()
    )


def test_card_four_scroll_is_continuous_and_reaches_the_bottom() -> None:
    builder = load_builder()
    offsets = builder.card_four_scroll_offsets(
        source_height=2400,
        viewport_height=900,
        frame_count=211,
    )
    assert len(offsets) == 211
    assert offsets[0] == 0
    assert offsets[-1] == 1500
    assert offsets == sorted(offsets)
    assert len(set(offsets[1:-1])) > 180


def test_card_six_uses_a_readable_field_focus_instead_of_a_clipped_split(tmp_path: Path) -> None:
    builder = load_builder()
    cards = builder.load_carousel_manifest()
    placeholders = [tmp_path / name for name in ("setup.png", "monitor.png", "guide.png")]
    html = builder.video_carousel_covers(*placeholders, cards)
    card_six = html[5]
    assert "condition-focus" in card_six
    assert "asym" not in card_six
    for value in ("연속 2석", "D–J열", "양끝 20% 제외", "3시간 이상"):
        assert value in card_six


def test_card_five_has_four_ordered_workflow_states(tmp_path: Path) -> None:
    builder = load_builder()
    html = builder.card_five_scene_htmls(tmp_path / "setup.png", tmp_path / "monitor.png")
    assert len(html) == 4
    assert "조건 설정" in html[0]
    assert "감시 시작" in html[1]
    assert "연속 좌석 후보 발견" in html[2]
    assert "중복·관람권·잔액 검증" in html[3]


def test_card_seven_has_four_honest_outcome_states(tmp_path: Path) -> None:
    builder = load_builder()
    pages = builder.card_seven_scene_htmls(tmp_path / "monitor.png")
    assert len(pages) == 4
    assert "조건 일치" in pages[0]
    assert "안전검증 통과" in pages[1]
    assert "최종 제출 1회" in pages[2]
    assert "결과 이메일 전송" in pages[3]
    raw = "\n".join(pages).lower()
    for banned in ("모바일티켓", "예매번호", "qr", "barcode", "fake-ticket"):
        assert banned not in raw


def test_redaction_blocks_private_fields() -> None:
    builder = load_builder()
    sample = "email=a@example.com cookie=secret voucher=1234 profile=/Users/name/private"
    redacted = builder.redact_visual_evidence(sample)
    for secret in ("a@example.com", "secret", "1234", "/Users/name/private"):
        assert secret not in redacted


def test_verify_video_carousel_rejects_wrong_count() -> None:
    builder = load_builder()
    try:
        builder.verify_video_carousel([], [], [])
    except ValueError as exc:
        assert "eight" in str(exc).lower()
    else:
        raise AssertionError("wrong card count must fail")
