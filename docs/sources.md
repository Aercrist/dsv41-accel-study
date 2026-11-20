# Sources

Each constant in `configs/` has a `# src: <key>` comment. The key refers to a row on this page.
We read the pages on 2026-11-14, unless a row gives a different date. Confidence:
- **V** vendor datasheet/page;
- **P** peer-reviewed paper or preprint;
- **R** reputable press/independent analysis;
- **E** analyst estimate/aggregator.

The YAML gives the label **assumption** to each value that is not in a source.
[docs/05_limitations.md](05_limitations.md) lists these values. The tornado analysis sweeps the
uncertain values.

## Workload (primary sources)

| key | what we take from it | source | conf. |
|---|---|---|---|
| ultrafast | step times, acceptance length, tokens/s, prefill times, TP layouts, kernel structure | github.com/basetenlabs/deepseek-ultrafast @ `76766a97` (README.md, crates/engine/src/{model,weights,ops}.rs, crates/server/src/engine.rs) | V |
| dsv41-hf | model config, safetensors headers (dtypes, shapes, bytes) | huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash @ `314113f8` (config.json, inference/config.json, inference/model.py) | V |
| dsv41-report | CED, CSA2 modes, 890 B/token KV, FP4 KV format, 552B/196B/16B/8B parameters, Fig. 2 decode FLOPs | DeepSeek-V4.1-Flash technical report (DeepSeek_V41_Tech_Report.pdf in the HF repo) | V |

## GPU baseline

| key | value(s) | source | quote | conf. |
|---|---|---|---|---|
| nv-bw-ultra | GB300: 288 GB HBM3E, 8 TB/s, 15 PF dense NVFP4, 5 PF dense FP8, NVLink 1.8 TB/s, up to 1,400 W, TSMC 4NP | developer.nvidia.com/blog/inside-nvidia-blackwell-ultra-the-chip-powering-the-ai-factory-era/ | "Bandwidth: 8 TB/s per GPU"; "15 PetaFLOPS dense NVFP4"; FP8 "5 \| 10 PetaFLOPS"; "Up to 1,400W" | V |
| lenovo-b300 | HGX B300 per GPU: 7.7 TB/s, FP8 9,000 TF sparse (4.5 PF dense), BF16 4,500 sparse, TDP 1,100 W | lenovopress.lenovo.com/lp2264-thinksystem-sr680a-v4-server | "GPU Memory Bandwidth \| 7.7 TB/s"; "FP8 Tensor Core \| 9,000 teraFLOPS*"; "TDP \| 1100W" | V (OEM) |
| nv-hgx | HGX B300 FP4: 144 \| 108 PFLOPS per 8 GPUs (sparse \| dense) | nvidia.com/en-us/data-center/hgx/ | "144 PFLOPS \| 108 PFLOPS" | V |
| stream-b200 | B200 STREAM triad 7.48 TB/s = 93.5% of peak (128 GB array). Version 3 of the same preprint reports ~52% at 4-16 GB arrays | arxiv.org/html/2512.02189v1 (and v3) | Table XIII "7.48" / "93.5" | P (preprint) |
| stream-h100 | DGX H100 STREAM triad 3,132 of 3,352 GB/s (93.4%) | NVIDIA GH200 benchmark guide DA-11356-002_10 | "Triad 3132" | V |
| ar-latency | 4x GB200 small-message all-reduce: NCCL ring 11.0 us; new kernel 2.37 us (measured); "roughly 5 us on four GPUs"; barrier ">1 us"; speed-of-light 1.404 us *computed* for 2x GB200 from measured L2 RTT 0.306 us and remote store 0.792 us | arxiv.org/pdf/2607.16100 | "reduces average latency for small messages from 11.0 µs for NCCL ring to 2.37 µs"; "a small-message AllReduce completes in roughly 5 µs on four GPUs"; "each barrier will incur more than 1 µs of overhead"; "the SoL latency of an AllReduce is computed to be 1.404 µs" | P (preprint) |
| launch-overhead | CUDA kernel launch ~2.1 us (stream), ~1.3 us (CUDA graph) on H100; batch-1 megakernel uses 78% of HBM BW | hazyresearch.stanford.edu/blog/2025-05-27-no-bubbles | "launch cost of about 2.1 microseconds"; "with CUDA graphs ... around 1.3 microseconds"; "we use 78% of memory bandwidth" | R |
| cuda-graphs | V100 per-kernel overhead 3.4 us with graphs vs 2.9 us execution | developer.nvidia.com/blog/cuda-graphs/ | "gives 3.4μs (vs 2.9μs kernel execution time)" | V |
| gpu-rental | B300 on-demand market median $9.50/GPU-hr (19 providers, 2026-11-14); Nebius HGX B300 $9.50; no public GB300 price | getdeploying.com/gpus/nvidia-b300; nebius.com/prices | "$9.50 per GPU per hour"; "NVIDIA HGX B300: $9.50" | E / V |
| epoch-b200 | B200 manufacturing cost ~$6,400 (HBM $2,900, logic $900, CoWoS-L $1,100 + ~$1,000 yield loss); 4NP wafer $17,000; HBM3E $14-17/GB | epoch.ai/data-insights/b200-cost-breakdown | "NVIDIA's B200 costs around $6,400 to produce" | E |
| nv-rubin | Rubin: 288 GB HBM4, 19.2 TB/s (NVL72 page) or 22 TB/s (HGX page), 17.5 PF dense FP8, NVLink 3-3.6 TB/s | nvidia.com/en-us/data-center/vera-rubin-nvl72/; nvidia.com/en-us/data-center/hgx/ | "288 GB HBM4 \| 19.2 TB/s"; "288 GB HBM4 \| 22 TB/s" | V (pages conflict) |

