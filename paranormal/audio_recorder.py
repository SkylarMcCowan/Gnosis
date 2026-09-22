"""Exclusive-create WAV originals; no processing or overwriting of evidence."""
import wave


class Recorder:
    def __init__(self, path, rate):
        self.stream = path.open('xb')
        try:
            self.wav = wave.open(self.stream, 'wb')
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)
            self.wav.setframerate(rate)
        except Exception:
            self.stream.close()
            raise
        self.frames = 0

    def write(self, pcm):
        self.wav.writeframesraw(pcm)
        self.frames += len(pcm) // 2

    def close(self):
        try:
            self.wav.close()
        finally:
            self.stream.close()
