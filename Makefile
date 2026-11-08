.PHONY: run demo snapshot-demo test check clean

run:
	python -m traceharbor.server

demo:
	python -m examples.demo_app

snapshot-demo:
	python -m examples.snapshot_demo

test:
	python -m unittest discover -v

check:
	python -m compileall -q traceharbor traceharbor_sdk examples tests
	ruff check traceharbor traceharbor_sdk examples tests
	mypy traceharbor traceharbor_sdk
	coverage run -m unittest discover -v
	coverage report --fail-under=70

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f traceharbor.db traceharbor.db-shm traceharbor.db-wal
	rm -rf traceharbor-artifacts
