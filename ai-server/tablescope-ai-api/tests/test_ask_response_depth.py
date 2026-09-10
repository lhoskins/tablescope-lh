"""Response-depth and document-context regression tests for /ai/ask."""

from app.models.schemas import ContextPackage
from app.routers.ai_ask import _prose_answer_profile
from app.services.context_builder import context_to_prompt_text


def test_detailed_summary_gets_long_form_profile():
    instruction, max_tokens = _prose_answer_profile(
        "Give me a detailed summary of the SCOR model"
    )

    assert max_tokens == 2400
    assert "700-1,100 words" in instruction
    assert "descriptive headings" in instruction


def test_plain_document_question_stays_concise():
    instruction, max_tokens = _prose_answer_profile("What is the SCOR model?")

    assert max_tokens == 1536
    assert instruction == "Keep the answer concise and conversational."


def test_retrieved_document_passage_is_not_truncated_at_500_characters():
    passage = "A" * 900
    context = ContextPackage(
        tenant_id=1,
        user_id=2,
        project_id=3,
        allowed_context={
            "metadata": [],
            "documents": [
                {
                    "payload": {
                        "chunk_text": passage,
                        "title": "SCOR Model Documentation",
                        "source_type": "reference_library",
                        "tier": "industry",
                        "retrieval_method": "hybrid",
                    }
                }
            ],
        },
    )

    rendered = context_to_prompt_text(context)

    assert passage in rendered
