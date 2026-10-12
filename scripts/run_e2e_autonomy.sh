#!/usr/bin/env bash
# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "================================================================="
echo "Carefold Autonomy Batch 1 E2E Test Suite Runner"
echo "================================================================="

cd "${ROOT_DIR}"

PYTHONPATH="${ROOT_DIR}/backend/src:${ROOT_DIR}/backend" \
"${ROOT_DIR}/backend/.venv/bin/pytest" \
  "${ROOT_DIR}/backend/tests/e2e_autonomy/" \
  -v \
  --durations=10 \
  "$@"

echo ""
echo "✓ All Autonomy Batch 1 E2E tests completed successfully."
