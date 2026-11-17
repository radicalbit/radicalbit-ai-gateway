import datetime
from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy import update

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration
from tests.common.fake_secret_provider import FakeSecretProvider

from radicalbit_ai_gateway.db.dao.project_config_dao import (
    ProjectConfigDAO,
    ServedConfigWithProject,
)
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.secret_dto import ProjectRef, SecretOut, SecretStatus
from radicalbit_ai_gateway.services.secret_service import SecretService
from radicalbit_ai_gateway.utils.exceptions import SecretsBackendError

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)

_MCP_CONFIG_WITH_SECRET = (
    'chat_models:\n'
    '  - model_id: m1\n'
    '    model: openai/gpt-4o-mini\n'
    'routes:\n'
    '  default-route:\n'
    '    chat_models: [m1]\n'
    '    mcp_servers: [github]\n'
    'mcp_servers:\n'
    '  - alias: github\n'
    '    transport: streamable_http\n'
    '    url: https://api.example.com/mcp/\n'
    '    headers:\n'
    '      Authorization: !secret GITHUB_TOKEN\n'
)

# The project is named after a key, so searching a key cannot match it.
PROJECT = ProjectRef(uuid=uuid.uuid4(), name='openai-project')


def _config_referencing(*keys: str) -> str:
    models = ''.join(
        f'  - model_id: m{i}\n    api_key: !secret {key}\n'
        for i, key in enumerate(keys)
    )
    return f'chat_models:\n{models}'


def _service(secret_provider_factory, *referenced_keys: str) -> SecretService:
    """Build a service on a DAO serving one config of PROJECT that references the keys."""
    dao = MagicMock(spec_set=ProjectConfigDAO)
    dao.list_served_with_project_name.return_value = (
        [
            ServedConfigWithProject(
                _config_referencing(*referenced_keys), PROJECT.uuid, PROJECT.name
            )
        ]
        if referenced_keys
        else []
    )
    return SecretService(
        project_config_dao=dao, secret_provider_factory=secret_provider_factory
    )


def _available(key: str, *used_in: ProjectRef) -> SecretOut:
    return SecretOut(key=key, used_in=list(used_in), status=None)


def _unavailable(key: str) -> SecretOut:
    return SecretOut(key=key, used_in=[PROJECT], status=SecretStatus.UNAVAILABLE)


@pytest.mark.parametrize(
    ('secrets', 'referenced', 'search', 'expected'),
    [
        pytest.param({}, (), None, [], id='empty backend'),
        pytest.param(
            {'OPENAI_API_KEY': 'sk-dummy-key'},
            (),
            None,
            [_available('OPENAI_API_KEY')],
            id='a row per backend key',
        ),
        pytest.param(
            {'ZETA': 'z', 'ALPHA': 'a', 'MIKE': 'm'},
            (),
            None,
            [_available('ALPHA'), _available('MIKE'), _available('ZETA')],
            id='sorted by key',
        ),
        pytest.param(
            {},
            ('DEAD_TOKEN',),
            None,
            [_unavailable('DEAD_TOKEN')],
            id='referenced but absent from the backend',
        ),
        pytest.param(
            {'OPENAI_API_KEY': 'sk-dummy'},
            ('OPENAI_API_KEY',),
            None,
            [_available('OPENAI_API_KEY', PROJECT)],
            id='in the backend and referenced',
        ),
        pytest.param(
            {'ALPHA': 'a', 'MIKE': 'm'},
            ('ZULU_DEAD', 'BRAVO_DEAD', 'MIKE'),
            None,
            [
                _unavailable('BRAVO_DEAD'),
                _unavailable('ZULU_DEAD'),
                _available('ALPHA'),
                _available('MIKE', PROJECT),
            ],
            id='unavailable first then by key',
        ),
        pytest.param(
            {'OPENAI_API_KEY': 'o', 'ANTHROPIC_API_KEY': 'a', 'GITHUB_TOKEN': 'g'},
            (),
            'API',
            [_available('ANTHROPIC_API_KEY'), _available('OPENAI_API_KEY')],
            id='search keeps keys containing the term',
        ),
        pytest.param(
            {'OPENAI_API_KEY': 'o', 'GITHUB_TOKEN': 'g'},
            (),
            'openai',
            [_available('OPENAI_API_KEY')],
            id='search ignores case',
        ),
        pytest.param(
            {'ANTHROPIC_API_KEY': 'a'},
            ('ANTHROPIC_API_KEY',),
            'openai',
            [],
            id='search matches the key not the projects using it',
        ),
        pytest.param(
            {'OPENAI_API_KEY': 'o', 'GITHUB_TOKEN': 'g'},
            ('OPENAI_ORG_KEY',),
            'OPENAI',
            [_unavailable('OPENAI_ORG_KEY'), _available('OPENAI_API_KEY')],
            id='search covers unavailable keys and keeps them first',
        ),
        pytest.param(
            {'OPENAI_API_KEY': 'o', 'GITHUB_TOKEN': 'g'},
            (),
            '',
            [_available('GITHUB_TOKEN'), _available('OPENAI_API_KEY')],
            id='empty search filters nothing',
        ),
    ],
)
def test_get_secrets(secrets, referenced, search, expected):
    service = _service(lambda: FakeSecretProvider(secrets), *referenced)

    assert service.get_secrets(search=search) == expected


