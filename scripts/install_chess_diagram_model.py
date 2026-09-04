from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_URL = "https://unpkg.com/@scoriiu/fenshot@0.1.4/model/chess-tiles-v2.onnx"
MODEL_SHA256 = "883f6a8e639e6d6b6399b3fda0508ad772e3c6f9cefa2e678a13f27b9fa6248d"
TARGET = ROOT / "data" / "models" / "chess-diagram" / "chess-tiles-v2.onnx"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    if TARGET.is_file() and _sha256(TARGET.read_bytes()) == MODEL_SHA256:
        print(f"Chess diagram model is already installed at {TARGET}")
        return
    print(f"Downloading {MODEL_URL}")
    with urllib.request.urlopen(MODEL_URL, timeout=120) as response:
        model = response.read()
    if _sha256(model) != MODEL_SHA256:
        raise RuntimeError("Downloaded chess diagram model failed SHA-256 verification")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".onnx.tmp")
    temporary.write_bytes(model)
    temporary.replace(TARGET)
    print(f"Installed chess diagram model at {TARGET}")


if __name__ == "__main__":
    main()
