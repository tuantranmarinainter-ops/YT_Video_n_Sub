import json
import unittest
from ytsub import subs
from ytsub.subs import Cue

VTT_ROLLING = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello<00:00:01.000><c> world</c>

00:00:02.000 --> 00:00:02.010
hello world

00:00:02.010 --> 00:00:04.000
hello world
next<00:00:03.000><c> line</c>
"""

class T(unittest.TestCase):
    def test_json3(self):
        j = json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "Xin "}, {"utf8": "ch&amp;ào"}]},
                                   {"tStartMs": 1500, "segs": [{"utf8": "\n"}]}]})
        c = subs.parse_json3(j)
        self.assertEqual([(x.start, x.end, x.text) for x in c], [(0, 1500, "Xin ch&ào")])

    def test_srt_roundtrip(self):
        srt = "1\n00:00:01,000 --> 00:00:02,500\nA\nB\n\n2\n00:00:03,000 --> 00:00:04,000\nC\n\n"
        self.assertEqual(subs.to_srt(subs.parse_text(srt)), srt)

    def test_rolling_vtt(self):
        c = subs.parse_text(VTT_ROLLING)
        self.assertEqual([x.text for x in c], ["hello world", "next line"])

    def test_bilingual(self):
        en = [Cue(0, 2000, "Hello"), Cue(2000, 4000, "World")]
        vi = [Cue(100, 1900, "Xin chào"), Cue(5000, 6000, "lẻ")]
        m = subs.merge_bilingual(en, vi, "#FF0")
        self.assertEqual(m[0].text, 'Hello\n<font color="#FF0">Xin chào</font>')
        self.assertEqual(m[1].text, "World")
        self.assertEqual(m[2].text, '<font color="#FF0">lẻ</font>')

    def test_txt_dedupe(self):
        self.assertEqual(subs.to_txt([Cue(0, 1, "a"), Cue(1, 2, "a"), Cue(2, 3, "b")]), "a\nb\n")

class TOrig(unittest.TestCase):
    def test_orig_track(self):
        from ytsub.engine import Engine
        e = Engine.__new__(Engine)
        M = lambda *ks: {k: [{}] for k in ks}
        cases = [
            ({"language": "sv", "subtitles": M("ar", "en", "vi"), "automatic_captions": M("ar", "en")}, ("en", "manual")),
            ({"subtitles": {}, "automatic_captions": M("en")}, ("en", "auto")),
            ({"subtitles": M("ja"), "automatic_captions": M("ja-orig", "en", "vi")}, ("ja", "manual")),
            ({"subtitles": {}, "automatic_captions": M("ko-orig", "en")}, ("ko-orig", "auto")),
            ({"subtitles": M("fr", "de")}, ("fr", "manual")),
            ({}, None),
        ]
        for info, want in cases:
            self.assertEqual(e._orig_track(info, ("en", "vi")), want, info)


if __name__ == "__main__":
    unittest.main()
