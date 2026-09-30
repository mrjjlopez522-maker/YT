"""Forced alignment of narration audio to its text (numpy only).

Method (the same idea as the aeneas project): synthesise the text with espeak-ng,
whose word timings are exact, then align that reference to the real narration
with dynamic time warping over MFCC features, and carry each word time across
the warping path. Works for any voice: neural TTS, a cloud provider, or your
own recording.
"""
from __future__ import annotations

import numpy as np

HOP = 0.010
WIN = 0.025


def _resample(x: np.ndarray, sr: int, target: int = 16000) -> np.ndarray:
    if sr == target:
        return x
    n = int(round(len(x) * target / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _mel_filterbank(n_fft: int, sr: int, n_mels: int = 40, fmax: float = 8000.0) -> np.ndarray:
    def mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)
    pts = hz(np.linspace(mel(0.0), mel(min(fmax, sr / 2)), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(1, n_mels + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        for k in range(a, b):
            fb[m - 1, k] = (k - a) / max(1, b - a)
        for k in range(b, c):
            fb[m - 1, k] = (c - k) / max(1, c - b)
    return fb


def mfcc(samples: np.ndarray, sr: int, n_mfcc: int = 13) -> np.ndarray:
    x = samples.astype(np.float32)
    if x.dtype != np.float32 or np.abs(x).max() > 1.5:
        x = x / 32768.0
    x = _resample(x, sr)
    sr = 16000
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])
    n_win, n_hop = int(WIN * sr), int(HOP * sr)
    if len(x) < n_win:
        x = np.pad(x, (0, n_win - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, n_win)[::n_hop] * np.hamming(n_win)
    n_fft = 512
    power = np.abs(np.fft.rfft(frames, n_fft)) ** 2
    logmel = np.log(power @ _mel_filterbank(n_fft, sr).T + 1e-10)
    n = logmel.shape[1]
    dct = np.cos(np.pi / n * (np.arange(n)[None, :] + 0.5) * np.arange(n)[:, None])
    coeffs = logmel @ dct.T
    feats = coeffs[:, 1:n_mfcc + 1]
    return (feats - feats.mean(axis=0)) / (feats.std(axis=0) + 1e-6)


def dtw_path(a: np.ndarray, b: np.ndarray) -> list[tuple[int, int]]:
    """Classic DTW (steps (1,0), (0,1), (1,1)), computed along anti-diagonals for speed."""
    n, m = len(a), len(b)
    cost = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0.0
    for k in range(2, n + m + 1):
        i = np.arange(max(1, k - m), min(n, k - 1) + 1)
        j = k - i
        best = np.minimum(np.minimum(acc[i - 1, j], acc[i, j - 1]), acc[i - 1, j - 1])
        acc[i, j] = cost[i - 1, j - 1] + best
    i, j, path = n, m, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        steps = ((acc[i - 1, j - 1], i - 1, j - 1), (acc[i - 1, j], i - 1, j), (acc[i, j - 1], i, j - 1))
        _, i, j = min(steps, key=lambda s: s[0])
    return path[::-1]


def _voiced_bounds(x: np.ndarray, sr: int, threshold: float = 0.01) -> tuple[int, int]:
    y = x.astype(np.float32)
    if np.abs(y).max() > 1.5:
        y = y / 32768.0
    loud = np.nonzero(np.abs(y) > threshold)[0]
    if len(loud) == 0:
        return 0, len(y)
    pad = int(0.02 * sr)
    return max(0, loud[0] - pad), min(len(y), loud[-1] + pad)


def align(ref_samples: np.ndarray, ref_sr: int, ref_times: list[float], target_samples: np.ndarray,
          target_sr: int) -> list[float]:
    """Map times in the reference audio to the corresponding times in the target audio."""
    ra, rb = _voiced_bounds(ref_samples, ref_sr)
    ta, tb = _voiced_bounds(target_samples, target_sr)
    fa = mfcc(ref_samples[ra:rb], ref_sr)
    fb = mfcc(target_samples[ta:tb], target_sr)
    path = dtw_path(fa, fb)
    first_target = {}
    for i, j in path:
        first_target.setdefault(i, j)
    ref_off, tgt_off = ra / ref_sr, ta / target_sr
    out = []
    for t in ref_times:
        frame = int(round((t - ref_off) / HOP))
        frame = min(max(frame, 0), len(fa) - 1)
        j = first_target.get(frame)
        if j is None:  # nearest aligned reference frame
            j = first_target[min(first_target, key=lambda f: abs(f - frame))]
        out.append(round(tgt_off + j * HOP, 3))
    # enforce monotonic order
    for k in range(1, len(out)):
        out[k] = max(out[k], out[k - 1])
    return out
