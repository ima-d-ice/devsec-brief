"""Shared test setup.

Unit tests must not download or load real transformer models. The API imports
the retrieval module, so we install a tiny deterministic stub before that
import. Integration tests still use the real database.
"""

import sys
import types

if "sentence_transformers" not in sys.modules:
    stub = types.ModuleType("sentence_transformers")

    class _DummyModel:
        def __init__(self, *args, **kwargs):
            pass

        def encode(self, values, **kwargs):
            import numpy as np

            return np.zeros((len(values), 1024))

        def predict(self, pairs):
            return [0.0] * len(pairs)

    stub.SentenceTransformer = _DummyModel
    stub.CrossEncoder = _DummyModel
    sys.modules["sentence_transformers"] = stub