## Memory, process, packaging

| key | value(s) | source | quote | conf. |
|---|---|---|---|---|
| hbm3e | HBM3E: 24 GB (8-high) / 36 GB (12-high) per stack, >9.2 Gb/s/pin, >1.2 TB/s per stack | micron.com/products/memory/hbm/hbm3e | "HBM3E 8-high provides 24GB capacity per placement"; "bandwidth of more than 1.2 TB/s per placement" | V |
| hbm4 | HBM4: 8 Gb/s, 2048-bit, up to 2 TB/s per stack (JEDEC); SK hynix >10 Gb/s, >40% better energy efficiency than HBM3E | storagenewsletter.com (JEDEC JESD270-4 release); theregister.com/2025/09/12/sk_hynix_hbm4_mass_production/ | "HBM4 boosts total bandwidth up to 2TB/s"; "boosted energy efficiency by more than 40 percent" | V / R |
| hbm-energy | HBM2 access energy 3.97 pJ/bit (device + I/O). No public absolute figure for HBM3/3E/4 | cs.utexas.edu/users/skeckler/pubs/MICRO_2017_Fine_Grained_DRAM.pdf | "The energy to access a bit in HBM2 is approximately 3.97 pJ/bit" | P |
| hbm-price | HBM3E $1.5-1.6 per Gb (= $12-12.8/GB), HBM4 ~$2/Gb in 2H26 | en.sedaily.com/finance/2026/07/12/... (DigiTimes) | "HBM3E prices, currently at $1.5-1.6 per Gb" | R |
| hbm-phy-area | HBM3E PHY ~11 mm2, HBM4 PHY ~15 mm2 (GUC). **Unverified**: seen only in search summaries of a Tom's Hardware article | tomshardware.com (GUC HBM4 base-die article) | n/a | unverified |
| sram-bitcell | TSMC HD bitcell 0.021 um2 on both N5 and N3E (0.0199 on N3B) | fuse.wikichip.org/news/7343/ (archived) | "Coming in at 0.021 µm², this is exactly the same bitcell size as their N5 node." | R |
| sram-density | N5 HD SRAM ~32 Mib/mm2 (matches TSMC ISSCC 2020 135 Mib test chip); N3E ~31.8 Mib/mm2; AMD 64 MiB V-Cache die = 36 mm2 (N7) | fuse.wikichip.org/news/3398/ ; /7343/ ; /5531/ (archived) | "~32 Mib/mm² of cache"; "N3E is roughly at 31.8 Mib/mm²" | R |
| logic-density | N5 measured 137.6 MTr/mm2; N3B/N3E 1.6x/1.7x chip-level scaling vs N5 | angstronomics.com/p/the-truth-of-tsmc-5nm; wikichip /7343/ | "TSMC N5 2-fin achieves a logic density of 137.6 MTr/mm²" | R |
| wafer-price | N5 ~$16,988 (CSET model); 4NP $17,000 (Epoch); N3 ~$20,000 (reported) | cset.georgetown.edu/...; epoch.ai/...; tomshardware.com/news/tsmc-will-charge-20000-per-3nm-wafer | "a single 300 mm wafer built on the 5nm node costs approximately $16,988" | E |
| defect-density | TSMC N5 D0 0.10-0.11 /cm2 (2020) | anandtech.com/show/16028 (archived) | "around 0.10 to 0.11 defects per square centimeter" | R |
| cowos-cost | CoWoS-L ~$1,100 per B200 + ~$1,000 packaging-yield loss | epoch.ai/data-insights/b200-cost-breakdown | packaging table "$1,100" | E |
| nre | 5 nm design cost $542.2M (IBS 2018; same article: realistic ~$280M); 5 nm mask set $6-12M | semiengineering.com/what-will-that-chip-cost; semiconductorx.com/semiconductor-photomasks.html | "pegged the cost of a 5nm chip at $542.2M"; "somewhere in the range of $280M" | E |

