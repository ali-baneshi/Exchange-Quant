.PHONY: test compile

test:
	cd core && python -m pytest test_*.py -v

compile:
	python -m compileall core
