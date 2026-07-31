.PHONY: dev test lint image install uninstall smoke

PORT ?= 8765
IMAGE ?= iteraforge:latest

dev:
	ITERAFORGE_DEV=1 uvicorn iteraforge.app:create_app --factory --host 127.0.0.1 --port $(PORT) --reload

test:
	pytest -q

lint:
	ruff check src tests

smoke:
	python -m iteraforge.smoke

image:
	podman build -t $(IMAGE) .

install:
	./install.sh

uninstall:
	./uninstall.sh
