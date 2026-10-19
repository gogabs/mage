"""O editor do Mage: uma página local, no navegador, feita para leitor de tela.

    python mage.py editor [pasta-do-jogo]

O editor serve as páginas só para este computador (127.0.0.1) e abre o
navegador. As páginas são HTML simples, com formulários, rótulos e títulos,
que o NVDA lê bem; tudo funciona sem JavaScript. Cada ação grava o game.json
ou chama as mesmas funções da linha de comando (rodar, conferir, exportar).
O código continua no editor de código que a pessoa preferir.
"""
import html
import json
import mimetypes
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, quote, urlsplit

from . import assets, export, project
from r36s_a11y.actions import (MOUSE_BUTTONS, MOUSE_LABELS, PAD_BUTTONS, PAD_LABELS,
                               R36S_BUTTONS, R36S_LABELS, XBOX, Actions)

RECENT_MAX = 8


# --- preferências ---------------------------------------------------------
def config_file():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "mage", "editor.json")


def load_config():
    try:
        with open(config_file(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data):
    file = config_file()
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def remember(path):
    data = load_config()
    recent = [p for p in data.get("recent", []) if p != path]
    data["recent"] = [path] + recent[:RECENT_MAX - 1]
    save_config(data)


# --- abrir coisas no computador --------------------------------------------
def open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: no Windows existe
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def code_command(folder, choice=None):
    """O comando que abre a pasta no editor de código escolhido (ou o VS Code)."""
    if choice:
        return shlex.split(choice, posix=sys.platform != "win32") + [folder]
    code = shutil.which("code")
    return [code, folder] if code else None


def open_code(folder, choice=None):
    cmd = code_command(folder, choice)
    if cmd:
        subprocess.Popen(cmd)
        return "Abrindo o projeto em %s." % os.path.basename(cmd[0])
    open_folder(folder)
    return ("Não achei o VS Code, então abri a pasta do projeto. Dá para escolher o "
            "editor de código nas preferências.")


# --- ações: do game.json para o formulário e de volta -------------------------
def _as_list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def action_rows(actions):
    """[{name, r36s, key, pad, mouse}] com textos, para o formulário."""
    rows = []
    for name, spec in (actions or {}).items():
        if isinstance(spec, str):
            spec = {"r36s": spec}
        rows.append({"name": name,
                     "r36s": ", ".join(_as_list(spec.get("r36s"))),
                     "key": ", ".join(_as_list(spec.get("key"))),
                     "pad": ", ".join(_as_list(spec.get("pad"))),
                     "mouse": ", ".join(_as_list(spec.get("mouse")))})
    return rows


def _split(text):
    return [part.strip() for part in text.split(",") if part.strip()]


def actions_from_form(form):
    """(ações, linhas do formulário) a partir dos campos enviados."""
    actions, rows = {}, []
    count = int(form.get("count", "0") or 0)
    for i in range(count + 1):
        row = {f: form.get("%s_%d" % (f, i), "").strip()
               for f in ("name", "r36s", "key", "pad", "mouse")}
        if not row["name"] or form.get("remove_%d" % i):
            continue
        rows.append(row)
        spec = {}
        for field in ("r36s", "key", "pad", "mouse"):
            values = _split(row[field])
            if values:
                spec[field] = values[0] if len(values) == 1 else values
        actions[row["name"]] = spec
    return actions, rows


# --- páginas ----------------------------------------------------------------
STYLE = """
:root { color-scheme: light dark; --fundo: #ffffff; --texto: #111111; --borda: #555555;
        --destaque: #0b57d0; --ok: #0a6b2d; --erro: #b3261e; --caixa: #f2f4f8; }
@media (prefers-color-scheme: dark) {
  :root { --fundo: #111418; --texto: #f1f1f1; --borda: #9aa0a6; --destaque: #8ab4f8;
          --ok: #7fd18b; --erro: #f2b8b5; --caixa: #1d2127; } }
body { background: var(--fundo); color: var(--texto); font: 1.15rem/1.6 system-ui, sans-serif;
       margin: 0 auto; max-width: 60rem; padding: 1rem; }
a { color: var(--destaque); }
fieldset { border: 2px solid var(--borda); border-radius: .5rem; margin: 0 0 1rem; padding: .75rem 1rem; }
legend { font-weight: bold; padding: 0 .25rem; }
label { display: block; margin-top: .5rem; font-weight: 600; }
input[type=text], select { font: inherit; width: 100%; box-sizing: border-box; padding: .35rem;
       border: 2px solid var(--borda); border-radius: .35rem; background: var(--fundo); color: var(--texto); }
input[type=checkbox] { width: 1.2rem; height: 1.2rem; vertical-align: middle; }
label.inline { display: inline; font-weight: normal; }
button { font: inherit; padding: .45rem 1rem; margin: .5rem .5rem 0 0; border-radius: .35rem;
         border: 2px solid var(--destaque); background: var(--destaque); color: var(--fundo); cursor: pointer; }
button.secundario { background: transparent; color: var(--destaque); }
:focus-visible { outline: 3px solid var(--destaque); outline-offset: 3px; }
.aviso { border: 3px solid var(--ok); border-radius: .5rem; padding: .5rem 1rem; margin: 1rem 0; }
.aviso.erro { border-color: var(--erro); }
.dica { font-size: 1rem; margin: .25rem 0 0; }
.caixa { background: var(--caixa); border-radius: .5rem; padding: .5rem 1rem; }
.arquivos li { margin: .5rem 0; display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
.arquivos img { max-width: 96px; max-height: 96px; image-rendering: pixelated; }
.arquivos form { display: inline; }
nav ul { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 1rem; }
.pular { position: absolute; left: -999px; }
.pular:focus { left: 1rem; top: 1rem; background: var(--fundo); padding: .5rem; }
"""


def esc(text):
    return html.escape(str(text), quote=True)


def page(title, body, notice=None):
    alert = ""
    if notice:
        kind, text, details = notice
        items = "".join("<li>%s</li>" % esc(d) for d in details)
        alert = ('<div id="aviso" class="aviso%s" role="alert" tabindex="-1"><p>%s</p>%s</div>'
                 '<script>document.getElementById("aviso").focus()</script>'
                 % (" erro" if kind == "erro" else "", esc(text),
                    "<ul>%s</ul>" % items if items else ""))
    return ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s · Mage</title><style>%s</style></head><body>'
            '<a class="pular" href="#conteudo">Pular para o conteúdo</a>'
            '<main id="conteudo">%s%s</main></body></html>'
            % (esc(title), STYLE, alert, body))


