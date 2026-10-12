# BytNode SDKs — common tasks. `make help` lists them.
SHELL := /usr/bin/env bash
ifeq ($(OS),Windows_NT)
  PY_VENV := .venv/Scripts/python
else
  PY_VENV := .venv/bin/python
endif
PYTHON ?= python3

.PHONY: help setup update-spec generate check-generated check check-python check-typescript test-live build

help:
	@echo "setup            Python venv + npm install"
	@echo "update-spec      download the public contract into spec/openapi.json"
	@echo "generate         regenerate both SDKs from spec/openapi.json"
	@echo "check-generated  fail if the generated code is not up to date"
	@echo "check            lint, type-check and test both SDKs (offline)"
	@echo "test-live        read-only tests against production (needs BYTNODE_API_KEY)"
	@echo "build            build the Python wheel and the npm package"

setup:
	$(PYTHON) -m venv .venv
	$(PY_VENV) -m pip install -q --upgrade pip
	$(PY_VENV) -m pip install -q -e "python[pandas]" pytest pytest-asyncio respx mypy ruff build
	cd typescript && npm ci

update-spec:
	$(PYTHON) codegen/generate.py --update-spec

generate:
	$(PYTHON) codegen/generate.py

check-generated:
	$(PYTHON) codegen/generate.py --check

check: check-python check-typescript

check-python:
	cd python && ../$(PY_VENV) -m ruff check src tests && ../$(PY_VENV) -m ruff format --check src tests
	cd python && ../$(PY_VENV) -m mypy
	cd python && ../$(PY_VENV) -m pytest -q

check-typescript:
	cd typescript && npx tsc --noEmit && npx vitest run && npx tsup

test-live:
	cd python && ../$(PY_VENV) -m pytest -m live -q
	cd typescript && npm run test:live

build:
	cd python && ../$(PY_VENV) -m build
	cd typescript && npx tsup && npm pack --dry-run
