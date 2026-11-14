<!-- generated from docs/templates/02_design_rationale.md.j2 by experiments/render_docs.py; edit the template -->
# 02 · Design rationale: what to build, and why

The bottleneck ([01](01_workload.md)) decides the target. Batch-1 decode of DeepSeek-V4.1-Flash
streams about 10.2 GB per GPU per step at TP4. Most of it is FP4
routed experts that are known only after each layer's gate. About half the step
(36%-57%) is fixed per-stage latency. The arithmetic per step is
about 229 GFLOP, under 50 µs of one B300's tensor cores.
**The platform must turn HBM bandwidth into tokens with almost no per-stage overhead. It does not need many FLOPs.**

## The options, quantified

Every row comes from the same simulator and workload (batch 1, context 2.6K, acceptance 5.6).

| option | chips | tok/s/user | system kW | tokens/J | $/M tok (owned) | memory |
|---|---|---|---|---|---|---|
| 4x GB300, deepseek-ultrafast (calibrated) | 4 | 1,697 | 3.4 | 0.505 | 0.91 | 1,152 GB |
| 4x GB300, dataflow-style software (projected) | 4 | 3,486 | 3.4 | 1.037 | 0.44 | 1,152 GB |
| 16x Alveo V80 FPGA | 16 | 1,180 | 2.4 | 0.485 | 1.36 | 512 GB |
| MDA-1 x4 (proposed) | 4 | 3,482 | 1.8 | 1.917 | 0.28 | 768 GB |
| SRAM-only dataflow (GroqChip-class) (1518 chips, 35 per layer) | 1,518 | 10,848 | 280.8 | 0.039 | no public price | 349 GB |
| Wafer-scale (WSE-3-class, 8 wafers) | 8 | 7,806 | 184.0 | 0.042 | no public price | 352 GB |

All $/M tokens are on one **owned** basis: GPUs at an assumed $45K each all-in, MDA-1 at cost plus
amortized NRE, FPGA cards at list price plus a server share. GPU power is 60% of TDP (assumption).
The SRAM-only and wafer-scale rows are idealized first-order bounds (`experiments/prefill_tradestudy.py`).
They size the system by weight capacity (307 GB resident) and assume optimistic fabric latencies.

### Software on the GPUs you already have (the counterfactual that decides everything)

The cheapest accelerator is a better runtime. With the same physics as MDA-1 (same HBM efficiency,
DRAM latency and collective speed-of-light), a dataflow-style program on 4 x GB300 projects
**3,486 tok/s/user**, 2.0x the measured engine. MDA-1 is
1.00x-1.20x of that across the joint Monte Carlo. The software
needs no NRE and no new hardware. It does need engineering: one persistent program per model,
flag-based hand-offs, TMA L2 prefetch of the next layers' dense weights, an unpadded expert layout,
and a ~1.4 µs all-reduce. Nobody has shown this for a 43-block MoE across 4 GPUs. It is the first
thing we would build.

### FPGA (AMD Alveo V80 / Versal HBM class)

* **Capacity forces 16 cards.** 32 GB HBM2e at 819 GB/s per card; ~300 GB of weights needs ≥10 cards (16 for power-of-two sharding). The aggregate bandwidth, 13 TB/s, is below 4 x GB300's 32 TB/s.
* **Compute is thin.** The DSP58 fabric gives ~35 TFLOP/s-equivalent of FP8 per card, so the drafter and 6-row verify GEMVs become partly compute-bound (0.94 ms of compute on the critical path).
* **Result: 1,180 tok/s/user, below the GPU baseline.**
* **What FPGA is good for here:** a zero-NRE prototype of the *control* ideas (static schedule, hardware router, prefetch, collectives) to de-risk an ASIC. Not a deployment vehicle for a 550B model.

### SRAM-only dataflow (Groq-class) and wafer-scale (Cerebras-class)

* **Capacity sets chip count, not bandwidth.** 307 GB of FP4/FP8 weights needs 1,518 chips of 230 MB or 8 wafers of 44 GB per model replica, at 281 kW and 184 kW.
* **Batch-1 speed can be high** in an idealized model (10,848 and 7,806 tok/s/user), because SRAM bandwidth is effectively unlimited. But energy per token at low batch is 12-13x worse than today's GPUs. These systems recover only by pipelining hundreds of concurrent requests.
* MoE makes this worse than for dense models: 91% of each layer's experts sit idle in SRAM at batch 1.

