#!/usr/bin/env python3
"""Merge aggregate pyfile + fn/class PNGs stacked vertically into one image.

Run after `scripts/plot_all_repos_histograms.py` has written:
  viz_output_all_repos/all_repos_pr_pyfile_histogram.png
  viz_output_all_repos/all_repos_pr_fn_class_changes_histogram.png

Output:
  viz_output_all_repos/all_repos_pr_py_and_fnclass_stacked.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = _ROOT / "viz_output_all_repos"

PYFILE_NAME = "all_repos_pr_pyfile_histogram.png"
FNCLASS_NAME = "all_repos_pr_fn_class_changes_histogram.png"
MERGED_NAME = "all_repos_pr_py_and_fnclass_stacked.png"


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
    py_path = OUT_DIR / PYFILE_NAME
    fn_path = OUT_DIR / FNCLASS_NAME
    out_path = OUT_DIR / MERGED_NAME

    left = load_png(py_path)
    right = load_png(fn_path)
    left, right = pad_to_same_width(left, right)

    merged = np.concatenate([left, right], axis=0)

    # Horizontal separator between panels.
    sep_h = max(8, int(round(0.01 * merged.shape[0])))
    channels = merged.shape[2]
    # Light gray line on white background.
    sep = np.ones((sep_h, merged.shape[1], channels), dtype=merged.dtype)
    if channels == 4:
        sep[:, :, 3] = 1.0
    for c in range(min(3, channels)):
        sep[:, :, c] *= 0.88
    merged = np.concatenate([left, sep, right], axis=0)

    # Use matplotlib to write out, preserving colors.
    plt.imsave(out_path, merged)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
