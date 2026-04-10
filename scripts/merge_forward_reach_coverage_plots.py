#!/usr/bin/env python3
"""
Merge FPR histograms (all PRs vs n_nodes>0 only) stacked vertically.

Run after `scripts/plot_all_repos_forward_reach_coverage.py` has written:
  viz_output_all_repos/flows/all_repos_pr_fpr_histogram.png
  viz_output_all_repos/flows/all_repos_pr_fpr_histogram_defined_only.png

Output:
  viz_output_all_repos/flows/all_repos_pr_fpr_histogram_merged.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = _ROOT / "viz_output_all_repos" / "flows"

ALL_NAME = "all_repos_pr_fpr_histogram.png"
DEFINED_NAME = "all_repos_pr_fpr_histogram_defined_only.png"
MERGED_NAME = "all_repos_pr_fpr_histogram_merged.png"


def load_png(path: Path) -> np.ndarray:
    if not path.is_file():
        raise SystemExit(f"Missing PNG: {path}")
    return mpimg.imread(path)


def pad_to_same_width(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    w = max(a.shape[1], b.shape[1])

    def pad(img: np.ndarray) -> np.ndarray:
        if img.shape[1] == w:
            return img
        h, w_old, channels = img.shape
        if channels == 4:
            bg_val = [1.0, 1.0, 1.0, 1.0]
        else:
            bg_val = [1.0, 1.0, 1.0]
        canvas = np.ones((h, w, channels), dtype=img.dtype)
        for c, v in enumerate(bg_val):
            canvas[:, :, c] *= v
        canvas[:, :w_old, :] = img
        return canvas

    return pad(a), pad(b)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_path = OUT_DIR / ALL_NAME
    def_path = OUT_DIR / DEFINED_NAME
    out_path = OUT_DIR / MERGED_NAME

    top = load_png(all_path)
    bottom = load_png(def_path)
    top, bottom = pad_to_same_width(top, bottom)

    merged = np.concatenate([top, bottom], axis=0)

    sep_h = max(8, int(round(0.01 * merged.shape[0])))
    channels = merged.shape[2]
    sep = np.ones((sep_h, merged.shape[1], channels), dtype=merged.dtype)
    if channels == 4:
        sep[:, :, 3] = 1.0
    for c in range(min(3, channels)):
        sep[:, :, c] *= 0.88

    merged = np.concatenate([top, sep, bottom], axis=0)

    plt.imsave(out_path, merged)
    all_path.unlink(missing_ok=True)
    def_path.unlink(missing_ok=True)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
