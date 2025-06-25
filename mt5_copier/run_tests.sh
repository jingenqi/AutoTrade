#!/bin/bash
echo "Running MT5 Trade Copier Tests"
echo "=============================="

# Set the Python path to include the project root
export PYTHONPATH=$PYTHONPATH:.

# Run unit tests first
echo "Running unit tests..."
python -m pytest tests/unit -v

# Run GUI tests
echo
echo "Running GUI tests..."
python -m pytest tests/gui -v

# Run integration tests
echo
echo "Running integration tests..."
python -m pytest tests/integration -v

echo
echo "All tests completed." 