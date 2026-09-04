"""Shared path constants used across the project."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ONNX_EMBED_PATH = _PROJECT_ROOT / "data" / "onnx_st" / "bge-m3-onnx"
GLOSSARY_PATH = _PROJECT_ROOT / "data" / "entity_glossary.json"
