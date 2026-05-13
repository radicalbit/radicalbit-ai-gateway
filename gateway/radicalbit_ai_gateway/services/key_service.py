from uuid import UUID

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    KeyFullOut,
    KeyGroupIn,
    KeyIn,
)
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.utils.exceptions import (
    GroupNotFoundError,
    KeyAlreadyExistsError,
    KeyGroupAlreadyExistsError,
    KeyInternalError,
    KeyNotFoundError,
    KeyOperationNotAllowedError,
)


class KeyService:
    def __init__(
        self,
        key_dao: KeyDAO,
        api_key_security: ApiKeySecurity,
        group_dao: GroupDAO,
    ):
        self.key_dao = key_dao
        self.api_key_security = api_key_security
        self.group_dao = group_dao

    def _get_key(self, key_uuid: UUID, include_groups: bool = False) -> KeyFullOut:
        key = self.key_dao.get_by_uuid(key_uuid)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        return KeyFullOut.from_key_obscured(
            key=key,
            include_groups=include_groups,
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

    def get_all(self, include_groups: bool, only_unassigned: bool) -> list[KeyFullOut]:
        keys = self.key_dao.get_all(only_unassigned=only_unassigned)
        return [
            KeyFullOut.from_key_obscured(
                key=key,
                include_groups=include_groups,
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

    def get_key_by_uuid(self, key_uuid: UUID, include_groups: bool) -> KeyFullOut:
        return self._get_key(key_uuid=key_uuid, include_groups=include_groups)

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
        return KeyFullOut.from_key_obscured(key=key, include_groups=True)

    def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        return self.key_dao.get_names_by_uuids(uuids)
