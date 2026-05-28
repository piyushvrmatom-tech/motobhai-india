#!/usr/bin/env bash
# Build script for Render — clears deprecated packages and installs deps
set -e
pip uninstall -y google-generativeai 2>/dev/null || true
pip uninstall -y google-cloud-firestore 2>/dev/null || true
pip install -r backend/requirements.txt
