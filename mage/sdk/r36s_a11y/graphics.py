"""Gráficos 2D opcionais: formas, sprites e texto, pela SDL2 do sistema.

No console, a tela é aberta só se o jogo registrar @game.on_draw; no PC há
sempre uma janela. A área de desenho é sempre 640x480 (escalada para a tela
real ou para o tamanho da janela); (0, 0) é o canto superior
esquerdo. Cores são tuplas (r, g, b) ou (r, g, b, a) de 0 a 255, ou "#rrggbb".

Os gráficos são um extra: o jogo continua tendo de ser jogável só pelo som.
"""
import ctypes
import math
import os

from . import native

WIDTH, HEIGHT = 640, 480
# Fonte padrão: a DejaVu Sans do console; no PC, a primeira que existir.
DEFAULT_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
DEFAULT_FONT = next((f for f in DEFAULT_FONTS if os.path.exists(f)), DEFAULT_FONTS[0])

SDL_INIT_VIDEO = 0x20
SDL_WINDOW_SHOWN = 0x4
SDL_WINDOW_RESIZABLE = 0x20
SDL_WINDOW_ALLOW_HIGHDPI = 0x2000
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x1001
SDL_RENDERER_ACCELERATED = 0x2
SDL_BLENDMODE_BLEND = 0x1
SDL_FLIP_HORIZONTAL, SDL_FLIP_VERTICAL = 0x1, 0x2
IMG_INIT_PNG = 0x2


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int)]


class _Color(ctypes.Structure):
    _fields_ = [("r", ctypes.c_uint8), ("g", ctypes.c_uint8), ("b", ctypes.c_uint8), ("a", ctypes.c_uint8)]


class _FPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float)]


class _Vertex(ctypes.Structure):
    _fields_ = [("position", _FPoint), ("color", _Color), ("tex_coord", _FPoint)]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int)]


# Pedidos à SDL no PC, antes de abrir a janela.
DESKTOP_HINTS = [
    (b"SDL_WINDOWS_DPI_AWARENESS", b"permonitorv2"),       # nítido com escala de 150%
    (b"SDL_GAMECONTROLLER_USE_BUTTON_LABELS", b"0"),       # botões pelo lugar, também na Nintendo
    (b"SDL_RENDER_SCALE_QUALITY", b"1"),                   # ampliação suave do quadro 640x480
]


def _load(names):
    return native.load(names, mode=ctypes.RTLD_GLOBAL)


def _optional(names):
    try:
        return _load(names)
    except OSError:
        return None


def _triangulate(points):
    """Divide um polígono simples (convexo ou não) em triângulos (orelhas)."""
    pts = list(points)
    if len(pts) < 3:
        return []
    area = sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))
    idx = list(range(len(pts))) if area < 0 else list(range(len(pts)))[::-1]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for i in range(len(idx)):
            a, b, c = pts[idx[i - 1]], pts[idx[i]], pts[idx[(i + 1) % len(idx)]]
            if cross(a, b, c) <= 0:
                continue
            if any(inside(pts[j], a, b, c) for j in idx if pts[j] not in (a, b, c)):
                continue
            tris.append((a, b, c))
            del idx[i]
            break
        else:
            break  # polígono estranho (se cruza): desenha o que deu
    if len(idx) == 3:
        tris.append(tuple(pts[i] for i in idx))
    return tris


def _color(c):
    if isinstance(c, str):
        c = c.lstrip("#")
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16) if len(c) >= 8 else 255)
    if len(c) == 3:
        return (int(c[0]), int(c[1]), int(c[2]), 255)
    return tuple(int(v) for v in c[:4])


