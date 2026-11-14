<!-- generated from docs/templates/05_limitations.md.j2 by experiments/render_docs.py; edit the template -->
# 05 · Limitations and assumptions

**This is a modeled projection, not silicon.** MDA-1 has not been designed beyond the block level,
synthesized (except for the router sketch), placed, timed or fabricated. Every MDA-1 and GPU-software
number is the output of a Python performance model whose inputs are listed below. GPU numbers labelled
*measured* are quoted from the deepseek-ultrafast README. We did not run the engine or profile GPUs.

## What is validated, and how far

| claim | validation | strength |
|---|---|---|
| model shapes and bytes | parameter counts, activated params and 890 B/token KV from checkpoint headers ([01](01_workload.md#2-architecture-numbers)) | strong |
| GPU decode step model | 2-parameter fit to 2 points. Leave-one-out +3.8% / -3.1%, but low power: any η prior from 0.70 to 0.90 passes within ~3% | **weak** |
| "about half the step is fixed latency" | 36%-57% across 10 refits, including the README's run-to-run extremes; consistent with published barrier and all-reduce latencies | moderate. Not confirmed by a profile; `tools/model_vs_nsys.py` prints the prediction in the engine's own `nsys_breakdown.py` groups. The split between collectives and other stages is **not** identified |
| GPU dataflow-style software ≈ MDA-1 speed | same simulator, same-physics constants; Monte Carlo 1.00x-1.20x | moderate. Nobody has built either |
| MDA-1 decode speed | bottom-up; joint Monte Carlo 1.68x-2.34x vs measured | **unvalidated**: no silicon, no RTL beyond the router |
| matrix-engine utilization | SCALE-Sim cross-check (led to a 1.6x correction) | moderate (compute stage only) |
| router latency | RTL verified in simulation, 256/256 vs a golden model | strong for function, weak for timing (not synthesized) |
| prefill / TTFT | **not validated**: measured prefill is 5.4x slower than our model; TP scaling mispredicted by -15% | weak; reported for completeness |
| cost, energy | first-order, sourced constants where they exist; GPU power and price are assumptions, so ratios are reported as ranges | weak to moderate |

## Every assumption

Sourced constants are keyed in [sources.md](sources.md). **A** marks assumptions with no public source;
the ones that matter are swept (tornado, Monte Carlo, or GPU price/power tables in [04](04_results.md#cost)).

**Workload**
* Batch 1, context about 2.6K, acceptance 5.6 tokens/step (README mean). The README's 1,740 tok/s x 3.30 ms implies 5.74. The README's range reaches 6.1, which exceeds the 6-row verify maximum, so its definition probably differs. We sweep 5.1-6.0. Verify is modeled at 6 rows; the engine adapts the length.
* **A** Expert routing is independent across a step's 6 rows (`locality = 0`). Locality 0.5 would cut bytes on every platform. The calibration then needs η = 0.53.
* **A** Kernel stages per op (`Op.n_kernels`, 388 per step) are our reading of `model.rs`, not a trace. All-reduces are treated as fused into producers (no extra stage); side-stream work (indexer weights, compressor, mHC dots, `main_proj`) carries no stage on the critical path. Only the product with κ is calibrated.
* Expert bytes on the GPU baseline use the engine's padded in-memory layout (`packing.rs::sgl_expert_bytes`, default on sm_103). **A**: we assume the padding is streamed from HBM.
* Decode indexer scan and top-k run replicated on every rank, as the engine does (`model.rs::idx_rows`).
* Engram tables sit in GPU HBM on the baseline, as in the engine, and in LPDDR on MDA-1. The vision tower is not modeled.

**GPU baseline and projections**
* Peak specs per NVIDIA/OEM pages (GB300 8 TB/s; HGX B300 7.7 TB/s, 4.5 PF FP8 dense). Calibrated: η = 0.774, κ = 3.71 µs per dependent stage.
* The all-reduce latency prior is 2.37 µs (sourced; the engine's one-shot NVLS design is closest to it). Alternatives of 5 and 10 µs fit equally well.
* **A** GPU power is 60% of TDP during batch-1 decode (swept 40-100%). We did not measure it, so every tokens/J ratio involving a GPU is a range.
* **A** GPU owned cost is $45K per GPU all-in (no public B300/GB300 price; swept $25-65K). The rental price, $9.50/GPU-hr, is sourced.
* **A** The dataflow-style software projection uses a 0.5 µs flag hand-off (sourced L2 round trip 0.306 µs plus tail), a 0.5 µs router, a 64 MB L2 staging slice (L2 size not sourced), the same DRAM first-byte latency as MDA-1 (0.5 µs), and the computed NVLink all-reduce speed-of-light (1.4 µs). It has not been demonstrated for this model.
* Rubin: 19.2 TB/s (NVL72 page; the HGX page says 22). **A** 1.8 kW power. Today's software constants are carried over unchanged.

**MDA-1**
* Package: 2 dies x 4 HBM3E 8-Hi at 8 TB/s total (sourced stack specs, run below their rating). η = the GPU's calibrated value (same HBM).
* **A** HBM cube shoreline 11 mm; per-op hand-off 0.2 µs; dependent-fetch latency 0.5 µs; router 0.1 µs (RTL 65 ns plus margin); collective 1.4 µs (computed NVLink speed-of-light for 2 x GB200, no link advantage assumed). All swept jointly.
* **A** Compute: 2 PF FP8 / 4 PF FP4 at 1.5 GHz, matrix efficiency 0.5 (SCALE-Sim-corrected), 16-row engine.
* **A** Area: SRAM 0.5 mm²/MiB (sourced density x2); FP8 MAC 80 µm², SerDes 0.7 mm²/lane (72 x 112G) and die-to-die 10 mm²/die are not sourced; HBM PHY 12 mm² comes from an unverified GUC figure.
* Energy: HBM 4.0 pJ/bit (HBM2 figure); SRAM 0.5 pJ/bit (**A**); NoC 0.5 pJ/bit (**A**); 112G link 5 pJ/bit (sourced); die-to-die 0.25 pJ/bit (sourced); MAC energies from 7 nm tables x2 (**A**); static 150 W per package (**A**); 88% power-delivery efficiency (**A**).
* Cost: wafer $17K, D0 0.10, HBM3E $15/GB, CoWoS-L ~$2.1K plus test (all sourced). NRE $300M (**A**, within the sourced $280-542M range), volume 20K (**A**), system share $8K per package (**A**). Manufacturing cost, with no margin and no respin. The comparison is fair for a build-vs-buy decision, not for a merchant chip.
* Not simulated: the NoC at flit level; HBM at bank/row level (efficiency factor only); thermal and power delivery beyond a loss factor; refresh, ECC/RAS; the fabric needed beyond 4 packages.

**Not modeled at all**: request scheduling and queueing; prefix-cache hit rates; KV eviction and the
SSD tier; vision; reasoning-effort effects on output length; failures. The static-schedule compiler,
which both MDA-1 and the dataflow-style software need, is out of scope. It is the largest engineering risk.

## What would change the conclusions

* **A profile showing the GPU step is mostly HBM-bound** (fixed share well under 36%). The 2x software and silicon headroom would shrink accordingly.
* **A demonstrated dataflow-style runtime** would confirm the software path and weaken the silicon case further. A runtime stuck well short of it would strengthen the silicon case.
* **Measured GPU power** would replace the softest assumption behind the tokens/J ratio.
* **GPU prices under about $30K**, volume under about 9,000 packages ($300M NRE), or NRE near $600M: MDA-1 would no longer cost less per token than GPUs running the same software.

<a id="revisions-after-adversarial-review"></a>

## Revisions after adversarial review

An independent reviewer (instructed to find what experts would object to) flagged these problems in an
earlier version. All were fixed:

1. MDA-1's lead over "ideal GPU software" came from asymmetric constants. Same-physics constants are now shared; the software projection is a projection, not a bound; the result is parity (Monte Carlo above).
2. Eight HBM3E stacks on one 448 mm² die is not buildable. MDA-1 is now a 2-die package with 11 mm per stack of shoreline.
3. MDA-1's HBM efficiency was set *above* the GPU's calibrated value while being called conservative. It now uses the same value.
4. Robustness was reported one parameter at a time. It is now a joint Monte Carlo with the worst corner.
5. The fixed-latency share was presented as tighter than the data allow. It is now a range over 10 refits, including run-to-run extremes, and the low-efficiency alternatives are no longer dismissed (B200 STREAM is ~52% at 4-16 GB arrays).
6. The GPU baseline ignored the engine's fusions (PDL, producer-pushed NVLS all-reduce, side streams), its padded expert layout (+26% bytes at TP8) and its replicated decode indexer. All are now modeled; "kernel launch" became "dependent-stage latency".
7. Cost mixed rental and owned bases in one column, had no prefill-pool cost, and used 2026 HBM4 prices for a 2027 part. Fixed. Energy now includes NoC and power-delivery loss; ratios are ranges over GPU power.
8. The Rubin and 8-chip comparisons gave GPUs today's overheads and MDA-1 its own. Both now include a same-software GPU row; the 8-chip MDA-1 headline was dropped.
9. Text errors: B300 is 7.7 TB/s (MDA-1 matches GB300's 8); the batch-256 comparison was inverted; the 1.4 µs all-reduce is a computed bound for 2 x GB200, not a measurement; per-GPU byte tables were inconsistent between pages; acceptance cannot exceed 6 with a 5-token draft.
