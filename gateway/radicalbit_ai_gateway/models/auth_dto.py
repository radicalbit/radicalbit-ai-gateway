import datetime
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute
from radicalbit_ai_gateway.db.tables.group_table import Group
from radicalbit_ai_gateway.db.tables.key_table import Key


class KeyIn(BaseModel, validate_assignment=True):
    name: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    def to_key(self, hashed_key: str, obscured_key: str) -> Key:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return Key(
            name=self.name,
            owner='gateway',
            key_metadata=None,
            hashed_key=hashed_key,
            obscured_key=obscured_key,
            created_at=now,
            updated_at=now,
        )


class KeyOut(BaseModel):
    uuid: UUID
    name: str
    owner: str
    metadata: dict[str, str] | None
    hashed_key: str
    api_key: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_key(
        key: Key,
    ) -> 'KeyOut':
        return KeyOut(
            uuid=key.uuid,
            name=key.name,
            owner=key.owner,
            metadata=json.loads(key.key_metadata) if key.key_metadata else None,
            created_at=str(key.created_at),
            updated_at=str(key.updated_at),
            hashed_key=key.hashed_key,
            api_key=key.obscured_key,
        )


class KeyGroupIn(BaseModel):
    group: UUID

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GroupKeyIn(BaseModel):
    key: UUID

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class KeysUuidIn(BaseModel):
    keys: list[UUID]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RouteGroupsIn(BaseModel):
    groups: list[UUID]

    def to_group_route(self, route_name: str, project_uuid: UUID) -> list[GroupRoute]:
        return [
            GroupRoute(group_uuid=i, route_name=route_name, project_uuid=project_uuid)
            for i in self.groups
        ]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GroupRoutesIn(BaseModel):
    routes: list[str]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    def to_project_group_routes(
        self, group_uuid: UUID, project_uuid: UUID
    ) -> list[GroupRoute]:
        """Build GroupRoute objects for project-scoped routes (local name only)."""
        return [
            GroupRoute(
                group_uuid=group_uuid,
                route_name=r,
                project_uuid=project_uuid,
            )
            for r in self.routes
        ]


class GroupRouteOut(BaseModel):
    name: str
    project_uuid: UUID
    project_name: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_group_route(route: GroupRoute) -> 'GroupRouteOut':
        return GroupRouteOut(
            name=route.route_name,
            project_uuid=route.project_uuid,
            project_name=route.project.name,
        )


class GroupIn(BaseModel, validate_assignment=True):
    name: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    def to_group(self) -> Group:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return Group(
            name=self.name,
            owner='gateway',
            group_metadata=None,
            created_at=now,
            updated_at=now,
        )


class GroupOut(BaseModel):
    uuid: UUID
    name: str
    owner: str
    metadata: dict[str, str] | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_group(group: Group) -> 'GroupOut':
        return GroupOut(
            uuid=group.uuid,
            name=group.name,
            owner=group.owner,
            metadata=json.loads(group.group_metadata) if group.group_metadata else None,
            created_at=str(group.created_at),
            updated_at=str(group.updated_at),
        )


class KeyFullOut(KeyOut):
    group: GroupOut | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    # Used only on Key creation, to return api_key not obscured
    @staticmethod
    def from_key(
        key: Key, plain_api_key: str, include_groups: bool = False
    ) -> 'KeyFullOut':
        return KeyFullOut(
            uuid=key.uuid,
            name=key.name,
            owner=key.owner,
            metadata=json.loads(key.key_metadata) if key.key_metadata else None,
            hashed_key=key.hashed_key,
            api_key=plain_api_key,
            group=GroupOut.from_group(key.group)
            if include_groups and key.group
            else None,
            created_at=str(key.created_at),
            updated_at=str(key.updated_at),
        )

    # Used to return Key with api_key obscured
    @staticmethod
    def from_key_obscured(key: Key, include_groups: bool = False) -> 'KeyFullOut':
        return KeyFullOut(
            uuid=key.uuid,
            name=key.name,
            owner=key.owner,
            metadata=json.loads(key.key_metadata) if key.key_metadata else None,
            hashed_key=key.hashed_key,
            api_key=key.obscured_key,
            group=GroupOut.from_group(key.group)
            if include_groups and key.group
            else None,
            created_at=str(key.created_at),
            updated_at=str(key.updated_at),
        )


class GroupFullOut(GroupOut):
    routes: list[GroupRouteOut] | None
    keys: list[KeyOut] | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_group(
        group: Group,
        include_routes: bool = False,
        include_keys: bool = False,
    ) -> 'GroupFullOut':
        return GroupFullOut(
            uuid=group.uuid,
            name=group.name,
            owner=group.owner,
            metadata=json.loads(group.group_metadata) if group.group_metadata else None,
            routes=[
                GroupRouteOut.from_group_route(route)
                for route in group.group_routes
                if route.project and route.project.deleted_at is None
            ]
            if include_routes
            else None,
            keys=[KeyOut.from_key(key) for key in group.keys] if include_keys else None,
            created_at=str(group.created_at),
            updated_at=str(group.updated_at),
        )


class GroupsRouteOut(BaseModel):
    route_name: str
    project_name: str
    groups: list[GroupOut] | None

    @staticmethod
    def from_group_route(
        project_name: str, route_name: str, groups: list[Group] | None
    ) -> 'GroupsRouteOut':
        return GroupsRouteOut(
            route_name=route_name,
            project_name=project_name,
            groups=[GroupOut.from_group(i) for i in groups] if groups else None,
        )


class KeyDetails(BaseModel):
    api_key_uuid: str
    api_key_name: str
    group_uuid: str
    group_name: str
    hashed_api_key: str
