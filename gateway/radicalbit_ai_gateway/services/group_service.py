import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_limit_dao import GroupLimitDAO
from radicalbit_ai_gateway.db.dao.group_route_dao import GroupRouteDAO
from radicalbit_ai_gateway.db.tables.group_limit_table import GroupLimit
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupIn,
    GroupRouteOut,
    GroupRoutesIn,
    GroupsRouteOut,
    KeyFullOut,
    KeyGroupIn,
    KeysUuidIn,
    RouteGroupsIn,
)
from radicalbit_ai_gateway.models.group_limiting import (
    GroupLimitOut,
    GroupLimitsApplyOut,
    GroupLimitsIn,
)
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    GroupAlreadyExistsError,
    GroupInternalError,
    GroupLimitAlreadyExistsError,
    GroupLimitNotFoundError,
    GroupNotFoundError,
    GroupOperationNotAllowedError,
    KeyNotFoundError,
    RouteNotFoundError,
)


class GroupService:
    def __init__(
        self,
        group_dao: GroupDAO,
        group_route_dao: GroupRouteDAO,
        key_service: KeyService,
        group_limit_dao: GroupLimitDAO,
        project_configs: dict[str, ProjectEntry] | None = None,
    ):
        self.group_dao = group_dao
        self.key_service = key_service
        self.group_route_dao = group_route_dao
        self.group_limit_dao = group_limit_dao
        self._project_configs = project_configs if project_configs is not None else {}

    def _validate_group(self, group_uuid: UUID) -> None:
        if not self.group_dao.get_by_uuid(group_uuid=group_uuid):
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')

    def _validate_route(self, project_name: str, route_name: str) -> None:
        entry = self._project_configs.get(project_name)
        if entry and route_name in entry.config.routes:
            return
        raise RouteNotFoundError(f'Route {project_name}/{route_name} not exists')

    def cleanup_orphaned_associations(
        self, project_uuid: UUID, project_name: str
    ) -> int:
        """Drop the project's group↔route associations whose route_name is not
        present in the currently served config. Must be called after the newly
        served config has been registered in project_configs. Returns the number
        of deleted associations.
        """
        entry = self._project_configs.get(project_name)
        valid_route_names = list(entry.config.routes) if entry else []
        return self.group_dao.delete_orphaned_associations(
            project_uuid, valid_route_names
        )

    def _get_group(
        self, group_uuid: UUID, include_routes: bool = False, include_keys: bool = False
    ) -> GroupFullOut:
        group = self.group_dao.get_by_uuid(group_uuid=group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        return GroupFullOut.from_group(
            group=group,
            include_routes=include_routes,
            include_keys=include_keys,
        )

    def _get_key(self, key_uuid: UUID) -> KeyFullOut:
        key = self.key_service.get_key_by_uuid(key_uuid, False)
        if not key:
            raise KeyNotFoundError(f'Key with UUID {key_uuid} not exists')
        return key

    def create_group(self, group_in: GroupIn) -> GroupFullOut:
        try:
            group = group_in.to_group()
            inserted = self.group_dao.insert(group)
            return GroupFullOut.from_group(group=inserted)
        except IntegrityError as e:
            # Check if it's a unique constraint violation on (NAME, OWNER)
            if 'uq_group_NAME_OWNER' in str(e.orig) or 'NAME' in str(e.orig):
                raise GroupAlreadyExistsError(
                    f'Group with name "{group_in.name}" already exists'
                ) from e
            raise GroupInternalError(
                f'An error occurred while creating the group: {e}'
            ) from e
        except Exception as e:
            raise GroupInternalError(
                f'An error occurred while creating the group: {e}'
            ) from e

    def get_all(self, include_routes: bool, include_keys: bool) -> list[GroupFullOut]:
        groups = self.group_dao.get_all()
        return [
            GroupFullOut.from_group(
                group=group,
                include_keys=include_keys,
                include_routes=include_routes,
            )
            for group in groups
        ]

    @task(name='check_route_access')
    def check_key_uuid_for_route(self, route: str, key_uuid: UUID) -> bool:
        project_name, local_route = route.split('/', 1)
        entry = self._project_configs.get(project_name)
        if not entry:
            return False
        return (
            self.group_dao.check_key_uuid_for_route(entry.uuid, local_route, key_uuid)
            is not None
        )

    def delete_group(
        self, group_uuid: UUID, include_routes: bool, include_keys: bool
    ) -> GroupFullOut:
        group = self.group_dao.get_by_uuid(group_uuid=group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        if group.owner != 'gateway':
            raise GroupOperationNotAllowedError(
                f'Group {group_uuid} cannot be deleted because owner is "{group.owner}"'
            )
        group_name = group.name
        deleted_group = self.group_dao.delete_by_uuid(group_uuid)
        if deleted_group is None:
            raise GroupInternalError(f'Group {group_name} not deleted')
        return GroupFullOut.from_group(
            group=deleted_group,
            include_keys=include_keys,
            include_routes=include_routes,
        )

    def get_group_by_uuid(
        self, group_uuid: UUID, include_routes: bool, include_keys: bool
    ) -> GroupFullOut:
        return self._get_group(
            group_uuid=group_uuid,
            include_routes=include_routes,
            include_keys=include_keys,
        )

    def update_group_name(self, group_uuid: UUID, group_in: GroupIn) -> GroupFullOut:
        group = self.group_dao.get_by_uuid(group_uuid=group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        if group.owner != 'gateway':
            raise GroupOperationNotAllowedError(
                f'Group {group_uuid} cannot be updated because owner is "{group.owner}"'
            )
        try:
            updated_rows = self.group_dao.update_group_name(
                group_uuid=group_uuid, name=group_in.name
            )
        except IntegrityError as e:
            # Check if it's a unique constraint violation on (NAME, OWNER)
            if 'uq_group_NAME_OWNER' in str(e.orig) or 'NAME' in str(e.orig):
                raise GroupAlreadyExistsError(
                    f'Group with name "{group_in.name}" already exists'
                ) from e
            raise GroupInternalError(
                f'An error occurred while updating the group: {e}'
            ) from e
        if updated_rows == 0:
            raise GroupInternalError(f'Group {group.name} not updated')
        return self._get_group(group_uuid)

    def add_project_routes(
        self,
        group_uuid: UUID,
        project_uuid: UUID,
        project_name: str,
        route: GroupRoutesIn,
        include_routes: bool,
        include_keys: bool,
    ) -> GroupFullOut:
        self._validate_group(group_uuid)
        for r in route.routes:
            self._validate_route(project_name, r)
        group_routes = route.to_project_group_routes(group_uuid, project_uuid)
        route_names = ', '.join(f'{project_name}/{r}' for r in route.routes)
        try:
            inserted = self.group_route_dao.add_bulk(group_routes)
        except IntegrityError as exc:
            raise GroupAlreadyExistsError(
                f'A group with uuid: {group_uuid} already exists for one of the route {route_names}'
            ) from exc
        if not inserted:
            raise GroupInternalError(
                f'An error occurred when adding {route_names} to group: {group_uuid}'
            )
        return self._get_group(group_uuid, include_routes, include_keys)

    def add_groups_to_project_route(
        self,
        project_uuid: UUID,
        project_name: str,
        route_name: str,
        route_groups_in: RouteGroupsIn,
        include_groups: bool,
    ) -> GroupsRouteOut:
        self._validate_route(project_name, route_name)
        for group_uuid in route_groups_in.groups:
            if not self.group_dao.get_by_uuid(group_uuid):
                raise GroupNotFoundError(f'Group {group_uuid} not found')
        groups_route = route_groups_in.to_group_route(
            route_name=route_name, project_uuid=project_uuid
        )
        try:
            inserted = self.group_route_dao.add_bulk(groups_route)
        except IntegrityError as exc:
            raise GroupAlreadyExistsError(
                f'One of the selected groups is already linked to route: {project_name}/{route_name}'
            ) from exc
        return GroupsRouteOut.from_group_route(
            project_name=project_name,
            route_name=route_name,
            groups=[i.group for i in inserted] if include_groups else None,
        )

    def remove_project_route(
        self,
        group_uuid: UUID,
        project_uuid: UUID,
        project_name: str,
        route_name: str,
    ) -> GroupFullOut:
        self._validate_route(project_name, route_name)
        self._validate_group(group_uuid)
        delete_rows = self.group_dao.remove_project_route(
            group_uuid, project_uuid, route_name
        )
        if delete_rows == 0:
            raise GroupInternalError(
                f'Route {route_name} not removed from group {group_uuid}'
            )
        return self._get_group(group_uuid)

    def add_keys(
        self,
        group_uuid: UUID,
        keys: KeysUuidIn,
        include_routes: bool,
        include_keys: bool,
    ) -> GroupFullOut:
        group = self.group_dao.get_by_uuid(group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        if group.owner != 'gateway':
            raise GroupOperationNotAllowedError(
                f'Group {group_uuid} cannot have keys assigned because owner is "{group.owner}"'
            )
        keys_out = [self._get_key(i) for i in keys.keys]
        keys_name = ', '.join([i.name for i in keys_out])
        keys_updated = [
            self.key_service.add_group_to_key(
                key_group_in=KeyGroupIn(group=group_uuid),
                key_uuid=i,
                include_groups=False,
            )
            for i in keys.keys
        ]
        if not keys_updated:
            raise GroupInternalError(
                f'An error occuered when adding {keys_name} to group: {group_uuid}'
            )
        return self._get_group(
            group_uuid=group_uuid,
            include_routes=include_routes,
            include_keys=include_keys,
        )

    async def remove_key(self, group_uuid: UUID, key_uuid: UUID) -> GroupFullOut:
        group = self.group_dao.get_by_uuid(group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        if group.owner != 'gateway':
            raise GroupOperationNotAllowedError(
                f'Group {group_uuid} cannot have keys removed because owner is "{group.owner}"'
            )
        deleted = await self.key_service.remove_group_from_key(
            key_uuid=key_uuid, group_uuid=group_uuid
        )
        if deleted == 0:
            raise GroupInternalError(f'Key {key_uuid} not removed')
        return self._get_group(group_uuid, True, True)

    def get_associable_keys(self, group_uuid: UUID) -> list[KeyFullOut]:
        return self.key_service.get_associable_keys(group_uuid)

    def get_associable_routes(
        self, group_uuid: UUID, project_name: str
    ) -> list[GroupRouteOut]:
        group = self.group_dao.get_by_uuid(group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        assigned = set(self.group_dao.get_route_names_by_group_uuid(group_uuid))
        entry = self._project_configs.get(project_name)
        if not entry:
            return []
        return [
            GroupRouteOut(
                name=route_name,
                project_uuid=entry.uuid,
                project_name=project_name,
            )
            for route_name in entry.config.routes
            if f'{project_name}/{route_name}' not in assigned
        ]

    def get_associable_groups_for_project_route(
        self,
        project_name: str,
        route_name: str,
        include_routes: bool,
        include_keys: bool,
    ) -> list[GroupFullOut]:
        self._validate_route(project_name, route_name)
        all_groups = self.group_dao.get_all()
        entry = self._project_configs.get(project_name)
        groups_with_route = {
            g.uuid
            for g in self.group_dao.get_all_group_by_route_name(entry.uuid, route_name)
        }
        return [
            GroupFullOut.from_group(
                group=g,
                include_routes=include_routes,
                include_keys=include_keys,
            )
            for g in all_groups
            if g.uuid not in groups_with_route
        ]

    def get_all_groups_by_route(
        self, project_name: str, route_name: str
    ) -> list[GroupFullOut]:
        entry = self._project_configs.get(project_name)
        if not entry:
            return []
        groups = self.group_dao.get_all_group_by_route_name(entry.uuid, route_name)
        return [GroupFullOut.from_group(group=group) for group in groups]

    def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        return self.group_dao.get_names_by_uuids(uuids)

    def add_limits_to_group(
        self, group_uuid: UUID, limits_in: GroupLimitsIn
    ) -> GroupLimitsApplyOut:
        group = self.group_dao.get_by_uuid(group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        if group.owner != 'gateway':
            raise GroupOperationNotAllowedError(
                f'Group {group_uuid} cannot have limits configured because owner is "{group.owner}"'
            )
        # The last limit applied always wins here too: re-submitting a
        # category/algorithm/window the group already has updates it in
        # place instead of colliding with the unique constraint.
        existing_by_signature = {
            (limit.category, limit.algorithm, limit.window_size): limit
            for limit in self.group_limit_dao.get_by_group_uuid(group_uuid)
        }
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        to_insert: list[GroupLimit] = []
        to_update: list[GroupLimit] = []
        for limit_in in limits_in.limits:
            signature = (
                limit_in.category.value,
                limit_in.algorithm.value,
                str(limit_in.window_size),
            )
            existing = existing_by_signature.get(signature)
            if existing is None:
                to_insert.append(limit_in.to_group_limit(group_uuid))
            else:
                existing.max_value = limit_in.value
                existing.updated_at = now
                to_update.append(existing)
        try:
            inserted = self.group_limit_dao.insert_many(to_insert) if to_insert else []
            updated = self.group_limit_dao.update_many(to_update) if to_update else []
        except IntegrityError as e:
            if 'uq_group_limit_GROUP_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE' in str(
                e.orig
            ):
                categories = ', '.join(
                    limit.category.value for limit in limits_in.limits
                )
                raise GroupLimitAlreadyExistsError(
                    f'One of the requested limits ({categories}) already exists '
                    f'on group "{group.name}" with the same algorithm and window'
                ) from e
            raise GroupInternalError(
                f'An error occurred while adding the limits: {e}'
            ) from e
        except Exception as e:
            raise GroupInternalError(
                f'An error occurred while adding the limits: {e}'
            ) from e
        applied = inserted + updated
        _, overwritten = self.key_service.propagate_group_limits(
            group_limits=applied, keys=group.keys
        )
        return GroupLimitsApplyOut(
            limits=[GroupLimitOut.from_group_limit(limit) for limit in applied],
            overwritten=overwritten,
        )

    def get_limits_for_group(self, group_uuid: UUID) -> list[GroupLimitOut]:
        self._validate_group(group_uuid)
        return [
            GroupLimitOut.from_group_limit(limit)
            for limit in self.group_limit_dao.get_by_group_uuid(group_uuid)
        ]

    async def delete_limit_from_group(
        self, group_uuid: UUID, limit_uuid: UUID
    ) -> GroupLimitOut:
        group = self.group_dao.get_by_uuid(group_uuid)
        if not group:
            raise GroupNotFoundError(f'Group with UUID {group_uuid} not exists')
        limit = self.group_limit_dao.get_by_uuid(limit_uuid)
        if not limit or limit.group_uuid != group_uuid:
            raise GroupLimitNotFoundError(
                f'Limit {limit_uuid} not found for group "{group.name}"'
            )
        out = GroupLimitOut.from_group_limit(limit)
        await self.key_service.clear_propagated_limit_counters(limit_uuid)
        # Cascades: deleting the group limit also removes every key_limit row
        # that was propagated from it.
        self.group_limit_dao.delete_by_uuid(limit_uuid)
        return out
