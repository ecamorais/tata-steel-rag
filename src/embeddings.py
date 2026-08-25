import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_DIM, EMBEDDING_MODEL_NAME

# BGE v1.5 models are trained asymmetrically for retrieval: queries get this
# instruction prefix, passages/documents are embedded as-is. Verified against
# the BAAI/bge-small-en-v1.5 model card on Hugging Face (2026-08-25) — this
# exact wording is shared across all English BGE v1.5 sizes.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        actual_dim = model.get_embedding_dimension()
        if actual_dim != EMBEDDING_DIM:
            raise ValueError(
                f"{EMBEDDING_MODEL_NAME} produced {actual_dim}-dim embeddings, "
                f"but config.EMBEDDING_DIM is {EMBEDDING_DIM}"
            )
        _model = model
    return _model


def encode_documents(texts: list[str], batch_size: int = 32, show_progress_bar: bool = False) -> np.ndarray:
    model = _get_model()
    return model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=show_progress_bar,
    )


def encode_query(text: str) -> np.ndarray:
    model = _get_model()
    return model.encode(QUERY_INSTRUCTION + text, normalize_embeddings=True)
