"""Bounded WAV segment processing. Source bytes are never overwritten."""
import array
import math
import random
import sys
import shutil
from pathlib import Path
import wave
from uuid import uuid4
from .audio_recorder import Recorder
from .evidence import EvidenceStore, safe_path, digest
from .spectrum import fft, db


def info(path):
    with wave.open(str(path), 'rb') as stream:
        if stream.getsampwidth() != 2 or stream.getnchannels() not in (1, 2) or stream.getcomptype() != 'NONE':
            raise ValueError('Review supports uncompressed 16-bit mono/stereo WAV sources.')
        return dict(rate=stream.getframerate(), channels=stream.getnchannels(),
                    frames=stream.getnframes(), duration=stream.getnframes() / stream.getframerate())


def read_segment(path, start, end):
    metadata = info(path)
    if not (0 <= start < end <= metadata['duration'] + 1e-6) or end - start > 120:
        raise ValueError('Select a valid segment of up to 120 seconds. Longer recordings can be reviewed in sections.')
    with wave.open(str(path), 'rb') as stream:
        stream.setpos(int(start * metadata['rate']))
        raw = stream.readframes(int((end - start) * metadata['rate']))
    samples = array.array('h')
    samples.frombytes(raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    if metadata['channels'] == 2:
        samples = array.array('h', (int((samples[i] + samples[i + 1]) / 2) for i in range(0, len(samples) - 1, 2)))
    return samples, metadata['rate']


def samples_bytes(samples):
    out = array.array('h', (max(-32768, min(32767, round(x))) for x in samples))
    if sys.byteorder != 'little':
        out.byteswap()
    return out.tobytes()


def visualization(path, start, end):
    samples, rate = read_segment(path, start, end)
    stride = max(1, len(samples) // 800)
    peaks = [max((abs(v) for v in samples[i:i + stride]), default=0) / 32768 for i in range(0, len(samples), stride)]
    size = 1024
    step = max(size, len(samples) // 160)
    window = [0.5 - .5 * math.cos(2 * math.pi * i / (size - 1)) for i in range(size)]
    spectrogram = []
    for offset in range(0, max(1, len(samples) - size + 1), step):
        frame = samples[offset:offset + size]
        values = [frame[i] / 32768 * window[i] if i < len(frame) else 0 for i in range(size)]
        bins = fft(values)[:size // 2]
        spectrogram.append([max(db(abs(v) / (size / 4)) for v in bins[i:i + 8]) for i in range(0, len(bins), 8)])
    return dict(waveform=peaks, spectrogram=spectrogram, rate=rate, start=start, end=end)


def derive(directory, source, start, end, gain_db=0, reverse=False, lowpass=0, highpass=0):
    store = EvidenceStore(directory)
    path = safe_path(directory, source)
    expected = next((r for r in store.manifest() if r['file'] == source), None)
    if expected is None:
        # Legacy sources are fingerprinted at first import; never claim capture-time integrity.
        expected = store.register(source, 'legacy', 'First review fingerprint; capture-time hash unavailable')
    if digest(path) != expected['sha256']:
        raise ValueError('Source hash mismatch; processing refused')
    samples, rate = read_segment(path, start, end)
    if not -36 <= gain_db <= 24 or not 0 <= lowpass < rate / 2 or not 0 <= highpass < rate / 2:
        raise ValueError('Gain/filter settings outside supported limits')
    if lowpass and highpass and highpass >= lowpass:
        raise ValueError('High-pass cutoff must be below low-pass cutoff')
    gain = 10 ** (gain_db / 20)
    lp_alpha = 1 - math.exp(-2 * math.pi * lowpass / rate) if lowpass else 0
    hp_alpha = math.exp(-2 * math.pi * highpass / rate) if highpass else 0
    last_in = hp = lp = 0.0
    output = array.array('h')
    clipped = 0
    for sample in samples:
        value = float(sample)
        if highpass:
            hp = hp_alpha * (hp + value - last_in)
            last_in = value
            value = hp
        if lowpass:
            lp += lp_alpha * (value - lp)
            value = lp
        value *= gain
        clipped += abs(value) > 32767
        output.append(max(-32768, min(32767, round(value))))
    if reverse:
        output.reverse()
    filename = f'derived-{uuid4().hex}.wav'
    recorder = Recorder(safe_path(directory, filename), rate)
    try:
        recorder.write(samples_bytes(output))
    finally:
        recorder.close()
    store.register(filename, 'derived', 'WAV selection / gain / first-order filters / reversal',
                   dict(start_seconds=start, end_seconds=end, gain_db=gain_db, reverse=reverse,
                        lowpass_hz=lowpass, highpass_hz=highpass, clipped_samples=clipped,
                        stereo_mix='Arithmetic mono average when source is stereo'),
                   [dict(file=source, sha256=expected['sha256'])])
    return filename


def simulated_sweep(directory, sources, fragment_ms=150, duration_seconds=10, random_order=True,
                    reverse=False, noise_db=-60, crossfade_ms=10, speed=1, seed=None):
    """Offline local-WAV montage, explicitly not RF reception. Bounded to 60 seconds."""
    if not sources or not 1 <= duration_seconds <= 60 or not 20 <= fragment_ms <= 2000 or not .25 <= speed <= 4:
        raise ValueError('Choose sources, 1–60 seconds, 20–2000 ms fragments, and speed 0.25–4×')
    if not 0 <= crossfade_ms <= fragment_ms / 2 or not -120 <= noise_db <= -12:
        raise ValueError('Crossfade must be at most half a fragment; noise must be −120 to −12 dBFS')
    store = EvidenceStore(directory)
    rate = 48000
    seed = seed if seed is not None else random.SystemRandom().randrange(2**32)
    rng = random.Random(seed)
    source_info = []
    provenance = []
    for original in sources:
        original = Path(original)
        metadata = info(original)
        filename = f'sweep-source-{uuid4().hex}.wav'
        target = store.directory / filename
        with original.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        record = store.register(filename, 'source', 'Local sweep source copy', {'source_name': original.name})
        source_info.append((target, metadata))
        provenance.append(dict(file=filename, sha256=record['sha256']))
    total = int(duration_seconds * rate)
    fragment = int(fragment_ms * rate / 1000)
    fade = int(crossfade_ms * rate / 1000)
    output = array.array('h')
    cursor = 0
    positions = [0.0] * len(sources)
    while len(output) < total:
        index = rng.randrange(len(sources)) if random_order else cursor % len(sources)
        path, meta = source_info[index]
        seconds = min(meta['duration'], fragment_ms / 1000 * speed)
        if seconds <= 0:
            raise ValueError('Sweep source is empty')
        start = rng.uniform(0, max(0, meta['duration'] - seconds)) if random_order else positions[index]
        if start + seconds > meta['duration']:
            start = 0
        samples, source_rate = read_segment(path, start, start + seconds)
        positions[index] = start + seconds
        if not samples:
            raise ValueError('Sweep source segment is empty')
        if reverse:
            samples.reverse()
        part = [samples[min(len(samples) - 1, int(i * source_rate * speed / rate))] for i in range(fragment)]
        overlap = min(fade, len(output))
        for i in range(overlap):
            weight = (i + 1) / (overlap + 1)
            output[len(output) - overlap + i] = round(output[len(output) - overlap + i] * (1 - weight) + part[i] * weight)
        output.extend(part[overlap:])
        cursor += 1
    amplitude = 0 if noise_db <= -120 else 32767 * 10 ** (noise_db / 20)
    data = samples_bytes(v + rng.uniform(-amplitude, amplitude) for v in output[:total])
    filename = f'simulated-sweep-{uuid4().hex}.wav'
    recorder = Recorder(store.directory / filename, rate)
    try:
        recorder.write(data)
    finally:
        recorder.close()
    store.register(filename, 'synthetic', 'SIMULATED RADIO SWEEP — NOT RF RECEPTION',
                   dict(fragment_ms=fragment_ms, duration_seconds=duration_seconds, random_order=random_order,
                        reverse=reverse, noise_db=noise_db, crossfade_ms=crossfade_ms, speed=speed, seed=seed), provenance)
    return filename
