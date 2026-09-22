"""Dependency-free audio measurements; all levels are digital dBFS, not dB SPL."""
import cmath
import math
import struct


def db(value):
    return 20 * math.log10(max(value, 1e-6))


def fft(values):
    """Radix-two FFT, used on a Hann-windowed analysis frame."""
    n = len(values)
    out = [complex(v) for v in values]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            out[i], out[j] = out[j], out[i]
    size = 2
    while size <= n:
        step = cmath.exp(-2j * math.pi / size)
        for start in range(0, n, size):
            w = 1
            for k in range(size // 2):
                a, b = out[start + k], w * out[start + k + size // 2]
                out[start + k], out[start + k + size // 2] = a + b, a - b
                w *= step
        size *= 2
    return out


def measure(pcm, rate, band=(20, 200)):
    samples = [s / 32768 for s in struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)]
    n = len(samples)
    if n == 0 or n & (n - 1):
        raise ValueError('Analysis requires a nonempty power-of-two PCM frame')
    power = sum(s * s for s in samples) / n
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    bins = fft([s * w for s, w in zip(samples, window)])[:n // 2 + 1]
    window_sum = sum(window)
    magnitude = [abs(v) * 2 / window_sum for v in bins]
    dominant = max(range(1, len(bins)), key=lambda i: magnitude[i])
    # Window-normalized one-sided band power, derived from the FFT.
    band_power = sum((1 if i in (0, n // 2) else 2) * abs(v) ** 2
                     for i, v in enumerate(bins) if band[0] <= i * rate / n <= band[1])
    band_power /= n * sum(w * w for w in window)
    return dict(rms_dbfs=db(math.sqrt(power)), peak_dbfs=db(max(map(abs, samples))),
                power=power, dominant_hz=dominant * rate / n,
                band_dbfs=db(math.sqrt(band_power)), spectrum=[db(v) for v in magnitude],
                waveform=samples[::max(1, n // 400)])
