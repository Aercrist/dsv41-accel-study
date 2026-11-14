<!-- generated from docs/templates/02_design_rationale.md.j2 by experiments/render_docs.py; edit the template -->
# 02 · Design rationale: what to build, and why

The bottleneck ([01](01_workload.md)) decides the target. Batch-1 decode of DeepSeek-V4.1-Flash
streams about 9.6 GB per chip per step at TP4, 74% of it FP4
routed experts that are known only after each layer's gate. Today
58% of the step is fixed per-layer latency. The arithmetic needed per step
is about 229 GFLOP, which a B300 could do in under 50 µs.
**The platform must convert HBM bandwidth into tokens with almost no per-layer overhead.
It does not need many FLOPs.**

## The options, quantified

Every row below comes from the same simulator and workload (batch 1, context 2.6K, acceptance 5.6), except where marked.

| option | chips | tok/s/user | system kW | tokens/J | $/M tok | memory capacity |
|---|---|---|---|---|---|---|
| 4x GB300, deepseek-ultrafast (calibrated) | 4 | 1,697 | 3.4 | 0.505 | 6.22 | 1,152 GB |
| 4x GB300, ideal software (bound) | 4 | 3,151 | 3.4 | 0.938 | 3.35 | 1,152 GB |
| 16x Alveo V80 FPGA | 16 | 1,179 | 2.4 | 0.485 | 1.36 | 512 GB |
| MDA-1 ASIC x4 (proposed) | 4 | 4,040 | 1.6 | 2.453 | 0.24 | 768 GB |
| SRAM-only dataflow (GroqChip-class) (1518 chips, 35 per layer) | 1,518 | 9,462 | 280.8 | 0.034 | no public price | 349 GB |
| Wafer-scale (WSE-3-class, 8 wafers) | 8 | 7,813 | 184.0 | 0.042 | no public price | 352 GB |

