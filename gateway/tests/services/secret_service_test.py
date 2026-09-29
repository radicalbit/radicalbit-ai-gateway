import datetime
import unittest
from unittest.mock import MagicMock
import uuid

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


def _served_configs_dao(served: list[tuple[ProjectRef, str]]) -> ProjectConfigDAO:
    """Return a DAO stand-in serving the given (project, config) pairs as published."""
    dao = MagicMock(spec_set=ProjectConfigDAO)
    dao.list_served_with_project_name.return_value = [
        ServedConfigWithProject(config_file, project.uuid, project.name)
        for project, config_file in served
    ]
    return dao


class SecretServiceBackendKeysTest(unittest.TestCase):
    """Backend key listing only — no served-configuration usage involved."""

    def _service(self, secrets: dict[str, str]) -> SecretService:
        return SecretService(
            project_config_dao=_served_configs_dao([]),
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
            project_config_dao=_served_configs_dao([]),
            secret_provider_factory=lambda: FakeSecretProvider(dict(secrets)),
        )
        assert [row.key for row in service.get_secrets()] == ['ALPHA']
        secrets['BRAVO'] = 'b'
        assert [row.key for row in service.get_secrets()] == ['ALPHA', 'BRAVO']


def _config_referencing(*keys: str) -> str:
    models = ''.join(
        f'  - model_id: m{i}\n    api_key: !secret {key}\n'
        for i, key in enumerate(keys)
    )
    return f'chat_models:\n{models}'


class SecretServiceUnavailableTest(unittest.TestCase):
    """Row set is the union of backend keys and published references."""

    def setUp(self):
        self.project = ProjectRef(uuid=uuid.uuid4(), name='project-a')

    def _service(self, secrets: dict[str, str], *referenced_keys: str) -> SecretService:
        served = (
            [(self.project, _config_referencing(*referenced_keys))]
            if referenced_keys
            else []
        )
        return SecretService(
            project_config_dao=_served_configs_dao(served),
            secret_provider_factory=lambda: FakeSecretProvider(secrets),
        )

    def test_key_referenced_but_absent_from_backend_is_unavailable(self):
        service = self._service({}, 'DEAD_TOKEN')

        assert service.get_secrets() == [
            SecretOut(
                key='DEAD_TOKEN',
                used_in=[self.project],
                status=SecretStatus.UNAVAILABLE,
            )
        ]

    def test_key_in_backend_and_referenced_carries_no_status(self):
        service = self._service({'OPENAI_API_KEY': 'sk-dummy'}, 'OPENAI_API_KEY')

        assert service.get_secrets() == [
            SecretOut(key='OPENAI_API_KEY', used_in=[self.project], status=None)
        ]

    def test_key_in_backend_and_unreferenced_carries_no_status(self):
        service = self._service({'OPENAI_API_KEY': 'sk-dummy'})

        assert service.get_secrets() == [
            SecretOut(key='OPENAI_API_KEY', used_in=[], status=None)
        ]

    def test_unavailable_rows_sort_first_then_by_key(self):
        service = self._service(
            {'ALPHA': 'a', 'MIKE': 'm'}, 'ZULU_DEAD', 'BRAVO_DEAD', 'MIKE'
        )

        assert [(row.key, row.status) for row in service.get_secrets()] == [
            ('BRAVO_DEAD', SecretStatus.UNAVAILABLE),
            ('ZULU_DEAD', SecretStatus.UNAVAILABLE),
            ('ALPHA', None),
            ('MIKE', None),
        ]

    def test_status_clears_once_the_key_is_back_in_the_backend(self):
        secrets: dict[str, str] = {}
        service = SecretService(
            project_config_dao=_served_configs_dao(
                [(self.project, _config_referencing('DEAD_TOKEN'))]
            ),
            secret_provider_factory=lambda: FakeSecretProvider(dict(secrets)),
        )
        assert service.get_secrets()[0].status == SecretStatus.UNAVAILABLE

        secrets['DEAD_TOKEN'] = 'restored'

        assert service.get_secrets() == [
            SecretOut(key='DEAD_TOKEN', used_in=[self.project], status=None)
        ]


class SecretServiceSearchTest(unittest.TestCase):
    """Server-side search on the secret key."""

    def setUp(self):
        self.project = ProjectRef(uuid=uuid.uuid4(), name='openai-project')

    def _service(self, secrets: dict[str, str], *referenced_keys: str) -> SecretService:
        served = (
            [(self.project, _config_referencing(*referenced_keys))]
            if referenced_keys
            else []
        )
        return SecretService(
            project_config_dao=_served_configs_dao(served),
            secret_provider_factory=lambda: FakeSecretProvider(secrets),
        )

    def test_search_keeps_only_keys_containing_the_term(self):
        service = self._service(
            {'OPENAI_API_KEY': 'o', 'ANTHROPIC_API_KEY': 'a', 'GITHUB_TOKEN': 'g'}
        )

        assert [row.key for row in service.get_secrets(search='API')] == [
            'ANTHROPIC_API_KEY',
            'OPENAI_API_KEY',
        ]

    def test_search_ignores_case(self):
        service = self._service({'OPENAI_API_KEY': 'o', 'GITHUB_TOKEN': 'g'})

        assert [row.key for row in service.get_secrets(search='openai')] == [
            'OPENAI_API_KEY'
        ]

    def test_search_matches_the_key_not_the_projects_using_it(self):
        # The project is named 'openai-project'; only the key is searched.
        service = self._service({'ANTHROPIC_API_KEY': 'a'}, 'ANTHROPIC_API_KEY')

        assert service.get_secrets(search='openai') == []

    def test_search_covers_unavailable_keys_and_keeps_them_first(self):
        service = self._service(
            {'OPENAI_API_KEY': 'o', 'GITHUB_TOKEN': 'g'}, 'OPENAI_ORG_KEY'
        )

        assert [(row.key, row.status) for row in service.get_secrets('OPENAI')] == [
            ('OPENAI_ORG_KEY', SecretStatus.UNAVAILABLE),
            ('OPENAI_API_KEY', None),
        ]

    def test_empty_search_filters_nothing(self):
        service = self._service({'OPENAI_API_KEY': 'o', 'GITHUB_TOKEN': 'g'})

        assert service.get_secrets(search='') == service.get_secrets()


class SecretServiceUsedInTest(DatabaseIntegration):
    """Derived per-key project usage — needs real served configs."""

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

    def test_key_absent_from_backend_and_referenced_only_by_a_draft_is_not_a_row(
        self,
    ):
        project = self._project()
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid,
                config_file='chat_models:\n'
                '  - model_id: m\n'
                '    api_key: !secret DRAFT_ONLY_KEY\n',
                config_status=ConfigStatus.DRAFT,
            )
        )

        service = self._service({})

        assert 'DRAFT_ONLY_KEY' not in [row.key for row in service.get_secrets()]

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
