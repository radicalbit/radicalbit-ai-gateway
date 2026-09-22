import datetime
import unittest
import uuid

from sqlalchemy import update

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.secret_dto import ProjectRef, SecretOut
from radicalbit_ai_gateway.services.secret_service import SecretService
from radicalbit_ai_gateway.utils.exceptions import SecretNotFoundError
from radicalbit_ai_gateway.utils.secrets import SecretProvider

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


class FakeSecretProvider(SecretProvider):
    """A secrets backend holding the given key/value mapping."""

    def __init__(self, secrets: dict[str, str]):
        self._secrets = secrets

    def get_secret(self, key: str) -> str:
        value = self._secrets.get(key)
        if value is None:
            raise SecretNotFoundError(key, 'fake')
        return value

    def list_secret_keys(self) -> list[str]:
        return list(self._secrets.keys())


class _NoUsageProjectConfigDAO:
    """A stand-in that reports no served-configuration usage.

    Lets the backend-key behaviour of SecretService be tested without a
    database: nothing here touches project_config or project tables.
    """

    def list_served_with_project_name(self):
        return []


class SecretServiceBackendKeysTest(unittest.TestCase):
    """Backend key listing only — no served-configuration usage involved."""

    def _service(self, secrets: dict[str, str]) -> SecretService:
        return SecretService(
            project_config_dao=_NoUsageProjectConfigDAO(),
            secret_provider_factory=lambda: FakeSecretProvider(secrets),
        )

    def test_get_secrets_returns_a_row_per_backend_key(self):
        service = self._service({'OPENAI_API_KEY': 'sk-dummy-key'})
        assert service.get_secrets() == [SecretOut(key='OPENAI_API_KEY')]

    def test_get_secrets_returns_no_values(self):
        service = self._service({'OPENAI_API_KEY': 'sk-dummy-key'})
        rows = service.get_secrets()
        assert 'sk-dummy-key' not in str(rows[0].model_dump())

    def test_get_secrets_empty_backend(self):
        assert self._service({}).get_secrets() == []

    def test_get_secrets_sorts_by_key(self):
        service = self._service({'ZETA': 'z', 'ALPHA': 'a', 'MIKE': 'm'})
        assert [row.key for row in service.get_secrets()] == ['ALPHA', 'MIKE', 'ZETA']

    def test_get_secrets_reads_the_backend_on_every_call(self):
        # The page must never show a stale snapshot, so the provider is built
        # per call. A backend that gained a key between calls shows it on the
        # second.
        secrets = {'ALPHA': 'a'}
        service = SecretService(
            project_config_dao=_NoUsageProjectConfigDAO(),
            secret_provider_factory=lambda: FakeSecretProvider(dict(secrets)),
        )
        assert [row.key for row in service.get_secrets()] == ['ALPHA']
        secrets['BRAVO'] = 'b'
        assert [row.key for row in service.get_secrets()] == ['ALPHA', 'BRAVO']


class SecretServiceUsedInTest(DatabaseIntegration):
    """Derived per-key project usage (AG-971) — needs real served configs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dao = ProjectConfigDAO(cls.db)

    def _service(self, secrets: dict[str, str]) -> SecretService:
        return SecretService(
            project_config_dao=self.dao,
            secret_provider_factory=lambda: FakeSecretProvider(secrets),
        )

    def _project(self, name: str = 'my-project'):
        return self.insert(db_mock.get_sample_project(uuid=uuid.uuid4(), name=name))

    def _served_config(self, project_uuid, config_file: str):
        return self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project_uuid,
                config_file=config_file,
                config_status=ConfigStatus.SERVED,
            )
        )

    def _row(self, service: SecretService, key: str) -> SecretOut:
        return next(r for r in service.get_secrets() if r.key == key)

    def test_key_used_by_a_published_configuration(self):
        project = self._project(name='project-a')
        self._served_config(
            project.uuid,
            'chat_models:\n  - model_id: m\n    api_key: !secret OPENAI_API_KEY\n',
        )

        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert self._row(service, 'OPENAI_API_KEY').used_in == [
            ProjectRef(uuid=project.uuid, name='project-a')
        ]

    def test_key_used_by_nobody(self):
        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})
        assert self._row(service, 'OPENAI_API_KEY').used_in == []

    def test_key_referenced_only_by_a_draft_reads_as_unused(self):
        project = self._project()
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid,
                config_file='chat_models:\n'
                '  - model_id: m\n'
                '    api_key: !secret OPENAI_API_KEY\n',
                config_status=ConfigStatus.DRAFT,
            )
        )

        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert self._row(service, 'OPENAI_API_KEY').used_in == []

    def test_reference_inside_mcp_server_block_counts(self):
        project = self._project(name='project-mcp')
        self._served_config(project.uuid, _MCP_CONFIG_WITH_SECRET)

        service = self._service({'GITHUB_TOKEN': 'ghp-dummy'})

        assert self._row(service, 'GITHUB_TOKEN').used_in == [
            ProjectRef(uuid=project.uuid, name='project-mcp')
        ]

    def test_soft_deleted_project_contributes_nothing(self):
        project = self._project()
        self._served_config(
            project.uuid,
            'chat_models:\n  - model_id: m\n    api_key: !secret OPENAI_API_KEY\n',
        )
        with self.db.begin_session() as session:
            session.execute(
                update(Project)
                .where(Project.uuid == project.uuid)
                .values(deleted_at=datetime.datetime.now(tz=_UTC))
            )

        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert self._row(service, 'OPENAI_API_KEY').used_in == []

    def test_soft_deleted_config_contributes_nothing(self):
        project = self._project()
        self._served_config(
            project.uuid,
            'chat_models:\n  - model_id: m\n    api_key: !secret OPENAI_API_KEY\n',
        )
        self.dao.soft_delete_by_project(project.uuid)

        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert self._row(service, 'OPENAI_API_KEY').used_in == []

    def test_used_in_is_sorted_case_insensitively(self):
        zebra = self._project(name='Zebra')
        apple = self._project(name='apple')
        self._served_config(
            zebra.uuid,
            'chat_models:\n  - model_id: m\n    api_key: !secret OPENAI_API_KEY\n',
        )
        self._served_config(
            apple.uuid,
            'chat_models:\n  - model_id: m2\n    api_key: !secret OPENAI_API_KEY\n',
        )

        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert [p.name for p in self._row(service, 'OPENAI_API_KEY').used_in] == [
            'apple',
            'Zebra',
        ]

    def test_unparsable_served_config_is_skipped_not_raised(self):
        # A served row that fails to parse must never take the whole
        # endpoint down for every other key and project.
        broken = self._project(name='broken-project')
        self._served_config(broken.uuid, 'chat_models: [\n  unterminated')
        healthy = self._project(name='healthy-project')
        self._served_config(
            healthy.uuid,
            'chat_models:\n  - model_id: m\n    api_key: !secret OPENAI_API_KEY\n',
        )

        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert self._row(service, 'OPENAI_API_KEY').used_in == [
            ProjectRef(uuid=healthy.uuid, name='healthy-project')
        ]