### Model-specific silicon (Etched-style) vs a decode-specialized programmable ASIC

DeepSeek shipped V3, V3.2, V4 and V4.1 within about two years. Each changed attention (MLA → DSA
indexer → CSA/HCA → CSA2 with cross-layer reuse) and the KV format. A chip that hard-wires V4.1's
dataflow risks obsolescence before volume. What has been stable across those generations, and across
other open MoEs, is narrower:

1. very low-batch decode of fine-grained MoE,
2. FP8/FP4 block-scaled weights,
3. top-k selection (routing and indexing), and
4. tiny-message collectives.

MDA-1 hard-wires only those primitives; everything model-specific is a compiled static schedule.

### ASIC (MDA-1): what silicon adds on top of the software counterfactual

At iso-bandwidth, MDA-1's batch-1 speed is the same as good GPU software. Silicon adds four things:

1. **Cost per unit of HBM bandwidth.** About half of a B300's die area serves FLOPs this workload never uses. MDA-1 is two 336 mm² dies ($271 of silicon) around the same 8 stacks. The result is 1.6x lower $/M tokens than GPUs running the same software at $45K/GPU. At $25K/GPU it loses (0.93x).
2. **Energy.** 1.8x tokens/J against the same-speed GPU if the GPU draws 60% of TDP (range 1.2x-3.1x for 40-100%). We have not measured GPU power, so this is the softest claim here.
3. **Latency by construction.** The static schedule *is* the dataflow execution model. It does not depend on a heroic runtime, and the 0.2 µs on-chip hand-off leaves headroom as chips are added (+15% over the GPU software at 16 chips, with the same per-peer latency assumed).
4. **Capacity right-sizing.** Engram's 203 GB of tables need 76 kB per step, so they go to LPDDR. Weights then fit in 8-Hi stacks (192 GB), not 12-Hi.

| decision | choice | reason (number from this study) |
|---|---|---|
| target phase | **decode only**; prefill stays on GPUs | prefill is compute-bound (01 §4); KV hand-off is 890 B/token (0.12 ms for a 4K-token turn) |
| package | **2 dies x 4 HBM3E stacks**, die-to-die link (like B300) | an HBM3E cube is ~11 mm wide; 8 stacks cannot sit on one sub-reticle die |
| memory | 8 x HBM3E, 8 TB/s per package (= GB300) | iso-bandwidth isolates architecture from memory technology |
| compute | 2 PF FP8 / 4 PF FP4xFP8 per package (40% of B300) | batch-1 needs ~0.2 PF; 2 PF keeps the batch-64 frontier near the GPU's |
| matrix engine | 16 rows x wide N, weight-streaming | SCALE-Sim: a 128x128 array reaches 0.3-1.5% utilization on decode GEMVs |
| SRAM | 256 MiB (≥8 MB staging needed at batch 1) | dies are HBM-shoreline-bound with 222 mm² of whitespace, so SRAM is nearly free |
| process | TSMC N4P (N5 family), not N3E | SRAM bitcell is 0.021 µm² on both; shoreline-bound dies; N3 wafers ~20% dearer |
| collectives | in-fabric all-reduce, direct 4-package mesh | latency set to NVLink's computed speed-of-light (1.4 µs), with no link advantage assumed |

## What a seasoned accelerator architect would weigh

* **The software counterfactual dominates the decision.** If Baseten can ship the dataflow-style runtime, most of MDA-1's speed comes for free on hardware they already run. Build silicon only for $/token and W/token at scale.
* **NRE amortization dominates ASIC cost.** At $300M NRE and 20K packages, NRE is $15,000 of $28,907 per package. Break-even against GPUs running the same software at $45K/GPU is about 9,000 packages ($300M NRE) or 18,000 ($600M). At hyperscaler volume that is easy; for a single inference provider it is the crux.
* **Time to market.** Our assumption: 24-30 months to volume for an N4P two-die package with HBM3E (team-dependent; not sourced). Rubin ships now. Rubin with dataflow-style software projects 6,453 tok/s/user; MDA-1-HBM4 at the same bandwidth, 6,987.
* **Risk register.** HBM and CoWoS supply (shared with GPU vendors); a static-schedule compiler that keeps up with a new model each quarter; the collective-latency target; demand that pays for low-latency tokens. If the market prices only throughput, GPUs with the same software are 1.27x ahead of MDA-1 per 4 chips at batch 256. MDA-1 carries 40% of their FLOPs.
