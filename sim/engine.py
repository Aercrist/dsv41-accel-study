"""Op-level, cycle-approximate scheduler for one decode step on one chip of a TP group.

All chips of the TP group run the same program on their shard, so one chip is simulated and
collectives are costed with `Hardware.coll_time`. Resources:

  * compute: executes ops in program order (the step is a dependency chain);
  * HBM: a bandwidth server that moves weight/KV bytes in chunks. Which chunk goes next is
    chosen work-conservingly by program order among the chunks that are *ready*;
  * links: collectives (latency + bytes / bandwidth), on the critical path.

The two execution policies differ only in when a chunk becomes ready:

  * `prefetch=False` (GPU kernels): an op's bytes are fetched by its own kernel, so they are
    ready when the op starts, and every op pays `kernel_overhead` per kernel boundary.
  * `prefetch=True` (statically scheduled dataflow): weights whose addresses are known ahead
    of time (everything except routed experts and top-k-selected KV) stream in as early as the
    staging buffer (`stage_bytes`) allows; routed-expert fetches are issued `router_latency`
    after the gate op finishes; each op pays `op_overhead` of pipeline fill/drain.

Times are in seconds.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from .hardware import Hardware
from .workload import Op

CHUNK = 4 << 20  # HBM scheduling granularity (bytes)
LOOKAHEAD = 256  # chunks the prefetcher considers at once


@dataclass
class OpTiming:
    op: Op
    start: float
    end: float
    fetch_done: float
    t_comp: float
    t_coll: float
    t_ovh: float
    hbm_bytes: float


@dataclass
class StepResult:
    step_time: float
    timings: list[OpTiming]
    hbm_busy: float
    hbm_bytes: float
    breakdown: dict = field(default_factory=dict)  # exposed time by cause
    by_category: dict = field(default_factory=dict)  # exposed time by op category


def _op_costs(op: Op, hw: Hardware, hit_rate: float):
    n = hw.n_chips
    static = op.w_tp / n + op.w_rep + op.kv_tp / n
    if hw.engram_in_hbm:
        static += op.host / n
    dyn = op.w_dyn / n * (1.0 - hit_rate) + op.kv_rep
    sram_t = (op.w_dyn / n * hit_rate) / hw.sram_bw if (hit_rate > 0 and hw.sram_bw > 0) else 0.0
    if op.kind == "topk":
        elems = op.flops.get("fp32", 0.0) / 4.0 / n
        t_comp = elems / hw.topk_rate
    else:
        t_comp = 0.0
        for p in set(op.flops) | set(op.flops_rep):
            f = op.flops.get(p, 0.0) / n + op.flops_rep.get(p, 0.0)
            if f <= 0:
                continue
            eff = 1.0 if op.kind in ("vector", "router") else hw.mm_eff
            t_comp += f / (hw.peak[p] * eff)
    t_coll = hw.coll_time(op.coll)
    if op.gather > 0 and n > 1:
        t_coll += hw.coll_latency + op.gather * (n - 1) / hw.link_bw
    if not hw.engram_in_hbm and op.host > 0 and not hw.prefetch:
        t_coll += hw.host_latency + op.host / n / hw.host_bw
    rounds = (op.serial_rounds - 1) * hw.serial_round_latency
    if hw.prefetch:
        ovh = (hw.op_overhead if op.kind != "collective" else 0.0) + rounds
    else:
        ovh = hw.kernel_overhead * op.n_kernels + rounds
    return static, dyn, sram_t, t_comp, t_coll, ovh


def simulate_step(ops: list[Op], hw: Hardware, hit_rate: float = 0.0) -> StepResult:
    n_ops = len(ops)
    costs = [_op_costs(o, hw, hit_rate) for o in ops]
    bw = hw.hbm_bw * hw.hbm_eff

    # source op of each data-dependent fetch: routed experts wait for the most recent gate
    src = [-1] * n_ops
    last_gate = -1
    for i, o in enumerate(ops):
        if o.kind == "router":
            last_gate = i
        src[i] = last_gate if o.name == "routed_experts" else i - 1

    # chunk list in program order: (op, is_dynamic, bytes, first_of_request)
    chunks: list[tuple[int, bool, float, bool]] = []
    remaining = [0] * n_ops
    for i, (st, dy, *_rest) in enumerate(costs):
        for dyn, b in ((False, st), (True, dy)):
            first = True
            while b > 1e-9:
                c = min(b, CHUNK)
                chunks.append((i, dyn, c, first))
                remaining[i] += 1
                b -= c
                first = False

    ends: list[float | None] = [None] * n_ops
    starts: list[float | None] = [None] * n_ops
    fetch_done = [0.0] * n_ops
    hbm_bytes_op = [0.0] * n_ops
    pending = list(range(len(chunks)))  # indices into chunks, program order
    t_h = 0.0
    busy = 0.0
    i_res = 0
    issued_static: dict[int, float] = {}  # op -> static bytes issued and not yet consumed

    def start_of(i: int) -> float | None:
        if i == 0:
            return costs[0][5]
        e = ends[i - 1]
        return None if e is None else e + costs[i][5]

    def resolve() -> None:
        nonlocal i_res
        while i_res < n_ops and remaining[i_res] == 0:
            i = i_res
            st = start_of(i)
            static, dyn, sram_t, t_comp, t_coll, _ = costs[i]
            starts[i] = st
            fd = max(fetch_done[i], st) if (static + dyn) > 0 else st
            ends[i] = max(st + t_comp, fd) + sram_t + t_coll
            fetch_done[i] = fd
            i_res += 1

    def buffer_ready_time(nbytes: float, t0: float) -> float:
        """Earliest t >= t0 at which `nbytes` more static bytes fit in the staging buffer."""
        cap = hw.stage_bytes
        held_unknown = 0.0
        releases = []
        for k, b in issued_static.items():
            e = ends[k]
            if e is None or e > t0:
                if e is None:
                    held_unknown += b
                else:
                    releases.append((e, b))
        held = held_unknown + sum(b for _, b in releases)
        if held + nbytes <= cap:
            return t0
        releases.sort()
        for e, b in releases:
            held -= b
            if held + nbytes <= cap:
                return e
        return float("inf")

    resolve()
    while pending:
        best_pos, best_t = None, float("inf")
        for pos in range(min(LOOKAHEAD, len(pending))):
            ci = pending[pos]
            i, dyn, b, first = chunks[ci]
            if not hw.prefetch or (dyn and ops[i].name != "routed_experts"):
                st = start_of(i) if i == i_res else None
                rt = float("inf") if st is None else st
            elif dyn:  # routed experts: issued after the gate resolves
                e = ends[src[i]]
                rt = float("inf") if e is None else e + hw.router_latency
            elif pos == 0:
                rt = 0.0
            else:
                rt = buffer_ready_time(b, t_h)
            t = max(t_h, rt)
            if t < best_t:
                best_pos, best_t = pos, t
                if t <= t_h:
                    break  # earliest-in-program-order chunk that is ready now
            if not hw.prefetch and i > i_res:
                break
        assert best_pos is not None and best_t < float("inf"), "scheduler deadlock"
        ci = pending.pop(best_pos)
        i, dyn, b, first = chunks[ci]
        lat = hw.hbm_latency if (dyn and first and hw.prefetch) else 0.0
        dur = b / bw
        t_h = best_t + lat + dur
        busy += dur
        if not dyn:
            issued_static[i] = issued_static.get(i, 0.0) + b
        hbm_bytes_op[i] += b
        fetch_done[i] = max(fetch_done[i], t_h)
        remaining[i] -= 1
        if remaining[i] == 0:
            resolve()
            for k in [k for k in issued_static if ends[k] is not None and k < i_res]:
                if ends[k] <= t_h:
                    del issued_static[k]
    resolve()

    step = ends[-1] + hw.step_overhead
    timings = []
    breakdown = {"overhead": hw.step_overhead, "collective": 0.0, "memory": 0.0, "compute": 0.0}
    by_cat: dict[str, float] = {}
    prev = 0.0
    for i, o in enumerate(ops):
        static, dyn, sram_t, t_comp, t_coll, ovh = costs[i]
        tm = OpTiming(o, starts[i], ends[i], fetch_done[i], t_comp, t_coll, ovh, hbm_bytes_op[i])
        timings.append(tm)
        exposed = ends[i] - prev
        body = exposed - ovh - t_coll
        breakdown["overhead"] += ovh
        breakdown["collective"] += t_coll
        if fetch_done[i] - starts[i] > t_comp + sram_t:
            breakdown["memory"] += max(0.0, body)
        else:
            breakdown["compute"] += max(0.0, body)
        by_cat[o.category] = by_cat.get(o.category, 0.0) + exposed
        prev = ends[i]
    return StepResult(step, timings, busy / step if step else 0.0, sum(hbm_bytes_op), breakdown, by_cat)
