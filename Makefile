PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV_PYTHON) -m pip

.PHONY: venv venv-system install install-offline test sample local-help lab lab-overlap clean clean-venv legacy-install

venv:
	$(PYTHON) -m venv $(VENV)

venv-system:
	$(PYTHON) -m venv --system-site-packages $(VENV)

install: venv
	$(VENV_PIP) install .

install-offline: venv-system
	$(VENV_PIP) install --no-deps .

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

sample:
	PYTHONPATH=src $(PYTHON) -m iperf3_plotter all sample/my_test.json --out results

local-help:
	PYTHONPATH=src $(PYTHON) -m iperf3_plotter --help

lab:
	bash lab/run_docker_lab.sh

lab-overlap:
	bash lab/run_docker_lab.sh --clients 2 --duration 12 --stagger 5 --parallel 3 --bw 50 --delay 10ms --cc cubic,reno

clean:
	rm -rf results data plots report.html report_assets lab-results build dist .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +

clean-venv:
	rm -rf $(VENV)

legacy-install:
	cp legacy/preprocessor.sh /usr/local/bin/preprocessor.sh
	cp legacy/plot_iperf.sh /usr/local/bin/plot_iperf.sh
	cp legacy/fairness.sh /usr/local/bin/fairness.sh
