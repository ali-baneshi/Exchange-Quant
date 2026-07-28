.PHONY: test compile lint

test:
	python -m pytest -q

compile:
	python -m compileall exchange_q research

lint:
	python -m ruff check exchange_q tests