def _signatures(sdl, img, ttf, gfx):
    vp, ci, cd, u8 = ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_uint8
    rp = ctypes.POINTER(_Rect)
    for name, res, args in [
        ("SDL_Init", ci, [ctypes.c_uint32]),
        ("SDL_CreateWindow", vp, [ctypes.c_char_p, ci, ci, ci, ci, ctypes.c_uint32]),
        ("SDL_CreateRenderer", vp, [vp, ci, ctypes.c_uint32]),
        ("SDL_RenderSetLogicalSize", ci, [vp, ci, ci]),
        ("SDL_SetRenderDrawBlendMode", ci, [vp, ci]),
        ("SDL_SetRenderDrawColor", ci, [vp, u8, u8, u8, u8]),
        ("SDL_RenderClear", ci, [vp]),
        ("SDL_RenderFillRect", ci, [vp, rp]),
        ("SDL_RenderDrawRect", ci, [vp, rp]),
        ("SDL_RenderPresent", None, [vp]),
        ("SDL_PumpEvents", None, []),
        ("SDL_ShowCursor", ci, [ci]),
        ("SDL_CreateTextureFromSurface", vp, [vp, vp]),
        ("SDL_FreeSurface", None, [vp]),
        ("SDL_QueryTexture", ci, [vp, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ci),
                                  ctypes.POINTER(ci), ctypes.POINTER(ci)]),
        ("SDL_RenderCopyEx", ci, [vp, vp, rp, rp, cd, vp, ci]),
        ("SDL_SetTextureAlphaMod", ci, [vp, u8]),
        ("SDL_SetTextureColorMod", ci, [vp, u8, u8, u8]),
        ("SDL_SetTextureBlendMode", ci, [vp, ci]),
        ("SDL_DestroyTexture", None, [vp]),
        ("SDL_DestroyRenderer", None, [vp]),
        ("SDL_DestroyWindow", None, [vp]),
        ("SDL_QuitSubSystem", None, [ctypes.c_uint32]),
        ("SDL_GetError", ctypes.c_char_p, []),
        ("SDL_CreateRGBSurfaceWithFormat", vp, [ctypes.c_uint32, ci, ci, ci, ctypes.c_uint32]),
        ("SDL_RenderReadPixels", ci, [vp, rp, ctypes.c_uint32, vp, ci]),
        ("SDL_GetRendererOutputSize", ci, [vp, ctypes.POINTER(ci), ctypes.POINTER(ci)]),
        ("SDL_SetHint", ci, [ctypes.c_char_p, ctypes.c_char_p]),
        ("SDL_SetWindowFullscreen", ci, [vp, ctypes.c_uint32]),
        ("SDL_GetWindowFlags", ctypes.c_uint32, [vp]),
        ("SDL_SetWindowTitle", None, [vp, ctypes.c_char_p]),
        ("SDL_RenderDrawLine", ci, [vp, ci, ci, ci, ci]),
        ("SDL_RenderDrawLines", ci, [vp, ctypes.POINTER(_Point), ci]),
        ("SDL_RenderDrawPoint", ci, [vp, ci, ci]),
        ("SDL_GetDisplayUsableBounds", ci, [ci, rp]),
    ]:
        f = getattr(sdl, name)
        f.restype, f.argtypes = res, args
    geometry = getattr(sdl, "SDL_RenderGeometry", None)  # SDL 2.0.18+
    if geometry is not None:
        geometry.restype = ci
        geometry.argtypes = [vp, vp, ctypes.POINTER(_Vertex), ci, ctypes.POINTER(ci), ci]
    if img is not None:
        _img_signatures(img)
    if ttf is not None:
        _ttf_signatures(ttf)
    if gfx is not None:
        _gfx_signatures(gfx)


def _img_signatures(img):
    vp, ci = ctypes.c_void_p, ctypes.c_int
    img.IMG_Init.restype, img.IMG_Init.argtypes = ci, [ci]
    img.IMG_Load.restype, img.IMG_Load.argtypes = vp, [ctypes.c_char_p]
    img.IMG_SavePNG.restype, img.IMG_SavePNG.argtypes = ci, [vp, ctypes.c_char_p]


def _ttf_signatures(ttf):
    vp, ci = ctypes.c_void_p, ctypes.c_int
    ttf.TTF_Init.restype, ttf.TTF_Init.argtypes = ci, []
    ttf.TTF_OpenFont.restype, ttf.TTF_OpenFont.argtypes = vp, [ctypes.c_char_p, ci]
    ttf.TTF_CloseFont.restype, ttf.TTF_CloseFont.argtypes = None, [vp]
    ttf.TTF_RenderUTF8_Blended.restype = vp
    ttf.TTF_RenderUTF8_Blended.argtypes = [vp, ctypes.c_char_p, _Color]
    ttf.TTF_SizeUTF8.restype = ci
    ttf.TTF_SizeUTF8.argtypes = [vp, ctypes.c_char_p, ctypes.POINTER(ci), ctypes.POINTER(ci)]


