import json
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from mage import assets, export, project  # noqa: E402


def write_tone(file, seconds=2.0, rate=22050, channels=1, width=2):
    frames = int(rate * seconds)
    with wave.open(file, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            fmt, scale, offset = "<h", 12000, 0
        else:
            fmt, scale, offset = "<B", 100, 128
        data = b"".join(struct.pack(fmt, int(offset + scale * math.sin(i * 0.05))) * channels
                        for i in range(frames))
        w.writeframes(data)


class AssetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "sapos")
        project.create(self.game, log=lambda *_: None)
        write_tone(os.path.join(self.game, "sounds", "musica.wav"))

    def manifest(self, **changes):
        file = os.path.join(self.game, "game.json")
        with open(file, encoding="utf-8") as f:
            data = json.load(f)
        data.update(changes)
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def export(self):
        notes = []
        out = export.r36s(self.game, log=notes.append)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            stage = os.path.join(self.tmp.name, "zip")
            z.extractall(stage)
        return names, notes, os.path.join(stage, "sapos")

    def need_sndfile(self):
        if assets._sndfile() is None:
            self.skipTest("sem libsndfile neste computador")

    def test_new_project_has_the_asset_folders(self):
        for folder in ("sounds", "images", "data"):
            self.assertTrue(os.path.isdir(os.path.join(self.game, folder)), folder)

    def test_folder_for_and_names(self):
        self.assertEqual(assets.folder_for("a.WAV"), "sounds")
        self.assertEqual(assets.folder_for("heroi.png"), "images")
        self.assertEqual(assets.folder_for("fase.json"), "data")
        self.assertEqual(assets.folder_for("LEIAME"), "data")
        self.assertEqual(assets.clean_name("pasta/ação.ogg"), "ação.ogg")
        for bad in ("a:b.png", "x.", "..", ""):
            with self.assertRaises(project.ProjectError):
                assets.clean_name(bad)

    def test_export_turns_wav_into_ogg_the_sdk_finds(self):
        self.need_sndfile()
        names, notes, stage = self.export()
        self.assertIn("sapos/sounds/musica.ogg", names)
        self.assertNotIn("sapos/sounds/musica.wav", names)
        self.assertTrue(any(n.startswith("Sons: ") for n in notes), notes)
        sys.path.insert(0, stage)
        try:
            from r36s_a11y import audio, sndfile
            full = audio.sound_file(os.path.join(stage, "sounds", "musica.wav"))
            self.assertTrue(full.endswith("musica.ogg"))
            channels, width, rate, data = sndfile.decode(full)
            self.assertEqual((channels, width, rate), (1, 2, 22050))
            self.assertAlmostEqual(len(data) / (2.0 * rate), 2.0, places=1)
        finally:
            sys.path.remove(stage)

    def test_eight_bit_stereo_wav_is_encoded(self):
        self.need_sndfile()
        src = os.path.join(self.tmp.name, "oito.wav")
        write_tone(src, seconds=1, channels=2, width=1)
        dest = os.path.join(self.tmp.name, "oito.ogg")
        assets.encode_ogg(src, dest)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(4), b"OggS")

    def test_compress_sounds_false_keeps_wav(self):
        self.manifest(export={"compress_sounds": False})
        names, notes, _ = self.export()
        self.assertIn("sapos/sounds/musica.wav", names)
        self.assertNotIn("sapos/sounds/musica.ogg", names)

    def test_old_sdk_keeps_wav_and_says_why(self):
        init = os.path.join(self.game, "r36s_a11y", "__init__.py")
        with open(init, encoding="utf-8") as f:
            text = f.read()
        with open(init, "w", encoding="utf-8") as f:
            f.write(text.replace('__version__ = "0.4.0"', '__version__ = "0.3.0"'))
        names, notes, _ = self.export()
        self.assertIn("sapos/sounds/musica.wav", names)
        self.assertTrue(any("mage.py update" in n for n in notes), notes)

    def test_existing_ogg_with_the_same_name_wins(self):
        self.need_sndfile()
        with open(os.path.join(self.game, "sounds", "musica.ogg"), "wb") as f:
            f.write(b"OggS feito a mao")
        names, _, stage = self.export()
        self.assertIn("sapos/sounds/musica.wav", names)
        with open(os.path.join(stage, "sounds", "musica.ogg"), "rb") as f:
            self.assertEqual(f.read(), b"OggS feito a mao")

    def test_compress_sounds_must_be_boolean(self):
        self.manifest(export={"compress_sounds": "sim"})
        _, problems = project.check(self.game)
        self.assertTrue(any("compress_sounds" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
