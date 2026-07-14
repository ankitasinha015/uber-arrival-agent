"""Rigorous validation of the axis_spread LLM judge (evals-skills:validate-evaluator).

Full methodology: stratified train/dev/test split → few-shot the judge from TRAIN →
measure TPR/TNR on DEV (iterate there) → measure ONCE on held-out TEST → Rogan-Gladen
correction of an unlabeled "production" batch → bootstrap 95% CI.

Convention (per the skill): positive class = Pass.
  TPR = P(judge Pass | human Pass);  TNR = P(judge Fail | human Fail).

Run:  EVAL_LIVE=1 python -m evals.validate_judge     (needs a key; ~70 judge calls)
"""

from __future__ import annotations

import os
import random

import numpy as np

from evals.evaluators import JUDGE_MODEL, judge_axis_spread
from evals.judge_dataset import build


def stratified_split(data, seed=42):
    rng = random.Random(seed)
    pos = [d for d in data if d[1]]; neg = [d for d in data if not d[1]]
    rng.shuffle(pos); rng.shuffle(neg)

    def cut(lst):
        n = len(lst); tr = max(2, round(n * 0.15)); dv = tr + round(n * 0.45)
        return lst[:tr], lst[tr:dv], lst[dv:]

    ptr, pdv, pte = cut(pos); ntr, ndv, nte = cut(neg)
    return ptr + ntr, pdv + ndv, pte + nte


def _rates(pairs):
    """pairs = [(judge_pass, human_pass)]; positive = Pass."""
    tp = sum(jp and hp for jp, hp in pairs)
    fn = sum((not jp) and hp for jp, hp in pairs)
    tn = sum((not jp) and (not hp) for jp, hp in pairs)
    fp = sum(jp and (not hp) for jp, hp in pairs)
    tpr = tp / (tp + fn) if (tp + fn) else float("nan")
    tnr = tn / (tn + fp) if (tn + fp) else float("nan")
    return tpr, tnr, (tp, fn, tn, fp)


def _judge(subset, examples):
    return [(bool(judge_axis_spread(cs, examples=examples).get("pass")), gold)
            for cs, gold, _ in subset]


def _bootstrap_ci(pairs, p_obs, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    arr = np.array([(int(jp), int(hp)) for jp, hp in pairs])
    est = []
    for _ in range(n):
        s = arr[rng.integers(0, len(arr), len(arr))]
        jp, hp = s[:, 0], s[:, 1]
        tp = ((jp == 1) & (hp == 1)).sum(); fn = ((jp == 0) & (hp == 1)).sum()
        tn = ((jp == 0) & (hp == 0)).sum(); fp = ((jp == 1) & (hp == 0)).sum()
        tpr = tp / (tp + fn) if (tp + fn) else 0
        tnr = tn / (tn + fp) if (tn + fp) else 0
        d = tpr + tnr - 1
        if abs(d) < 1e-6:
            continue
        est.append(min(1, max(0, (p_obs + tnr - 1) / d)))
    return (float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))) if est else (float("nan"),) * 2


def main() -> int:
    if os.environ.get("EVAL_LIVE") != "1":
        print("Set EVAL_LIVE=1 (and a key) to run the live judge validation.")
        return 0

    train, dev, _ = stratified_split(build(seed=42))
    npos = lambda s: sum(1 for _, g, _ in s if g)
    print(f"model: {JUDGE_MODEL}")

    # few-shot from TRAIN only (never dev/test). Span distinct axes among the pass
    # examples so every axis's spread is demonstrated.
    seen, span = set(), []
    for cs, g, _ in train:
        if g and cs["axis"] not in seen:
            span.append((cs, g)); seen.add(cs["axis"])
    shots = span[:3] + [(cs, g) for cs, g, _ in train if not g][:2]
    print(f"split  train {len(train)} ({npos(train)}P)  · dev {len(dev)} ({npos(dev)}P) "
          f"· few-shot axes: {[cs['axis'] for cs, _ in span[:3]]}")

    dev_pairs = _judge(dev, shots)
    tpr, tnr, cm = _rates(dev_pairs)
    print(f"\nDEV   TPR {tpr:.0%}  TNR {tnr:.0%}   (TP={cm[0]} FN={cm[1]} TN={cm[2]} FP={cm[3]})")
    for (jp, hp), (cs, gold, note) in zip(dev_pairs, dev):
        if jp != hp:
            print(f"  DISAGREE: human={'P' if hp else 'F'} judge={'P' if jp else 'F'}  [{cs['axis']}] {note}")

    # FINAL: a FRESH held-out set (different seed → unseen cases), measured once.
    test = build(seed=123)
    test_pairs = _judge(test, shots)
    t_tpr, t_tnr, t_cm = _rates(test_pairs)
    print(f"\nTEST  TPR {t_tpr:.0%}  TNR {t_tnr:.0%}   (TP={t_cm[0]} FN={t_cm[1]} TN={t_cm[2]} FP={t_cm[3]})  [fresh held-out n={len(test)}, one shot]")

    # Rogan-Gladen on an unlabeled 'production' batch (fresh seed, labels ignored)
    prod = build(seed=7)[:24]
    prod_pass = [bool(judge_axis_spread(cs, examples=shots).get("pass")) for cs, _, _ in prod]
    p_obs = sum(prod_pass) / len(prod_pass)
    denom = t_tpr + t_tnr - 1
    theta = min(1, max(0, (p_obs + t_tnr - 1) / denom)) if abs(denom) > 1e-6 else float("nan")
    lo, hi = _bootstrap_ci(test_pairs, p_obs)
    print(f"\nPRODUCTION (n={len(prod)} unlabeled)  raw judge pass {p_obs:.0%}")
    print(f"  Rogan-Gladen corrected true pass rate: {theta:.0%}   95% CI [{lo:.0%}, {hi:.0%}]")
    print("  (correction uses test TPR/TNR; CI is wide by design at this sample size)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