def form(action, token, inner, label=None, cls=""):
    button = '<button type="submit"%s>%s</button>' % (
        ' class="%s"' % cls if cls else "", esc(label)) if label else ""
    return ('<form method="post" action="%s"><input type="hidden" name="token" value="%s">'
            '%s%s</form>' % (action, esc(token), inner, button))


def field(name, label, value="", hint=None, readonly=False):
    hint_id = "%s-dica" % name
    return ('<label for="%s">%s</label><input type="text" id="%s" name="%s" value="%s"%s%s>%s'
            % (name, esc(label), name, name, esc(value),
               ' aria-describedby="%s"' % hint_id if hint else "",
               " readonly" if readonly else "",
               '<p class="dica" id="%s">%s</p>' % (hint_id, esc(hint)) if hint else ""))


def select(name, label, value, options):
    """options: [(valor, texto)]; um valor que não está na lista vira campo de texto."""
    if value and value not in [v for v, _ in options]:
        return field(name, label + " (separe com vírgula)", value)
    opts = "".join('<option value="%s"%s>%s</option>' % (
        esc(v), " selected" if v == value else "", esc(t)) for v, t in options)
    return '<label for="%s">%s</label><select id="%s" name="%s">%s</select>' % (
        name, esc(label), name, name, opts)


R36S_OPTIONS = [("", "nenhum")] + [(b, R36S_LABELS.get(b, b.upper())) for b in R36S_BUTTONS]
PAD_OPTIONS = [("", "automático (o mesmo lugar do botão do R36S)")] + [
    (p, "%s (Xbox)" % PAD_LABELS[XBOX][p]) for p in PAD_BUTTONS if p != "guide"]
MOUSE_OPTIONS = [("", "nenhum")] + [(m, MOUSE_LABELS[m]) for m in MOUSE_BUTTONS]


