.PHONY: run demo test check clean

run:
	python -m traceharbor.server

demo:
	python -m examples.demo_app

test:
	python -m unittest discover -v

check:
	python -m compileall -q traceharbor traceharbor_sdk examples tests
	python -m unittest discover -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f traceharbor.db traceharbor.db-shm traceharbor.db-wal