def _gfx_signatures(gfx):
    vp, ci, u8, i16 = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8, ctypes.c_int16
    gfx.filledCircleRGBA.argtypes = [vp, i16, i16, i16, u8, u8, u8, u8]
    gfx.aacircleRGBA.argtypes = [vp, i16, i16, i16, u8, u8, u8, u8]
    gfx.thickLineRGBA.argtypes = [vp, i16, i16, i16, i16, u8, u8, u8, u8, u8]
    gfx.aalineRGBA.argtypes = [vp, i16, i16, i16, i16, u8, u8, u8, u8]
    gfx.filledPolygonRGBA.argtypes = [vp, ctypes.POINTER(i16), ctypes.POINTER(i16), ci, u8, u8, u8, u8]
    gfx.aapolygonRGBA.argtypes = [vp, ctypes.POINTER(i16), ctypes.POINTER(i16), ci, u8, u8, u8, u8]
    gfx.pixelRGBA.argtypes = [vp, i16, i16, u8, u8, u8, u8]


class Image:
    """Uma imagem (textura). Desenhe com Graphics.draw."""

    def __init__(self, texture, width, height):
        self.texture = texture
        self.width = width
        self.height = height


class Font:
    """Uma fonte TTF num tamanho."""

    def __init__(self, handle, size):
        self.handle = handle
        self.size = size


