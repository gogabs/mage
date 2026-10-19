"""Áudio 3D com OpenAL Soft, carregada em tempo de execução via ctypes.

Coordenadas da OpenAL (em metros):
  x positivo = direita, y positivo = cima, z negativo = frente.

Só sons mono são posicionados; sons estéreo tocam sempre no centro.
Arquivos: WAV (PCM 8/16 bits) e OGG Vorbis (pela libvorbisfile do sistema ou,
no Windows, pela libsndfile).
"""
import ctypes
import math
import os
import wave

from . import native

# --- constantes da OpenAL ------------------------------------------------
AL_SOURCE_RELATIVE = 0x202
AL_PITCH = 0x1003
AL_POSITION = 0x1004
AL_LOOPING = 0x1007
AL_BUFFER = 0x1009
AL_GAIN = 0x100A
AL_ORIENTATION = 0x100F
AL_SOURCE_STATE = 0x1010
AL_PLAYING = 0x1012
AL_PAUSED = 0x1013
AL_REFERENCE_DISTANCE = 0x1020
AL_ROLLOFF_FACTOR = 0x1021
AL_MAX_DISTANCE = 0x1023
AL_FORMAT_MONO8 = 0x1100
AL_FORMAT_MONO16 = 0x1101
AL_FORMAT_STEREO8 = 0x1102
AL_FORMAT_STEREO16 = 0x1103
AL_DISTANCE_MODEL = 0xD000
AL_INVERSE_DISTANCE_CLAMPED = 0xD002
ALC_HRTF_SOFT = 0x1992

# EFX (reverberação)
AL_EFFECT_TYPE = 0x8001
AL_EFFECT_REVERB = 0x0001
AL_EFFECTSLOT_EFFECT = 0x0001
AL_AUXILIARY_SEND_FILTER = 0x20006
AL_FILTER_NULL = 0
REVERB_PARAMS = {   # nome -> parâmetro AL_REVERB_*
    "density": 0x0001, "diffusion": 0x0002, "gain": 0x0003, "gain_hf": 0x0004,
    "decay": 0x0005, "decay_hf_ratio": 0x0006, "reflections_gain": 0x0007,
    "reflections_delay": 0x0008, "late_gain": 0x0009, "late_delay": 0x000A,
}

# Ambientes prontos (baseados nos presets EFX da Creative).
REVERB_PRESETS = {
    "quarto": dict(density=0.43, diffusion=1.0, gain=0.32, gain_hf=0.6, decay=0.4,
                   decay_hf_ratio=0.83, reflections_gain=0.15, reflections_delay=0.002,
                   late_gain=1.06, late_delay=0.003),
    "corredor": dict(density=1.0, diffusion=1.0, gain=0.32, gain_hf=0.71, decay=1.49,
                     decay_hf_ratio=0.59, reflections_gain=0.25, reflections_delay=0.007,
                     late_gain=1.66, late_delay=0.011),
    "estacionamento": dict(density=1.0, diffusion=1.0, gain=0.32, gain_hf=1.0, decay=1.65,
                           decay_hf_ratio=1.5, reflections_gain=0.21, reflections_delay=0.008,
                           late_gain=0.27, late_delay=0.012),
    "cozinha": dict(density=1.0, diffusion=0.9, gain=0.32, gain_hf=0.9, decay=1.0,
                    decay_hf_ratio=1.2, reflections_gain=0.5, reflections_delay=0.004,
                    late_gain=1.2, late_delay=0.006),
    "metro": dict(density=1.0, diffusion=1.0, gain=0.32, gain_hf=0.71, decay=3.1,
                  decay_hf_ratio=1.0, reflections_gain=0.15, reflections_delay=0.03,
                  late_gain=1.4, late_delay=0.03),
    "igreja": dict(density=1.0, diffusion=1.0, gain=0.32, gain_hf=0.6, decay=5.5,
                   decay_hf_ratio=0.6, reflections_gain=0.2, reflections_delay=0.04,
                   late_gain=1.3, late_delay=0.05),
    "floresta": dict(density=1.0, diffusion=0.3, gain=0.32, gain_hf=0.02, decay=1.49,
                     decay_hf_ratio=0.54, reflections_gain=0.05, reflections_delay=0.16,
                     late_gain=0.2, late_delay=0.09),
}

