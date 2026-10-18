"""Optional bounded WAV/Vorbis streaming on the SDK's existing OpenAL context.

Four 64 KiB buffers per voice, synchronous refill in Audio.update. No worker
thread owns the OpenAL context. Public entry: audio.stream(name, path).play().
"""
import ctypes as C
import os
import wave

CHUNK = 65536
BUFFERS = 4
AL_BUFFER = 0x1009
AL_LOOPING = 0x1007
AL_BUFFERS_QUEUED = 0x1015
AL_BUFFERS_PROCESSED = 0x1016
AL_SOURCE_STATE = 0x1010
AL_PLAYING = 0x1012
AL_PAUSED = 0x1013


def _check_error(audio, operation):
    error = audio.al.alGetError()
    if error:
        raise RuntimeError('OpenAL error 0x%04x during %s' % (error, operation))


def _bind(al):
    specs = {
        'alGetError': ([], C.c_int),
        'alGenBuffers': ([C.c_int, C.POINTER(C.c_uint)], None),
        'alDeleteBuffers': ([C.c_int, C.POINTER(C.c_uint)], None),
        'alSourceQueueBuffers': ([C.c_uint, C.c_int, C.POINTER(C.c_uint)], None),
        'alSourceUnqueueBuffers': ([C.c_uint, C.c_int, C.POINTER(C.c_uint)], None),
        'alGetSourcei': ([C.c_uint, C.c_int, C.POINTER(C.c_int)], None),
    }
    for name, (args, result) in specs.items():
        fn = getattr(al, name)
        if isinstance(fn, C._CFuncPtr):
            fn.argtypes, fn.restype = args, result


