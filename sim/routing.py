"""Expert-routing statistics used by the workload builder.

`distinct_experts` is the expected number of distinct experts touched when R token-rows each
select k of E experts. With independent uniform routing (the auxiliary-loss-free balancer
targets uniform long-run load) this is E * (1 - (1 - k/E)^R). Real consecutive tokens share
experts more often than that; `locality` in [0, 1] shrinks the effective number of
independent rows, R_eff = 1 + (R - 1) * (1 - locality). locality = 0 (default) is the
pessimistic case: most bytes moved per step, for every platform alike.
"""
from __future__ import annotations


def distinct_experts(rows: float, k: int, n_experts: int, locality: float = 0.0) -> float:
    if rows <= 0:
        return 0.0
    r_eff = 1.0 + (rows - 1.0) * (1.0 - locality)
    return n_experts * (1.0 - (1.0 - k / n_experts) ** r_eff)


def rows_per_expert(rows: float, k: int, n_experts: int, locality: float = 0.0) -> float:
    """Average token-rows served by each touched expert (sets GEMM M for an expert)."""
    d = distinct_experts(rows, k, n_experts, locality)
    return rows * k / d if d else 0.0