def test_get_secrets_reads_the_backend_on_every_call():
    # The page must never show a stale snapshot, so the provider is built per
    # call: a key added between calls shows up, and a referenced key that is
    # back in the backend is no longer unavailable.
    secrets = {'ALPHA': 'a'}
    service = _service(lambda: FakeSecretProvider(dict(secrets)), 'DEAD_TOKEN')
    assert service.get_secrets() == [_unavailable('DEAD_TOKEN'), _available('ALPHA')]

    secrets |= {'BRAVO': 'b', 'DEAD_TOKEN': 'restored'}

    assert service.get_secrets() == [
        _available('ALPHA'),
        _available('BRAVO'),
        _available('DEAD_TOKEN', PROJECT),
    ]


class _UnreachableSecretProvider(FakeSecretProvider):
    """A secrets backend whose listing fails, as an unreachable one does."""

    def __init__(self):
        super().__init__({})

    def list_secret_keys(self) -> list[str]:
        raise SecretsBackendError('connection refused')


def _failing_factory():
    raise SecretsBackendError('authentication failed')


@pytest.mark.parametrize(
    ('factory', 'message'),
    [
        (_UnreachableSecretProvider, 'connection refused'),
        (_failing_factory, 'authentication failed'),
    ],
)
def test_backend_failure_propagates(factory, message):
    # Not an empty list, and not every referenced key reported unavailable.
    service = _service(factory, 'OPENAI_API_KEY')

    with pytest.raises(SecretsBackendError, match=message):
        service.get_secrets()


_OPENAI_CONFIG = 'chat_models:\n  - model_id: m\n    api_key: !secret OPENAI_API_KEY\n'


class SecretServiceUsedInTest(DatabaseIntegration):
    """Derived per-key project usage — needs real served configs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dao = ProjectConfigDAO(cls.db)

    def _secrets(self, secrets: dict[str, str]) -> list[SecretOut]:
        return SecretService(
            project_config_dao=self.dao,
            secret_provider_factory=lambda: FakeSecretProvider(secrets),
        ).get_secrets()

    def _project(self, name: str):
        return self.insert(db_mock.get_sample_project(uuid=uuid.uuid4(), name=name))

    def _config(self, project, config_file: str, status=ConfigStatus.SERVED):
        return self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, config_file=config_file, config_status=status
            )
        )

    def test_published_configurations_make_a_key_used(self):
        zebra = self._project('Zebra')
        apple = self._project('apple')
        mcp = self._project('project-mcp')
        # A served row that fails to parse must never take the whole endpoint
        # down for every other key and project.
        broken = self._project('broken-project')
        self._config(zebra, _OPENAI_CONFIG)
        self._config(
            apple,
            'chat_models:\n  - model_id: m2\n    api_key: !secret OPENAI_API_KEY\n',
        )
        self._config(mcp, _MCP_CONFIG_WITH_SECRET)
        self._config(broken, 'chat_models: [\n  unterminated')

        secrets = self._secrets({'OPENAI_API_KEY': 'sk', 'GITHUB_TOKEN': 'ghp'})

        assert secrets == [
            _available('GITHUB_TOKEN', ProjectRef(uuid=mcp.uuid, name='project-mcp')),
            _available(
                'OPENAI_API_KEY',
                # Sorted case-insensitively
                ProjectRef(uuid=apple.uuid, name='apple'),
                ProjectRef(uuid=zebra.uuid, name='Zebra'),
            ),
        ]

    def test_drafts_and_deleted_configurations_use_no_key(self):
        draft = self._project('draft-project')
        # A key absent from the backend and referenced only by a draft is not a row
        self._config(
            draft,
            _config_referencing('OPENAI_API_KEY', 'DRAFT_ONLY_KEY'),
            status=ConfigStatus.DRAFT,
        )
        deleted_project = self._project('deleted-project')
        self._config(deleted_project, _OPENAI_CONFIG)
        with self.db.begin_session() as session:
            session.execute(
                update(Project)
                .where(Project.uuid == deleted_project.uuid)
                .values(deleted_at=datetime.datetime.now(tz=_UTC))
            )
        deleted_config = self._project('deleted-config')
        self._config(deleted_config, _OPENAI_CONFIG)
        self.dao.soft_delete_by_project(deleted_config.uuid)

        assert self._secrets({'OPENAI_API_KEY': 'sk'}) == [_available('OPENAI_API_KEY')]
