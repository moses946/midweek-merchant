"""Minimal sparse MILP builder on top of HiGHS (highspy).

Variables are created in numpy-index blocks and constraints are accumulated as sparse
rows, which keeps model construction fast (no per-term Python expression objects).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import highspy
import numpy as np

INF = highspy.kHighsInf


@dataclass
class Solution:
    status: str
    objective: float
    x: np.ndarray
    gap: float
    runtime: float

    @property
    def ok(self) -> bool:
        return (
            self.status in ("Optimal", "Time limit reached", "Solution limit reached", "Interrupted by user")
            and self.x.size > 0
        )


class LinModel:
    def __init__(self) -> None:
        self.lb: list[float] = []
        self.ub: list[float] = []
        self.obj: list[float] = []
        self.integer: list[bool] = []
        self._rows_idx: list[np.ndarray] = []
        self._rows_val: list[np.ndarray] = []
        self.row_lo: list[float] = []
        self.row_hi: list[float] = []

    # ------------------------------------------------------------------ variables
    @property
    def n_vars(self) -> int:
        return len(self.lb)

    def add_vars(
        self, shape: int | tuple[int, ...], lb: float = 0.0, ub: float = 1.0, integer: bool = True
    ) -> np.ndarray:
        n = int(np.prod(shape))
        start = self.n_vars
        self.lb.extend([lb] * n)
        self.ub.extend([ub] * n)
        self.obj.extend([0.0] * n)
        self.integer.extend([integer] * n)
        return np.arange(start, start + n).reshape(shape)

    def add_var(self, lb: float = 0.0, ub: float = 1.0, integer: bool = True) -> int:
        return int(self.add_vars(1, lb, ub, integer)[0])

    def set_bounds(self, idx: int | np.ndarray, lb: float | None = None, ub: float | None = None) -> None:
        for i in np.atleast_1d(idx).ravel():
            if lb is not None:
                self.lb[int(i)] = lb
            if ub is not None:
                self.ub[int(i)] = ub

    def add_obj(self, idx: int | np.ndarray, coef: float | np.ndarray) -> None:
        idx = np.atleast_1d(idx).ravel()
        coef = (
            np.broadcast_to(np.asarray(coef, dtype=float), idx.shape).ravel()
            if np.ndim(coef)
            else np.full(idx.shape, float(coef))
        )
        for i, c in zip(idx, coef, strict=True):
            self.obj[int(i)] += float(c)

    # ------------------------------------------------------------------ constraints
    def add_row(
        self,
        idx: Sequence[int] | np.ndarray,
        val: Sequence[float] | np.ndarray | float,
        lo: float = -INF,
        hi: float = INF,
    ) -> None:
        idx = np.asarray(idx, dtype=np.int64).ravel()
        val = (
            np.broadcast_to(np.asarray(val, dtype=float), idx.shape).ravel()
            if np.ndim(val)
            else np.full(idx.shape, float(val))
        )
        self._rows_idx.append(idx)
        self._rows_val.append(np.asarray(val, dtype=float))
        self.row_lo.append(lo)
        self.row_hi.append(hi)

    def le(self, idx, val, rhs: float) -> None:  # noqa: ANN001
        self.add_row(idx, val, -INF, rhs)

    def ge(self, idx, val, rhs: float) -> None:  # noqa: ANN001
        self.add_row(idx, val, rhs, INF)

    def eq(self, idx, val, rhs: float) -> None:  # noqa: ANN001
        self.add_row(idx, val, rhs, rhs)

    # ------------------------------------------------------------------ solve
    def solve(
        self,
        maximize: bool = True,
        time_limit: float = 60,
        mip_gap: float = 0.003,
        threads: int | None = None,
        verbose: bool = False,
    ) -> Solution:
        h = highspy.Highs()
        if not verbose:
            h.silent()
        h.setOptionValue("time_limit", float(time_limit))
        h.setOptionValue("mip_rel_gap", float(mip_gap))
        if threads:
            h.setOptionValue("threads", int(threads))
        n = self.n_vars
        lp = highspy.HighsLp()
        lp.num_col_ = n
        lp.num_row_ = len(self.row_lo)
        lp.col_cost_ = np.asarray(self.obj, dtype=float)
        lp.col_lower_ = np.asarray(self.lb, dtype=float)
        lp.col_upper_ = np.asarray(self.ub, dtype=float)
        lp.row_lower_ = np.asarray(self.row_lo, dtype=float)
        lp.row_upper_ = np.asarray(self.row_hi, dtype=float)
        lens = np.array([len(r) for r in self._rows_idx], dtype=np.int64)
        lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
        lp.a_matrix_.start_ = np.concatenate([[0], np.cumsum(lens)]).astype(np.int32)
        lp.a_matrix_.index_ = (np.concatenate(self._rows_idx) if self._rows_idx else np.array([])).astype(
            np.int32
        )
        lp.a_matrix_.value_ = np.concatenate(self._rows_val) if self._rows_val else np.array([])
        lp.integrality_ = [
            highspy.HighsVarType.kInteger if b else highspy.HighsVarType.kContinuous for b in self.integer
        ]
        lp.sense_ = highspy.ObjSense.kMaximize if maximize else highspy.ObjSense.kMinimize
        h.passModel(lp)
        h.run()
        status = h.modelStatusToString(h.getModelStatus())
        info = h.getInfo()
        sol = h.getSolution()
        x = np.asarray(sol.col_value) if sol.value_valid else np.array([])
        return Solution(
            status=status,
            objective=float(info.objective_function_value),
            x=x,
            gap=float(info.mip_gap),
            runtime=float(h.getRunTime()),
        )
