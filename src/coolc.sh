#!/usr/bin/env bash
# Lanza el compilador de COOL dentro del entorno gestionado por uv.

set -e

INPUT_FILE="$1"
if [ -z "$INPUT_FILE" ]; then
    echo "Uso: $0 <archivo.cl>" >&2
    exit 1
fi

OUTPUT_FILE="${INPUT_FILE%.cl}.mips"

# Resolver el directorio del proyecto (donde está pyproject.toml).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "CoolCompiler 1.0"
echo "Copyright (c) 2025: Leynier"

uv run python -m src.coolc "$INPUT_FILE" "$OUTPUT_FILE"
