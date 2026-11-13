"""The API's operations, one class per tag. Generated: do not edit.

Written by generator/generate_client.py from openapi.json (run scripts/generate.sh).
"""

from __future__ import annotations

import builtins
import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from radicalbit_gateway import models
from radicalbit_gateway._types import NOT_GIVEN, FileTypes, NotGiven

if TYPE_CHECKING:
    from radicalbit_gateway._client import Gateway


class ConfigsResource:
    """The ``configs`` operations."""

    def __init__(self, client: Gateway) -> None:
        self._client = client

    def approve(self, project_uuid: UUID, config_uuid: UUID) -> models.ProjectOut:
        """Request to publish a draft config: it becomes ready to serve."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/projects/{project_uuid}/configs/{config_uuid}/approve',
            path_params={'project_uuid': project_uuid, 'config_uuid': config_uuid},
            response=models.ProjectOut,
        )

    def cancel_approval(
        self, project_uuid: UUID, config_uuid: UUID
    ) -> models.ProjectOut:
        """Cancel a request to publish: the config goes back to draft."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/projects/{project_uuid}/configs/{config_uuid}/cancel-approval',
            path_params={'project_uuid': project_uuid, 'config_uuid': config_uuid},
            response=models.ProjectOut,
        )

    def save(
        self, project_uuid: UUID, config_uuid: UUID, *, config_file: str
    ) -> models.ProjectOut:
        """Save a YAML configuration into a config slot that is not served."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/projects/{project_uuid}/configs/{config_uuid}',
            path_params={'project_uuid': project_uuid, 'config_uuid': config_uuid},
            json={'configFile': config_file},
            response=models.ProjectOut,
        )

    def serve(self, project_uuid: UUID, config_uuid: UUID) -> models.ProjectOut:
        """Publish an approved config: it replaces the one served, if any."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/projects/{project_uuid}/configs/{config_uuid}/serve',
            path_params={'project_uuid': project_uuid, 'config_uuid': config_uuid},
            response=models.ProjectOut,
        )

    def unserve(self, project_uuid: UUID, config_uuid: UUID) -> models.ProjectOut:
        """Stop serving the served config: the project serves no routes."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/projects/{project_uuid}/configs/{config_uuid}/unserve',
            path_params={'project_uuid': project_uuid, 'config_uuid': config_uuid},
            response=models.ProjectOut,
        )

    def upload(
        self, project_uuid: UUID, config_uuid: UUID, *, file: FileTypes
    ) -> models.ProjectOut:
        """Upload a .yaml or .yml file (2 MB at most) into a config slot that is not served."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/projects/{project_uuid}/configs/{config_uuid}/import',
            path_params={'project_uuid': project_uuid, 'config_uuid': config_uuid},
            data={},
            files={'file': file},
            response=models.ProjectOut,
        )

    def validate(self, *, config_file: str) -> models.ConfigValidationOut:
        """Validate a YAML configuration against the config schema, saving nothing.

        Secrets are not checked: saving a valid config can still fail on them.
        """
        return self._client._request(
            'POST',
            '/public/api/v1/configs/validate',
            json={'configFile': config_file},
            response=models.ConfigValidationOut,
        )


class GroupsResource:
    """The ``groups`` operations."""

    def __init__(self, client: Gateway) -> None:
        self._client = client

    def add_keys(
        self,
        group_uuid: UUID,
        *,
        keys: builtins.list[UUID],
        include_routes: bool | NotGiven = NOT_GIVEN,
        include_keys: bool | NotGiven = NOT_GIVEN,
    ) -> models.GroupFullOut:
        """Add credentials to the group. A credential belongs to one group at most."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/groups/{group_uuid}/keys',
            path_params={'group_uuid': group_uuid},
            query={'include_routes': include_routes, 'include_keys': include_keys},
            json={'keys': keys},
            response=models.GroupFullOut,
        )

    def add_routes(
        self,
        group_uuid: UUID,
        project_uuid: UUID,
        *,
        routes: builtins.list[str],
        include_routes: bool | NotGiven = NOT_GIVEN,
        include_keys: bool | NotGiven = NOT_GIVEN,
    ) -> models.GroupFullOut:
        """Let the group's credentials call routes of a project's served config."""
        return self._client._request(
            'PATCH',
            '/public/api/v1/groups/{group_uuid}/projects/{project_uuid}/routes',
            path_params={'group_uuid': group_uuid, 'project_uuid': project_uuid},
            query={'include_routes': include_routes, 'include_keys': include_keys},
            json={'routes': routes},
            response=models.GroupFullOut,
        )

    def create(self, *, name: str) -> models.GroupFullOut:
        """Create a group of credentials."""
        return self._client._request(
            'POST',
            '/public/api/v1/groups',
            json={'name': name},
            response=models.GroupFullOut,
        )

    def get(
        self,
        group_uuid: UUID,
        *,
        include_routes: bool | NotGiven = NOT_GIVEN,
        include_keys: bool | NotGiven = NOT_GIVEN,
    ) -> models.GroupFullOut:
        """Get a group."""
        return self._client._request(
            'GET',
            '/public/api/v1/groups/{group_uuid}',
            path_params={'group_uuid': group_uuid},
            query={'include_routes': include_routes, 'include_keys': include_keys},
            response=models.GroupFullOut,
        )

    def list(
        self,
        *,
        include_routes: bool | NotGiven = NOT_GIVEN,
        include_keys: bool | NotGiven = NOT_GIVEN,
    ) -> builtins.list[models.GroupFullOut]:
        """List the groups."""
        return self._client._request(
            'GET',
            '/public/api/v1/groups',
            query={'include_routes': include_routes, 'include_keys': include_keys},
            response=builtins.list[models.GroupFullOut],
        )

    def remove_key(self, group_uuid: UUID, key_uuid: UUID) -> models.GroupFullOut:
        """Remove a credential from the group."""
        return self._client._request(
            'DELETE',
            '/public/api/v1/groups/{group_uuid}/keys/{key_uuid}',
            path_params={'group_uuid': group_uuid, 'key_uuid': key_uuid},
            response=models.GroupFullOut,
        )

    def remove_route(
        self, group_uuid: UUID, project_uuid: UUID, route_name: str
    ) -> models.GroupFullOut:
        """Stop the group's credentials from calling a route."""
        return self._client._request(
            'DELETE',
            '/public/api/v1/groups/{group_uuid}/projects/{project_uuid}/routes/{route_name}',
            path_params={
                'group_uuid': group_uuid,
                'project_uuid': project_uuid,
                'route_name': route_name,
            },
            response=models.GroupFullOut,
        )