def home_page(token, recent):
    items = "".join('<li>%s</li>' % form("/open", token,
                                         '<input type="hidden" name="folder" value="%s">' % esc(p),
                                         label="Abrir %s" % p, cls="secundario")
                    for p in recent if os.path.isfile(os.path.join(p, "game.json")))
    body = ['<h1>Mage</h1><p>Crie um jogo novo ou abra um que já existe.</p>',
            '<h2>Novo jogo</h2>',
            form("/new", token,
                 field("folder", "Pasta do jogo novo",
                       hint="Caminho completo, como C:\\jogos\\corrida-de-sapos. "
                            "O nome da pasta vira o id do jogo.")
                 + field("name", "Nome do jogo", hint="O nome que o Luma fala.")
                 + field("author", "Autor"), label="Criar jogo"),
            '<h2>Abrir jogo</h2>',
            form("/open", token, field("folder", "Pasta do jogo", hint="A pasta que tem o game.json."),
                 label="Abrir")]
    if items:
        body.append('<h2>Abertos recentemente</h2><ul>%s</ul>' % items)
    body.append('<p><a href="/settings">Preferências</a></p>')
    return "".join(body)


def project_page(token, path, manifest, rows=None):
    rows = action_rows(manifest.get("actions")) if rows is None else rows
    m = manifest
    nav = ('<nav aria-label="Seções"><ul><li><a href="#propriedades">Propriedades</a></li>'
           '<li><a href="#acoes">Ações</a></li><li><a href="#arquivos">Arquivos</a></li>'
           '<li><a href="#ferramentas">Rodar e exportar</a></li>'
           '<li><a href="/">Outro jogo</a></li><li><a href="/settings">Preferências</a></li></ul></nav>')
    head = '<h1>%s</h1><p class="caixa">Pasta: %s</p>%s' % (esc(m.get("name", "")), esc(path), nav)

    props = form("/properties", token,
                 field("name", "Nome", m.get("name", ""), "O nome que o Luma fala.")
                 + field("id", "Id", m.get("id", ""), "Igual ao nome da pasta; não muda por aqui.",
                         readonly=True)
                 + field("description", "Descrição", m.get("description", ""),
                         "Falada quando o jogador pede detalhes no Luma.")
                 + field("version", "Versão", m.get("version", ""), "Como 1.0.0.")
                 + field("author", "Autor", m.get("author", ""))
                 + field("languages", "Idiomas", ", ".join(m.get("languages", [])),
                         "Separe com vírgula, como pt-BR, en.")
                 + field("tags", "Tags", ", ".join(m.get("tags", [])),
                         "Para o filtro do Luma; separe com vírgula."),
                 label="Salvar propriedades")

    fieldsets = []
    for i, row in enumerate(rows + [{"name": "", "r36s": "", "key": "", "pad": "", "mouse": ""}]):
        new = i == len(rows)
        legend = "Nova ação" if new else "Ação %s" % row["name"]
        inner = (field("name_%d" % i, "Nome da ação", row["name"],
                       "Como o código chama a ação, por exemplo pular." if new else None)
                 + select("r36s_%d" % i, "Botão do R36S", row["r36s"], R36S_OPTIONS)
                 + field("key_%d" % i, "Teclas", row["key"],
                         "Separe com vírgula, como space, return. Vazio usa as teclas do botão "
                         "do R36S." if new else None)
                 + select("pad_%d" % i, "Botão do controle", row["pad"], PAD_OPTIONS)
                 + select("mouse_%d" % i, "Botão do mouse", row["mouse"], MOUSE_OPTIONS))
        if not new:
            inner += ('<p><input type="checkbox" id="remove_%d" name="remove_%d" value="1">'
                      '<label class="inline" for="remove_%d">Remover a ação %s</label></p>'
                      % (i, i, i, esc(row["name"])))
        fieldsets.append("<fieldset><legend>%s</legend>%s</fieldset>" % (esc(legend), inner))
    actions = form("/actions", token,
                   '<input type="hidden" name="count" value="%d">' % len(rows) + "".join(fieldsets),
                   label="Salvar ações")

    files = files_section(token, path)

    tools = ("".join([
        form("/run", token, "", label="Rodar o jogo"),
        form("/code", token, "", label="Abrir no editor de código", cls="secundario"),
        form("/folder", token, "", label="Abrir a pasta do jogo", cls="secundario"),
        form("/check", token, "", label="Conferir o projeto", cls="secundario"),
        "<h3>Exportar</h3>",
        form("/export", token, select("to", "Para onde", "all", [
            ("all", "R36S e Windows"), ("r36s", "Só R36S (zip para o cartão)"),
            ("windows", "Só Windows (.exe)")]), label="Exportar"),
        '<p class="dica">A primeira exportação para Windows baixa o Python e as DLLs e '
        'pode demorar alguns minutos.</p>']))

    return (head
            + '<h2 id="propriedades">Propriedades</h2>' + props
            + '<h2 id="acoes">Ações</h2><p>O que o jogador aperta para cada ação, em cada '
              'dispositivo. O jogo lê isto do game.json sozinho.</p>'
              '<p>Nomes de teclas: space, return, escape, tab, backspace, up, down, left, right, '
              'letras, números, f1 a f12, shift, alt. Separe várias com vírgula.</p>' + actions
            + '<h2 id="arquivos">Arquivos</h2>' + files
            + '<h2 id="ferramentas">Rodar e exportar</h2>' + tools)


