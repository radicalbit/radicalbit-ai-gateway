from unittest.mock import patch

from radicalbit_ai_gateway.events.buffer import CeleryBuffer


class TestCeleryBuffer:
    def test_initialization(self):
        """Test CeleryBuffer initializes with correct defaults."""
        buffer = CeleryBuffer(task_name='test_task', buffer_name='TestBuffer')
        assert buffer._buffer == []
        assert buffer._closed is False

    def test_add_record_to_buffer(self):
        """Test adding a record to the buffer."""
        buffer = CeleryBuffer(task_name='test_task', buffer_name='TestBuffer')

        record = {'test': 'record'}
        with patch.object(buffer, '_start_timer_unlocked'):
            buffer.add(record)

        assert buffer._buffer == [record]

    def test_batch_flush_when_full(self):
        """Test that buffer flushes when batch size is reached."""
        buffer = CeleryBuffer(task_name='test_task', buffer_name='TestBuffer')
        buffer._batch_size = 3  # Small batch size for testing

        with patch.object(buffer, '_send_batch') as mock_send:
            # Add records up to batch size
            for i in range(3):
                buffer.add({'id': i})

            # Should flush when batch is full
            mock_send.assert_called_once()
            assert len(buffer._buffer) == 0

    def test_flush(self):
        """Test manual flush of buffer."""
        buffer = CeleryBuffer(task_name='test_task', buffer_name='TestBuffer')

        with patch.object(buffer, '_send_batch') as mock_send:
            buffer.add({'test': 'record'})
            buffer.flush()

            mock_send.assert_called_once()
            assert len(buffer._buffer) == 0

    def test_close(self):
        """Test closing the buffer."""
        buffer = CeleryBuffer(task_name='test_task', buffer_name='TestBuffer')

        with patch.object(buffer, 'flush') as mock_flush:
            buffer.close()

            assert buffer._closed is True
            mock_flush.assert_called_once()

    def test_closed_buffer_drops_records(self):
        """Test that closed buffer drops new records."""
        buffer = CeleryBuffer(task_name='test_task', buffer_name='TestBuffer')
        buffer.close()

        with patch('radicalbit_ai_gateway.events.buffer.logger') as mock_logger:
            buffer.add({'test': 'record'})

            mock_logger.warning.assert_called_once()
            assert 'closed' in mock_logger.warning.call_args[0][0].lower()