class Graphics:
    def __init__(self, title="Jogo", base_dir="."):
        self.title = title
        self.base_dir = base_dir
        self.available = False
        self.desktop = False
        self.window = self.renderer = None
        self.img = self.ttf = self.gfx = None
        self._color = (255, 255, 255, 255)
        self._text_cache = {}   # (fonte, texto, cor) -> [Image, quadros sem uso]
        self._default_font = None

    def open(self, desktop=False):
        """Abre a tela. No console, em tela cheia; no PC (desktop=True), numa
        janela redimensionável, com o quadro 640x480 escalado e tarjas.

        Só a SDL2 é obrigatória. Sem SDL2_image não há imagens, sem SDL2_ttf
        não há texto, e sem SDL2_gfx as formas são desenhadas pela própria SDL.
        """
        try:
            self.sdl = _load(["libSDL2-2.0.so.0", "SDL2", "SDL2.dll"])
        except OSError as exc:
            print("[r36s_a11y] sem gráficos: %s" % exc)
            return False
        self.img = _optional(["libSDL2_image-2.0.so.0", "SDL2_image", "SDL2_image.dll"])
        self.ttf = _optional(["libSDL2_ttf-2.0.so.0", "SDL2_ttf", "SDL2_ttf.dll"])
        self.gfx = _optional(["libSDL2_gfx-1.0.so.0", "SDL2_gfx", "SDL2_gfx.dll"])
        missing = [n for n, lib in (("SDL2_image", self.img), ("SDL2_ttf", self.ttf)) if lib is None]
        if missing:
            print("[r36s_a11y] gráficos sem %s" % " e ".join(missing))
        _signatures(self.sdl, self.img, self.ttf, self.gfx)
        sdl = self.sdl
        self.desktop = desktop
        if desktop:
            for name, value in DESKTOP_HINTS:
                sdl.SDL_SetHint(name, value)
        if sdl.SDL_Init(SDL_INIT_VIDEO) != 0:
            print("[r36s_a11y] sem gráficos: %s" % sdl.SDL_GetError().decode())
            return False
        if desktop:
            flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI
            scale = self._window_scale()
        else:
            on_console = os.path.exists("/opt/a11y")
            flags = SDL_WINDOW_FULLSCREEN_DESKTOP if on_console else SDL_WINDOW_SHOWN
            scale = 1
        self.window = sdl.SDL_CreateWindow(self.title.encode("utf-8"), 0x2FFF0000, 0x2FFF0000,
                                           WIDTH * scale, HEIGHT * scale, flags)
        if not self.window:
            print("[r36s_a11y] sem gráficos: %s" % sdl.SDL_GetError().decode())
            return False
        self.renderer = sdl.SDL_CreateRenderer(self.window, -1, SDL_RENDERER_ACCELERATED)
        if not self.renderer:  # sem GPU (testes): renderizador por software
            self.renderer = sdl.SDL_CreateRenderer(self.window, -1, 0)
        if not self.renderer:
            print("[r36s_a11y] sem gráficos: %s" % sdl.SDL_GetError().decode())
            return False
        sdl.SDL_RenderSetLogicalSize(self.renderer, WIDTH, HEIGHT)
        sdl.SDL_SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_BLEND)
        sdl.SDL_ShowCursor(1 if desktop else 0)
        if self.img is not None:
            self.img.IMG_Init(IMG_INIT_PNG)
        if self.ttf is not None:
            self.ttf.TTF_Init()
        self.available = True
        return True

    def _window_scale(self):
        """Maior escala inteira de 640x480 que cabe com folga na tela."""
        bounds = _Rect()
        if self.sdl.SDL_GetDisplayUsableBounds(0, ctypes.byref(bounds)) != 0:
            return 1
        scale = int(min(bounds.w * 0.9 / WIDTH, bounds.h * 0.9 / HEIGHT))
        return max(1, min(scale, 4))

    def set_title(self, title):
        """Título da janela no PC (o leitor de tela fala ao trocar de janela)."""
        self.title = title
        if self.available:
            self.sdl.SDL_SetWindowTitle(self.window, title.encode("utf-8"))

    @property
    def fullscreen(self):
        if not self.available:
            return False
        return bool(self.sdl.SDL_GetWindowFlags(self.window) & SDL_WINDOW_FULLSCREEN_DESKTOP)

    def toggle_fullscreen(self, on=None):
        """Tela cheia no PC (F11 ou Alt + Enter); on=None alterna."""
        if not self.available:
            return
        on = not self.fullscreen if on is None else on
        self.sdl.SDL_SetWindowFullscreen(self.window, SDL_WINDOW_FULLSCREEN_DESKTOP if on else 0)

    # --- quadro ----------------------------------------------------------
    def begin(self):
        self.sdl.SDL_PumpEvents()  # a SDL precisa disso para manter a tela viva
        self.clear((0, 0, 0))
        self._color = (255, 255, 255, 255)

    def end(self):
        self.sdl.SDL_RenderPresent(self.renderer)
        # textos que não foram desenhados por 60 quadros saem do cache
        for key, entry in list(self._text_cache.items()):
            entry[1] += 1
            if entry[1] > 60:
                self.sdl.SDL_DestroyTexture(entry[0].texture)
                del self._text_cache[key]

    # --- cor e formas --------------------------------------------------
    def set_color(self, color):
        """Cor padrão dos próximos desenhos."""
        self._color = _color(color)

    def _c(self, color):
        return self._color if color is None else _color(color)

    def clear(self, color=(0, 0, 0)):
        """Pinta a tela inteira."""
        r, g, b, a = _color(color)
        self.sdl.SDL_SetRenderDrawColor(self.renderer, r, g, b, a)
        self.sdl.SDL_RenderClear(self.renderer)

    def rect(self, x, y, w, h, color=None, fill=True):
        r, g, b, a = self._c(color)
        self.sdl.SDL_SetRenderDrawColor(self.renderer, r, g, b, a)
        rect = _Rect(int(x), int(y), int(w), int(h))
        if fill:
            self.sdl.SDL_RenderFillRect(self.renderer, ctypes.byref(rect))
        else:
            self.sdl.SDL_RenderDrawRect(self.renderer, ctypes.byref(rect))

    def line(self, x1, y1, x2, y2, color=None, width=1):
        r, g, b, a = self._c(color)
        if self.gfx is None:
            self._line(x1, y1, x2, y2, (r, g, b, a), width)
        elif width <= 1:
            self.gfx.aalineRGBA(self.renderer, int(x1), int(y1), int(x2), int(y2), r, g, b, a)
        else:
            self.gfx.thickLineRGBA(self.renderer, int(x1), int(y1), int(x2), int(y2), int(width), r, g, b, a)

    def circle(self, x, y, radius, color=None, fill=True):
        r, g, b, a = self._c(color)
        if self.gfx is None:
            n = max(12, int(radius * 1.5))
            pts = [(x + radius * math.cos(2 * math.pi * i / n), y + radius * math.sin(2 * math.pi * i / n))
                   for i in range(n)]
            self._shape(pts, (r, g, b, a), fill)
            return
        f = self.gfx.filledCircleRGBA if fill else self.gfx.aacircleRGBA
        f(self.renderer, int(x), int(y), int(radius), r, g, b, a)

    def polygon(self, points, color=None, fill=True):
        """points: [(x, y), ...] com 3 ou mais pontos."""
        r, g, b, a = self._c(color)
        if self.gfx is None:
            self._shape(points, (r, g, b, a), fill)
            return
        n = len(points)
        vx = (ctypes.c_int16 * n)(*[int(p[0]) for p in points])
        vy = (ctypes.c_int16 * n)(*[int(p[1]) for p in points])
        f = self.gfx.filledPolygonRGBA if fill else self.gfx.aapolygonRGBA
        f(self.renderer, vx, vy, n, r, g, b, a)

    def point(self, x, y, color=None):
        r, g, b, a = self._c(color)
        if self.gfx is None:
            self.sdl.SDL_SetRenderDrawColor(self.renderer, r, g, b, a)
            self.sdl.SDL_RenderDrawPoint(self.renderer, int(x), int(y))
            return
        self.gfx.pixelRGBA(self.renderer, int(x), int(y), r, g, b, a)

    # Formas sem a SDL2_gfx (no Windows ela não tem DLL oficial).
    def _line(self, x1, y1, x2, y2, c, width):
        if width <= 1:
            self.sdl.SDL_SetRenderDrawColor(self.renderer, *c)
            self.sdl.SDL_RenderDrawLine(self.renderer, int(x1), int(y1), int(x2), int(y2))
            return
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        ox, oy = -dy / length * width / 2.0, dx / length * width / 2.0
        self._shape([(x1 + ox, y1 + oy), (x2 + ox, y2 + oy), (x2 - ox, y2 - oy), (x1 - ox, y1 - oy)],
                    c, True)

    def _shape(self, points, c, fill):
        if not fill or getattr(self.sdl, "SDL_RenderGeometry", None) is None:
            pts = [_Point(int(round(p[0])), int(round(p[1]))) for p in points]
            pts.append(pts[0])
            self.sdl.SDL_SetRenderDrawColor(self.renderer, *c)
            self.sdl.SDL_RenderDrawLines(self.renderer, (_Point * len(pts))(*pts), len(pts))
            return
        tris = _triangulate([(float(p[0]), float(p[1])) for p in points])
        if not tris:
            return
        color = _Color(*c)
        verts = (_Vertex * (3 * len(tris)))()
        for i, tri in enumerate(tris):
            for j, (px, py) in enumerate(tri):
                verts[3 * i + j] = _Vertex(_FPoint(px, py), color, _FPoint(0, 0))
        self.sdl.SDL_RenderGeometry(self.renderer, None, verts, len(verts), None, 0)

    def _path(self, path):
        return path if os.path.isabs(path) else os.path.join(self.base_dir, path)

    def screenshot(self, path):
        """Salva o quadro atual em PNG (chame no fim de on_draw). Útil para testar."""
        if not self.available or self.img is None:
            return
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        self.sdl.SDL_GetRendererOutputSize(self.renderer, ctypes.byref(w), ctypes.byref(h))
        fmt = 0x16762004  # SDL_PIXELFORMAT_ARGB8888
        surface = self.sdl.SDL_CreateRGBSurfaceWithFormat(0, w.value, h.value, 32, fmt)
        pixels = ctypes.cast(surface + 32, ctypes.POINTER(ctypes.c_void_p))[0]  # SDL_Surface.pixels
        pitch = ctypes.cast(surface + 24, ctypes.POINTER(ctypes.c_int))[0]       # SDL_Surface.pitch
        self.sdl.SDL_RenderReadPixels(self.renderer, None, fmt, pixels, pitch)
        self.img.IMG_SavePNG(surface, self._path(path).encode())
        self.sdl.SDL_FreeSurface(surface)

    # --- imagens --------------------------------------------------------
    def image(self, path):
        """Carrega um PNG (ou outro formato da SDL2_image), relativo à pasta do jogo."""
        if not self.available or self.img is None:
            return Image(None, 0, 0)
        surface = self.img.IMG_Load(self._path(path).encode())
        if not surface:
            raise IOError("%s: %s" % (path, self.sdl.SDL_GetError().decode()))
        texture = self.sdl.SDL_CreateTextureFromSurface(self.renderer, surface)
        self.sdl.SDL_FreeSurface(surface)
        return self._wrap(texture)

    def _wrap(self, texture):
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        self.sdl.SDL_QueryTexture(texture, None, None, ctypes.byref(w), ctypes.byref(h))
        self.sdl.SDL_SetTextureBlendMode(texture, SDL_BLENDMODE_BLEND)
        return Image(texture, w.value, h.value)

    def draw(self, image, x, y, src=None, scale=1.0, rotation=0.0,
             flip_x=False, flip_y=False, alpha=255, tint=None):
        """Desenha uma imagem com o canto superior esquerdo em (x, y).

        src=(x, y, w, h) recorta um quadro de uma folha de sprites. rotation em
        graus, em torno do centro. tint=(r, g, b) multiplica as cores.
        """
        if not self.available or image.texture is None:
            return
        sx, sy, sw, sh = src if src else (0, 0, image.width, image.height)
        srect = _Rect(int(sx), int(sy), int(sw), int(sh))
        drect = _Rect(int(x), int(y), int(sw * scale), int(sh * scale))
        tr, tg, tb = _color(tint)[:3] if tint else (255, 255, 255)
        self.sdl.SDL_SetTextureColorMod(image.texture, tr, tg, tb)
        self.sdl.SDL_SetTextureAlphaMod(image.texture, int(alpha))
        flip = (SDL_FLIP_HORIZONTAL if flip_x else 0) | (SDL_FLIP_VERTICAL if flip_y else 0)
        self.sdl.SDL_RenderCopyEx(self.renderer, image.texture, ctypes.byref(srect),
                                  ctypes.byref(drect), float(rotation), None, flip)

    # --- texto ----------------------------------------------------------
    def font(self, path=None, size=24):
        """Carrega uma fonte TTF; sem path, usa a DejaVu Sans do sistema."""
        if not self.available or self.ttf is None:
            return Font(None, size)
        handle = self.ttf.TTF_OpenFont(self._path(path or DEFAULT_FONT).encode(), int(size))
        if not handle:
            raise IOError("%s: %s" % (path or DEFAULT_FONT, self.sdl.SDL_GetError().decode()))
        return Font(handle, size)

    def _font(self, font):
        if font is not None:
            return font
        if self._default_font is None:
            self._default_font = self.font()
        return self._default_font

    def measure(self, text, font=None):
        """Tamanho (largura, altura) do texto em pixels."""
        font = self._font(font)
        if font.handle is None or not text:
            return (0, 0)
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        self.ttf.TTF_SizeUTF8(font.handle, text.encode("utf-8"), ctypes.byref(w), ctypes.byref(h))
        return (w.value, h.value)

    def text(self, text, x, y, font=None, color=None, align="left"):
        """Escreve o texto com o topo em y; align: "left", "center" ou "right"."""
        font = self._font(font)
        if not self.available or font.handle is None or not text:
            return
        c = self._c(color)
        key = (id(font), text, c)
        entry = self._text_cache.get(key)
        if entry is None:
            surface = self.ttf.TTF_RenderUTF8_Blended(font.handle, text.encode("utf-8"), _Color(*c))
            if not surface:
                return
            texture = self.sdl.SDL_CreateTextureFromSurface(self.renderer, surface)
            self.sdl.SDL_FreeSurface(surface)
            entry = self._text_cache[key] = [self._wrap(texture), 0]
        entry[1] = 0
        image = entry[0]
        if align == "center":
            x -= image.width / 2
        elif align == "right":
            x -= image.width
        self.draw(image, x, y)

    def close(self):
        if not self.available:
            return
        for image, _ in self._text_cache.values():
            self.sdl.SDL_DestroyTexture(image.texture)
        self._text_cache.clear()
        self.sdl.SDL_DestroyRenderer(self.renderer)
        self.sdl.SDL_DestroyWindow(self.window)
        self.sdl.SDL_QuitSubSystem(SDL_INIT_VIDEO)
        self.available = False
