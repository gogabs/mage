import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from mage import editor, project  # noqa: E402


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class EditorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(editor, "config_file",
                                    lambda: os.path.join(self.tmp.name, "cfg", "editor.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server, self.editor = editor.make_server()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.opener = urllib.request.build_opener(NoRedirect)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read().decode("utf-8")

    def post(self, path, data, token=True):
        if token:
            data = dict(data, token=self.editor.token)
        body = urllib.parse.urlencode(data).encode()
        try:
            with self.opener.open(self.base + path, body) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("Location", "")

    def new_game(self):
        folder = os.path.join(self.tmp.name, "corrida-de-sapos")
        status, where = self.post("/new", {"folder": folder, "name": "Corrida de Sapos",
                                           "author": "Gabs"})
        self.assertEqual((status, where), (303, "/project"))
        return folder

    def manifest(self, folder):
        with open(os.path.join(folder, "game.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_home_has_labelled_forms(self):
        html = self.get("/")
        self.assertIn('lang="pt-BR"', html)
        self.assertIn('<label for="folder">Pasta do jogo novo</label>', html)
        self.assertIn("Criar jogo", html)

    def test_create_and_show_project(self):
        folder = self.new_game()
        html = self.get("/project")
        self.assertIn('role="alert"', html)
        self.assertIn("Jogo Corrida de Sapos criado", html)
        self.assertIn("<h1>Corrida de Sapos</h1>", html)
        self.assertIn("Ação bip", html)
        self.assertIn("sounds/bip.wav", html)
        self.assertNotIn('role="alert"', self.get("/project"))  # o aviso aparece uma vez
        with open(os.path.join(self.tmp.name, "cfg", "editor.json")) as f:
            self.assertEqual(json.load(f)["recent"], [folder])

    def test_post_without_token_is_refused(self):
        status, _ = self.post("/new", {"folder": os.path.join(self.tmp.name, "x")}, token=False)
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "x")))

    def test_other_hosts_are_refused(self):
        request = urllib.request.Request(self.base + "/", headers={"Host": "evil.example:80"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(request)
        e.exception.close()
        self.assertEqual(e.exception.code, 403)

    def test_save_properties(self):
        folder = self.new_game()
        self.post("/properties", {"name": "Sapos", "description": "Pule.", "version": "1.2.0",
                                  "author": "", "languages": "pt-BR, en", "tags": "a11y"})
        m = self.manifest(folder)
        self.assertEqual((m["name"], m["version"], m["languages"]), ("Sapos", "1.2.0", ["pt-BR", "en"]))
        self.assertNotIn("author", m)
        self.assertIn("bip", m["actions"])  # o resto do game.json continua

    def test_bad_version_is_not_saved(self):
        folder = self.new_game()
        self.post("/properties", {"name": "Sapos", "version": "um", "languages": "", "tags": ""})
        self.assertEqual(self.manifest(folder)["version"], "0.1.0")
        self.assertIn("1.0.0", self.get("/project"))

    def test_edit_add_and_remove_actions(self):
        folder = self.new_game()
        form = {"count": "3",
                "name_0": "bip", "r36s_0": "b", "key_0": "space, j", "pad_0": "", "mouse_0": "left",
                "name_1": "repetir", "r36s_1": "select", "key_1": "tab", "pad_1": "", "mouse_1": "",
                "remove_1": "1",
                "name_2": "sair", "r36s_2": "a", "key_2": "", "pad_2": "", "mouse_2": "",
                "name_3": "pular", "r36s_3": "x", "key_3": "w", "pad_3": "y", "mouse_3": ""}
        status, _ = self.post("/actions", form)
        self.assertEqual(status, 303)
        actions = self.manifest(folder)["actions"]
        self.assertEqual(actions, {"bip": {"r36s": "b", "key": ["space", "j"], "mouse": "left"},
                                   "sair": {"r36s": "a"},
                                   "pular": {"r36s": "x", "key": "w", "pad": "y"}})

    def test_invalid_action_keeps_what_was_typed(self):
        folder = self.new_game()
        before = self.manifest(folder)["actions"]
        status, html = self.post("/actions", {"count": "0", "name_0": "pular", "r36s_0": "z",
                                              "key_0": "space", "pad_0": "", "mouse_0": ""})
        self.assertEqual(status, 200)
        self.assertIn("não é um botão do R36S", html)
        self.assertIn('value="pular"', html)
        self.assertEqual(self.manifest(folder)["actions"], before)

    def test_check_and_export(self):
        folder = self.new_game()
        self.post("/check", {})
        self.assertIn("Tudo certo", self.get("/project"))
        self.post("/export", {"to": "r36s"})
        self.assertIn("corrida-de-sapos-r36s.zip", self.get("/project"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "dist", "corrida-de-sapos-r36s.zip")))

    def test_sounds_are_served_only_from_sounds(self):
        self.new_game()
        with urllib.request.urlopen(self.base + "/sound?file=sounds/bip.wav") as r:
            self.assertEqual(r.read(4), b"RIFF")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + "/sound?file=game.json")
        e.exception.close()

    def test_open_code_uses_the_chosen_editor(self):
        folder = self.new_game()
        self.post("/settings", {"code_editor": "meu-editor --novo"})
        with mock.patch.object(editor.subprocess, "Popen") as popen:
            self.post("/code", {})
        popen.assert_called_once_with(["meu-editor", "--novo", folder])

    def test_run_starts_the_game_window(self):
        folder = self.new_game()
        with mock.patch.object(project.subprocess, "Popen") as popen:
            self.post("/run", {})
        args, kwargs = popen.call_args
        self.assertEqual(args[0][1], "main.py")
        self.assertEqual((kwargs["cwd"], kwargs["env"]["A11Y_PLATAFORMA"]), (folder, "pc"))
        self.assertIn("Abrindo o jogo", self.get("/project"))

    def test_html_is_escaped(self):
        folder = self.new_game()
        self.post("/properties", {"name": "<script>x</script>", "version": "0.1.0",
                                  "languages": "", "tags": ""})
        html = self.get("/project")
        self.assertNotIn("<script>x</script>", html)
        self.assertTrue(re.search(r"&lt;script&gt;x&lt;/script&gt;", html))
        self.assertEqual(self.manifest(folder)["name"], "<script>x</script>")


if __name__ == "__main__":
    unittest.main()
