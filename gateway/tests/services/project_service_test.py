import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, call, patch
import uuid
import zipfile

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.limiting.limits import shared_limits
from radicalbit_ai_gateway.limiting.windows import project_window
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import (
    ProjectBudgetLimitIn,
    ProjectBudgetLimitsIn,
    ProjectBudgetLimitValueIn,
)
from radicalbit_ai_gateway.models.project_dto import (
    ConfigListFilter,
    ProjectConfigFileIn,
    ProjectFilter,
    ProjectIn,
)
from radicalbit_ai_gateway.models.project_status import ProjectStatus
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectAlreadyExistsError,
    ProjectBudgetLimitAlreadyExistsError,
    ProjectBudgetLimitConflictError,
    ProjectBudgetLimitNotFoundError,
    ProjectConfigValidationError,
    ProjectNotFoundError,
)

_VALID = db_mock.VALID_CONFIG_YAML

_VALID_WITH_ROUTE_BUDGET_LIMITING = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
    params:
      latency_ms: 150
      response_text: "mock response"
routes:
  test-route:
    chat_models:
      - mock-chat
    budget_limiting:
      window_size: "1 day"
      max_budget: 5.0
"""

_ROUTE_BUDGET = ProjectConfigFileIn(config_file=_VALID_WITH_ROUTE_BUDGET_LIMITING)


class ProjectServiceTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = ProjectService(
            ProjectDAO(cls.db),
            ProjectConfigDAO(cls.db),
            ProjectBudgetLimitDAO(cls.db),
        )

    def _create(self, name='proj'):
        out = self.svc.create_project(ProjectIn(name=name))
        return out, out.configs[0].uuid, out.configs[1].uuid

    def _approve(self, project_uuid, config_uuid, config=None):
        self.svc.update_config(
            project_uuid, config_uuid, config or ProjectConfigFileIn(config_file=_VALID)
        )
        return self.svc.approve_config(project_uuid, config_uuid)

    def _serve(self, project_uuid, config_uuid, config=None):
        self._approve(project_uuid, config_uuid, config)
        return self.svc.serve_config(project_uuid, config_uuid)

    def _add_limit(self, project_uuid):
        return self.svc.add_budget_limits_to_project(
            project_uuid, db_mock.get_sample_project_budget_limits_in()
        )

    @staticmethod
    def _slot(res, config_uuid):
        return next(c for c in res.configs if c.uuid == config_uuid)

    # --- create / update ---

    def test_create_project_seeds_two_empty_draft_slots(self):
        out, _, _ = self._create()

        assert [c.slot for c in out.configs] == ['A', 'B']
        assert all(c.config_status == ConfigStatus.DRAFT for c in out.configs)
        assert all(c.created_at is not None for c in out.configs)
        assert all(c.updated_at is None for c in out.configs)
        assert out.project_status == ProjectStatus.DEV
        assert out.served_config_uuid is None

    def test_create_project_already_exists(self):
        # IntegrityError -> ProjectAlreadyExistsError mapping is a unit concern,
        # tested with a mocked DAO to stay independent of create_all metadata.
        svc = ProjectService(MagicMock(), MagicMock(), MagicMock())
        svc.project_dao.insert_with_configs = MagicMock(
            side_effect=IntegrityError(None, None, BaseException('uq_project_NAME'))
        )
        with pytest.raises(ProjectAlreadyExistsError):
            svc.create_project(ProjectIn(name='dup'))

    def test_update_config_ok(self):
        out, a, _ = self._create()

        res = self.svc.update_config(
            out.uuid, a, ProjectConfigFileIn(config_file=_VALID)
        )

        ca = self._slot(res, a)
        assert ca.config_file == _VALID
        assert ca.config_status == ConfigStatus.DRAFT
        assert ca.updated_at is not None

    def test_invalid_operations_raise(self):
        out, a, b = self._create()
        self._serve(out.uuid, a)
        missing = uuid.uuid4()
        valid = ProjectConfigFileIn(config_file=_VALID)
        svc = self.svc
        cases = [
            (
                'update invalid yaml',
                lambda: svc.update_config(
                    out.uuid, b, ProjectConfigFileIn(config_file='::not yaml::')
                ),
                ProjectConfigValidationError,
            ),
            (
                'update served is read-only',
                lambda: svc.update_config(out.uuid, a, valid),
                ProjectConfigValidationError,
            ),
            (
                'update wrong project',
                lambda: svc.update_config(missing, b, valid),
                ProjectNotFoundError,
            ),
            (
                'cancel when not ready',
                lambda: svc.cancel_approval(out.uuid, b),
                ProjectConfigValidationError,
            ),
            (
                'serve requires approval',
                lambda: svc.serve_config(out.uuid, b),
                ProjectConfigValidationError,
            ),
            (
                'unserve when not served',
                lambda: svc.unserve_config(out.uuid, b),
                ProjectConfigValidationError,
            ),
            (
                'get config wrong project',
                lambda: svc.get_config(missing, a),
                ProjectNotFoundError,
            ),
            (
                'export all not found',
                lambda: svc.export_all_configs(missing),
                ProjectNotFoundError,
            ),
            (
                'export not found',
                lambda: svc.export_config(missing, uuid.uuid4()),
                ProjectNotFoundError,
            ),
            (
                'import into served',
                lambda: svc.import_config(out.uuid, a, _VALID.encode()),
                ProjectConfigValidationError,
            ),
            (
                'import invalid yaml',
                lambda: svc.import_config(out.uuid, b, b'::not yaml::'),
                ProjectConfigValidationError,
            ),
            (
                'import non utf8',
                lambda: svc.import_config(out.uuid, b, b'\xff\xfe'),
                ProjectConfigValidationError,
            ),
            (
                'import not found',
                lambda: svc.import_config(missing, uuid.uuid4(), _VALID.encode()),
                ProjectNotFoundError,
            ),
            (
                'add budget limits not found',
                lambda: self._add_limit(missing),
                ProjectNotFoundError,
            ),
            (
                'get budget limits not found',
                lambda: svc.get_budget_limits_for_project(missing),
                ProjectNotFoundError,
            ),
            (
                'budget limit conflicts not found',
                lambda: svc.get_budget_limit_conflicts(missing),
                ProjectNotFoundError,
            ),
            (
                'update budget limit value project not found',
                lambda: svc.update_budget_limit_value(
                    missing, uuid.uuid4(), ProjectBudgetLimitValueIn(value=1)
                ),
                ProjectNotFoundError,
            ),
            (
                'delete budget limit project not found',
                lambda: asyncio.run(
                    svc.delete_budget_limit_from_project(missing, uuid.uuid4())
                ),
                ProjectNotFoundError,
            ),
        ]
        for case, operation, error in cases:
            with self.subTest(case), pytest.raises(error):
                operation()

    # --- lifecycle ---

    def test_approve_then_cancel(self):
        out, a, _ = self._create()

        res = self._approve(out.uuid, a)
        assert self._slot(res, a).config_status == ConfigStatus.READY_TO_SERVE

        res = self.svc.cancel_approval(out.uuid, a)
        assert self._slot(res, a).config_status == ConfigStatus.DRAFT

    def test_serve_swap_and_unserve(self):
        out, a, b = self._create()
        self._approve(out.uuid, b)

        res = self._serve(out.uuid, a)
        assert res.project_status == ProjectStatus.PROD
        assert res.served_config_uuid == a
        assert self._slot(res, a).config_status == ConfigStatus.SERVED

        # Serving the other slot swaps the displaced one back to draft
        res = self.svc.serve_config(out.uuid, b)
        st = {c.uuid: c.config_status for c in res.configs}
        assert st == {a: ConfigStatus.DRAFT, b: ConfigStatus.SERVED}
        assert res.served_config_uuid == b

        res = self.svc.unserve_config(out.uuid, b)
        assert res.project_status == ProjectStatus.DEV
        assert res.served_config_uuid is None

    def test_delete_project(self):
        out, _, _ = self._create(name='reuse-me')
        self._add_limit(out.uuid)
        with pytest.raises(ProjectAlreadyExistsError):
            self.svc.create_project(ProjectIn(name='reuse-me'))

        deleted = asyncio.run(self.svc.delete_project(out.uuid))

        assert deleted.uuid == out.uuid
        with pytest.raises(ProjectNotFoundError):
            self.svc.get_by_uuid(out.uuid)
        assert self.svc.project_budget_limit_dao.get_by_project_uuid(out.uuid) == []
        # The name of a deleted project can be reused
        again = self.svc.create_project(ProjectIn(name='reuse-me'))
        assert again.uuid != out.uuid
        assert again.name == 'reuse-me'

    def test_get_config(self):
        out, a, _ = self._create()
        slot = self.svc.get_config(out.uuid, a)
        assert slot.uuid == a and slot.slot == 'A'

    # --- export / import ---

    def test_export_config_names_the_file_by_status(self):
        out, a, _ = self._create()

        content, filename = self.svc.export_config(out.uuid, a)
        assert filename == 'proj_config.zip'
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == ['proj_config_A_draft.yaml']
            assert archive.read('proj_config_A_draft.yaml').decode() == (
                out.configs[0].config_file
            )

        self._serve(out.uuid, a)

        content, filename = self.svc.export_config(out.uuid, a)
        assert filename == 'proj_config.zip'
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == ['proj_config_A_served.yaml']

    def test_export_all_configs_returns_zip_with_both_slots(self):
        out, _, _ = self._create()
        content, filename = self.svc.export_all_configs(out.uuid)
        assert filename == 'proj_config.zip'
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == [
                'proj_config_A_draft.yaml',
                'proj_config_B_draft.yaml',
            ]

    def test_export_all_configs_skips_empty_slots(self):
        project = self.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='partial')
        )
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.A, config_file=_VALID
            )
        )
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.B, config_file=None
            )
        )
        content, _ = self.svc.export_all_configs(project.uuid)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == ['partial_config_A_draft.yaml']

    def test_export_of_empty_configs_raises(self):
        project = self.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='all-empty')
        )
        config = self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.A, config_file=None
            )
        )
        with pytest.raises(ProjectConfigValidationError):
            self.svc.export_all_configs(project.uuid)
        with pytest.raises(ProjectConfigValidationError):
            self.svc.export_config(project.uuid, config.uuid)

    def test_import_config_writes_draft(self):
        out, a, _ = self._create()
        res = self.svc.import_config(out.uuid, a, _VALID.encode())
        ca = self._slot(res, a)
        assert ca.config_file == _VALID
        assert ca.config_status == ConfigStatus.DRAFT
        assert ca.updated_at is not None

    # --- listing / filters ---

    def test_get_all_and_filters(self):
        served, a, _ = self._create(name='served')
        self._serve(served.uuid, a)
        self._create(name='dev')

        assert len(self.svc.get_all()) == 2
        prod = self.svc.get_all_filtered(ProjectFilter.PROD)
        assert [p.uuid for p in prod] == [served.uuid]
        dev = self.svc.get_all_filtered(ProjectFilter.DEV)
        assert served.uuid not in [p.uuid for p in dev]
        active = self.svc.get_all_active()
        assert [p.uuid for p in active] == [served.uuid]

    def test_get_configs_filters_by_status(self):
        # served-only: slot A served, slot B left as the untouched seed.
        served, a, _ = self._create(name='served')
        self._serve(served.uuid, a)

        # draft-only: slot A saved (still DRAFT), never approved/served.
        draft_proj, da, _ = self._create(name='draft')
        self.svc.update_config(
            draft_proj.uuid, da, ProjectConfigFileIn(config_file=_VALID)
        )

        # untouched: both slots are EMPTY (seeded DRAFT with a NULL updated_at).
        self._create(name='untouched')

        assert len(self.svc.get_configs(None)) == 3
        assert len(self.svc.get_configs(ConfigListFilter.ALL)) == 3

        published = self.svc.get_configs(ConfigListFilter.PUBLISHED)
        assert [p.uuid for p in published] == [served.uuid]

        # "Draft" only matches the genuine draft, not the EMPTY seeded ones.
        draft = self.svc.get_configs(ConfigListFilter.DRAFT)
        assert [p.uuid for p in draft] == [draft_proj.uuid]

        assert self.svc.get_configs(ConfigListFilter.REQUEST_TO_PUBLISH) == []

    def test_limits_are_included_only_when_asked(self):
        out, _, _ = self._create(name='with-limits')
        self._add_limit(out.uuid)

        assert self.svc.get_by_uuid(out.uuid).limits is None
        assert [
            limit.window_size
            for limit in self.svc.get_by_uuid(out.uuid, include_limits=True).limits
        ] == ['1 day']
        [found] = [p for p in self.svc.get_all_filtered() if p.uuid == out.uuid]
        assert found.limits is None
        [found] = [
            p
            for p in self.svc.get_all_filtered(include_limits=True)
            if p.uuid == out.uuid
        ]
        assert [limit.window_size for limit in found.limits] == ['1 day']

    # --- project budget limits ---

    def test_add_budget_limits_then_update_a_value(self):
        out, _, _ = self._create(name='budget-ok')
        limits = self.svc.add_budget_limits_to_project(
            out.uuid,
            db_mock.get_sample_project_budget_limits_in(
                limits=[
                    db_mock.get_sample_project_budget_limit_in(window_size='1 day'),
                    db_mock.get_sample_project_budget_limit_in(
                        window_size='1 month', value=15
                    ),
                ]
            ),
        )
        assert {limit.window_size for limit in limits} == {'1 day', '1 month'}
        fetched = self.svc.get_budget_limits_for_project(out.uuid)
        assert {limit.window_size for limit in fetched} == {'1 day', '1 month'}
        limit = next(lim for lim in limits if lim.window_size == '1 day')

        updated = self.svc.update_budget_limit_value(
            out.uuid, limit.uuid, ProjectBudgetLimitValueIn(value=42.5)
        )

        # The row is kept and the previous maximum is returned
        assert updated.uuid == limit.uuid
        assert updated.value == 42.5
        assert updated.previous_value == limit.value
        assert updated.window_size == limit.window_size
        saved = {
            lim.uuid: lim.value
            for lim in self.svc.get_budget_limits_for_project(out.uuid)
        }
        assert saved[limit.uuid] == 42.5

    def test_add_budget_limits_to_project_duplicate_window_raises(self):
        out, _, _ = self._create(name='budget-dup')
        self._add_limit(out.uuid)
        with pytest.raises(ProjectBudgetLimitAlreadyExistsError):
            self._add_limit(out.uuid)

    def test_add_budget_limits_conflict_names_the_published_routes(self):
        out, a, _ = self._create(name='budget-conflict-routes')
        self._serve(out.uuid, a, _ROUTE_BUDGET)
        with pytest.raises(ProjectBudgetLimitConflictError) as exc_info:
            self._add_limit(out.uuid)
        assert exc_info.value.routes == ['test-route']

    def test_budget_limits_with_the_same_window_and_another_algorithm_coexist(self):
        out, _, _ = self._create(name='budget-same-window')
        added = self.svc.add_budget_limits_to_project(
            out.uuid,
            ProjectBudgetLimitsIn(
                limits=[
                    ProjectBudgetLimitIn(window_size='1 day', value=10),
                    ProjectBudgetLimitIn(
                        algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
                        window_size='1 day',
                        value=20,
                    ),
                ]
            ),
        )
        assert len(added) == 2

    def test_budget_limit_conflicts_of_the_published_config(self):
        out, a, _ = self._create(name='budget-conflicts-published-only')
        conflicts = self.svc.get_budget_limit_conflicts(out.uuid)
        assert (conflicts.published, conflicts.draft, conflicts.budget_routing) == (
            [],
            [],
            [],
        )

        self._serve(out.uuid, a, _ROUTE_BUDGET)

        conflicts = self.svc.get_budget_limit_conflicts(out.uuid)
        assert conflicts.published == ['test-route']
        assert conflicts.draft_configs == []
        project = self.svc.get_by_uuid(out.uuid, include_limits=True)
        assert project.route_budgets.published == ['test-route']
        assert project.route_budgets.draft == []
        assert project.route_budgets.draft_configs == []
        assert self.svc.get_by_uuid(out.uuid).route_budgets is None

    def test_budget_limit_conflicts_lists_published_and_draft_routes(self):
        out, a, b = self._create(name='budget-conflicts')
        self._serve(out.uuid, a, _ROUTE_BUDGET)
        self.svc.update_config(out.uuid, b, _ROUTE_BUDGET)
        conflicts = self.svc.get_budget_limit_conflicts(out.uuid)
        assert conflicts.published == ['test-route']
        assert conflicts.draft == ['test-route']
        assert conflicts.budget_routing == []

    def test_budget_limit_conflicts_names_each_draft_slot_with_route_budgets(self):
        out, a, b = self._create(name='budget-conflicts-draft-slots')
        self.svc.update_config(out.uuid, a, _ROUTE_BUDGET)
        self.svc.update_config(
            out.uuid,
            b,
            ProjectConfigFileIn(
                config_file=_VALID_WITH_ROUTE_BUDGET_LIMITING.replace(
                    'test-route', 'other-route'
                )
            ),
        )
        conflicts = self.svc.get_budget_limit_conflicts(out.uuid)
        assert [(c.config_uuid, c.slot, c.routes) for c in conflicts.draft_configs] == [
            (a, 'A', ['test-route']),
            (b, 'B', ['other-route']),
        ]
        assert sorted(conflicts.draft) == ['other-route', 'test-route']

        # A draft without route budgets is skipped
        self.svc.update_config(out.uuid, b, ProjectConfigFileIn(config_file=_VALID))

        conflicts = self.svc.get_budget_limit_conflicts(out.uuid)
        assert [(c.config_uuid, c.slot) for c in conflicts.draft_configs] == [(a, 'A')]

    def test_delete_budget_limit_from_project_ok(self):
        out, _, _ = self._create(name='budget-delete-ok')
        [limit] = self._add_limit(out.uuid)
        deleted = asyncio.run(
            self.svc.delete_budget_limit_from_project(out.uuid, limit.uuid)
        )
        assert deleted.uuid == limit.uuid
        assert self.svc.get_budget_limits_for_project(out.uuid) == []

    def test_a_budget_limit_of_another_project_is_not_found(self):
        owner, _, _ = self._create(name='budget-owner')
        other, _, _ = self._create(name='budget-other')
        [limit] = self._add_limit(owner.uuid)

        for limit_uuid in (limit.uuid, uuid.uuid4()):
            with self.subTest(limit_uuid=limit_uuid):
                with pytest.raises(ProjectBudgetLimitNotFoundError):
                    asyncio.run(
                        self.svc.delete_budget_limit_from_project(
                            other.uuid, limit_uuid
                        )
                    )
                with pytest.raises(ProjectBudgetLimitNotFoundError):
                    self.svc.update_budget_limit_value(
                        other.uuid, limit_uuid, ProjectBudgetLimitValueIn(value=1)
                    )

    # --- reverse validation: route config vs. existing project budget limit ---

    def test_saving_a_route_budget_is_rejected_once_the_project_has_one(self):
        out, a, _ = self._create(name='route-conflict-update')
        self._add_limit(out.uuid)

        with pytest.raises(ProjectConfigValidationError) as exc_info:
            self.svc.update_config(out.uuid, a, _ROUTE_BUDGET)
        assert exc_info.value.routes == ['test-route']
        with pytest.raises(ProjectConfigValidationError):
            self.svc.import_config(
                out.uuid, a, _VALID_WITH_ROUTE_BUDGET_LIMITING.encode()
            )
        # Guards against over-rejection: a project budget limit alone (no route
        # budget_limiting in the submitted config) must not block saving.
        res = self.svc.update_config(
            out.uuid, a, ProjectConfigFileIn(config_file=_VALID)
        )
        assert self._slot(res, a).config_file == _VALID

    def test_publishing_a_route_budget_is_rejected_once_the_project_has_one(self):
        out, a, b = self._create(name='route-conflict-publish')
        self.svc.update_config(out.uuid, a, _ROUTE_BUDGET)
        self._approve(out.uuid, b, _ROUTE_BUDGET)

        # Allowed while only unpublished configs set a route budget
        assert len(self._add_limit(out.uuid)) == 1

        with pytest.raises(ProjectConfigValidationError):
            self.svc.approve_config(out.uuid, a)
        with pytest.raises(ProjectConfigValidationError):
            self.svc.serve_config(out.uuid, b)


class TestBudgetLimitRedisClear:
    """Mock-based tests for the Redis-clear side effects of budget limit
    deletion, mirroring key_service_test.py::TestDeleteLimitFromKey.
    """

    def _make_service(self, limits=()):
        project_uuid = uuid.uuid4()
        project_dao = MagicMock(spec_set=ProjectDAO)
        project_config_dao = MagicMock(spec_set=ProjectConfigDAO)
        project_budget_limit_dao = MagicMock(spec_set=ProjectBudgetLimitDAO)
        project_dao.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_project(uuid=project_uuid)
        )
        project_config_dao.list_by_project = MagicMock(return_value=[])
        project_config_dao.get_served_by_project = MagicMock(return_value=None)
        project_config_dao.soft_delete_by_project = MagicMock(return_value=1)
        project_dao.soft_delete = MagicMock(return_value=1)
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project_uuid, window_size=window
            )
            for window in limits
        ]
        project_budget_limit_dao.get_by_project_uuid = MagicMock(return_value=limits)
        project_budget_limit_dao.delete_by_project_uuid = MagicMock(
            return_value=len(limits)
        )
        project_budget_limit_dao.get_by_uuid = MagicMock(
            return_value=limits[0] if limits else None
        )
        project_budget_limit_dao.delete_by_uuid = MagicMock(return_value=1)
        service = ProjectService(
            project_dao, project_config_dao, project_budget_limit_dao
        )
        return service, project_uuid, limits, project_budget_limit_dao

    @staticmethod
    def _window(project_uuid, limit):
        return project_window(str(project_uuid), limit.algorithm, limit.window_size)

    # A Redis-side error clearing the counter must not undo the delete.
    @pytest.mark.parametrize(
        'clear_error',
        [None, ConnectionError('redis unreachable')],
        ids=['ok', 'redis down'],
    )
    @pytest.mark.asyncio
    async def test_delete_budget_limit_from_project_clears_redis_counter(
        self, clear_error
    ):
        service, project_uuid, [limit], dao = self._make_service(['1 day'])

        with patch.object(
            shared_limits, 'clear', new=AsyncMock(side_effect=clear_error)
        ) as mock_clear:
            res = await service.delete_budget_limit_from_project(
                project_uuid, limit.uuid
            )

        dao.delete_by_uuid.assert_called_once_with(limit.uuid)
        mock_clear.assert_awaited_once_with(self._window(project_uuid, limit))
        assert res.uuid == limit.uuid

    @pytest.mark.parametrize(
        'clear_error',
        [None, ConnectionError('redis unreachable')],
        ids=['ok', 'redis down'],
    )
    @pytest.mark.asyncio
    async def test_delete_project_clears_every_budget_limit_counter(self, clear_error):
        service, project_uuid, limits, dao = self._make_service(['1 day', '1 month'])

        with patch.object(
            shared_limits, 'clear', new=AsyncMock(side_effect=clear_error)
        ) as mock_clear:
            res = await service.delete_project(project_uuid)

        dao.delete_by_project_uuid.assert_called_once_with(project_uuid)
        assert mock_clear.await_args_list == [
            call(self._window(project_uuid, limit)) for limit in limits
        ]
        assert res.uuid == project_uuid

    @pytest.mark.asyncio
    async def test_delete_project_with_no_budget_limits_skips_cleanup(self):
        service, project_uuid, _, dao = self._make_service()

        with patch.object(shared_limits, 'clear', new=AsyncMock()) as mock_clear:
            await service.delete_project(project_uuid)

        dao.delete_by_project_uuid.assert_not_called()
        mock_clear.assert_not_awaited()
