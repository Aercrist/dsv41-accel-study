<!-- generated from docs/templates/06_simulator.md.j2 by experiments/render_docs.py; edit the template -->
# 06 · The simulator

`sim/` is an analytical plus op-level, cycle-approximate performance model. It is parameterized by
YAML (`configs/hw/*.yaml`) and driven by the model's own config and checkpoint manifest. One decode
step of DeepSeek-V4.1-Flash is about 554 ops at batch 1; a simulation takes a few ms, so the
experiment suite runs thousands of them in about 20 s.

```
data/                         raw inputs: HF config, checkpoint manifest (safetensors headers), reported numbers
sim/modelspec.py              shapes + bytes per tensor; reproduces 552B / 196B / 16B / 8B / 890 B/token
sim/workload.py               op graph of one decode step (DSpark draft + 6-row verify + heads), with TP sharding
sim/routing.py                expected distinct experts per step (uniform, or with locality)
sim/engine.py                 event-driven scheduler: compute, HBM (chunked, prioritized), links
sim/calibrate.py              2-parameter GPU fit + leave-one-out validation
sim/prefill.py                chunked roofline prefill (CED path), uncalibrated
sim/energy.py, sim/cost.py    bottom-up ASIC area/power/cost; GPU TDP and rental/owned cost
sim/expert_cache.py           LRU/LFU/Belady/Che expert-cache study on synthetic traces
experiments/*.py              every table and figure in docs/04
rtl/                          MoE top-k router, SystemVerilog + Icarus testbench vs numpy
```

## Workload model

`decode_step()` emits one `Op` per projection, attention, indexer, top-k, router, expert block,
mHC mix, collective and head. Each carries:

* weight bytes split three ways: sharded across chips (`w_tp`), replicated on every chip
  (`w_rep`), and data-dependent routed experts (`w_dyn`). Bytes come from the checkpoint's on-disk
  format, including scale tensors;
* cache bytes (SWA ring, top-k latent KV, index K scan);
* FLOPs by precision (FP4xFP8, FP8, BF16, FP32), split into sharded and replicated;
* all-reduce and all-gather payloads;
* the number of GPU kernels the op maps to in deepseek-ultrafast (approximate, from `model.rs`).

Routed-expert bytes use the expected number of distinct experts among the step's rows (`routing.py`).
With batch ≥ 2 the step is split into two micro-batches whose ops interleave. They share weight
fetches, and the second micro-batch fetches only the experts the first did not.

## Execution model (`engine.py`)

One chip of the TP group is simulated; the others are symmetric.

* **Compute** issues ops in program order and is occupied for each op's compute time
  (FLOPs / (peak x efficiency x M-utilization)).
* **An op ends** when its compute is done and all its bytes have arrived, plus collective time.
  Collective time = latency + 2·S·(n−1)/n / link bandwidth.
* **HBM** serves 4 MB chunks at `hbm_bw x hbm_eff`. When it frees, it picks the earliest-in-program-order
  chunk that is *ready*. When a chunk becomes ready depends on the execution policy:

| policy | static weights ready | routed experts ready | overhead per op |
|---|---|---|---|
| GPU kernels (`prefetch: false`) | when the op starts | when the op starts | `kernel_overhead` x kernels |
| dataflow (`prefetch: true`) | as soon as the staging buffer (`stage_bytes`) has room | `router_latency` after the gate op ends (+ first-byte latency) | `op_overhead` (pipeline fill/drain) |

* **Critical path.** Walking back from the last op along the binding dependency (data, or the
  compute-issue front) attributes every microsecond of the step to overhead, collective, memory or
  compute. That attribution is what `fig_step_breakdown` shows.

At batch 1 the graph is a chain, and the model reduces to
`end_i = max(end_{i-1} + overhead_i + compute_i, fetch_done_i) + collective_i`.

<a id="calibration"></a>

## Calibration

Fitted on the two measured step times: η (HBM efficiency) = 0.774 and
κ (exposed latency per dependent kernel stage) = 3.71 µs. Every
other GPU constant is a published spec or a sourced prior. The as-built engine is modeled with its
padded expert layout, fused producer-pushed all-reduces, side streams, and replicated decode indexer.
Leave-one-out with η pinned to STREAM: +3.8% (TP8 from TP4) and
-3.1% (the reverse). This is a weak test; see [04](04_results.md#calibration)
for what the data do and do not pin.

## Symmetric constants

Platforms differ only in YAML constants, so a comparison is only as fair as its constants. Where the
physics is the same, the constant is the same on every platform: HBM efficiency (calibrated),
DRAM first-byte latency (0.5 µs) and collective latency (1.4 µs computed speed-of-light). Where a
mechanism differs, the constant differs and the mechanism is written next to it in the YAML:
* per-stage hand-off: GPU today κ (fitted); GPU barrier 1 µs; GPU flags 0.5 µs; MDA-1 on-chip 0.2 µs;
* router: GPU 0.5 µs; MDA-1 0.1 µs (RTL).

Joint uncertainty over all of them is in `monte_carlo()` (`experiments/decode_experiments.py`).

## Cross-checks

| check | result |
|---|---|
| parameter counts, KV bytes vs the tech report | exact to the paper's precision |
| decode FLOP growth 4K → 1M vs paper Fig. 2 | +33% vs +25% (see [01](01_workload.md)) |
| matrix-engine utilization vs SCALE-Sim v3 | model was 1.5-1.7x optimistic; corrected |
| router RTL vs numpy | 256/256, 98 cycles |
| `pytest tests/` | invariants: byte conservation, batch-1 chain equivalence, monotonicity in bandwidth/latency, calibration reproduces measurements |
| independent adversarial review | 9 classes of problems found and fixed ([05](05_limitations.md#revisions-after-adversarial-review)) |

## Tools we did not use

Timeloop/Accelergy, LLMCompass and ASTRA-sim target dense layer mapping, GPU-style kernels or
large-scale training collectives. None of them models the data-dependent expert fetch behind a gate
or a static prefetch window, which is what decides this design. We used SCALE-Sim where a mature
tool answers a narrow question (matrix-engine utilization). Porting the op graph to ASTRA-sim's
execution-trace format is a natural next step for multi-node studies.

## Extending

* New hardware: copy a YAML in `configs/hw/` (`extends:` works) and add it to `experiments/platforms.py`.
* New model: point `ModelSpec.load()` at another config and manifest. `workload.py` encodes
  V4.1's structure (CSA2 modes, CED, DSpark), so a different architecture needs its own builder.
