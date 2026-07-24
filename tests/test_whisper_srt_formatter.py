from types import SimpleNamespace
import unittest

from app.services.transcriber.whisper_srt_formatter import segments_to_srt


class WhisperSrtFormatterTests(unittest.TestCase):
    def test_produces_numbered_millisecond_srt_with_two_line_cues(self):
        texts = "Note that there is a time delay of about one minute between action items in the council chambers.".split()
        words = [
            SimpleNamespace(start=i * 0.35, end=(i + 1) * 0.35, word=text)
            for i, text in enumerate(texts)
        ]
        segment = SimpleNamespace(start=0.0, end=len(words) * 0.35, text=" ".join(texts), words=words)

        output = segments_to_srt([segment], max_line_chars=42)

        self.assertTrue(output.startswith("1\n00:00:00,000 --> "))
        self.assertIn("-->", output)
        for block in output.strip().split("\n\n"):
            self.assertLessEqual(len(block.splitlines()[2:]), 2)

    def test_preserves_silence_gap_between_cues(self):
        words = [
            SimpleNamespace(start=0.0, end=0.5, word="Hello."),
            SimpleNamespace(start=3.0, end=3.5, word="Welcome."),
        ]
        segment = SimpleNamespace(start=0.0, end=3.5, text="Hello. Welcome.", words=words)
        output = segments_to_srt([segment])
        self.assertEqual(output.count("-->"), 2)
        self.assertIn("00:00:03,000 --> 00:00:03,500", output)


if __name__ == "__main__":
    unittest.main()
