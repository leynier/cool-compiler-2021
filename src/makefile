.PHONY: clean main test pytest lint format typecheck

main:
	# Compiling the compiler :)

clean:
	rm -rf build/*
	rm -rf ../tests/*/*.mips

pytest:
	uv run pytest ../tests -v --tb=short -m=${TAG}

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run ty check .

test: format lint typecheck pytest
