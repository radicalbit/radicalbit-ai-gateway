from collections.abc import Sequence
import datetime
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_limit_dao import GroupLimitDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.db.tables.group_limit_table import GroupLimit
from radicalbit_ai_gateway.db.tables.key_limit_table import KeyLimit
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.limiting.credential_limiter import clear_limit_counter
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    KeyFullOut,
    KeyGroupIn,
    KeyIn,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
    CredentialLimitsIn,
)
from radicalbit_ai_gateway.models.group_limiting import GroupLimitOverwriteWarning
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    CredentialLimitAlreadyExistsError,
    CredentialLimitNotFoundError,
    GroupNotFoundError,
    KeyAlreadyExistsError,
    KeyGroupAlreadyExistsError,
    KeyInternalError,
    KeyNotFoundError,
    KeyOperationNotAllowedError,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class KeyService:
    def __init__(
        self,
        key_dao: KeyDAO,
        api_key_security: ApiKeySecurity,
        group_dao: GroupDAO,
        key_limit_dao: KeyLimitDAO,
        group_limit_dao: GroupLimitDAO,
    ):
        self.key_dao = key_dao
        self.api_key_security = api_key_security
        self.group_dao = group_dao
        self.key_limit_dao = key_limit_dao
        self.group_limit_dao = group_limit_dao

    def _get_key(
        self,
        key_uuid: UUID,
        include_groups: bool = False,
        include_limits: bool = False,
    ) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        return KeyFullOut.from_key_obscured(
            key=key,
            include_groups=include_groups,
            include_limits=include_limits,
        )

    def create_key(self, key_in: KeyIn) -> KeyFullOut:
        try:
            api_key_sec = self.api_key_security.generate_key()
            to_insert = key_in.to_key(
                hashed_key=api_key_sec.hashed_key, obscured_key=api_key_sec.obscured_key
            )
            inserted = self.key_dao.insert(to_insert)
            return KeyFullOut.from_key(
                key=inserted, plain_api_key=api_key_sec.plain_key
            )
        except IntegrityError as e:
            # Check if it's a unique constraint violation on NAME, OWNER
            if 'uq_key_NAME_OWNER' in str(e.orig) or 'NAME' in str(e.orig):
                raise KeyAlreadyExistsError(
                    f'Key with name "{key_in.name}" already exists'
                ) from e
            raise KeyInternalError(
                f'An error occurred while creating the key: {e}'
            ) from e
        except Exception as e:
            raise KeyInternalError(
                f'An error occurred while creating the key: {e}'
            ) from e

    def get_all(
        self,
        include_groups: bool,
        only_unassigned: bool,
        include_limits: bool = False,
    ) -> list[KeyFullOut]:
        keys = self.key_dao.get_all(only_unassigned=only_unassigned)
        return [
            KeyFullOut.from_key_obscured(
                key=key,
                include_groups=include_groups,
                include_limits=include_limits,
            )
            for key in keys
        ]

    def delete_key(self, key_uuid: UUID, include_groups: bool = False) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        if key.owner != 'gateway':
            raise KeyOperationNotAllowedError(
                f'Key {key_uuid} cannot be deleted because owner is "{key.owner}"'
            )
        deleted_rows = self.key_dao.delete_by_uuid(key_uuid)
        if deleted_rows == 0:
            raise KeyInternalError(f'Key {key.name} not deleted')
        return KeyFullOut.from_key_obscured(key=key, include_groups=include_groups)

    def get_key_by_uuid(
        self,
        key_uuid: UUID,
        include_groups: bool,
        include_limits: bool = False,
    ) -> KeyFullOut:
        return self._get_key(
            key_uuid=key_uuid,
            include_groups=include_groups,
            include_limits=include_limits,
        )

    def update_key_name(self, key_uuid: UUID, key_in: KeyIn) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        if key.owner != 'gateway':
            raise KeyOperationNotAllowedError(
                f'Key {key_uuid} cannot be updated because owner is "{key.owner}"'
            )
        try:
            updated_rows = self.key_dao.update_key_name(key_uuid, key_in.name)
        except IntegrityError as e:
            # Check if it's a unique constraint violation on NAME, OWNER
            if 'uq_key_NAME_OWNER' in str(e.orig) or 'NAME' in str(e.orig):
                raise KeyAlreadyExistsError(
                    f'Key with name "{key_in.name}" already exists'
                ) from e
            raise KeyInternalError(
                f'An error occurred while updating the key: {e}'
            ) from e
        if updated_rows == 0:
            raise KeyInternalError(f'Key {key.name} not updated')
        return self._get_key(key_uuid)

    def add_group_to_key(
        self, key_uuid: UUID, key_group_in: KeyGroupIn, include_groups: bool
    ) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        if key.group_uuid:
            raise KeyGroupAlreadyExistsError(
                f'Key with UUID {key_uuid} already has a group assigned: {key.group.name}'
            )
        if key.owner != 'gateway':
            raise KeyOperationNotAllowedError(
                f'Key {key_uuid} cannot be assigned to a group because owner is "{key.owner}"'
            )
        group = self.group_dao.get_by_uuid(key_group_in.group)
        if group and key.owner != group.owner:
            raise KeyOperationNotAllowedError(
                f'Cannot assign a {key.owner!r} key to a {group.owner!r} group'
            )
        try:
            inserted = self.key_dao.assign_group(
                key_uuid=key_uuid, group_uuid=key_group_in.group
            )
            if inserted is None:
                raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        except IntegrityError as exc:
            raise KeyInternalError(
                f'An error occurred while assigning the group to the key: {exc}'
            ) from exc
        else:
            group_limits = self.group_limit_dao.get_by_group_uuid(key_group_in.group)
            if group_limits:
                self.propagate_group_limits(group_limits=group_limits, keys=[inserted])
            return KeyFullOut.from_key_obscured(
                key=inserted, include_groups=include_groups
            )

    async def remove_group_from_key(
        self, key_uuid: UUID, group_uuid: UUID
    ) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        if key.owner != 'gateway':
            raise KeyOperationNotAllowedError(
                f'Key {key_uuid} cannot be unassigned from group because owner is "{key.owner}"'
            )
        removed_rows = self.key_dao.remove_group(key_uuid=key_uuid)
        if removed_rows == 0:
            raise KeyInternalError(
                f'Group with UUID {group_uuid} not removed from key {key.name}'
            )
        propagated = self.key_limit_dao.delete_group_limits_by_key_uuid(key_uuid)
        await self._clear_limit_counters(propagated)
        return KeyFullOut.from_key_obscured(key=key, include_groups=True)

    def propagate_group_limits(
        self, group_limits: Sequence[GroupLimit], keys: Sequence[Key]
    ) -> tuple[list[CredentialLimitOut], list[GroupLimitOverwriteWarning]]:
        """Copy each group limit onto each key's own limits. The last limit
        applied to a credential always wins: an existing limit for the same
        (key, category, algorithm, window_size) — individually-set or from
        another group — is overwritten, not skipped.
        """
        if not group_limits or not keys:
            return [], []
        existing_by_signature = {
            (limit.key_uuid, limit.category, limit.algorithm, limit.window_size): limit
            for limit in self.key_limit_dao.get_all_by_key_uuids(
                [key.uuid for key in keys]
            )
        }
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        to_insert: list[KeyLimit] = []
        to_update: list[KeyLimit] = []
        overwritten: list[GroupLimitOverwriteWarning] = []
        for key in keys:
            for group_limit in group_limits:
                signature = (
                    key.uuid,
                    group_limit.category,
                    group_limit.algorithm,
                    group_limit.window_size,
                )
                existing = existing_by_signature.get(signature)
                if existing is not None:
                    was_from_a_different_source = (
                        existing.group_limit_uuid != group_limit.uuid
                    )
                    existing.max_value = group_limit.max_value
                    existing.group_limit_uuid = group_limit.uuid
                    existing.updated_at = now
                    to_update.append(existing)
                    if was_from_a_different_source:
                        overwritten.append(
                            GroupLimitOverwriteWarning(
                                key_uuid=key.uuid,
                                key_name=key.name,
                                category=CredentialLimitCategory(group_limit.category),
                                algorithm=LimitingAlgorithmType(group_limit.algorithm),
                                window_size=group_limit.window_size,
                            )
                        )
                else:
                    to_insert.append(
                        KeyLimit(
                            key_uuid=key.uuid,
                            category=group_limit.category,
                            algorithm=group_limit.algorithm,
                            window_size=group_limit.window_size,
                            max_value=group_limit.max_value,
                            group_limit_uuid=group_limit.uuid,
                            created_at=now,
                            updated_at=now,
                        )
                    )
        inserted = self.key_limit_dao.insert_many(to_insert) if to_insert else []
        updated = self.key_limit_dao.update_many(to_update) if to_update else []
        applied = [
            CredentialLimitOut.from_key_limit(limit) for limit in inserted + updated
        ]
        return applied, overwritten

    async def clear_propagated_limit_counters(self, group_limit_uuid: UUID) -> None:
        limits = self.key_limit_dao.get_by_group_limit_uuid(group_limit_uuid)
        await self._clear_limit_counters(limits)

    @staticmethod
    async def _clear_limit_counters(limits: Sequence[KeyLimit]) -> None:
        """Best-effort: the DB rows are already gone (or about to be, via a
        cascading delete), that's what matters.
        """
        for limit in limits:
            try:
                await clear_limit_counter(
                    credential_uuid=str(limit.key_uuid),
                    category=limit.category,
                    algorithm=limit.algorithm,
                    window_size=limit.window_size,
                )
            except Exception:
                logger.exception(
                    'Failed to clear the limit counter for limit %s on key %s',
                    limit.uuid,
                    limit.key_uuid,
                )

    def get_associable_keys(self, group_uuid: UUID) -> list[KeyFullOut]:
        group = self.group_dao.get_by_uuid(group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        if group.owner != 'gateway':
            return []
        keys = self.key_dao.get_all(only_unassigned=True, owner='gateway')
        return [KeyFullOut.from_key_obscured(key=key) for key in keys]

    def get_associable_groups(
        self, key_uuid: UUID, include_routes: bool, include_keys: bool
    ) -> list[GroupFullOut]:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        if key.owner != 'gateway':
            return []
        if key.group_uuid:
            return []
        groups = self.group_dao.get_all_by_owner(owner='gateway')
        return [
            GroupFullOut.from_group(
                group=group,
                include_routes=include_routes,
                include_keys=include_keys,
            )
            for group in groups
        ]

    def get_key_by_hashed_key(self, hashed_api_key) -> KeyFullOut:
        key = self.key_dao.get_key_by_hashed_key(hashed_api_key=hashed_api_key)
        if not key:
            raise KeyNotFoundError('Key with does not exists')
        return KeyFullOut.from_key_obscured(
            key=key, include_groups=True, include_limits=True
        )

    def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        return self.key_dao.get_names_by_uuids(uuids)

    def add_limits_to_key(
        self,
        key_uuid: UUID,
        limits_in: CredentialLimitsIn,
        include_groups: bool = False,
    ) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        if key.owner != 'gateway':
            raise KeyOperationNotAllowedError(
                f'Key {key_uuid} cannot have limits configured because owner is "{key.owner}"'
            )
        existing_signatures = {
            (limit.category, limit.algorithm, limit.window_size)
            for limit in self.key_limit_dao.get_by_key_uuid(key_uuid)
        }
        for limit_in in limits_in.limits:
            signature = (
                limit_in.category.value,
                limit_in.algorithm.value,
                str(limit_in.window_size),
            )
            if signature in existing_signatures:
                # No overwrite here, regardless of whether the existing limit
                # is individually-set or inherited from a group: delete it
                # first, then add the new one, if you want to replace it.
                raise CredentialLimitAlreadyExistsError(
                    f'A limit for {limit_in.category.value} with algorithm '
                    f'{limit_in.algorithm.value} and window {limit_in.window_size} '
                    f'already exists on credential "{key.name}"'
                )
        try:
            self.key_limit_dao.insert_many(limits_in.to_key_limits(key_uuid))
        except IntegrityError as e:
            if 'uq_key_limit_KEY_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE' in str(e.orig):
                raise CredentialLimitAlreadyExistsError(
                    f'One of the requested limits already exists on credential '
                    f'"{key.name}" with the same algorithm and window'
                ) from e
            raise KeyInternalError(
                f'An error occurred while adding the limits: {e}'
            ) from e
        except Exception as e:
            raise KeyInternalError(
                f'An error occurred while adding the limits: {e}'
            ) from e
        return self._get_key(
            key_uuid, include_groups=include_groups, include_limits=True
        )

    def get_limits_for_key(self, key_uuid: UUID) -> list[CredentialLimitOut]:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        return [
            CredentialLimitOut.from_key_limit(limit)
            for limit in self.key_limit_dao.get_by_key_uuid(key_uuid)
        ]

    async def delete_limit_from_key(
        self, key_uuid: UUID, limit_uuid: UUID
    ) -> CredentialLimitOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        limit = self.key_limit_dao.get_by_uuid(limit_uuid)
        if not limit or limit.key_uuid != key_uuid:
            raise CredentialLimitNotFoundError(
                f'Limit {limit_uuid} not found for key "{key.name}"'
            )
        out = CredentialLimitOut.from_key_limit(limit)
        self.key_limit_dao.delete_by_uuid(limit_uuid)
        await self._clear_limit_counters([limit])
        return out
