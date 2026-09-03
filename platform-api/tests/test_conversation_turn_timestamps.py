from datetime import UTC, datetime

from app.models.analytics_conversation import AnalyticsConversationTurn
from app.routes.conversational_analytics_conversations import _turn_to_response


def test_turn_response_exposes_persisted_dialogue_timestamps() -> None:
    created_at = datetime(2026, 8, 31, 5, 31, 45, tzinfo=UTC)
    updated_at = datetime(2026, 8, 31, 5, 32, 10, tzinfo=UTC)
    turn = AnalyticsConversationTurn(
        id=7,
        conversation_id=3,
        sequence=1,
        user_message="Why is the backup job failure rate rising?",
        status="success",
        assistant_message="The failure rate is increasing.",
        created_at=created_at,
        updated_at=updated_at,
    )

    response = _turn_to_response(turn)

    assert response.created_at == created_at
    assert response.updated_at == updated_at
