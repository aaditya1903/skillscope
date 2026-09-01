#!/usr/bin/env bash
# Inert demonstration script. SkillScope records its metadata and never runs it.
set -euo pipefail
echo "Would roll out ${1:-<digest>} after readiness passes."
