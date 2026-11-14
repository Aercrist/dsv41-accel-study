"""Run every experiment and regenerate results/ and the generated docs. `make reproduce`."""
from __future__ import annotations

import time


def main() -> None:
    t0 = time.time()
    from experiments import decode_experiments, prefill_tradestudy, render_docs, scalesim_crosscheck, workload_analysis
    steps = [("workload analysis (Phase 1)", workload_analysis.main),
             ("SCALE-Sim cross-check", scalesim_crosscheck.run),
             ("decode experiments (calibration, comparison, sweeps, tornado, ablation)", decode_experiments.main),
             ("prefill / TTFT / trade study", prefill_tradestudy.main),
             ("render docs from results", render_docs.main)]
    for name, fn in steps:
        t = time.time()
        fn()
        print(f"[{time.time() - t:6.1f}s] {name}")
    print(f"done in {time.time() - t0:.1f}s; see results/ and docs/")


if __name__ == "__main__":
    main()
