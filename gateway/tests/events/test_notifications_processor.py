from datetime import datetime
from unittest.mock import patch
import uuid

from radicalbit_ai_gateway.events.buffer import CeleryBuffer
from radicalbit_ai_gateway.events.notifications_processor import (
    _create_notification_dict,
    emit_notification,
)


class TestCreateNotificationDict:
    def test_create_notification_dict_creates_correct_structure(self):
        """Test that _create_notification_dict creates a notification with all required fields."""

        window_id = uuid.uuid4()
        notification = _create_notification_dict(
            route_name='test-route',
            direction='input',
            window_size=60,
            max_tokens=1000,
            current_usage=500,
            reset_time=1234567890,
            window_id=window_id,
        )

        assert notification['ROUTE_NAME'] == 'test-route'
        assert notification['DIRECTION'] == 'input'
        assert notification['WINDOW_SIZE'] == 60
        assert notification['MAX_TOKENS'] == 1000
        assert notification['CURRENT_USAGE'] == 500
        assert notification['RESET_TIME'] == 1234567890
        assert notification['WINDOW_ID'] == window_id
        assert isinstance(notification['TIMESTAMP'], datetime)


class TestCeleryBuffer:
    def test_initialization(self):
        """Test CeleryBuffer initializes with correct defaults."""
        buffer = CeleryBuffer(task_name='emit_notification', buffer_name='TestBuffer')
        assert buffer._buffer == []
        assert buffer._closed is False

    def test_add_notification_to_buffer(self):
        """Test adding a notification to the buffer."""
        buffer = CeleryBuffer(task_name='emit_notification', buffer_name='TestBuffer')

        notification = {'test': 'notification'}
        with patch.object(buffer, '_start_timer_unlocked'):
            buffer.add(notification)

        assert buffer._buffer == [notification]

    def test_batch_flush_when_full(self):
        """Test that buffer flushes when batch size is reached."""
        buffer = CeleryBuffer(task_name='emit_notification', buffer_name='TestBuffer')
        buffer._batch_size = 3  # Small batch size for testing

        with patch.object(buffer, '_send_batch') as mock_send:
            # Add notifications up to batch size
            for i in range(3):
                buffer.add({'id': i})

            # Should flush when batch is full
            mock_send.assert_called_once()
            assert len(buffer._buffer) == 0

    def test_flush(self):
        """Test manual flush of buffer."""
        buffer = CeleryBuffer(task_name='emit_notification', buffer_name='TestBuffer')

        with patch.object(buffer, '_send_batch') as mock_send:
            buffer.add({'test': 'notification'})
            buffer.flush()

            mock_send.assert_called_once()
            assert len(buffer._buffer) == 0

    def test_close(self):
        """Test closing the buffer."""
        buffer = CeleryBuffer(task_name='emit_notification', buffer_name='TestBuffer')

        with patch.object(buffer, 'flush') as mock_flush:
            buffer.close()

            assert buffer._closed is True
            mock_flush.assert_called_once()

    def test_closed_buffer_drops_notifications(self):
        """Test that closed buffer drops new notifications."""
        buffer = CeleryBuffer(task_name='emit_notification', buffer_name='TestBuffer')
        buffer.close()

        with patch('radicalbit_ai_gateway.events.buffer.logger') as mock_logger:
            buffer.add({'test': 'notification'})

            mock_logger.warning.assert_called_once()
            assert 'closed' in mock_logger.warning.call_args[0][0].lower()


class TestEmitNotification:
    @patch('radicalbit_ai_gateway.events.notifications_processor._notifications_buffer')
    def test_emit_notification_adds_to_buffer(self, mock_buffer):
        """Test that emit_notification creates and adds notification to buffer."""

        window_id = uuid.uuid4()
        emit_notification(
            route_name='test-route',
            direction='output',
            window_size=30,
            max_tokens=500,
            current_usage=250,
            reset_time=1234567890,
            window_id=window_id,
        )

        mock_buffer.add.assert_called_once()
        notification = mock_buffer.add.call_args[0][0]

        assert notification['ROUTE_NAME'] == 'test-route'
        assert notification['DIRECTION'] == 'output'
        assert notification['WINDOW_SIZE'] == 30
        assert notification['MAX_TOKENS'] == 500
        assert notification['CURRENT_USAGE'] == 250
        assert notification['RESET_TIME'] == 1234567890
        assert notification['WINDOW_ID'] == window_id
