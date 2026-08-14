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
        self.assertEqual([card["duration"] for card in cards], [6, 6, 7, 9, 8, 7, 9, 6])
        self.assertTrue(all(str(card["headline"]).strip() for card in cards))
        self.assertTrue(all(card["motion"] in {"ken-burns", "red-drift", "proof-pan"} for card in cards))

    def test_manifest_excludes_benchmark_and_banned_copy(self) -> None:
        raw = MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn("ScreenRecording_08-14-2026", raw)
        self.assertNotIn("ai_freaks", raw.lower())
        self.assertNotIn(BANNED_COPY, raw)


class VideoCarouselOutputTests(unittest.TestCase):
    def test_eight_png_covers_are_exact_instagram_dimensions(self) -> None:
        covers = sorted((OUTPUT / "covers").glob("*.png"))
        self.assertEqual(len(covers), 8)
        for cover in covers:
            self.assertEqual(png_size(cover), (1080, 1350), cover)

    def test_eight_mp4_cards_match_media_contract(self) -> None:
        cards = self.load_cards()
        videos = sorted((OUTPUT / "cards").glob("*.mp4"))
        self.assertEqual(len(videos), 8)
        for video, card in zip(videos, cards):
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
        self.assertEqual(sum(name.startswith("cards/") and name.endswith(".mp4") for name in names), 8)
        self.assertEqual(sum(name.startswith("covers/") and name.endswith(".png") for name in names), 8)
        self.assertNotIn("ScreenRecording_08-14-2026 17-39-23_1.MP4", names)


if __name__ == "__main__":
    unittest.main()
