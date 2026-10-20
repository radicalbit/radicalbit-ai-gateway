import datetime
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.models.auth_dto import KeyFullOut
from radicalbit_ai_gateway.models.credential_expiry import CredentialState


class KeyDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_dao = KeyDAO(cls.db)
        cls.group_dao = GroupDAO(cls.db)

    def test_insert(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid

    def test_get_all(self):
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='three'),
        ]
        _ = [self.key_dao.insert(i) for i in api_keys]
        res = self.key_dao.get_all(only_unassigned=False)
        assert len(res) == 3

    def test_delete_key(self):
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
        ]
        _ = [self.key_dao.insert(i) for i in api_keys]
        res = self.key_dao.get_all(False)
        assert len(res) == 2
        deleted_rows = self.key_dao.delete_by_uuid(api_keys[0].uuid)
        assert deleted_rows == 1
        res = self.key_dao.get_all(False)
        assert len(res) == 1

    def test_get_key_by_uuid(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        retrieved_key = self.key_dao.get_by_uuid(key.uuid)
        assert retrieved_key.uuid == key.uuid
        assert retrieved_key.name == key.name

    def test_update_key_name(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        new_name = 'new-name'
        updated_rows = self.key_dao.update_key_name(key.uuid, new_name)
        assert updated_rows == 1
        retrieved_key = self.key_dao.get_by_uuid(key.uuid)
        assert retrieved_key.uuid == key.uuid
        assert retrieved_key.name == new_name

    def test_get_key_hashed_key(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        retrieved_key = self.key_dao.get_key_by_hashed_key(db_mock.HASHED_KEY)
        assert retrieved_key.uuid == key.uuid

    def test_assign_group(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        group = db_mock.get_sample_group_plain()
        inserted_group = self.group_dao.insert(group)
        assert inserted.uuid == key.uuid
        assigned_key = self.key_dao.assign_group(key.uuid, inserted_group.uuid)
        assert assigned_key is not None
        assert assigned_key.group_uuid == inserted_group.uuid

    def test_assign_group_not_exists_error(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        pytest.raises(
            IntegrityError,
            self.key_dao.assign_group,
            key_uuid=key.uuid,
            group_uuid=uuid.uuid4(),
        )

    def test_get_all_keys_ungrouped(self):
        group_one, group_two = uuid.uuid4(), uuid.uuid4()
        self.group_dao.insert(db_mock.get_sample_group(uuid=group_one, name='g1'))
        self.group_dao.insert(db_mock.get_sample_group(uuid=group_two, name='g2'))
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one', group_uuid=group_one),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_key(
                uuid=uuid.uuid4(), name='three', group_uuid=group_two
            ),
        ]
        _ = [self.key_dao.insert(i) for i in api_keys]
        res = self.key_dao.get_all(only_unassigned=True)
        assert len(res) == 1

    def test_expires_on_round_trips_as_a_date(self):
        key = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name='expiring', expires_on=datetime.date(2026, 11, 10)
        )
        self.key_dao.insert(key)
        assert self.key_dao.get_by_uuid(key.uuid).expires_on == datetime.date(
            2026, 11, 10
        )

    def test_a_key_without_expiry_date_reads_back_as_none(self):
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), name='never')
        self.key_dao.insert(key)
        out = KeyFullOut.from_key_obscured(self.key_dao.get_by_uuid(key.uuid))
        assert out.expires_on is None
        assert out.state == CredentialState.ACTIVE

    # --- rotation (AG-1042, AG-1043) ---

    _UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
    NOW = datetime.datetime(2026, 11, 1, 12, tzinfo=_UTC)
    GRACE_END = datetime.datetime(2026, 11, 2, 12, tzinfo=_UTC)

    def _insert_rotatable(self, name: str):
        key = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name=name, hashed_key=f'{name}-v1'
        )
        self.key_dao.insert(key)
        return key

    def _rotate(self, key, expected='v1', new='v2', grace_ends_at=GRACE_END, now=NOW):
        return self.key_dao.rotate(
            key_uuid=key.uuid,
            expected_hashed_key=f'{key.name}-{expected}',
            hashed_key=f'{key.name}-{new}',
            obscured_key=f'obscured-{new}',
            grace_ends_at=grace_ends_at,
            now=now,
        )

    def test_rotate_with_a_grace_period_keeps_both_values_findable(self):
        key = self._insert_rotatable('rot-grace')
        rotated = self._rotate(key)
        assert rotated.hashed_key == 'rot-grace-v2'
        assert rotated.obscured_key == 'obscured-v2'
        assert rotated.grace_ends_at == self.GRACE_END
        assert rotated.last_rotated_at == self.NOW
        assert self.key_dao.get_key_by_hashed_key('rot-grace-v2').uuid == key.uuid
        assert self.key_dao.get_key_by_hashed_key('rot-grace-v1').uuid == key.uuid

    def test_rotate_with_no_grace_period_forgets_the_previous_value(self):
        key = self._insert_rotatable('rot-none')
        rotated = self._rotate(key, grace_ends_at=None)
        assert rotated.grace_ends_at is None
        assert rotated.last_rotated_at == self.NOW
        assert self.key_dao.get_key_by_hashed_key('rot-none-v1') is None
        assert self.key_dao.get_key_by_hashed_key('rot-none-v2').uuid == key.uuid

    def test_rotate_is_refused_while_a_grace_period_is_running(self):
        key = self._insert_rotatable('rot-twice')
        self._rotate(key)
        before_end = self.GRACE_END - datetime.timedelta(seconds=1)
        assert self._rotate(key, expected='v2', new='v3', now=before_end) is None
        assert self.key_dao.get_key_by_hashed_key('rot-twice-v3') is None
        assert self.key_dao.get_key_by_hashed_key('rot-twice-v1').uuid == key.uuid

    def test_rotate_succeeds_again_once_the_grace_period_is_over(self):
        key = self._insert_rotatable('rot-again')
        self._rotate(key)
        rotated = self._rotate(key, expected='v2', new='v3', now=self.GRACE_END)
        assert rotated.hashed_key == 'rot-again-v3'
        assert self.key_dao.get_key_by_hashed_key('rot-again-v1') is None
        assert self.key_dao.get_key_by_hashed_key('rot-again-v2').uuid == key.uuid

    def test_a_concurrent_rotation_from_the_same_value_loses(self):
        key = self._insert_rotatable('rot-race')
        assert self._rotate(key, grace_ends_at=None) is not None
        # A second request that read the key before the first one wrote
        assert self._rotate(key, new='v3', grace_ends_at=None) is None
        assert self.key_dao.get_key_by_hashed_key('rot-race-v2').uuid == key.uuid

    def test_end_grace_period_forgets_the_previous_value(self):
        key = self._insert_rotatable('rot-end')
        self._rotate(key)
        ended = self.key_dao.end_grace_period(key.uuid, now=self.NOW)
        assert ended.grace_ends_at is None
        assert ended.last_rotated_at == self.NOW
        assert self.key_dao.get_key_by_hashed_key('rot-end-v1') is None
        assert self.key_dao.get_key_by_hashed_key('rot-end-v2').uuid == key.uuid

    def test_end_grace_period_with_none_running_changes_nothing(self):
        key = self._insert_rotatable('rot-end-none')
        assert self.key_dao.end_grace_period(key.uuid, now=self.NOW) is None
        self._rotate(key)
        assert self.key_dao.end_grace_period(key.uuid, now=self.GRACE_END) is None
