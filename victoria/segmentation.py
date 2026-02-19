"""
Segmentation module for pipe concentration analysis.

Divides pipes into fixed-length physical segments and computes the
length-weighted average concentration in each segment by overlapping
the segment grid with the FIFO parcel state returned by Victoria.

Typical usage
-------------
    from victoria.segmentation import PipeSegmentation
    import pandas as pd

    seg = PipeSegmentation(model, seg_length_m=6.0)

    # Concentration profile of one pipe at the current simulation state
    profile = seg.segment_pipe(pipe, species='Ca', units='mg')

    # DataFrame with all pipes × all segments
    df = seg.segment_network(network, species='Ca', units='mg')

    # Time-series: call seg.record_step() inside your simulation loop,
    # then retrieve seg.to_dataframe() afterwards.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd

__all__ = ['PipeSegmentation']


class PipeSegmentation:
    """
    Segment-level concentration calculator for Victoria pipe models.

    Parameters
    ----------
    model : Victoria
        An initialised Victoria instance (after fill_network).
    seg_length_m : float
        Physical length of each segment in metres.  The last segment of
        a pipe may be shorter than this value.

    Attributes
    ----------
    seg_length_m : float
        Segment length used for all calculations.
    _time_records : list
        Internal buffer used by :meth:`record_step` / :meth:`to_dataframe`.
    """

    def __init__(self, model: Any, seg_length_m: float = 6.0) -> None:
        if seg_length_m <= 0:
            raise ValueError(f"seg_length_m must be > 0, got {seg_length_m}")
        self.model = model
        self.seg_length_m = seg_length_m
        self._time_records: List[Dict] = []

    # ------------------------------------------------------------------
    # Core calculation
    # ------------------------------------------------------------------

    def segment_pipe(
        self,
        pipe: Any,
        species: str,
        units: str = 'mg',
    ) -> List[Dict]:
        """
        Compute concentration for every fixed-length segment of one pipe.

        The method fetches the current parcel state via
        ``Victoria.get_conc_pipe`` and overlaps each physical segment with
        the normalised parcel positions to derive a length-weighted average
        concentration.

        Parameters
        ----------
        pipe : epynet pipe object
            Must expose ``.uid`` and ``.length`` attributes.
        species : str
            Chemical element / species name passed to PHREEQC
            (e.g. ``'Ca'``, ``'Cl'``).
        units : str
            Concentration units string accepted by PhreeqPython
            (e.g. ``'mg'``, ``'mmol'``).

        Returns
        -------
        list of dict
            One entry per segment with keys:

            ``seg_id``
                1-based sequential segment index.
            ``x_start_m``
                Segment start position [m from inlet].
            ``x_end_m``
                Segment end position [m from inlet].
            ``x_mid_m``
                Segment midpoint [m from inlet].
            ``length_m``
                Actual segment length in metres (last segment may differ).
            ``conc``
                Length-weighted average concentration in the segment.
            ``n_parcels``
                Number of FIFO parcels overlapping this segment.

        Returns an empty list when the pipe has no length, the segment
        length is invalid, or no parcel data is available.
        """
        pipe_length: float = getattr(pipe, 'length', 0.0)
        if pipe_length <= 0 or self.seg_length_m <= 0:
            return []

        parcels = self.model.get_conc_pipe(pipe, species, units)
        if not parcels:
            return []

        n_segs = math.ceil(pipe_length / self.seg_length_m)
        results: List[Dict] = []

        for seg_idx in range(n_segs):
            s0 = seg_idx * self.seg_length_m
            s1 = min(s0 + self.seg_length_m, pipe_length)

            # Normalised segment bounds (0–1 within pipe)
            x0_seg = s0 / pipe_length
            x1_seg = s1 / pipe_length

            weighted_sum = 0.0
            overlap_total = 0.0
            n_overlapping = 0

            for pa in parcels:
                ov0 = max(pa['x0'], x0_seg)
                ov1 = min(pa['x1'], x1_seg)
                if ov1 <= ov0:
                    continue
                overlap_frac = ov1 - ov0
                weighted_sum += pa['q'] * overlap_frac
                overlap_total += overlap_frac
                n_overlapping += 1

            conc = weighted_sum / overlap_total if overlap_total > 0 else 0.0

            results.append({
                'seg_id':    seg_idx + 1,
                'x_start_m': round(s0, 6),
                'x_end_m':   round(s1, 6),
                'x_mid_m':   round((s0 + s1) / 2, 6),
                'length_m':  round(s1 - s0, 6),
                'conc':      conc,
                'n_parcels': n_overlapping,
            })

        return results

    # ------------------------------------------------------------------
    # Network-level convenience
    # ------------------------------------------------------------------

    def segment_network(
        self,
        network: Any,
        species: str,
        units: str = 'mg',
    ) -> pd.DataFrame:
        """
        Segment all pipes in *network* and return a tidy DataFrame.

        Parameters
        ----------
        network : epynet Network object
            Used to iterate over ``network.pipes``.
        species : str
            Chemical element / species name.
        units : str
            Concentration units string.

        Returns
        -------
        pandas.DataFrame
            Columns: ``pipe``, ``seg_id``, ``x_start_m``, ``x_end_m``,
            ``x_mid_m``, ``length_m``, ``conc``, ``n_parcels``.
            The ``conc`` column contains concentrations in *units* per litre.
        """
        rows: List[Dict] = []
        for pipe in network.pipes:
            segs = self.segment_pipe(pipe, species, units)
            for s in segs:
                rows.append({'pipe': pipe.uid, **s})

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        # Reorder columns for readability
        col_order = ['pipe', 'seg_id', 'x_start_m', 'x_end_m',
                     'x_mid_m', 'length_m', 'conc', 'n_parcels']
        return df[col_order].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Time-series recording
    # ------------------------------------------------------------------

    def record_step(
        self,
        network: Any,
        species: str,
        units: str = 'mg',
        time_s: Optional[float] = None,
        step: Optional[int] = None,
    ) -> None:
        """
        Record segment concentrations for the current simulation state.

        Call this inside your simulation loop after
        ``Victoria.step()``.  Retrieve the full time-series with
        :meth:`to_dataframe`.

        Parameters
        ----------
        network : epynet Network
            Used to iterate over pipes.
        species : str
            Chemical element / species name.
        units : str
            Concentration units string.
        time_s : float, optional
            Elapsed simulation time in seconds.  Stored as-is if provided.
        step : int, optional
            Step counter.  Stored as-is if provided.
        """
        for pipe in network.pipes:
            segs = self.segment_pipe(pipe, species, units)
            for s in segs:
                record: Dict = {'pipe': pipe.uid}
                if step is not None:
                    record['step'] = step
                if time_s is not None:
                    record['time_s'] = time_s
                    record['time_min'] = round(time_s / 60, 4)
                record.update(s)
                self._time_records.append(record)

    def to_dataframe(self) -> pd.DataFrame:
        """
        Return all recorded time-series data as a tidy DataFrame.

        Returns
        -------
        pandas.DataFrame
            Columns depend on whether ``time_s`` / ``step`` were supplied
            to :meth:`record_step`, but always include ``pipe``,
            ``seg_id``, and ``conc``.

        Notes
        -----
        Calling this method does **not** clear the internal buffer.
        Call :meth:`reset` to start a new recording.
        """
        if not self._time_records:
            return pd.DataFrame()
        return pd.DataFrame(self._time_records).reset_index(drop=True)

    def reset(self) -> None:
        """Clear all previously recorded time-series data."""
        self._time_records = []

    # ------------------------------------------------------------------
    # Metadata helper
    # ------------------------------------------------------------------

    def pipe_metadata(self, network: Any) -> pd.DataFrame:
        """
        Return a summary of segment counts per pipe.

        Parameters
        ----------
        network : epynet Network

        Returns
        -------
        pandas.DataFrame
            Columns: ``pipe``, ``pipe_length_m``, ``seg_length_m``,
            ``n_segs``, ``last_seg_m``.
        """
        rows = []
        for pipe in network.pipes:
            L = getattr(pipe, 'length', 0.0)
            if L <= 0:
                continue
            n = math.ceil(L / self.seg_length_m)
            last = L - (n - 1) * self.seg_length_m
            rows.append({
                'pipe':         pipe.uid,
                'pipe_length_m': round(L, 4),
                'seg_length_m': self.seg_length_m,
                'n_segs':       n,
                'last_seg_m':   round(last, 4),
            })
        return pd.DataFrame(rows).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"PipeSegmentation(seg_length_m={self.seg_length_m}, "
            f"recorded_steps={len(self._time_records)})"
        )
