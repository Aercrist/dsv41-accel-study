PY ?= python3
.PHONY: reproduce test rtl clean all

## Regenerate every result, figure and generated doc (about a minute).
reproduce:
	@command -v iverilog >/dev/null 2>&1 && $(MAKE) --no-print-directory rtl || echo "iverilog not found: using results/router.json from the last run"
	$(PY) -m experiments.run_all

## Invariants + calibration checks.
test:
	$(PY) -m pytest -q tests

## MoE router RTL vs numpy golden model (Icarus Verilog).
rtl:
	@mkdir -p rtl/build results
	$(PY) rtl/check_router.py gen
	iverilog -g2012 -o rtl/build/router.vvp rtl/moe_topk_router.sv rtl/tb_moe_topk_router.sv
	vvp -n rtl/build/router.vvp >/dev/null
	$(PY) rtl/check_router.py check

clean:
	rm -rf results/*.json results/*.png rtl/build .pytest_cache

all: clean reproduce test
