from __future__ import annotations

import json
import struct
import subprocess
import unittest
import zipfile
from pathlib import Path


VISUALS = Path(__file__).resolve().parents[1]
MANIFEST = VISUALS / "carousel_manifest.json"
OUTPUT = VISUALS / "video-carousel"
BUILD_SCRIPT = VISUALS / "build_visuals.py"
BANNED_COPY = "Prickly AI는 사람이 반복하던 일을 실제로 작동하는 자동화로 바꾼다."


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        signature = handle.read(24)
    if signature[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", signature[16:24])


class VideoCarouselManifestTests(unittest.TestCase):
    def load_cards(self) -> list[dict[str, object]]:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))["cards"]

    def test_manifest_has_eight_ordered_cards_and_exact_durations(self) -> None:
        cards = self.load_cards()
        self.assertEqual([card["number"] for card in cards], list(range(1, 9)))
        self.assertEqual(
            [card["media_type"] for card in cards],
            ["png", "png", "png", "mp4", "mp4", "png", "mp4", "png"],
        )
        self.assertEqual([card["duration"] for card in cards], [None, None, None, 7, 8, None, 8, None])
        self.assertTrue(all(str(card["headline"]).strip() for card in cards))
        allowed = {"none", "setup-scroll", "workflow-sequence", "outcome-sequence"}
        self.assertTrue(all(card["motion"] in allowed for card in cards))
        self.assertGreaterEqual(len({card["composition"] for card in cards}), 6)

    def test_card_seven_copy_describes_outcome_flow_without_fake_transaction(self) -> None:
        card = self.load_cards()[6]
        self.assertIn("결과 알림", str(card["headline"]) + str(card["supporting"]))
        raw = json.dumps(card, ensure_ascii=False).lower()
        for banned in ("모바일티켓", "예매번호", "qr", "barcode", "실제 예매 완료"):
            self.assertNotIn(banned, raw)

    def test_card_two_explains_why_the_odyssey_belongs_on_yongsan_imax(self) -> None:
        card = self.load_cards()[1]
        self.assertEqual(card["headline"], "오디세이를\n용산 IMAX에서 꼭 봐야 하는 이유.")
        self.assertEqual(
            card["supporting"],
            "IMAX를 위해 촬영한 장면을\n이 압도적인 화면으로 보고 싶으니까.",
        )
        self.assertNotIn("여기서만", str(card["headline"]) + str(card["supporting"]))

    def test_cover_uses_approved_price_kicker_copy(self) -> None:
        card = self.load_cards()[0]
        self.assertEqual(card["kicker"], "30만 원까지 오른 용아맥 표.")
        self.assertEqual(card["headline"], "며칠째 새로고침 중인 사람?")
        self.assertEqual(card["supporting"], "나도 그랬음.")
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('class="cover-kicker"', source)

    def test_manifest_excludes_benchmark_and_banned_copy(self) -> None:
        raw = MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn("ScreenRecording_08-14-2026", raw)
        self.assertNotIn("ai_freaks", raw.lower())
        self.assertNotIn(BANNED_COPY, raw)


class VideoCarouselOutputTests(unittest.TestCase):
    def test_cover_headline_uses_large_mobile_first_type(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            ".full .copy h1{font-size:86px;line-height:1.08;letter-spacing:-5.8px}",
            source,
        )

    def test_comparison_slide_stacks_35mm_over_imax_and_fills_the_canvas(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('<b class="format-label">35MM</b>', source)
        self.assertIn('<b class="format-label imax">IMAX 70MM</b>', source)
        self.assertIn(".format-frame.narrow{height:248px}", source)
        self.assertIn(".format-frame.tall{height:474px}", source)

    def test_cards_two_through_eight_use_twenty_percent_larger_type(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        expected_rules = (
            ".compare .copy h1{font-size:53px",
            ".evidence .copy h1{font-size:70px}",
            ".setup-scroll .copy h1{font-size:62px",
            ".flowstage .copy h1{font-size:78px}",
            ".condition-focus .copy h1{font-size:67px",
            ".outcome .copy h1{font-size:82px}",
            ".note .copy h1{font-size:72px",
        )
        for rule in expected_rules:
            self.assertIn(rule, source)

    def test_condition_slide_uses_the_shared_dark_product_background(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(".condition-focus{background:#090909;color:#f7f7f4}", source)
        self.assertNotIn(".condition-focus{background:#f2f0eb", source)

    def test_eight_png_covers_are_exact_instagram_dimensions(self) -> None:
        covers = sorted((OUTPUT / "covers").glob("*.png"))
        self.assertEqual(len(covers), 8)
        for cover in covers:
            self.assertEqual(png_size(cover), (1080, 1350), cover)

    def test_publishable_sequence_has_five_pngs_and_three_mp4s(self) -> None:
        cards = self.load_cards()
        media = sorted((OUTPUT / "cards").glob("*"))
        self.assertEqual(
            [path.name for path in media],
            ["01.png", "02.png", "03.png", "04.mp4", "05.mp4", "06.png", "07.mp4", "08.png"],
        )
        for image in [path for path in media if path.suffix == ".png"]:
            self.assertEqual(png_size(image), (1080, 1350), image)
        for video in [path for path in media if path.suffix == ".mp4"]:
            card = cards[int(video.stem) - 1]
            probe = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_name,width,height,r_frame_rate,pix_fmt:format=duration",
                    "-of",
                    "json",
                    str(video),
                ],
                text=True,
            )
            data = json.loads(probe)
            stream = data["streams"][0]
            self.assertEqual(stream["codec_name"], "h264")
            self.assertEqual((stream["width"], stream["height"]), (1080, 1350))
            self.assertEqual(stream["r_frame_rate"], "30/1")
            self.assertEqual(stream["pix_fmt"], "yuv420p")
            self.assertAlmostEqual(float(data["format"]["duration"]), float(card["duration"]), delta=0.1)

    def load_cards(self) -> list[dict[str, object]]:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))["cards"]

    def test_package_contains_only_publishable_video_carousel_files(self) -> None:
        archive = VISUALS / "prickly-imax-helper-video-carousel.zip"
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
        self.assertEqual(sum(name.startswith("cards/") and name.endswith(".mp4") for name in names), 3)
        self.assertEqual(sum(name.startswith("cards/") and name.endswith(".png") for name in names), 5)
        self.assertEqual(sum(name.startswith("covers/") for name in names), 0)
        self.assertNotIn("ScreenRecording_08-14-2026 17-39-23_1.MP4", names)


if __name__ == "__main__":
    unittest.main()