FORMATS = {
    (1, 1): AL_FORMAT_MONO8, (1, 2): AL_FORMAT_MONO16,
    (2, 1): AL_FORMAT_STEREO8, (2, 2): AL_FORMAT_STEREO16,
}

MAX_SOURCES = 32


def _load(names):
    return native.load(names)


class _VorbisInfo(ctypes.Structure):
    _fields_ = [("version", ctypes.c_int), ("channels", ctypes.c_int),
                ("rate", ctypes.c_long)]


def decode_wav(path):
    with wave.open(path, "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())
    if (channels, width) not in FORMATS:
        raise ValueError("%s: WAV precisa ser PCM 8 ou 16 bits, mono ou estéreo" % path)
    return channels, width, rate, data


SOUND_EXTENSIONS = (".ogg", ".wav")


def sound_file(path):
    """O arquivo de som em path ou, se ele não existir, o de mesmo nome com a
    outra extensão (.ogg ou .wav). Assim o código pode pedir "sounds/bip.wav"
    e achar o "sounds/bip.ogg" que a exportação comprimiu, ou pedir só
    "sounds/bip"."""
    if os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    if ext.lower() not in SOUND_EXTENSIONS:
        root = path
    for alt in SOUND_EXTENSIONS:
        if os.path.exists(root + alt):
            return root + alt
    return path


_vorbis = None


def decode_ogg(path):
    """OGG Vorbis pela libvorbisfile ou, sem ela (no Windows), pela libsndfile."""
    try:
        _vorbisfile()
    except OSError:
        from . import sndfile
        return sndfile.decode(path)
    return _decode_vorbis(path)


def _vorbisfile():
    global _vorbis
    if _vorbis is None:
        lib = _load(["libvorbisfile.so.3", "vorbisfile", "libvorbisfile.dll", "libvorbisfile-3.dll"])
        lib.ov_fopen.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        lib.ov_info.restype = ctypes.POINTER(_VorbisInfo)
        lib.ov_info.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.ov_read.restype = ctypes.c_long
        lib.ov_read.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_int)]
        lib.ov_clear.argtypes = [ctypes.c_void_p]
        _vorbis = lib
    return _vorbis


def _decode_vorbis(path):
    vf = ctypes.create_string_buffer(8192)  # maior que OggVorbis_File em qualquer arquitetura
    if _vorbis.ov_fopen(path.encode(), vf) != 0:
        raise ValueError("%s: não é um OGG Vorbis válido" % path)
    try:
        info = _vorbis.ov_info(vf, -1).contents
        channels, rate = info.channels, info.rate
        chunk = ctypes.create_string_buffer(65536)
        section = ctypes.c_int(0)
        parts = []
        while True:
            n = _vorbis.ov_read(vf, chunk, len(chunk), 0, 2, 1, ctypes.byref(section))
            if n <= 0:
                break
            parts.append(chunk.raw[:n])
    finally:
        _vorbis.ov_clear(vf)
    if channels not in (1, 2):
        raise ValueError("%s: só mono ou estéreo" % path)
    return channels, 2, rate, b"".join(parts)


class Sound:
    """Um som carregado (buffer da OpenAL). Toque com play()."""

    def __init__(self, audio, name, buffer_id, channels):
        self.audio = audio
        self.name = name
        self.buffer_id = buffer_id
        self.channels = channels

    def play(self, loop=False, volume=1.0, pitch=1.0, pos=None, pan=None, reverb=None):
        """Toca o som e devolve a Voice que está tocando.

        pos=(x, y, z) posiciona em 3D; pan de -1 (esquerda) a 1 (direita) é um
        atalho para posição a 1 m do ouvinte. Sem pos nem pan, toca no centro.
        reverb: passa pelo ambiente (Audio.set_reverb); padrão é só com pos.
        """
        if reverb is None:
            reverb = pos is not None
        return self.audio._play(self, loop, volume, pitch, pos, pan, reverb)


