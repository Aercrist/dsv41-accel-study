<!-- generated from docs/templates/POST.md.j2 by experiments/render_docs.py; edit the template -->
# Draft posts

Repo link placeholder: `https://github.com/benblaine/dsv41-accel-study` (update once published).
Attach `results/fig_step_breakdown.png` to post 1 and `results/fig_ablation.png` to post 3.

## X thread

**1/**
Baseten's deepseek-ultrafast runs DeepSeek-V4.1-Flash at 1,740 tok/s on 4x GB300. I modeled where the time goes.

About half of each 3.3 ms decode step isn't moving weights. It's fixed per-stage latency: ~39 µs per transformer block, waiting on dependent kernels and all-reduces. 🧵 [step breakdown]

**2/**
That's why 8 GPUs are only 22% faster per step than 4. More GPUs shrink the streaming. The latency stays.

It's also why Rubin's 2.4x bandwidth buys only ~41% with today's per-stage latency (modeled).

**3/**
The fix is an execution model, not more silicon. One persistent program, flag hand-offs instead of barriers, and the next layers' weights streaming while this layer's experts load.

Same 4x GB300, modeled: 3,486 tok/s/user, 2.0x. [ablation]

**4/**
Then I designed the silicon anyway. MDA-1: a decode ASIC with the same 8 TB/s HBM, 2 PF FP8, a hardware MoE router (RTL-verified) and in-fabric all-reduce.

It hits the HBM roofline: 3,482 tok/s/user. Same as good software on the same bandwidth. Silicon doesn't buy speed here.

**5/**
What it buys is economics: ~1.6x lower $/token and ~1.8x tokens/J vs GPUs running that same software. That's at $45K/GPU and 60% TDP; the range is in the repo.

Break-even is ~9,000 chips at $300M NRE. Hyperscaler math, not startup math.

**6/**
Things that surprised me:
• A 128x128 systolic array runs these decode GEMVs at 0.3-1.5% utilization (SCALE-Sim). The engine has to be 16 rows wide.
• SRAM expert caches are a dead end. They need GBs per chip.
• Engram's 203 GB of tables serve ~23 MB/s of lookups. Put them in LPDDR.
• At TP8 the expert layout pads +26% bytes.

**7/**
Everything is open and reproducible: simulator, calibration, joint Monte Carlo, ablation, router RTL, and the list of claims an adversarial review made me fix. `make reproduce`.

→ https://github.com/benblaine/dsv41-accel-study

## LinkedIn

Baseten open-sourced deepseek-ultrafast, a hand-tuned engine that decodes DeepSeek-V4.1-Flash at 1,740 tokens/s per user on 4x GB300. I used it as the reference workload for a hardware study, and the answer surprised me.

About half of every decode step is fixed per-stage latency, not memory bandwidth. A dataflow-style execution model removes most of it: on the same GPUs, the model projects 2.0x the speed. A custom decode ASIC built around that execution model reaches the same speed at the same memory bandwidth. Its advantage is cost and energy per token at volume, not raw speed.

The simulator, calibration against Baseten's published numbers, the joint uncertainty analysis and a verified RTL block are all in the repo, reproducible with one command. All projections are modeled.

## Reply to the Baseten team

Hi Baseten team, thanks for open-sourcing deepseek-ultrafast. It's the most legible serving engine I've read, and it made a serious hardware study possible.

I built an op-level performance model from the engine's source and V4.1's checkpoint headers. It accounts for PDL, the producer-pushed NVLS all-reduces, side streams, and the padded `sgl` expert layout. Fitted to your README's step times (3.30 ms TP4, 2.71 ms TP8), it attributes ~1.7 ms of each TP4 step (50%; 36%-57% across alternative fits) to dependent-stage latency, not weight streaming.

Three things you might find useful:

1. **Software ceiling.** On the same 4x GB300 the model projects about 3,486 tok/s/user from:
   - one persistent program with flag hand-offs;
   - L2 prefetch of the next layers' dense weights while the current layer's experts stream;
   - an unpadded expert layout;
   - an all-reduce near NVLink's speed-of-light.

   The prefetch piece is the least obvious. A layer's gate→expert gap is exactly when the next layers' attention and shared-expert weights can stream.
2. **TP8 padding.** At TP8 the 288→384 padding of each rank's expert slice adds ~26% to routed-expert bytes, if the padding is streamed.
3. **One profile settles it.** `tools/model_vs_nsys.py` prints the model's prediction in the exact groups of your `tools/nsys_breakdown.py`. One `nsys` run would confirm or kill the diagnosis. I'd love to compare notes if you're up for sharing a breakdown.

The ASIC side (MDA-1) is a simulated projection. It matches that software ceiling and wins only on $/token and W/token at volume. Everything is here: https://github.com/benblaine/dsv41-accel-study
