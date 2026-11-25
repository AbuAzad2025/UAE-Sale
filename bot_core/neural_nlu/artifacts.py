"""Verify the model shipped with the application release."""

from hashlib import sha256
from pathlib import Path

RELEASE_MODEL = (Path(__file__).resolve().parents[1] / "artifacts" / "v7").resolve()


def verify_release_model(directory: Path = RELEASE_MODEL) -> None:
    expected = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, name = line.split()
        expected[name] = digest
    if set(expected) != {"model.pt", "vocab.json"}:
        raise ValueError("Invalid release model manifest")
    for name, digest in expected.items():
        if sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Release model checksum mismatch: {name}")


if __name__ == "__main__":
    verify_release_model()
    print(f"Model weights and vocabulary verified ({RELEASE_MODEL.name}).")