class Voice:
    """Um som tocando (fonte da OpenAL)."""

    def __init__(self, audio, source_id):
        self.audio = audio
        self.source_id = source_id
        self.fade = None   # (volume inicial, volume final, duração, decorrido, parar no fim)
        self.volume = 1.0

    @property
    def playing(self):
        if self.source_id is None:
            return False
        state = ctypes.c_int(0)
        self.audio.al.alGetSourcei(self.source_id, AL_SOURCE_STATE, ctypes.byref(state))
        return state.value in (AL_PLAYING, AL_PAUSED)

    def set_volume(self, volume, fade=0.0):
        if self.source_id is None:
            return
        if fade > 0:
            self.fade = (self.volume, volume, fade, 0.0, False)
        else:
            self.fade = None
            self._gain(volume)

    def _gain(self, volume):
        self.volume = volume
        self.audio.al.alSourcef(self.source_id, AL_GAIN, ctypes.c_float(volume))

    def set_pitch(self, pitch):
        if self.source_id is not None:
            self.audio.al.alSourcef(self.source_id, AL_PITCH, ctypes.c_float(pitch))

    def set_position(self, x, y, z):
        if self.source_id is not None:
            self.audio._place(self.source_id, (x, y, z), None)

    def set_pan(self, pan):
        if self.source_id is not None:
            self.audio._place(self.source_id, None, pan)

    def pause(self):
        if self.source_id is not None:
            self.audio.al.alSourcePause(self.source_id)

    def resume(self):
        """Retoma um som pausado (sons tocando ou parados não são afetados)."""
        if self.source_id is None:
            return
        state = ctypes.c_int(0)
        self.audio.al.alGetSourcei(self.source_id, AL_SOURCE_STATE, ctypes.byref(state))
        if state.value == AL_PAUSED:
            self.audio.al.alSourcePlay(self.source_id)

    def stop(self, fade=0.0):
        if self.source_id is None:
            return
        if fade > 0:
            self.fade = (self.volume, 0.0, fade, 0.0, True)
        else:
            self.audio.al.alSourceStop(self.source_id)


class _NullVoice(Voice):
    """Devolvida quando não há áudio; aceita tudo e não faz nada."""

    def __init__(self):
        Voice.__init__(self, None, None)


