from unittest.mock import AsyncMock, MagicMock, patch

from radicalbit_ai_gateway.events import events_processor


async def test_cancel_alert_dispatches_cancels_the_pending_tasks():
    tasks = MagicMock()
    tasks.cancel = AsyncMock()

    with patch.object(events_processor, '_alert_tasks', tasks):
        await events_processor.cancel_alert_dispatches()

    tasks.cancel.assert_awaited_once_with()
