from collections import defaultdict
from collections.abc import Callable
import logging

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.models.secret_dto import ProjectRef, SecretOut
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.secrets import SecretProvider, get_secret_provider
from radicalbit_ai_gateway.utils.yaml_utils import extract_secret_references

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class SecretService:
    """Reads the secrets backend and derives which projects use each key."""

    def __init__(
        self,
        project_config_dao: ProjectConfigDAO,
        secret_provider_factory: Callable[[], SecretProvider] = get_secret_provider,
    ):
        self._project_config_dao = project_config_dao
        self._secret_provider_factory = secret_provider_factory

    def get_secrets(self) -> list[SecretOut]:
        """Return a row per secret key the backend holds, sorted by key.

        The provider is built on every call, so the result reflects the
        backend at read time rather than a snapshot. Each row's ``used_in``
        is derived the same way, by parsing the configurations currently
        served.
        """
        provider = self._secret_provider_factory()
        used_in = self._usage_by_key()
        return [
            SecretOut(key=key, used_in=used_in.get(key, []))
            for key in sorted(provider.list_secret_keys())
        ]

    def _usage_by_key(self) -> dict[str, list[ProjectRef]]:
        """Map secret key -> projects referencing it in their served config.

        No stored mapping: every served configuration is parsed on read with
        the same extractor the YAML editor uses, so a reference inside
        ``mcp_servers[].headers`` or ``mcp_servers[].env`` counts exactly like
        one anywhere else. A config that fails to parse is logged and skipped
        rather than raised, mirroring the startup route registrar
        (``server.py``'s ``_safe_register``): one bad row must never take the
        whole Secrets page down.
        """
        references: list[tuple[str, ProjectRef]] = []
        for served in self._project_config_dao.list_served_with_project_name():
            if not served.config_file:
                logger.warning(
                    'Served config for project %s has no content — skipping '
                    'it for secret usage',
                    served.project_uuid,
                )
                continue
            project = ProjectRef(uuid=served.project_uuid, name=served.project_name)
            try:
                keys = {
                    key for key, _line in extract_secret_references(served.config_file)
                }
            except Exception:
                logger.exception(
                    'Could not parse the served config for project %s while '
                    'deriving secret usage — skipping it',
                    served.project_uuid,
                )
                continue
            references.extend((key, project) for key in keys)

        used_in: dict[str, list[ProjectRef]] = defaultdict(list)
        for key, project in sorted(
            references, key=lambda pair: pair[1].name.casefold()
        ):
            used_in[key].append(project)
        return dict(used_in)