GPU $/M tokens is at the **market rental** price ($9.50/GPU-hr, [sources](sources.md#gpu-baseline)); the ASIC
row is **owned TCO including NRE**. The two bases are not comparable, so [04](04_results.md#cost) also
puts the GPU on an owned basis. The SRAM-only and wafer-scale rows are idealized first-order bounds
(see `experiments/prefill_tradestudy.py`): they size the system by weight capacity
(307 GB resident) and assume optimistic fabric latencies.

### FPGA (AMD Alveo V80 / Versal HBM class)

* **Capacity forces 16 cards.** Each V80 has 32 GB of HBM2e at 819 GB/s, so ~300 GB of weights needs ≥10 cards (16 for power-of-two sharding). The aggregate bandwidth (13 TB/s) is less than half of 4 x GB300 (32 TB/s).
* **Compute is thin.** The DSP58 fabric gives ~35 TFLOP/s-equivalent of FP8 per card, so the drafter and the 6-row verify GEMVs become partly compute-bound (0.92 ms of compute on the critical path; `results/decode.json`).
* **Result: 1,179 tok/s/user, below the GPU baseline**, at 0.48 tok/J.
* **What FPGA is good for here:** a zero-NRE prototype of the *control* ideas: the static schedule, the hardware router, prefetch and collectives. It can de-risk the ASIC's architecture. It is not a deployment vehicle for a 550B model.

### SRAM-only dataflow (Groq-class) and wafer-scale (Cerebras-class)

* **Capacity sets chip count, not bandwidth.** 307 GB of FP4/FP8 weights needs 1,518 chips of 230 MB or 8 wafers of 44 GB per model replica, at 281 kW and 184 kW.
* **Batch-1 per-user speed can be very high,** because SRAM bandwidth is effectively unlimited (an idealized 9,462 and 7,813 tok/s/user).
* **Energy per token at low batch is 12-15x worse than the GPU.** These systems recover only by pipelining hundreds of concurrent requests through the layer groups.
* **They are also exposed to model churn.** A 1.5k-chip replica is laid out for one model's size.
* MoE makes this worse than for dense models: 91% of each layer's experts sit idle in SRAM at batch 1.

### Model-specific silicon (Etched-style) vs. a decode-specialized programmable ASIC

DeepSeek shipped V3, V3.2, V4 and V4.1 within about two years. Each changed the attention
mechanism (MLA → DSA indexer → CSA/HCA → CSA2 with cross-layer reuse) and the KV format. A chip
that hard-wires V4.1's dataflow risks obsolescence before it reaches volume. What *has* been stable
across those generations, and across Kimi, GLM and Qwen MoEs, is narrower:

1. very low-batch decode of fine-grained MoE,
2. FP8/FP4 block-scaled weights,
3. top-k selection (routing and sparse-attention indexing), and
4. tiny-message collectives.

MDA-1 hard-wires only those primitives. Everything model-specific (layer order, CSA2 modes,
mHC, DSpark) is a compiled static schedule.

### ASIC (chosen)

An HBM-based, statically scheduled decode chip, built to match the bottleneck:

| decision | choice | reason (number from this study) |
|---|---|---|
| target phase | **decode only**; prefill stays on GPUs (disaggregated) | prefill is compute-bound (01 §4); KV hand-off costs only 890 B/token (≈0.12 ms for a 4K-token turn over 400 Gb/s RDMA) |
| memory | 8 x HBM3E per chip at 8 TB/s (iso-bandwidth with B300) | bandwidth sets speed; iso-bandwidth isolates the architectural gain from memory-technology gains |
| HBM capacity | 8-Hi 24 GB stacks (192 GB/chip), not 12-Hi | the weights need about 76 GB/chip at TP4; same bandwidth, lower cost |
| Engram tables | LPDDR5X beside each chip | 203 GB of tables, but 76 kB of lookups per step, with addresses known in advance |
| compute | 2 PF FP8 / 4 PF FP4xFP8 dense per chip (40% of B300) | batch-1 needs about 0.2 PF effective; 2 PF keeps the chip on the GPU's batch-64 frontier (04 §batch) |
| matrix engine shape | 16 rows x wide N, weight-streaming | SCALE-Sim: a 128x128 array reaches 0.3-1.5% utilization on decode GEMVs (04 §SCALE-Sim) |
| SRAM | 256 MiB (≥32 MB staging needed) | 32 MB of staging captures the full prefetch benefit (`fig_sram_sweep`); the rest holds KV, batch staging and scratch, and fits in die area that HBM shoreline forces on the chip anyway |
| scheduling | static, compiler-generated, no kernels | removes the 1.9 ms of fixed overhead (01 §6) |
| collectives | in-fabric all-reduce over a direct 4-chip mesh | 2 per layer on the critical path; latency set equal to the measured NVLink speed-of-light (1.4 µs) |
| process | **TSMC N4P (N5 family)**, not N3E | SRAM bitcell is the same 0.021 µm² on N5 and N3E ([sources](sources.md)), and the die is HBM-shoreline-bound (448 mm², 44 mm² of it whitespace), so N3 would buy almost no area at about 20% higher wafer cost and higher NRE |

## What a seasoned accelerator architect would weigh

* **The software counterfactual.** The best plausible GPU software (megakernel + L2 prefetch + 2.37 µs all-reduce) reaches 3,151 tok/s/user on the same 4 x GB300: 1.9x of today's. MDA-1 is 1.28x beyond that bound at 4 chips, and 1.51x at 8. **The silicon case rests on strong scaling, energy and cost, not batch-1 speed at 4 chips.** We would tell Baseten to chase the software headroom first. It is free and nearly doubles speed.
* **NRE amortization dominates ASIC cost.** At $300M NRE and 20K chips, NRE is $15,000 of the $28,843 per-chip cost; the die is only $207. Break-even production volume against GPUs owned at $45K each is about 6,420 chips against ideal GPU software (2,994 against today's), and twice that at $600M NRE (batch 1; tornado in [04](04_results.md#tornado)). At hyperscaler volumes this is easy; for a single inference provider it is the crux.
* **Time to market.** Our assumption is about 24-30 months from start to volume for a reticle-class N4P die with HBM3E (team-dependent; not sourced). Rubin (HBM4, 19-22 TB/s) is shipping now. The comparison that matters at launch is MDA-1-HBM4 vs Rubin ([04](04_results.md#next-generation)). Rubin with today's per-layer overheads gains only 37% over GB300 despite 2.75x the bandwidth.
* **Perf/W.** 2.45 vs 0.51 tokens/J (4.9x). About half comes from finishing the step sooner; the other half from not carrying 5 PF of idle tensor cores. The GPU figure is an assumption (60% of TDP, swept 40-100%).
* **Risk register.** HBM3E supply and CoWoS capacity (shared with the GPU vendors), the compiler (a static scheduler for a new model per quarter), the 1.4 µs collective target, and dependence on low-batch, latency-priced demand. If the market prices only throughput, GPUs at batch 256 are within 1.11x of MDA-1 per 4 chips.
