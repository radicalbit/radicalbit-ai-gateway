import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.limiting.credential_limiter import clear_limit_counter
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    KeyFullOut,
    KeyGroupIn,
    KeyIn,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitOut,
    CredentialLimitsIn,
)
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
    ):
        self.key_dao = key_dao
        self.api_key_security = api_key_security
        self.group_dao = group_dao
        self.key_limit_dao = key_limit_dao

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
            return KeyFullOut.from_key_obscured(
                key=inserted, include_groups=include_groups
            )

    def remove_group_from_key(self, key_uuid: UUID, group_uuid: UUID) -> KeyFullOut:
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
        return KeyFullOut.from_key_obscured(key=key, include_groups=True)

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
        try:
            self.key_limit_dao.insert_many(limits_in.to_key_limits(key_uuid))
        except IntegrityError as e:
            if 'uq_key_limit_KEY_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE' in str(e.orig):
                categories = ', '.join(
                    limit.category.value for limit in limits_in.limits
                )
                raise CredentialLimitAlreadyExistsError(
                    f'One of the requested limits ({categories}) already exists '
                    f'on credential "{key.name}" with the same algorithm and window'
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
        # Built before deletion so the caller still sees what was removed.
        out = CredentialLimitOut.from_key_limit(limit)
        self.key_limit_dao.delete_by_uuid(limit_uuid)
        try:
            await clear_limit_counter(
                credential_uuid=str(key_uuid),
                category=limit.category,
                algorithm=limit.algorithm,
                window_size=limit.window_size,
            )
        except Exception:
            # The DB row is already gone — that's the source of truth for
            # whether the limit exists. A stale counter left behind here
            # would only matter if a new limit with the exact same
            # category/algorithm/window is created before it naturally
            # expires, so this is worth logging but not worth failing the
            # request over.
            logger.exception(
                'Failed to clear the limit counter for limit %s on key %s',
                limit_uuid,
                key_uuid,
            )
        return out
