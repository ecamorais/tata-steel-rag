from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config import GENERATION_MAX_TOKENS, GENERATION_MODEL_NAME
from src.prompt import SYSTEM_INSTRUCTION, build_user_content


class Citation(BaseModel):
    source_file: str
    page_number: int


class AnswerWithCitations(BaseModel):
    answer: str
    found: bool
    citations: list[Citation]


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def generate_answer(query: str, chunks: list[dict]) -> AnswerWithCitations:
    client = _get_client()
    user_content = build_user_content(query, chunks)

    response = client.models.generate_content(
        model=GENERATION_MODEL_NAME,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=AnswerWithCitations,
            max_output_tokens=GENERATION_MAX_TOKENS,
        ),
    )
    return response.parsed