def files_section(token, path):
    """Sons, imagens e dados do jogo, com o formulário para adicionar mais."""
    upload = ('<form method="post" action="/upload" enctype="multipart/form-data">'
              '<input type="hidden" name="token" value="%s">'
              '<label for="files">Arquivos para adicionar</label>'
              '<input type="file" id="files" name="files" multiple aria-describedby="files-dica">'
              '<p class="dica" id="files-dica">Sons vão para sounds, imagens para images e o '
              'resto (JSON, texto, fases) para data. Um arquivo com o mesmo nome é '
              'substituído.</p><button type="submit">Adicionar arquivos</button></form>'
              % esc(token))
    parts = [upload]
    n = 0
    for folder, items in assets.listing(path).items():
        parts.append("<h3>%s <span class=\"dica\">(%s)</span></h3>" % (
            assets.LABELS[folder], folder))
        if not items:
            parts.append("<p>Nenhum arquivo em %s.</p>" % folder)
            continue
        rows = []
        for rel, size in items:
            n += 1
            label = '<span id="arq-%d">%s</span>, %s' % (n, esc(rel), assets.size_text(size))
            preview = ""
            if folder == "sounds" and rel.lower().endswith((".wav", ".ogg")):
                preview = (' <audio controls preload="none" aria-labelledby="arq-%d" '
                           'src="/file?name=%s"></audio>' % (n, quote(rel)))
            elif folder == "images":
                preview = ' <img alt="" loading="lazy" src="/file?name=%s">' % quote(rel)
            remove = form("/remove", token, '<input type="hidden" name="file" value="%s">'
                          % esc(rel), label="Apagar %s" % rel, cls="secundario")
            rows.append("<li>%s%s%s</li>" % (label, preview, remove))
        parts.append("<ul class=\"arquivos\">%s</ul>" % "".join(rows))
    return "".join(parts)


def remove_page(token, rel):
    return ("<h1>Apagar %s?</h1><p>O arquivo sai da pasta do jogo e não vai para a "
            "lixeira.</p>" % esc(rel)
            + form("/remove", token, '<input type="hidden" name="file" value="%s">'
                   '<input type="hidden" name="confirm" value="1">' % esc(rel),
                   label="Apagar")
            + '<p><a href="/project#arquivos">Cancelar</a></p>')


def settings_page(token, config):
    return ('<h1>Preferências</h1>'
            + form("/settings", token,
                   field("code_editor", "Editor de código", config.get("code_editor", ""),
                         "O comando que abre uma pasta no seu editor, como code, notepad++ ou "
                         "o caminho do programa. Vazio usa o VS Code, se estiver instalado."),
                   label="Salvar preferências")
            + '<p><a href="/project">Voltar ao jogo</a> · <a href="/">Início</a></p>')