class Audio:
    def __init__(self, base_dir="."):
        self.base_dir = base_dir
        self.sounds = {}
        self.voices = {}      # source_id -> Voice
        self.free = []        # fontes livres
        self.available = False
        self.hrtf = False
        try:
            self._open()
            self.available = True
        except OSError:
            pass

    def _open(self):
        al = _load(["libopenal.so.1", "openal", "OpenAL32.dll", "soft_oal.dll"])
        al.alcOpenDevice.restype = ctypes.c_void_p
        al.alcOpenDevice.argtypes = [ctypes.c_char_p]
        al.alcCreateContext.restype = ctypes.c_void_p
        al.alcCreateContext.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        al.alcMakeContextCurrent.argtypes = [ctypes.c_void_p]
        al.alcIsExtensionPresent.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        al.alcGetIntegerv.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_int)]
        al.alcDestroyContext.argtypes = [ctypes.c_void_p]
        al.alcCloseDevice.argtypes = [ctypes.c_void_p]
        al.alBufferData.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_char_p,
                                    ctypes.c_int, ctypes.c_int]
        al.alSourcef.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_float]
        al.alSource3f.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_float,
                                  ctypes.c_float, ctypes.c_float]
        al.alSourcei.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        al.alListener3f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float,
                                    ctypes.c_float]
        al.alListenerfv.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
        self.al = al

        self.device = al.alcOpenDevice(None)   # dispositivo padrão = dmix do ALSA
        if not self.device:
            raise OSError("OpenAL não abriu o dispositivo padrão")
        attrs = None
        if al.alcIsExtensionPresent(self.device, b"ALC_SOFT_HRTF"):
            attrs = (ctypes.c_int * 3)(ALC_HRTF_SOFT, 1, 0)
        self.context = al.alcCreateContext(self.device, attrs)
        if not self.context:
            raise OSError("OpenAL não criou o contexto")
        al.alcMakeContextCurrent(self.context)
        if attrs is not None:
            status = ctypes.c_int(0)
            al.alcGetIntegerv(self.device, ALC_HRTF_SOFT, 1, ctypes.byref(status))
            self.hrtf = bool(status.value)
        al.alDistanceModel(AL_INVERSE_DISTANCE_CLAMPED)
        self.listener((0.0, 0.0, 0.0), 0.0)
        self.slot = None
        self.effect = None
        try:
            self._open_efx()
        except (AttributeError, OSError):
            self.slot = None   # sem EFX: tudo funciona, só sem reverberação

    def _open_efx(self):
        al = self.al
        if not al.alcIsExtensionPresent(self.device, b"ALC_EXT_EFX"):
            return
        al.alEffecti.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        al.alEffectf.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_float]
        al.alAuxiliaryEffectSloti.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        al.alSource3i.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int]
        slot, effect = ctypes.c_uint(0), ctypes.c_uint(0)
        al.alGenAuxiliaryEffectSlots(1, ctypes.byref(slot))
        al.alGenEffects(1, ctypes.byref(effect))
        al.alEffecti(effect.value, AL_EFFECT_TYPE, AL_EFFECT_REVERB)
        self.slot, self.effect = slot.value, effect.value
        self.reverb_on = False

    def set_reverb(self, preset=None, **params):
        """Muda o ambiente: um nome de REVERB_PRESETS, parâmetros soltos, ou None para desligar.

        Afeta os sons tocados com reverb (por padrão, os que têm pos).
        """
        if not self.available or self.slot is None:
            return
        al = self.al
        if preset is None and not params:
            al.alAuxiliaryEffectSloti(self.slot, AL_EFFECTSLOT_EFFECT, 0)
            self.reverb_on = False
            return
        values = dict(REVERB_PRESETS[preset]) if preset else {}
        values.update(params)
        for name, value in values.items():
            al.alEffectf(self.effect, REVERB_PARAMS[name], ctypes.c_float(value))
        # recarregar o efeito no slot aplica os parâmetros novos
        al.alAuxiliaryEffectSloti(self.slot, AL_EFFECTSLOT_EFFECT, self.effect)
        self.reverb_on = True

    # --- sons --------------------------------------------------------
    def load(self, name, path):
        """Carrega um WAV ou OGG (relativo à pasta do jogo) com um nome.

        Se o arquivo não existir, vale o de mesmo nome com a outra extensão."""
        full = sound_file(path if os.path.isabs(path) else os.path.join(self.base_dir, path))
        if not self.available:
            sound = Sound(self, name, None, 1)
            self.sounds[name] = sound
            return sound
        if full.lower().endswith(".ogg"):
            channels, width, rate, data = decode_ogg(full)
        else:
            channels, width, rate, data = decode_wav(full)
        buf = ctypes.c_uint(0)
        self.al.alGenBuffers(1, ctypes.byref(buf))
        self.al.alBufferData(buf.value, FORMATS[(channels, width)], data, len(data), rate)
        sound = Sound(self, name, buf.value, channels)
        self.sounds[name] = sound
        return sound

    def __getitem__(self, name):
        return self.sounds[name]

    def _source(self):
        if self.free:
            return self.free.pop()
        if len(self.voices) < MAX_SOURCES:
            src = ctypes.c_uint(0)
            self.al.alGenSources(1, ctypes.byref(src))
            return src.value
        # sem fonte livre: reaproveita a primeira que já terminou, senão a mais antiga
        finished = [s for s, v in self.voices.items() if not v.playing]
        sid = finished[0] if finished else next(iter(self.voices))
        self.al.alSourceStop(sid)
        old = self.voices.pop(sid)
        old.source_id = None
        return sid

    def _place(self, sid, pos, pan):
        al = self.al
        if pos is None and pan is not None:
            pan = max(-1.0, min(1.0, pan))
            pos = (pan, 0.0, -math.sqrt(1.0 - pan * pan))
            al.alSourcei(sid, AL_SOURCE_RELATIVE, 1)
        elif pos is None:
            pos = (0.0, 0.0, 0.0)
            al.alSourcei(sid, AL_SOURCE_RELATIVE, 1)
        else:
            al.alSourcei(sid, AL_SOURCE_RELATIVE, 0)
        al.alSource3f(sid, AL_POSITION, *[ctypes.c_float(v) for v in pos])

    def _play(self, sound, loop, volume, pitch, pos, pan, reverb=False):
        if not self.available or sound.buffer_id is None:
            return _NullVoice()
        al = self.al
        sid = self._source()
        al.alSourceStop(sid)
        al.alSourcei(sid, AL_BUFFER, sound.buffer_id)
        al.alSourcei(sid, AL_LOOPING, 1 if loop else 0)
        al.alSourcef(sid, AL_PITCH, ctypes.c_float(pitch))
        al.alSourcef(sid, AL_REFERENCE_DISTANCE, ctypes.c_float(1.0))
        al.alSourcef(sid, AL_ROLLOFF_FACTOR, ctypes.c_float(1.0))
        al.alSourcef(sid, AL_MAX_DISTANCE, ctypes.c_float(100.0))
        self._place(sid, pos, pan)
        if self.slot is not None:
            al.alSource3i(sid, AL_AUXILIARY_SEND_FILTER,
                          self.slot if reverb else 0, 0, AL_FILTER_NULL)
        voice = Voice(self, sid)
        voice._gain(volume)
        self.voices[sid] = voice
        al.alSourcePlay(sid)
        return voice

    # --- ouvinte -----------------------------------------------------
    def listener(self, pos, facing=0.0):
        """Posição do ouvinte e para onde ele olha (graus; 0 = frente, 90 = direita)."""
        if not getattr(self, "al", None):
            return
        self.al.alListener3f(AL_POSITION, *[ctypes.c_float(v) for v in pos])
        rad = math.radians(facing)
        ori = (ctypes.c_float * 6)(math.sin(rad), 0.0, -math.cos(rad), 0.0, 1.0, 0.0)
        self.al.alListenerfv(AL_ORIENTATION, ori)

    # --- laço ----------------------------------------------------------
    def update(self, dt):
        """Avança fades e devolve fontes que terminaram para o reaproveitamento."""
        if not self.available:
            return
        for sid, voice in list(self.voices.items()):
            if voice.fade is not None:
                start, end, total, elapsed, stop = voice.fade
                elapsed += dt
                t = min(1.0, elapsed / total)
                voice._gain(start + (end - start) * t)
                if t >= 1.0:
                    voice.fade = None
                    if stop:
                        self.al.alSourceStop(sid)
                else:
                    voice.fade = (start, end, total, elapsed, stop)
            if voice.fade is None and not voice.playing:
                del self.voices[sid]
                voice.source_id = None
                self.free.append(sid)

    def pause_all(self):
        for voice in self.voices.values():
            voice.pause()

    def resume_all(self):
        for voice in self.voices.values():
            voice.resume()

    def close(self):
        if not self.available:
            return
        self.al.alcMakeContextCurrent(None)
        self.al.alcDestroyContext(self.context)
        self.al.alcCloseDevice(self.device)
        self.available = False


# Bounded streaming is optional; existing load()/Sound callers remain supported.
def _install_streaming():
    import sys
    from .streaming import install
    install(sys.modules[__name__])


_install_streaming()