class KeysResource:
    """The ``keys`` operations."""

    def __init__(self, client: Gateway) -> None:
        self._client = client

    def create(
        self, *, name: str, expires_on: datetime.date | None | NotGiven = NOT_GIVEN
    ) -> models.KeyFullOut:
        """Create a credential. The response is the only one carrying its value."""
        return self._client._request(
            'POST',
            '/public/api/v1/keys',
            json={'expiresOn': expires_on, 'name': name},
            response=models.KeyFullOut,
        )

    def delete(
        self, key_uuid: UUID, *, include_groups: bool | NotGiven = NOT_GIVEN
    ) -> models.KeyFullOut:
        """Delete a credential: it stops authenticating at once."""
        return self._client._request(
            'DELETE',
            '/public/api/v1/keys/{key_uuid}',
            path_params={'key_uuid': key_uuid},
            query={'include_groups': include_groups},
            response=models.KeyFullOut,
        )

    def end_grace_period(self, key_uuid: UUID) -> models.KeyFullOut:
        """End a rotation's grace period: the previous value stops authenticating."""
        return self._client._request(
            'DELETE',
            '/public/api/v1/keys/{key_uuid}/rotation',
            path_params={'key_uuid': key_uuid},
            response=models.KeyFullOut,
        )

    def get(
        self,
        key_uuid: UUID,
        *,
        include_groups: bool | NotGiven = NOT_GIVEN,
        include_limits: bool | NotGiven = NOT_GIVEN,
    ) -> models.KeyFullOut:
        """Get a credential."""
        return self._client._request(
            'GET',
            '/public/api/v1/keys/{key_uuid}',
            path_params={'key_uuid': key_uuid},
            query={'include_groups': include_groups, 'include_limits': include_limits},
            response=models.KeyFullOut,
        )

    def list(
        self,
        *,
        include_groups: bool | NotGiven = NOT_GIVEN,
        only_unassigned: bool | NotGiven = NOT_GIVEN,
        include_limits: bool | NotGiven = NOT_GIVEN,
    ) -> builtins.list[models.KeyFullOut]:
        """List the credentials."""
        return self._client._request(
            'GET',
            '/public/api/v1/keys',
            query={
                'include_groups': include_groups,
                'only_unassigned': only_unassigned,
                'include_limits': include_limits,
            },
            response=builtins.list[models.KeyFullOut],
        )

    def rotate(self, key_uuid: UUID, *, grace_period: str | None) -> models.KeyFullOut:
        """Give a credential a new value. The previous value keeps
        authenticating for the grace period; null ends it at once.
        """
        return self._client._request(
            'POST',
            '/public/api/v1/keys/{key_uuid}/rotation',
            path_params={'key_uuid': key_uuid},
            json={'gracePeriod': grace_period},
            response=models.KeyFullOut,
        )


class ProjectsResource:
    """The ``projects`` operations."""

    def __init__(self, client: Gateway) -> None:
        self._client = client

    def create(
        self, *, name: str, description: str | None | NotGiven = NOT_GIVEN
    ) -> models.ProjectOut:
        """Create a project, with two draft config slots (A and B)."""
        return self._client._request(
            'POST',
            '/public/api/v1/projects',
            json={'description': description, 'name': name},
            response=models.ProjectOut,
        )

    def get(
        self, project_uuid: UUID, *, include_limits: bool | NotGiven = NOT_GIVEN
    ) -> models.ProjectOut:
        """Get a project with its two config slots."""
        return self._client._request(
            'GET',
            '/public/api/v1/projects/{project_uuid}',
            path_params={'project_uuid': project_uuid},
            query={'include_limits': include_limits},
            response=models.ProjectOut,
        )

    def list(
        self,
        *,
        filter: models.ProjectFilter | None | NotGiven = NOT_GIVEN,
        include_limits: bool | NotGiven = NOT_GIVEN,
    ) -> builtins.list[models.ProjectOut]:
        """List the projects, optionally filtered."""
        return self._client._request(
            'GET',
            '/public/api/v1/projects',
            query={'filter': filter, 'include_limits': include_limits},
            response=builtins.list[models.ProjectOut],
        )


class Resources:
    """One attribute per tag of the API, each sending its requests through ``client``."""

    def __init__(self, client: Gateway) -> None:
        self.configs = ConfigsResource(client)
        self.groups = GroupsResource(client)
        self.keys = KeysResource(client)
        self.projects = ProjectsResource(client)