## Energy

| key | value(s) | source | quote | conf. |
|---|---|---|---|---|
| mac-energy | 7 nm op energy: Int8 mult 0.070, BF16 mult 0.210, FP16 mult 0.340, FP32 mult 1.310, FP32 add 0.380 pJ (TPUv4i Table 2); Horowitz 45 nm table; LPDDR 640 pJ/32-bit word | cs.cmu.edu/~18742/papers/Jouppi2021.pdf (ISCA 2021); NVIDIA Hot Chips 2023 keynote | "Int 8 0.200 0.070"; "LPDDR DRAM GB 640pJ/word" | P / V |
| sram-energy | 7 nm SRAM read per 64 bits: 8 KB 7.5 pJ, 1 MB 14 pJ (0.22 pJ/bit) | Jouppi et al. ISCA 2021 Table 2 | "1 MB SRAM 100.000 14.000" | P |
| serdes-energy | 112G LR SerDes in 5 nm <5 pJ/bit; NVL72 NVLink passive copper ~5 pJ/bit; NVLink-C2C 1.3 pJ/bit; UCIe 0.25-0.5 pJ/bit | synopsys.com (112G bulletin); Hot Chips 2025 tutorial (Helms); Hot Chips 2022 Grace; uciexpress.org | "less than five picojoules per bit"; "NVL72 NVLink ... ~ 5 pJ/bit" | V / R |
| h100-efficiency | H100 ~9 TOPS/W (Int8/FP8) chip level | NVIDIA Hot Chips 2023 keynote | "9 TOPS/W (Int8/FP8)" | V |

## Other platforms

| key | value(s) | source | conf. |
|---|---|---|---|
| amd-v80 | Alveo V80: 32 GB HBM2e @ 819 GB/s, 190 W TDP, 2.6M LUTs, 10,848 DSPs, 752 Mb on-chip RAM, 4x200G QSFP56, $9,495 MSRP | AMD DS1013 v1.0; amd.com product page | V |
| amd-versal-hbm | Versal HBM series: "Up to 75 TOPs with INT8 and 17.5 TFLOPs of DSP compute" | Versal HBM product brief | V |
| groq | GroqChip: 230 MB SRAM, 80 TB/s on-die, 215 W TDP (300 W max), 14 nm, 725 mm2 | Groq product brief v1.7 (archived); theregister.com 2020-09-29 | V / R |
| cerebras | WSE-3: 44 GB SRAM, 21 PB/s, 46,225 mm2, TSMC 5 nm; CS-3 23 kW peak | Cerebras Hot Chips 2024; cerebras.ai blog | V |
| tpu7x | TPU7x: 192 GiB HBM, 7,380 GB/s, 4,614 TFLOPS FP8 | docs.cloud.google.com/tpu/docs/tpu7x | V |
| trainium | Trn2: 96 GiB, 2.9 TB/s, 1.3 PF dense FP8; Trn3: 144 GB HBM3e, 4.9 TB/s, 2.52 PF FP8, 3 nm | aws.amazon.com blogs / what's new (2025-12) | V |
| etched | Sohu: 144 GB HBM, 4 nm (pre-tape-out claims; no power/FLOPS/BW published) | computerbase.de 2024-06; theregister.com 2024-06-26 | R |

## Expert locality, TCO

| key | value(s) | source | conf. |
|---|---|---|---|
| expert-locality | DeepSeek-V2-Lite LRU with 32 of 64 experts cached: 28% miss; experts resident ~19-22 tokens; Mixtral 4/8: 40% miss | arxiv.org/pdf/2412.00099 (TMLR 2025) | P |
| expert-locality-2 | DeepSeek-V2-Lite oracle segment-cache hit 42-58% at cache = 2x active experts; LRU reaches 56-75% of optimal | arxiv.org/pdf/2505.16056 (ICLR 2026) | P |
| electricity | US industrial electricity 8.62 c/kWh (2025 average) | eia.gov/energyexplained/electricity/prices-and-factors-affecting-prices.php | V |
| pue | PUE 1.44 for >= 20 MW data centers (1.54 all) | Uptime Institute 2025 annual survey | R |

## Not found (treated as assumptions, see 05_limitations.md)

- Absolute HBM3/3E/4 pJ/bit
- FP8 MAC energy and area at 5 nm
- full-swing wire energy at 5-7 nm
- NVLink one-shot all-reduce latency on H100
- N4P bitcell
- N3 MTr/mm2
- 3 nm design cost
- verified HBM3E PHY area
- N4P/N3 defect density
- Blackwell L2 size
- GB300 public rental price
- price to buy a GPU
- DeepSeek-V3/V4 expert-cache hit rates
