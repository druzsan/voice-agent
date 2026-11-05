"""One turn at a time per conversation, and hanging up waits for it."""

import anyio
import pytest

from tests.fakes import FakeRecognizer, InMemoryConversationRepository, wav_of_silence
from voice_agent.conversation.turns import TurnInProgress
from voice_agent.services import Services

pytestmark = pytest.mark.anyio


async def test_a_second_turn_is_refused_while_the_first_runs(
    services: Services, recognizer: FakeRecognizer
) -> None:
    turns = services.turns()
    conversation = (await turns.start()).conversation
    recognizer.release = anyio.Event()

    async with anyio.create_task_group() as group:
        group.start_soon(turns.voice_turn, conversation.id, wav_of_silence())
        await anyio.wait_all_tasks_blocked()

        with pytest.raises(TurnInProgress):
            await turns.text_turn(conversation.id, "Me too", "keyboard")
        recognizer.release.set()


async def test_hanging_up_waits_for_the_running_turn(
    services: Services,
    recognizer: FakeRecognizer,
    repository: InMemoryConversationRepository,
) -> None:
    turns = services.turns()
    conversation = (await turns.start()).conversation
    recognizer.release = anyio.Event()

    async with anyio.create_task_group() as group:
        group.start_soon(turns.voice_turn, conversation.id, wav_of_silence())
        await anyio.wait_all_tasks_blocked()
        group.start_soon(turns.end, conversation.id, "hangup")
        await anyio.wait_all_tasks_blocked()
        # Still waiting for the turn
        ended = await repository.get_conversation(conversation.id)
        assert ended is not None and ended.ended_at is None
        recognizer.release.set()

    detail = await repository.get_detail(conversation.id)
    assert detail is not None
    assert detail.end_reason == "hangup"
    # Greeting, the caller's words and the answer, all before the end
    assert [m.role for m in detail.messages] == ["assistant", "user", "assistant"]
    assert all(
        detail.ended_at and m.created_at <= detail.ended_at for m in detail.messages
    )
