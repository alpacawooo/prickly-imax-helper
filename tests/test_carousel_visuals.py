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
    assert [card["duration"] for card in cards] == [6, 6, 7, 9, 8, 7, 9, 6]
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
    assert recipes["slow-push"]["max_scale"] <= 1.05
    assert recipes["guided-focus"]["transition_ms"] <= 300
    assert recipes["guided-scroll"]["transition_ms"] <= 300
    assert recipes["text-reveal"]["transition_ms"] <= 300


def test_card_seven_has_three_real_scene_states(tmp_path: Path) -> None:
    builder = load_builder()
    html = builder.card_seven_scene_htmls(
        tmp_path / "setup.png", tmp_path / "monitor.png", tmp_path / "guide.png"
    )
    assert len(html) == 3
    assert "설정 완료" in html[0]
    assert "armed" in html[1] and "match:null" in html[1]
    assert "설치 안내" in html[2]


def test_card_three_stages_evidence_before_final_claim(tmp_path: Path) -> None:
    builder = load_builder()
    html = builder.card_three_scene_htmls(tmp_path / "evidence.png", "최종 문구")
    assert len(html) == 3
    assert "1석/624석" in html[0]
    assert "붙어 있는 2석" not in html[0]
    assert "외딴 한 자리" in html[1]
    assert "최종 문구" in html[2]


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
