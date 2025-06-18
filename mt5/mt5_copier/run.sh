#!/bin/bash
### COMMON SETUP; DO NOT MODIFY ###
set -e
# cd to the directory of the script to ensure paths are correct
cd "$(dirname "$0")"

# --- CONFIGURE THIS SECTION ---
# Command to run all tests (now using pytest)
run_all_tests() {
  echo "Running all unit tests with pytest..."
  # -v for verbose, --color=yes to force color, add any other flags needed
  pytest -v --color=yes tests/
}

# Command to run specific test files
run_selected_tests() {
  local test_files=("$@")
  # Prepend 'tests/' directory to each file if not already present
  local prefixed_files=()
  for file in "${test_files[@]}"; do
    if [[ "$file" == tests/* ]]; then
      prefixed_files+=("$file")
    else
      prefixed_files+=("tests/$file")
    fi
  done
  
  echo "Running selected tests: ${prefixed_files[*]}"
  pytest -v --color=yes "${prefixed_files[@]}"
}

# --- END CONFIGURATION SECTION ---
### COMMON EXECUTION; DO NOT MODIFY ###
# No args is all tests
if [ $# -eq 0 ]; then
  run_all_tests
  exit $?
fi

# Handle comma-separated input
if [[ "$1" == *","* ]]; then

  IFS=',' read -r -a TEST_FILES <<< "$1"
else
  TEST_FILES=("$@")
fi

# Run them all together
run_selected_tests "${TEST_FILES[@]}"
