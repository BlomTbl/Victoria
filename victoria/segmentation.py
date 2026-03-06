"""
Segmentation module — version 3.

Changes compared to v2:
  - _seg_fast: fully vectorised with numpy.
    Parcel arrays (x0, x1, high-fraction, sc-fraction) are built once
    per pipe; all segment overlaps are computed as a (n_segs × n_parcels)
    matrix operation. No Python loop over parcels. Gives a large speed-up
    for pipes with many segments and/or many parcels.
  - _seg_phreeqc: same vectorisation applied for the overlap/weighted-
    average step; the concentration values are still produced by
    quality.get_conc_pipe (PHREEQC), but the subsequent aggregation per
    segment is now O(n_segs) instead of O(n_segs × n_parcels) in Python.
  - calibrate(): warning for more than two end-members (from v2) retained.
  - All other functionality identical to v2.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import math as _math_seg

_NICE_LENGTHS = [1, 2, 5, 10, 25, 50, 100, 250, 500]


def _round_nice(x: float) -> float:
    for n in _NICE_LENGTHS:
        if n >= x:
            return float(n)
    return float(round(x / 100) * 100)


def suggest_seg_length(network: Any, hydstep_s: float,
                       min_segs_per_pipe: int = 5,
                       velocity_percentile: float = 50.0) -> Dict:
    lengths = [
        (getattr(p, "uid", str(i)), getattr(p, "length", 0.0))
        for i, p in enumerate(network.pipes)
        if getattr(p, "length", 0.0) > 0
    ]
    if not lengths:
        return {
            "seg_length_m": 10.0, "seg_length_raw": 10.0,
            "L_min_m": 0, "L_min_pipe": "-", "v_typ_ms": 0,
            "parcel_shift_m": 0, "n_segs_total": 0, "warn_too_fine": False,
        }

    uid_min, L_min = min(lengths, key=lambda x: x[1])

    vels = []
    for link in network.links:
        try:
            v = abs(link.velocity)
            if v > 1e-4:
                vels.append(v)
        except Exception:
            pass
    if vels:
        vels.sort()
        idx   = int(len(vels) * velocity_percentile / 100)
        v_typ = vels[min(idx, len(vels) - 1)]
    else:
        v_typ = 0.1

    parcel_shift = v_typ * hydstep_s
    seg_raw      = L_min / min_segs_per_pipe
    seg_nice     = _round_nice(seg_raw)
    warn         = seg_nice < parcel_shift / 4
    n_segs       = sum(_math_seg.ceil(l / seg_nice) for _, l in lengths)

    return {
        "seg_length_m":   seg_nice,
        "seg_length_raw": round(seg_raw, 2),
        "L_min_m":        L_min,
        "L_min_pipe":     uid_min,
        "v_typ_ms":       round(v_typ, 4),
        "parcel_shift_m": round(parcel_shift, 1),
        "n_segs_total":   n_segs,
        "warn_too_fine":  warn,
    }


def print_seg_advice(r: Dict) -> None:
    print(f"  Recommended segment length : {r['seg_length_m']:.0f} m  "
          f"(exact {r['seg_length_raw']:.1f} m)")
    segs_per_min = int(r["L_min_m"] / r["seg_length_m"])
    print(f"  Shortest pipe            : {r['L_min_m']:.1f} m  "
          f"(pipe '{r['L_min_pipe']}')  -> {segs_per_min} segments")
    print(f"  Typical velocity         : {r['v_typ_ms']:.3f} m/s  "
          f"-> parcel length {r['parcel_shift_m']:.1f} m/step")
    print(f"  Total segments           : {r['n_segs_total']}")
    if r["warn_too_fine"]:
        print(f"  Tip: segments ({r['seg_length_m']:.0f}m) << parcel length "
              f"({r['parcel_shift_m']:.0f}m/step).")
        print("       Larger segment length gives less calculation time "
              "without loss of information.")


__all__ = ["PipeSegmentation"]


class PipeSegmentation:
    """
    Fixed-length pipe segmentation for spatial water quality analysis.

    Two modes:
    - **PhreeqPython mode** (default): uses PHREEQC for concentrations.
    - **Fast mode** (after calibrate()): linear interpolation based on two
      end-members — no PHREEQC calls. Only valid for two-endmember mixtures
      (see calibrate() for details).
    """

    def __init__(self, model: Any, seg_length_m: float = 6.0) -> None:
        if seg_length_m <= 0:
            raise ValueError(f"seg_length_m must be > 0, got {seg_length_m}")
        self.model        = model
        self.seg_length_m = seg_length_m
        self._time_records: List[Dict] = []

        self._sol_high_num: Optional[int] = None
        self._ca_high_mg:   float         = 0.0
        self._sc_high:      float         = 0.0
        self._calibrated:   bool          = False

    # ── Calibration ───────────────────────────────────────────────────────────

    def calibrate(self, sol_high: Any, sc_high: float = 1000.0,
                  sc_low: float = 0.0, species: str = "Ca",
                  units: str = "mg") -> None:
        """
        One-time calibration based on sol_high.

        After this call, record_step/segment_pipe no longer uses PhreeqPython;
        concentration is computed as:

            conc = frac_high * ca_high_mg
            sc   = frac_high * sc_high

        **Note: this is only correct for two-endmember mixtures.**
        If the network has more than two source solutions, all other sources
        are ignored and results are only an approximation. A warning is
        logged in that case.

        Parameters
        ----------
        sol_high :  PHREEQC solution with high concentration (high end-member).
        sc_high :   Specific conductivity of sol_high (µS/cm).
        sc_low :    Specific conductivity of the low end-member (default 0).
        species :   Element to calibrate on (default 'Ca').
        units :     Concentration units (default 'mg').
        """
        self._sol_high_num = sol_high.number
        self._sc_high      = sc_high
        try:
            self._ca_high_mg = sol_high.total(species, units)
        except Exception:
            self._ca_high_mg = 0.0
        self._calibrated = True

        # ── Warning for more than two end-members ────────────────────────────
        self._check_multiendmember_warning()

    def _check_multiendmember_warning(self) -> None:
        """
        Scan the current parcel states for the number of unique solution numbers.
        Logs a warning if more than two end-members are present, because the
        linear calibration is then inaccurate.
        """
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        unique_nums: set = set()
        for pipe_model in self.model.models.pipes.values():
            for parcel in getattr(pipe_model, 'state', []):
                unique_nums.update(parcel.get('q', {}).keys())
            if len(unique_nums) > 2:
                break   # Vroeg stoppen — we hebben al genoeg informatie

        if len(unique_nums) > 2:
            _logger.warning(
                "calibrate() detected %d unique solution numbers in pipe states "
                "(%s). The fast linear calibration is only accurate for two-endmember "
                "mixtures. Results for other sources will be silently ignored. "
                "Consider using the PhreeqPython mode (without calibrate()) for "
                "multi-source networks.",
                len(unique_nums),
                sorted(unique_nums),
            )

    # ── Fast computation ──────────────────────────────────────────────────────

    def _fast(self, q: Dict[int, float]):
        frac = q.get(self._sol_high_num, 0.0)
        return frac * self._ca_high_mg, frac * self._sc_high

    # ── Segment computation ───────────────────────────────────────────────────

    def segment_pipe(self, pipe: Any, species: str = "Ca",
                     units: str = "mg") -> List[Dict]:
        pipe_length: float = getattr(pipe, "length", 0.0)
        if pipe_length <= 0 or self.seg_length_m <= 0:
            return []
        if self._calibrated:
            return self._seg_fast(pipe, pipe_length)
        return self._seg_phreeqc(pipe, pipe_length, species, units)

    def _seg_fast(self, pipe: Any, pipe_length: float) -> List[Dict]:
        link_model = self.model.models.pipes.get(pipe.uid)
        if link_model is None:
            return []
        state = getattr(link_model, "state", [])
        if not state:
            return []

        n_segs = math.ceil(pipe_length / self.seg_length_m)

        # ── Build parcel arrays once ──────────────────────────────────────────
        px0   = np.array([p["x0"] for p in state], dtype=np.float64)
        px1   = np.array([p["x1"] for p in state], dtype=np.float64)
        p_hi  = np.array([p["q"].get(self._sol_high_num, 0.0) for p in state],
                          dtype=np.float64)
        p_conc = p_hi * self._ca_high_mg   # concentration contribution per parcel
        p_sc   = p_hi * self._sc_high       # sc contribution per parcel

        # ── Segment boundaries as arrays ──────────────────────────────────────
        seg_idx_arr = np.arange(n_segs, dtype=np.float64)
        s0_arr = seg_idx_arr * self.seg_length_m
        s1_arr = np.minimum(s0_arr + self.seg_length_m, pipe_length)
        x0_seg = s0_arr / pipe_length
        x1_seg = s1_arr / pipe_length

        # ── Vectorised overlap matrix: shape (n_segs, n_parcels) ─────────────
        # ov[i, j] = overlap of segment i with parcel j (0 if no overlap)
        ov = np.maximum(
            0.0,
            np.minimum(x1_seg[:, None], px1[None, :]) -
            np.maximum(x0_seg[:, None], px0[None, :])
        )  # (n_segs, n_parcels)

        ot       = ov.sum(axis=1)                    # total overlap per segment
        wc       = (ov * p_conc[None, :]).sum(axis=1)
        ws       = (ov * p_sc[None, :]).sum(axis=1)
        n_ov_arr = (ov > 0).sum(axis=1)

        safe_ot = np.where(ot > 0, ot, 1.0)         # avoid division by zero

        results = []
        for i in range(n_segs):
            s0 = float(s0_arr[i])
            s1 = float(s1_arr[i])
            t  = float(ot[i])
            results.append({
                "seg_id":    i + 1,
                "x_start_m": round(s0, 6),
                "x_end_m":   round(s1, 6),
                "x_mid_m":   round((s0 + s1) / 2, 6),
                "length_m":  round(s1 - s0, 6),
                "conc":      float(wc[i] / safe_ot[i]) if t > 0 else 0.0,
                "sc":        float(ws[i] / safe_ot[i]) if t > 0 else 0.0,
                "n_parcels": int(n_ov_arr[i]),
            })
        return results

    def _seg_phreeqc(self, pipe: Any, pipe_length: float,
                     species: str, units: str) -> List[Dict]:
        parcels = self.model.get_conc_pipe(pipe, species, units)
        if not parcels:
            return []

        n_segs = math.ceil(pipe_length / self.seg_length_m)

        # ── Build parcel arrays once ──────────────────────────────────────────
        px0   = np.array([p["x0"] for p in parcels], dtype=np.float64)
        px1   = np.array([p["x1"] for p in parcels], dtype=np.float64)
        pconc = np.array([p["q"]  for p in parcels], dtype=np.float64)

        # ── Segment boundaries as arrays ──────────────────────────────────────
        seg_idx_arr = np.arange(n_segs, dtype=np.float64)
        s0_arr = seg_idx_arr * self.seg_length_m
        s1_arr = np.minimum(s0_arr + self.seg_length_m, pipe_length)
        x0_seg = s0_arr / pipe_length
        x1_seg = s1_arr / pipe_length

        # ── Vectorised overlap matrix: shape (n_segs, n_parcels) ─────────────
        ov = np.maximum(
            0.0,
            np.minimum(x1_seg[:, None], px1[None, :]) -
            np.maximum(x0_seg[:, None], px0[None, :])
        )

        ot       = ov.sum(axis=1)
        ws       = (ov * pconc[None, :]).sum(axis=1)
        n_ov_arr = (ov > 0).sum(axis=1)
        safe_ot  = np.where(ot > 0, ot, 1.0)

        results = []
        for i in range(n_segs):
            s0 = float(s0_arr[i])
            s1 = float(s1_arr[i])
            t  = float(ot[i])
            results.append({
                "seg_id":    i + 1,
                "x_start_m": round(s0, 6),
                "x_end_m":   round(s1, 6),
                "x_mid_m":   round((s0 + s1) / 2, 6),
                "length_m":  round(s1 - s0, 6),
                "conc":      float(ws[i] / safe_ot[i]) if t > 0 else 0.0,
                "n_parcels": int(n_ov_arr[i]),
            })
        return results

    # ── Network level ────────────────────────────────────────────────────────

    def segment_network(self, network: Any, species: str = "Ca",
                        units: str = "mg") -> pd.DataFrame:
        rows: List[Dict] = []
        for pipe in network.pipes:
            for s in self.segment_pipe(pipe, species, units):
                rows.append({"pipe": pipe.uid, **s})
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        base = ["pipe", "seg_id", "x_start_m", "x_end_m", "x_mid_m",
                "length_m", "conc"]
        if "sc" in df.columns:
            base.append("sc")
        base.append("n_parcels")
        return df[[c for c in base if c in df.columns]].reset_index(drop=True)

    def record_step(self, network: Any, species: str = "Ca", units: str = "mg",
                    time_s: Optional[float] = None,
                    step: Optional[int] = None) -> None:
        for pipe in network.pipes:
            for s in self.segment_pipe(pipe, species, units):
                record: Dict = {"pipe": pipe.uid}
                if step   is not None:
                    record["step"] = step
                if time_s is not None:
                    record["time_s"]   = time_s
                    record["time_min"] = round(time_s / 60, 4)
                record.update(s)
                self._time_records.append(record)

    def to_dataframe(self) -> pd.DataFrame:
        if not self._time_records:
            return pd.DataFrame()
        return pd.DataFrame(self._time_records).reset_index(drop=True)

    def reset(self) -> None:
        self._time_records = []

    def pipe_metadata(self, network: Any) -> pd.DataFrame:
        rows = []
        for pipe in network.pipes:
            L = getattr(pipe, "length", 0.0)
            if L <= 0:
                continue
            n    = math.ceil(L / self.seg_length_m)
            last = L - (n - 1) * self.seg_length_m
            rows.append({
                "pipe":          pipe.uid,
                "pipe_length_m": round(L, 4),
                "seg_length_m":  self.seg_length_m,
                "n_segs":        n,
                "last_seg_m":    round(last, 4),
            })
        return pd.DataFrame(rows).reset_index(drop=True)

    def __repr__(self) -> str:
        return (
            f"PipeSegmentation(seg_length_m={self.seg_length_m}, "
            f"calibrated={self._calibrated}, "
            f"recorded={len(self._time_records)})"
        )
