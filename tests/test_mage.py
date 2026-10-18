import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from mage import cli, downloads, export, project  # noqa: E402


def fake_python_package():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for name in ("tools/python.exe", "tools/pythonw.exe", "tools/python313.dll",
                     "tools/python3.dll", "tools/LICENSE.txt", "tools/DLLs/_ctypes.pyd",
                     "tools/Lib/os.py", "tools/Lib/site-packages/pip/__init__.py",
                     "tools/Lib/test/test_os.py", "tools/include/Python.h"):
            z.writestr(name, "x")
    data.seek(0)
    return zipfile.ZipFile(data)


def fake_dlls(dest, log=print):
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "SDL2.dll"), "w") as f:
        f.write("x")


class CriadorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = os.path.join(self.tmp.name, "corrida-de-sapos")
        project.create(self.game, name="Corrida de Sapos", log=lambda *_: None)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self):
        with open(os.path.join(self.game, "game.json"), encoding="utf-8") as f:
            return json.load(f)

    def write_manifest(self, data):
        with open(os.path.join(self.game, "game.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_new_project_is_valid_and_has_the_sdk(self):
        manifest = project.load(self.game)
        self.assertEqual(manifest["id"], "corrida-de-sapos")
        self.assertEqual(manifest["name"], "Corrida de Sapos")
        self.assertIn("bip", manifest["actions"])
        for rel in ("main.py", "sounds/bip.wav", "r36s_a11y/__init__.py", "r36s_a11y/game.py"):
            self.assertTrue(os.path.isfile(os.path.join(self.game, rel)), rel)
        with self.assertRaises(project.ProjectError):
            project.create(self.game)  # pasta já usada

    def test_id_comes_from_the_folder(self):
        self.assertEqual(project.make_id("Meu Jogão Legal!"), "meu-jogao-legal")

    def test_check_lists_every_problem(self):
        data = self.manifest()
        data.update(id="Corrida", version="1", exec="nada.py",
                    actions={"pular": {"r36s": "botao"}})
        del data["name"]
        self.write_manifest(data)
        _, problems = project.check(self.game)
        text = "\n".join(problems)
        for part in ('"name"', "Corrida", "1.0.0", "nada.py", "pular"):
            self.assertIn(part, text)

    def test_package_skips_development_files(self):
        for rel in ("tests/test_x.py", "dist/velho.zip", "r36s_a11y/dll/SDL2.dll",
                    "rascunho/nota.txt", "__pycache__/main.cpython-313.pyc",
                    "jogo/tools/mapa.py"):
            os.makedirs(os.path.dirname(os.path.join(self.game, rel)), exist_ok=True)
            open(os.path.join(self.game, rel), "w").close()
        data = self.manifest()
        data["export"] = {"ignore": ["rascunho"]}
        self.write_manifest(data)
        rels = [rel for _, rel in project.package_files(self.game, data)]
        self.assertIn("main.py", rels)
        self.assertIn("r36s_a11y/game.py", rels)
        self.assertIn("jogo/tools/mapa.py", rels)  # só o tools da raiz é de desenvolvimento
        for rel in rels:
            self.assertFalse(rel.startswith(("tests/", "dist/", "r36s_a11y/dll", "rascunho",
                                             "__pycache__")), rel)

    def test_package_refuses_names_the_card_cannot_hold(self):
        # O Windows não cria esses nomes, então a pasta é simulada.
        walk = [(self.game, ["sounds"], ["game.json"]),
                (os.path.join(self.game, "sounds"), [], ["bip.wav", "Bip.wav", "o que?.wav"])]
        with mock.patch.object(project.os, "walk", lambda path: iter(walk)):
            with self.assertRaises(project.ProjectError) as e:
                project.package_files(self.game, self.manifest())
        self.assertIn("maiúsculas", str(e.exception))
        self.assertIn("o que?.wav", str(e.exception))

    def test_export_r36s_zip_has_the_game_folder(self):
        out = export.r36s(self.game, log=lambda *_: None)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        self.assertIn("corrida-de-sapos/game.json", names)
        self.assertIn("corrida-de-sapos/r36s_a11y/game.py", names)
        self.assertFalse(any("/dll/" in n for n in names))

    def test_export_windows_builds_an_isolated_exe(self):
        with mock.patch.object(downloads, "python_package", lambda log=print: fake_python_package()), \
                mock.patch.object(downloads, "install_dlls", fake_dlls):
            out = export.windows(self.game, log=lambda *_: None)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            pth = z.read("Corrida de Sapos/python313._pth").decode()
            launcher = z.read("Corrida de Sapos/sitecustomize.py").decode()
        app = "Corrida de Sapos/"
        for rel in ("Corrida de Sapos.exe", "python313.dll", "DLLs/_ctypes.pyd", "Lib/os.py",
                    "jogo/main.py", "jogo/r36s_a11y/dll/SDL2.dll", "LICENCA-Python.txt"):
            self.assertIn(app + rel, names)
        for rel in ("python.exe", "pythonw.exe", "Lib/site-packages/pip/__init__.py",
                    "Lib/test/test_os.py", "include/Python.h"):
            self.assertNotIn(app + rel, names)
        self.assertEqual(pth.split(), ["Lib", "DLLs", ".", "import", "site"])
        compile(launcher, "sitecustomize.py", "exec")
        self.assertIn("'corrida-de-sapos'", launcher)

    def test_cli_commands_are_in_english(self):
        other = os.path.join(self.tmp.name, "outro-jogo")
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(cli.main(["new", other, "--name", "Outro", "--author", "Gabs"]), 0)
            self.assertEqual(cli.main(["check", other]), 0)
            self.assertEqual(cli.main(["export", other, "--to", "r36s"]), 0)
        self.assertEqual(project.load(other)["author"], "Gabs")
        self.assertTrue(os.path.isfile(os.path.join(other, "dist", "outro-jogo-r36s.zip")))
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["novo", other])

    def test_bundled_sdk_matches_origin(self):
        with open(os.path.join(project.SDK_DIR, "origin.json")) as f:
            origin = json.load(f)
        self.assertEqual(origin["version"], project.sdk_version())
        self.assertEqual(len(origin["commit"]), 40)

    def test_exe_name_is_valid_on_windows(self):
        self.assertEqual(export.exe_name("Dead vs. Alive"), "Dead vs. Alive")
        self.assertEqual(export.exe_name("Sim: ou não? ..."), "Sim ou não")

    def test_launcher_runs_the_game_and_writes_the_log(self):
        """O sitecustomize abre o jogo quando o Python começa, como o .exe faria."""
        app = os.path.join(self.tmp.name, "app")
        os.makedirs(os.path.join(app, "jogo"))
        with open(os.path.join(app, "jogo", "main.py"), "w") as f:
            f.write("import os\nprint('pasta', os.path.basename(os.getcwd()))\n")
        with open(os.path.join(app, "sitecustomize.py"), "w", encoding="utf-8") as f:
            f.write(export.LAUNCHER % {"id": "teste", "exec": "main.py", "name": "Teste"})
        appdata = os.path.join(self.tmp.name, "appdata")
        env = dict(os.environ, PYTHONPATH=app, APPDATA=appdata)
        result = subprocess.run([sys.executable, "-c", "print('não devia rodar')"],
                                env=env, stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        with open(os.path.join(appdata, "r36s-a11y", "teste", "teste.log")) as f:
            self.assertEqual(f.read(), "pasta jogo\n")

    def test_game_reads_actions_from_game_json(self):
        env = {"A11Y_GAME_DIR": self.game, "A11Y_FALA": "terminal", "ALSOFT_DRIVERS": "null",
               "A11Y_SAVE_DIR": os.path.join(self.tmp.name, "save"), "A11Y_PLATAFORMA": "pc"}
        with mock.patch.dict(os.environ, env):
            from r36s_a11y.game import Game  # a cópia da engine, em mage/sdk
            game = Game()
        self.assertEqual(sorted(game.action_map.names()), ["bip", "repetir", "sair"])
        self.assertEqual(game.label("bip"), "espaço")
        self.assertEqual(game.label("bip", "r36s"), "B")


if __name__ == "__main__":
    unittest.main()
