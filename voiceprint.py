"""
voiceprint.py — a small, dependency-free speaker model.

It learns what *your* voice looks like statistically (loudness envelope, pitch
proxy, brightness/spectral balance) and can then tell whether a given recording
sounds like you.

Honest limits: this separates clearly different voices (different pitch, timbre,
mic position). It is not a biometric lock and it won't confuse-proof against a
very similar voice. Treat it as "is that probably me talking?" — not security.
"""

import math
import os
import wave

BANDS = (180, 320, 520, 820, 1250, 1850, 2600, 3400)


# ------------------------------------------------------------------ features
def _goertzel(samples, rate, freq):
    """Energy at one frequency, without numpy."""
    n = len(samples)
    if not n:
        return 0.0
    k = int(0.5 + (n * freq) / rate)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)
    s0 = s1 = s2 = 0.0
    for s in samples:
        s0 = s + coeff * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return math.sqrt(max(0.0, power)) / n


def _frames(samples, size, hop):
    for i in range(0, max(1, len(samples) - size + 1), hop):
        yield samples[i:i + size]


def features(wav_path: str):
    """Extract a fixed-length feature vector from a 16-bit mono WAV.

    Returns None (never raises) when the clip is unusable, so callers can just
    skip a bad sample instead of crashing the enrolment.
    """
    try:
        return _features(wav_path)
    except Exception:
        return None


def _features(wav_path: str):
    with wave.open(wav_path, "rb") as wf:
        rate = wf.getframerate()
        width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError("Expected 16-bit audio")
    samples = [int.from_bytes(raw[i:i + 2], "little", signed=True)
               for i in range(0, len(raw) - 1, 2)]
    if not samples:
        raise ValueError("Empty recording")

    size = max(64, int(rate * 0.03))
    hop = max(32, int(rate * 0.015))
    rms_list, zcr_list, cent_list = [], [], []
    band_acc = [0.0] * len(BANDS)

    for fr in _frames(samples, size, hop):
        if not fr:
            continue
        energy = sum(v * v for v in fr) / len(fr)
        rms = math.sqrt(energy)
        if rms < 120:                      # skip silence
            continue
        crossings = sum(1 for a, b in zip(fr, fr[1:]) if (a >= 0) != (b >= 0))
        zcr = crossings / max(1, len(fr) - 1)

        energies = []
        total = 0.0
        for bi, freq in enumerate(BANDS):
            e = _goertzel(fr, rate, freq)
            energies.append(e)
            total += e
            band_acc[bi] += e
        if total <= 1e-9:
            continue
        centroid = sum(f * e for f, e in zip(BANDS, energies)) / total
        rms_list.append(rms)
        zcr_list.append(zcr)
        cent_list.append(centroid)

    if len(rms_list) < 3:
        raise ValueError("Not enough speech in that recording")

    def mean(v):
        return sum(v) / len(v)

    def std(v):
        m = mean(v)
        return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))

    total_band = sum(band_acc) or 1.0
    vec = [
        mean(rms_list) / 3000.0,
        std(rms_list) / 3000.0,
        mean(zcr_list),
        std(zcr_list),
        mean(cent_list) / 3000.0,
        std(cent_list) / 3000.0,
    ] + [b / total_band for b in band_acc]
    return [round(v, 6) for v in vec]


# ------------------------------------------------------------------ compare
def similarity(a, b) -> float:
    """0..1, where 1 is identical."""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0 or db == 0:
        return 0.0
    cos = num / (da * db)
    # cosine on non-negative features lands ~0.95+ for everything, so stretch
    # the useful band (0.93..1.0) out to 0..1
    return max(0.0, min(1.0, (cos - 0.93) / 0.07))


def centroid(vectors):
    """Average several enrolments into one reference print."""
    if not vectors:
        return []
    n = len(vectors[0])
    return [round(sum(v[i] for v in vectors) / len(vectors), 6) for i in range(n)]


def match(print_vec, sample_vec, threshold: float = 0.55):
    """Returns (is_me, score)."""
    score = similarity(print_vec, sample_vec)
    return score >= threshold, score


def wav_exists(path: str) -> bool:
    return bool(path) and os.path.exists(path)
