"""Диагностика: RAW vs FILTERED vs ОМЕГА."""
import os
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(BASE, "src"), os.path.join(BASE, "src", "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import analysis as hrv

path = sys.argv[1]
raw = open(path, encoding="utf-8").read()

sections, cur = [], None
for line in raw.split("\n"):
    s = line.strip()
    if s == "[RR]":
        cur = []
        sections.append(cur)
        continue
    if s.startswith("["):
        cur = None
        continue
    if cur is not None and s:
        cur.extend(int(v) for v in s.split(",") if v.strip())

print(f"Секций [RR]: {len(sections)}")
for i, rr in enumerate(sections):
    if len(rr) < 10:
        continue
    m = hrv.calc_metrics(rr)
    st = hrv.calc_stress(rr)
    print(f"--- секция {i}: n={len(rr)}  ЧСС={m['mean_hr']:.0f}  Мо={st['mo_ms']:.0f}  "
          f"RMSSD={m['rmssd']:.1f}  ИН={st['si']:.1f}  длительность={sum(rr)/1000:.0f} c")

all_rr = [r for sec in sections for r in sec]

import numpy as np

def tp_periodogram(seq, fs=4.0):
    t = np.cumsum(seq) / 1000.0
    x = np.interp(np.arange(t[0], t[-1], 1.0 / fs), t, seq)
    x = x - x.mean()
    n = len(x)
    w = np.hanning(n)
    norm = fs * np.sum(w ** 2)
    P = np.abs(np.fft.rfft(x * w)) ** 2 / norm
    P[1:] *= 2
    f = np.fft.rfftfreq(n, 1.0 / fs)
    trapz = getattr(np, "trapezoid", None) or np.trapz
    def bp(lo, hi):
        m = (f >= lo) & (f < hi)
        return float(trapz(P[m], f[m]))
    return bp(0.0033, 0.04) + bp(0.04, 0.15) + bp(0.15, 0.4)

for dev in (0.20, 0.25, 0.30, 0.35):
    seq = hrv.filter_rr(all_rr, dev=dev)
    m = hrv.calc_metrics(seq)
    st = hrv.calc_stress(seq)
    d = [abs(b - a) for a, b in zip(seq, seq[1:])]
    nn50 = sum(1 for v in d if v > 50)
    pnn50 = 100.0 * nn50 / len(d) if d else 0.0
    print(f"--- dev={dev:.2f}: n={len(seq)}  ЧСС={m['mean_hr']:.0f}  Мо={st['mo_ms']:.0f}  "
          f"RMSSD={m['rmssd']:.1f}  NN50={nn50}  pNN50={pnn50:.1f}  "
          f"ИН={st['si']:.1f}  TP={tp_periodogram(seq):.0f}")

print("--- ОМЕГА   : n≈220  ЧСС≈65  Мо=920  RMSSD=167.5  NN50=152  pNN50=69.1  ИН=6.5  TP=42578")