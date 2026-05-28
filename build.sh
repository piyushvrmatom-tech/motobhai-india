#!/usr/bin/env bash
# Build script for Render — clears deprecated SDK cache and installs deps
set -e
pip uninstall -y google-generativeai 2>/dev/null || true
pip install -r backend/requirements.txt
