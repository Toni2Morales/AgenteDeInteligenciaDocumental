"""Verify the local Ollama setup and the real embedding dimension.

Usage::

    python scripts/verify_ollama.py

The script first tries the Ollama HTTP API, which is the source of truth. When
the server is reachable but cannot run the model (for example because the
inference runner is missing from the installation), it falls back to reading
the GGUF metadata of the already downloaded model file. That is still real data
taken from the model artifact, never a guessed value, but the output clearly
states which method was used so the difference is never hidden.

The reported dimension is the value you must put in ``EMBEDDING_DIMENSION``
before running the migrations.
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.config.settings import settings  # noqa: E402
from app.services.ollama import OllamaClient, OllamaError  # noqa: E402

_GGUF_MAGIC = b"GGUF"
_STRING_TYPE = 8
_ARRAY_TYPE = 9
_BOOL_TYPE = 7
_SCALAR_FORMATS = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    10: "<Q",
    11: "<q",
    12: "<d",
}


class _Reader:
    """Sequential reader over a GGUF file handle."""

    def __init__(self, handle) -> None:
        self._handle = handle

    def read(self, size: int) -> bytes:
        data = self._handle.read(size)
        if len(data) != size:
            raise ValueError("Unexpected end of GGUF file.")
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def string(self) -> str:
        length = self.u64()
        return self.read(length).decode("utf-8", "replace")

    def value(self, value_type: int):
        if value_type == _STRING_TYPE:
            return self.string()
        if value_type == _ARRAY_TYPE:
            element_type = self.u32()
            count = self.u64()
            return [self.value(element_type) for _ in range(count)]
        if value_type == _BOOL_TYPE:
            return bool(self.read(1)[0])
        fmt = _SCALAR_FORMATS.get(value_type)
        if fmt is None:
            raise ValueError(f"Unsupported GGUF value type: {value_type}")
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))[0]


def read_gguf_metadata(path: Path) -> dict:
    """Read the metadata key/value block at the start of a GGUF file."""
    with path.open("rb") as handle:
        if handle.read(4) != _GGUF_MAGIC:
            raise ValueError(f"{path} is not a GGUF file.")
        reader = _Reader(handle)
        version = reader.u32()
        if version < 2:
            raise ValueError(f"Unsupported GGUF version: {version}")
        reader.u64()  # tensor count (not needed here)
        kv_count = reader.u64()
        metadata: dict = {}
        for _ in range(kv_count):
            key = reader.string()
            value_type = reader.u32()
            metadata[key] = reader.value(value_type)
        return metadata


def read_embedding_dimension(path: Path) -> int | None:
    """Return ``*.<arch>.embedding_length`` from a GGUF file, if present."""
    metadata = read_gguf_metadata(path)
    for key, value in metadata.items():
        if key.endswith(".embedding_length") and isinstance(value, int):
            return value
    return None


def models_dir() -> Path:
    """Resolve the Ollama models directory."""
    override = os.environ.get("OLLAMA_MODELS")
    return Path(override) if override else Path.home() / ".ollama" / "models"


def find_model_blob(model: str) -> Path | None:
    """Locate the GGUF model layer of a locally downloaded Ollama model."""
    name, _, tag = model.partition(":")
    manifest = (
        models_dir() / "manifests" / "registry.ollama.ai" / "library" / name / (tag or "latest")
    )
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return None
    for layer in data.get("layers", []):
        if layer.get("mediaType", "").endswith(".image.model"):
            digest = layer.get("digest", "")
            if digest.startswith("sha256:"):
                blob = models_dir() / "blobs" / f"sha256-{digest.removeprefix('sha256:')}"
                return blob if blob.is_file() else None
    return None


def main() -> int:
    client = OllamaClient(
        base_url=settings.ollama_base_url,
        llm_model=settings.ollama_llm_model,
        embedding_model=settings.ollama_embedding_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    status = client.check()
    if not status.available:
        print(f"[X] Ollama is not reachable at {settings.ollama_base_url}.")
        return 1

    print(f"[OK] Ollama {status.version} reachable at {settings.ollama_base_url}")
    print(f"     models: {', '.join(status.models) or '(none)'}")

    if not status.embedding_model_present:
        print(
            f"[X] Embedding model '{settings.ollama_embedding_model}' is not downloaded. "
            f"Run: ollama pull {settings.ollama_embedding_model}"
        )
        return 1
    if not status.llm_model_present:
        print(
            f"[!] Language model '{settings.ollama_llm_model}' is not downloaded. "
            f"Run: ollama pull {settings.ollama_llm_model}"
        )

    dimension: int | None = None
    source = "Ollama API"
    try:
        dimension = client.embedding_dimension(model=settings.ollama_embedding_model)
    except OllamaError as exc:
        print(f"[!] The Ollama API could not run the model: {exc}")
        blob = find_model_blob(settings.ollama_embedding_model)
        if blob is not None:
            try:
                dimension = read_embedding_dimension(blob)
                source = f"GGUF metadata of {blob.name}"
            except (ValueError, OSError) as read_exc:
                print(f"[X] Could not read GGUF metadata: {read_exc}")

    if dimension is None:
        print("[X] Could not determine the embedding dimension.")
        return 1

    print(f"[OK] Embedding dimension = {dimension} (source: {source})")
    print("     Set this value in your .env file:")
    print(f"     EMBEDDING_DIMENSION={dimension}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
