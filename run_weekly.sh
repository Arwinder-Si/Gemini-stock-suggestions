#!/bin/bash
cd "$(dirname "$0")"
set -a
[ -f .env ] && source .env
set +a
source venv/bin/activate
python -m hermes.cli weekly
