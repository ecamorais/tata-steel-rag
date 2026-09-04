from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config import GENERATION_MAX_TOKENS, GENERATION_MODEL_NAME
from src.prompt import SYSTEM_INSTRUCTION, build_comparison_user_content, build_user_content

COMPARISON_ADDENDUM = (
    "\n\nThe sources below are grouped by fiscal year under \"=== FY... ===\" "
    "headers. Explicitly compare/contrast figures across years, calling out "
    "increases, decreases, and totals per year."
)


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


def generate_answer(query: str, chunks: list[dict], comparison_mode: bool = False) -> AnswerWithCitations:
    client = _get_client()
    if comparison_mode:
        user_content = build_comparison_user_content(query, chunks)
        instruction = SYSTEM_INSTRUCTION + COMPARISON_ADDENDUM
    else:
        user_content = build_user_content(query, chunks)
        instruction = SYSTEM_INSTRUCTION

    response = client.models.generate_content(
        model=GENERATION_MODEL_NAME,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=instruction,
            response_mime_type="application/json",
            response_schema=AnswerWithCitations,
            max_output_tokens=GENERATION_MAX_TOKENS,
        ),
    )
    return response.parsed
