from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Iterable

import numpy as np

_STREAMS = {"run", "mulligan", "draws", "tutor", "opponent", "targeting"}


def _normalize_parts(parts: Iterable[object]) -> str:
    return "|".join(str(part) for part in parts)


@dataclass(frozen=True)
class RNGManager:
    base_seed: int

    def seed(self, stream: str, *parts: object) -> int:
        if stream not in _STREAMS:
            raise ValueError(f"Unsupported RNG stream: {stream}")
        material = f"{int(self.base_seed)}::{stream}::{_normalize_parts(parts)}".encode("utf-8")
        digest = hashlib.blake2b(material, digest_size=8).digest()
        return int.from_bytes(digest, "big") & 0x7FFFFFFF

    def python(self, stream: str, *parts: object) -> random.Random:
        return random.Random(self.seed(stream, *parts))

    def numpy(self, stream: str, *parts: object) -> np.random.Generator:
        return np.random.default_rng(self.seed(stream, *parts))

    def permutation(self, stream: str, size: int, *parts: object) -> np.ndarray:
        rng = self.numpy(stream, *parts)
        return np.argsort(rng.random(size), kind="stable").astype(np.int16)