# --- servidor -----------------------------------------------------------------
class Editor:
    """O estado do editor: o projeto aberto, o aviso da próxima página e o token."""

    def __init__(self, path=None):
        self.token = secrets.token_urlsafe(16)
        self.path = None
        self.notice = None
        self.games = []
        if path:
            self.open(path)

    def open(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(os.path.join(path, "game.json")):
            raise project.ProjectError("não achei o game.json em %s" % path)
        self.path = path
        remember(path)

    def say(self, text, details=(), kind="ok"):
        self.notice = (kind, text, list(details))

    def take_notice(self):
        notice, self.notice = self.notice, None
        return notice


class Handler(BaseHTTPRequestHandler):
    editor = None   # Editor, definido em serve()
    port = 0

    def log_message(self, fmt, *args):
        pass

    # respostas
    def send_page(self, title, body, status=200):
        data = page(title, body, self.editor.take_notice()).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, where):
        self.send_response(303)
        self.send_header("Location", where)
        self.end_headers()

    def deny(self, status=403):
        self.send_response(status)
        self.end_headers()

    def local(self):
        """Só aceita pedidos para este endereço (protege de sites que fingem ser o editor)."""
        host = self.headers.get("Host", "")
        return host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port)

    # GET
    def do_GET(self):
        if not self.local():
            return self.deny()
        url = urlsplit(self.path)
        ed = self.editor
        if url.path == "/":
            return self.send_page("Início", home_page(ed.token, load_config().get("recent", [])))
        if url.path == "/settings":
            return self.send_page("Preferências", settings_page(ed.token, load_config()))
        if url.path == "/project":
            if not ed.path:
                return self.redirect("/")
            manifest, problems = project.check(ed.path)
            if not manifest:
                ed.say("Não deu para ler o projeto.", problems, "erro")
                ed.path = None
                return self.redirect("/")
            return self.send_page(manifest.get("name", "Jogo"), project_page(ed.token, ed.path, manifest))
        if url.path == "/file" and ed.path:
            full = assets.inside(ed.path, parse_qs(url.query).get("name", [""])[0])
            if not full:
                return self.deny(404)
            with open(full, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        return self.deny(404)

    # POST
    def do_POST(self):
        if not self.local():
            return self.deny()
        size = int(self.headers.get("Content-Length", "0") or 0)
        if size > assets.MAX_UPLOAD:
            self.close_connection = True
            self.editor.say("Os arquivos passam de %s; adicione menos de uma vez." %
                            assets.size_text(assets.MAX_UPLOAD), kind="erro")
            return self.redirect("/project#arquivos")
        raw = self.rfile.read(size)
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            data = parse_multipart(ctype, raw)
        else:
            data = {k: v[-1] for k, v in
                    parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()}
        if data.get("token") != self.editor.token:
            return self.deny()
        route = urlsplit(self.path).path
        handler = getattr(self, "post_" + route.strip("/"), None)
        if handler is None:
            return self.deny(404)
        try:
            return handler(data)
        except project.ProjectError as e:
            self.editor.say("Não deu.", str(e).splitlines(), "erro")
            return self.redirect("/project" if self.editor.path else "/")
        except Exception as e:  # o editor continua aberto e conta o que houve
            self.editor.say("Algo deu errado: %s" % e, kind="erro")
            return self.redirect("/project" if self.editor.path else "/")

    def post_new(self, data):
        folder = data.get("folder", "").strip()
        if not folder:
            raise project.ProjectError("diga a pasta do jogo novo")
        manifest = project.create(folder, name=data.get("name", "").strip() or None,
                                  author=data.get("author", "").strip() or None,
                                  log=lambda *_: None)
        self.editor.open(folder)
        self.editor.say("Jogo %s criado. Ele já roda e fala." % manifest["name"])
        return self.redirect("/project")

    def post_open(self, data):
        self.editor.open(data.get("folder", "").strip() or ".")
        return self.redirect("/project")

    def _manifest(self):
        if not self.editor.path:
            raise project.ProjectError("nenhum jogo aberto")
        manifest, problems = project.check(self.editor.path)
        if not manifest:
            raise project.ProjectError("\n".join(problems))
        return manifest

    def post_properties(self, data):
        manifest = self._manifest()
        for key in ("name", "description", "version", "author"):
            value = data.get(key, "").strip()
            if value or key in ("name", "version"):
                manifest[key] = value
            else:
                manifest.pop(key, None)
        for key in ("languages", "tags"):
            values = _split(data.get(key, ""))
            if values:
                manifest[key] = values
            else:
                manifest.pop(key, None)
        problems = project.manifest_problems(manifest, self.editor.path)
        if problems:
            self.editor.say("As propriedades não foram salvas.", problems, "erro")
            return self.redirect("/project#propriedades")
        project.save_manifest(self.editor.path, manifest)
        self.editor.say("Propriedades salvas.")
        return self.redirect("/project")

    def post_actions(self, data):
        manifest = self._manifest()
        actions, rows = actions_from_form(data)
        try:
            Actions().define(actions)
        except (ValueError, KeyError, TypeError) as e:
            # mostra de novo o que a pessoa escreveu, para ela corrigir
            self.editor.say("As ações não foram salvas.", [str(e)], "erro")
            return self.send_page(manifest.get("name", "Jogo"),
                                  project_page(self.editor.token, self.editor.path, manifest, rows))
        manifest["actions"] = actions
        project.save_manifest(self.editor.path, manifest)
        self.editor.say("Ações salvas: %d." % len(actions))
        return self.redirect("/project")

    def post_run(self, data):
        self._manifest()
        self.editor.games.append(project.start_game(self.editor.path, pc=True, log=lambda *_: None))
        self.editor.say("Abrindo o jogo numa janela.")
        return self.redirect("/project")

    def post_code(self, data):
        self._manifest()
        self.editor.say(open_code(self.editor.path, load_config().get("code_editor") or None))
        return self.redirect("/project")

    def post_folder(self, data):
        self._manifest()
        open_folder(self.editor.path)
        self.editor.say("Abrindo a pasta do jogo.")
        return self.redirect("/project")

    def post_check(self, data):
        manifest, problems, files = project.check_all(self.editor.path or ".")
        if problems:
            self.editor.say("O projeto tem problemas:", problems, "erro")
        else:
            self.editor.say("Tudo certo: %s %s, %d arquivos para exportar." % (
                manifest["name"], manifest["version"], len(files)))
        return self.redirect("/project")

    def post_export(self, data):
        self._manifest()
        to = data.get("to", "all")
        targets = list(export.TARGETS) if to == "all" else [to]
        if any(t not in export.TARGETS for t in targets):
            raise project.ProjectError("destino desconhecido: %s" % to)
        notes = []
        done = [export.TARGETS[t](self.editor.path, log=notes.append) for t in targets]
        sounds = sorted(set(n for n in notes if n.startswith(("Sons:", "Os WAV", "ficou em WAV"))))
        self.editor.say("Exportado. Os arquivos estão na pasta dist do jogo:",
                        [os.path.basename(p) for p in done] + sounds)
        return self.redirect("/project")

    def post_upload(self, data):
        self._manifest()
        uploads = [f for f in data.get("files", []) if f[0]]
        if not uploads:
            raise project.ProjectError("escolha pelo menos um arquivo")
        added = []
        for name, content in uploads:
            rel, replaced = assets.add(self.editor.path, name, content)
            added.append("%s%s" % (rel, " (substituído)" if replaced else ""))
        self.editor.say("Arquivos adicionados: %d." % len(added), added)
        return self.redirect("/project#arquivos")

    def post_remove(self, data):
        self._manifest()
        rel = data.get("file", "")
        if not assets.inside(self.editor.path, rel):
            raise project.ProjectError("%s não é um arquivo de sounds, images ou data" % rel)
        if data.get("confirm") != "1":
            return self.send_page("Apagar arquivo", remove_page(self.editor.token, rel))
        assets.remove(self.editor.path, rel)
        self.editor.say("%s apagado." % rel)
        return self.redirect("/project#arquivos")

    def post_settings(self, data):
        config = load_config()
        choice = data.get("code_editor", "").strip()
        if choice:
            config["code_editor"] = choice
        else:
            config.pop("code_editor", None)
        save_config(config)
        self.editor.say("Preferências salvas.")
        return self.redirect("/project" if self.editor.path else "/")


def parse_multipart(ctype, raw):
    """Os campos de um formulário multipart: texto como str, arquivos em
    data["files"] como [(nome, bytes)]."""
    msg = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + raw)
    data = {"files": []}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        content = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            # o navegador manda o nome em UTF-8 cru; o parser guarda os bytes como substitutos
            filename = filename.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
            data["files"].append((filename, content))
        elif name:
            data[name] = content.decode("utf-8", "replace")
    return data


def make_server(path=None, port=0):
    """O servidor do editor em 127.0.0.1 (porta livre com port=0), sem iniciar."""
    editor = Editor(path)
    handler = type("EditorHandler", (Handler,), {"editor": editor})
    server = HTTPServer(("127.0.0.1", port), handler)
    handler.port = server.server_address[1]
    return server, editor


def serve(path=None, port=0, browser=True):
    server, editor = make_server(path, port)
    url = "http://127.0.0.1:%d/%s" % (server.server_address[1], "project" if editor.path else "")
    print("Editor do Mage em %s (Ctrl+C para fechar)" % url)
    if browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
