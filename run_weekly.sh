#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python -m hermes.cli weekly