class Decoder:
    def __init__(self, path, module):
        self.wav = self.vf = self.snd = None
        self.lib = None
        self.closed = False
        self.section = None
        if path.lower().endswith('.wav'):
            self.wav = wave.open(path, 'rb')
            self.channels, self.width, self.rate = (self.wav.getnchannels(),
                self.wav.getsampwidth(), self.wav.getframerate())
            if (self.channels, self.width) not in module.FORMATS:
                self.close()
                raise ValueError('Unsupported WAV format: '+path)
        else:
            try:
                lib = module._vorbisfile()
            except OSError:  # Windows: OGG pela libsndfile
                from .sndfile import SndFile
                self.snd = SndFile(path)
                self.channels, self.width, self.rate = self.snd.channels, 2, self.snd.rate
                self.format = module.FORMATS[(self.channels, self.width)]
                return
            lib.ov_fopen.argtypes = [C.c_char_p, C.c_void_p]
            lib.ov_fopen.restype = C.c_int
            lib.ov_info.argtypes = [C.c_void_p, C.c_int]
            lib.ov_info.restype = C.POINTER(module._VorbisInfo)
            lib.ov_read.argtypes = [C.c_void_p, C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_int, C.POINTER(C.c_int)]
            lib.ov_read.restype = C.c_long
            lib.ov_pcm_seek.argtypes = [C.c_void_p, C.c_longlong]
            lib.ov_pcm_seek.restype = C.c_int
            lib.ov_clear.argtypes = [C.c_void_p]
            self.lib = lib
            vf = C.create_string_buffer(8192)
            if lib.ov_fopen(os.fsencode(path), vf):
                raise ValueError('Invalid Vorbis file: '+path)
            self.vf = vf
            info = lib.ov_info(vf, -1).contents
            self.channels, self.width, self.rate = info.channels, 2, info.rate
            if self.channels not in (1, 2):
                self.close()
                raise ValueError('Only mono/stereo streams are supported')
        self.format = module.FORMATS[(self.channels, self.width)]

    def read(self):
        if self.wav:
            return self.wav.readframes(CHUNK // (self.channels * self.width))
        if self.snd:
            return self.snd.read(CHUNK)
        chunk = C.create_string_buffer(CHUNK)
        section = C.c_int(0)
        parts, total, holes = [], 0, 0
        while total < CHUNK:
            n = self.lib.ov_read(self.vf, chunk, CHUNK-total, 0, 2, 1, C.byref(section))
            if n == 0:
                break
            if n < 0:
                holes += 1
                if holes > 8:
                    raise ValueError('Vorbis decode error')
                continue
            if section.value != self.section:
                info = self.lib.ov_info(self.vf, -1).contents
                if info.channels != self.channels or info.rate != self.rate:
                    raise ValueError('Chained Vorbis stream changes format')
                self.section = section.value
            # .raw copies all 64 KiB even when Vorbis produced a partial block.
            parts.append(C.string_at(chunk, n));total += n
        return b''.join(parts)

    def rewind(self):
        if self.wav:
            self.wav.rewind()
        elif self.snd:
            self.snd.rewind()
        elif self.lib.ov_pcm_seek(self.vf, 0):
            raise ValueError('Vorbis rewind failed')
        self.section = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.wav:
            self.wav.close();self.wav = None
        if self.snd:
            self.snd.close();self.snd = None
        if self.vf is not None:
            self.lib.ov_clear(self.vf);self.vf = None


def install(module):
    Audio, Voice = module.Audio, module.Voice
    if getattr(Audio, '_streaming_installed', False):
        return
    Audio._streaming_installed = True

    class StreamVoice(Voice):
        def __init__(self, audio, sid, decoder, loop):
            super().__init__(audio, sid)
            self.sid, self.decoder, self.loop = sid, decoder, loop
            self.ended = self.stopping = self.disposed = False
            self.paused = False
            self.underruns = 0
            self.pump_seconds = 0.0
            self.buffers = (C.c_uint * BUFFERS)()
            audio.al.alGenBuffers(BUFFERS, self.buffers)
            try:
                _check_error(audio, 'stream buffer allocation')
            except Exception:
                audio.al.alDeleteBuffers(BUFFERS, self.buffers)
                raise

        @property
        def active(self):
            """Logical ownership; playing remains the actual OpenAL state."""
            if self.disposed or self.source_id is None:
                return False
            if self.stopping:
                return self.fade is not None or self.playing
            return not self.ended or self.playing

        def fill(self, buffer):
            data = self.decoder.read()
            if not data and self.loop:
                self.decoder.rewind();data = self.decoder.read()
            if not data:
                self.ended = True
                return False
            self.audio.al.alBufferData(buffer, self.decoder.format, data, len(data), self.decoder.rate)
            _check_error(self.audio, 'stream PCM upload')
            value = C.c_uint(buffer)
            self.audio.al.alSourceQueueBuffers(self.sid, 1, C.byref(value))
            _check_error(self.audio, 'stream buffer queue')
            return True

        def pump(self):
            if self.disposed or self.source_id is None or self.stopping or self.paused:
                return
            import time
            started = time.monotonic()
            before = C.c_int()
            self.audio.al.alGetSourcei(self.sid, AL_SOURCE_STATE, C.byref(before))
            if before.value not in (AL_PLAYING, AL_PAUSED) and not self.ended:
                self.underruns += 1
            processed = C.c_int()
            self.audio.al.alGetSourcei(self.sid, AL_BUFFERS_PROCESSED, C.byref(processed))
            for _ in range(processed.value):
                value = C.c_uint()
                self.audio.al.alSourceUnqueueBuffers(self.sid, 1, C.byref(value))
                _check_error(self.audio, 'stream buffer unqueue')
                if not self.ended:
                    self.fill(value.value)
            state, queued = C.c_int(), C.c_int()
            self.audio.al.alGetSourcei(self.sid, AL_SOURCE_STATE, C.byref(state))
            self.audio.al.alGetSourcei(self.sid, AL_BUFFERS_QUEUED, C.byref(queued))
            if queued.value and state.value not in (AL_PLAYING, AL_PAUSED):
                self.audio.al.alSourcePlay(self.sid)  # recover a refill underrun
                _check_error(self.audio, 'stream underrun recovery')
            self.pump_seconds += time.monotonic() - started

        def stop(self, fade=0):
            self.stopping = True
            if not fade:
                self.fade = None
            super().stop(fade)

        def pause(self):
            self.paused = True
            super().pause()

        def resume(self):
            self.paused = False
            super().resume()

        def dispose(self):
            if self.disposed:
                return
            self.disposed = True
            self.audio.al.alSourceStop(self.sid)
            self.audio.al.alSourcei(self.sid, AL_BUFFER, 0)
            self.audio.al.alDeleteBuffers(BUFFERS, self.buffers)
            self.decoder.close()
            self.source_id = None
            self.fade = None

    class StreamSound:
        def __init__(self, audio, name, path):
            self.audio, self.name, self.path = audio, name, path
            self.buffer_id = None
        def play(self, loop=False, volume=1, pitch=1, pos=None, pan=None, reverb=None):
            audio = self.audio
            if not audio.available:
                return module._NullVoice()
            _check_error(audio, 'before streaming setup')
            decoder = Decoder(self.path, module)
            sid = audio._source()
            voice = None
            try:
                audio.al.alSourceStop(sid)
                audio.al.alSourcei(sid, AL_BUFFER, 0)
                audio.al.alSourcei(sid, AL_LOOPING, 0)
                audio.al.alSourcef(sid, module.AL_PITCH, C.c_float(pitch))
                audio._place(sid, pos, pan)
                if audio.slot is not None:
                    audio.al.alSource3i(sid, module.AL_AUXILIARY_SEND_FILTER,
                        audio.slot if reverb or (reverb is None and pos is not None) else 0, 0, 0)
                _check_error(audio, 'stream source preparation')
                voice = StreamVoice(audio, sid, decoder, loop)
                voice._gain(volume)
                for buffer in voice.buffers:
                    if not voice.fill(buffer): break
                audio.voices[sid] = voice
                audio._streams.append(voice)
                if not voice.ended or voice.playing:
                    audio.al.alSourcePlay(sid)
                else:
                    queued = C.c_int()
                    audio.al.alGetSourcei(sid, AL_BUFFERS_QUEUED, C.byref(queued))
                    if queued.value: audio.al.alSourcePlay(sid)
                _check_error(audio, 'stream playback start')
                return voice
            except Exception:
                if voice is not None: voice.dispose()
                else: decoder.close()
                audio.free.append(sid)
                raise

    original_init, original_update = Audio.__init__, Audio.update
    original_source, original_close = Audio._source, Audio.close
    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._streams = []
        if self.available:
            _bind(self.al)
    def stream(self, name, path):
        full = path if os.path.isabs(path) else os.path.join(self.base_dir, path)
        sound = StreamSound(self, name, full)
        self.sounds[name] = sound
        return sound
    def source(self):
        # Release queued stream buffers before original SDK recycles a source.
        if not self.free and len(self.voices) >= module.MAX_SOURCES:
            finished = [sid for sid,v in self.voices.items()
                        if not (v.active if isinstance(v, StreamVoice) else v.playing)]
            sid = finished[0] if finished else next(iter(self.voices))
            voice = self.voices.pop(sid)
            if isinstance(voice, StreamVoice):
                voice.dispose()
            else:
                self.al.alSourceStop(sid)
                voice.source_id = None
            return sid
        return original_source(self)
    def update(self, dt):
        # Preserve SDK fade semantics while retiring streamed sources by
        # logical completion. Another expensive refill can exhaust a source
        # that was just pumped; AL_STOPPED alone must not discard that decoder.
        if not self.available:
            return
        for sid, voice in list(self.voices.items()):
            if voice.fade is not None:
                start, end, total, elapsed, stop = voice.fade
                elapsed += dt
                t = min(1.0, elapsed / total)
                voice._gain(start + (end-start)*t)
                if t >= 1.0:
                    voice.fade = None
                    if stop: self.al.alSourceStop(sid)
                else:
                    voice.fade = (start,end,total,elapsed,stop)
            if isinstance(voice, StreamVoice):
                voice.pump()
                alive = voice.active
            else:
                alive = voice.playing
            if voice.fade is None and not alive:
                del self.voices[sid]
                voice.source_id = None
                if isinstance(voice, StreamVoice):
                    voice.dispose();self._streams.remove(voice)
                self.free.append(sid)
    def close(self):
        for voice in list(self._streams): voice.dispose()
        self._streams.clear()
        original_close(self)
    Audio.__init__, Audio.stream = initialize, stream
    Audio._source, Audio.update, Audio.close = source, update, close
