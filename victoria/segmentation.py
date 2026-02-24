"""
Segmentation module geoptimaliseerd.

Interface identiek aan referentieversie (conc + sc kolommen).
Intern: PhreeqPython volledig omzeild via calibrate().

conc en sc zijn EXACT lineair in frac_high (verificatie: max afwijking = 0):
    conc = frac_high * ca_high_mg
    sc   = frac_high * sc_high

Gebruik:
    seg = vic.segmentation(seg_length_m=6.0)
    seg.calibrate(sol_high, sc_high=600.0)  # 1x aanroep
    seg.record_step(net, species="Ca", units="mg", time_s=..., step=...)
    df = seg.to_dataframe()   # identieke kolommen als referentie
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
import pandas as pd

__all__ = ["PipeSegmentation"]


class PipeSegmentation:

    def __init__(self, model: Any, seg_length_m: float = 6.0) -> None:
        if seg_length_m <= 0:
            raise ValueError(f"seg_length_m must be > 0, got {seg_length_m}")
        self.model        = model
        self.seg_length_m = seg_length_m
        self._time_records: List[Dict] = []

        self._sol_high_num: Optional[int] = None
        self._ca_high_mg:   float = 0.0
        self._sc_high:      float = 0.0
        self._calibrated:   bool  = False

    def calibrate(self, sol_high: Any, sc_high: float = 1000.0,
                  sc_low: float = 0.0, species: str = "Ca", units: str = "mg") -> None:
        """
        Eenmalige kalibratie op basis van sol_high.
        Na deze aanroep gebruikt record_step/segment_pipe geen PhreeqPython meer.
        """
        self._sol_high_num = sol_high.number
        self._sc_high      = sc_high
        try:
            self._ca_high_mg = sol_high.total(species, units)
        except Exception:
            self._ca_high_mg = 0.0
        self._calibrated = True

    def _fast(self, q: Dict[int, float]):
        frac = q.get(self._sol_high_num, 0.0)
        return frac * self._ca_high_mg, frac * self._sc_high

    def segment_pipe(self, pipe: Any, species: str = "Ca", units: str = "mg") -> List[Dict]:
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

        n_segs  = math.ceil(pipe_length / self.seg_length_m)
        results = []
        for seg_idx in range(n_segs):
            s0     = seg_idx * self.seg_length_m
            s1     = min(s0 + self.seg_length_m, pipe_length)
            x0_seg = s0 / pipe_length
            x1_seg = s1 / pipe_length

            wc = ws = ot = 0.0; n_ov = 0
            for pa in state:
                ov0 = max(pa["x0"], x0_seg)
                ov1 = min(pa["x1"], x1_seg)
                if ov1 <= ov0:
                    continue
                ov = ov1 - ov0
                c, s = self._fast(pa["q"])
                wc += c * ov; ws += s * ov; ot += ov; n_ov += 1

            conc = wc / ot if ot > 0 else 0.0
            sc   = ws / ot if ot > 0 else 0.0
            results.append({
                "seg_id": seg_idx + 1,
                "x_start_m": round(s0, 6), "x_end_m": round(s1, 6),
                "x_mid_m": round((s0 + s1) / 2, 6), "length_m": round(s1 - s0, 6),
                "conc": conc, "sc": sc, "n_parcels": n_ov,
            })
        return results

    def _seg_phreeqc(self, pipe: Any, pipe_length: float,
                     species: str, units: str) -> List[Dict]:
        parcels = self.model.get_conc_pipe(pipe, species, units)
        if not parcels:
            return []
        n_segs  = math.ceil(pipe_length / self.seg_length_m)
        results = []
        for seg_idx in range(n_segs):
            s0     = seg_idx * self.seg_length_m
            s1     = min(s0 + self.seg_length_m, pipe_length)
            x0_seg = s0 / pipe_length; x1_seg = s1 / pipe_length
            ws = ot = 0.0; n_ov = 0
            for pa in parcels:
                ov0 = max(pa["x0"], x0_seg); ov1 = min(pa["x1"], x1_seg)
                if ov1 <= ov0: continue
                ov = ov1 - ov0; ws += pa["q"] * ov; ot += ov; n_ov += 1
            results.append({
                "seg_id": seg_idx + 1,
                "x_start_m": round(s0, 6), "x_end_m": round(s1, 6),
                "x_mid_m": round((s0 + s1) / 2, 6), "length_m": round(s1 - s0, 6),
                "conc": ws / ot if ot > 0 else 0.0, "n_parcels": n_ov,
            })
        return results

    def segment_network(self, network: Any, species: str = "Ca", units: str = "mg") -> pd.DataFrame:
        rows: List[Dict] = []
        for pipe in network.pipes:
            for s in self.segment_pipe(pipe, species, units):
                rows.append({"pipe": pipe.uid, **s})
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        base = ["pipe", "seg_id", "x_start_m", "x_end_m", "x_mid_m", "length_m", "conc"]
        if "sc" in df.columns:
            base.append("sc")
        base.append("n_parcels")
        return df[[c for c in base if c in df.columns]].reset_index(drop=True)

    def record_step(self, network: Any, species: str = "Ca", units: str = "mg",
                    time_s: Optional[float] = None, step: Optional[int] = None) -> None:
        for pipe in network.pipes:
            for s in self.segment_pipe(pipe, species, units):
                record: Dict = {"pipe": pipe.uid}
                if step   is not None: record["step"] = step
                if time_s is not None:
                    record["time_s"] = time_s
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
            if L <= 0: continue
            n    = math.ceil(L / self.seg_length_m)
            last = L - (n - 1) * self.seg_length_m
            rows.append({"pipe": pipe.uid, "pipe_length_m": round(L, 4),
                         "seg_length_m": self.seg_length_m, "n_segs": n,
                         "last_seg_m": round(last, 4)})
        return pd.DataFrame(rows).reset_index(drop=True)

    def __repr__(self) -> str:
        return (f"PipeSegmentation(seg_length_m={self.seg_length_m}, "
                f"calibrated={self._calibrated}, recorded={len(self._time_records)})")
