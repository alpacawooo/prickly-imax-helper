from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("prickly_visual_builder", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_locks_six_card_sequence() -> None:
    cards = load_builder().load_carousel_manifest()
    assert [card["number"] for card in cards] == [1, 2, 3, 4, 5, 6]
    assert [card["media_type"] for card in cards] == [
        "png", "png", "png", "mp4", "mp4", "png"
    ]
    assert [card["duration"] for card in cards] == [None, None, None, 3, 8, None]
    assert cards[4]["composition"] == "monitoring-process"
    assert cards[5]["composition"] == "black-note-cta"
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


def test_cover_html_has_six_distinct_compositions_and_no_fake_chrome(tmp_path: Path) -> None:
    builder = load_builder()
    cards = builder.load_carousel_manifest()
    placeholders = [tmp_path / name for name in ("setup.png", "monitor.png", "guide.png")]
    html = builder.video_carousel_covers(*placeholders, cards)
    assert len(html) == 6
    joined = "\n".join(html)
    for banned in ("browserbar", "status-grid", "phone-mockup", "class=\"pill", "eyebrow"):
        assert banned not in joined
    for composition in {card["composition"] for card in cards}:
        assert any(f'data-composition="{composition}"' in page for page in html)
    assert "05/06" in html[4]
    assert "06/06" in html[5]
    assert "/8" not in joined


def test_motion_recipes_are_restrained() -> None:
    recipes = load_builder().motion_recipes()
    assert set(recipes) == {"setup-scroll", "workflow-sequence"}
    assert recipes["setup-scroll"] == {"duration": 3, "fps": 30, "viewport_height": 800}
    assert all(
        recipe.get("transition_ms", 0) <= 220
        for recipe in recipes.values()
    )


def test_card_four_scroll_matches_the_fast_benchmark_tempo() -> None:
    builder = load_builder()
    offsets = builder.card_four_scroll_offsets(
        source_height=1098,
        viewport_height=800,
        frame_count=90,
    )
    assert len(offsets) == 90
    assert offsets[0] == 0
    assert offsets[-1] == 298
    assert offsets == sorted(offsets)
    assert offsets[49:] == [298] * 41
    assert len(set(offsets[:50])) >= 40


def test_redaction_blocks_private_fields() -> None:
    builder = load_builder()
    sample = "email=a@example.com cookie=secret voucher=1234 profile=/Users/name/private"
    redacted = builder.redact_visual_evidence(sample)
    for secret in ("a@example.com", "secret", "1234", "/Users/name/private"):
        assert secret not in redacted


def test_monitor_sampling_reads_local_state_only() -> None:
    builder = load_builder()
    states = iter([
        {"status": "armed", "open_dates": 12, "eligible_shows": 35, "match": None,
         "last_scan_lane": "discovery"},
        {"status": "armed", "open_dates": 12, "eligible_shows": 35, "match": None,
         "last_scan_lane": "hot"},
    ])
    sleeps: list[float] = []
    sampled = builder.sample_monitor_states(
        lambda: next(states), count=2, interval_seconds=0.4, sleeper=sleeps.append
    )
    assert sampled[0]["last_scan_lane"] == "discovery"
    assert sampled[1]["last_scan_lane"] == "hot"
    assert sleeps == [0.4]


def test_redacted_monitor_state_invokes_only_diagnose(monkeypatch) -> None:
    builder = load_builder()
    calls: list[tuple[list[str], dict[str, object]]] = []
    payload = {
        "status": {
            "status": "armed", "detail": "email=a@example.com cookie=secret",
            "open_dates": 12, "eligible_shows": 35, "match": None, "errors": 0,
            "last_scan_lane": "hot", "profile": "/Users/name/private ",
        }
    }

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=json.dumps(payload), returncode=0)

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    state = builder.read_redacted_monitor_state(Path("/tmp/prickly-imax"))
    assert [call[0] for call in calls] == [["/tmp/prickly-imax", "diagnose"]]
    assert set(state) == {
        "status", "detail", "open_dates", "eligible_shows", "match", "errors",
        "last_scan_lane",
    }
    raw = json.dumps(state, ensure_ascii=False)
    for secret in ("a@example.com", "secret", "/Users/name/private"):
        assert secret not in raw


def test_verify_video_carousel_rejects_wrong_count() -> None:
    builder = load_builder()
    try:
        builder.verify_video_carousel([], [], [])
    except ValueError as exc:
        assert "six" in str(exc).lower()
    else:
        raise AssertionError("wrong card count must fail")
