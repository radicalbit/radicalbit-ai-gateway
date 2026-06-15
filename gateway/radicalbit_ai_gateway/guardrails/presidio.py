import logging

from azure.health.deidentification import DeidentificationClient
from azure.identity import ClientSecretCredential, EnvironmentCredential
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import AzureHealthDeidRecognizer
from presidio_anonymizer import AnonymizerEngine

from radicalbit_ai_gateway.models.guardrails import AhdsParams
from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


class PresidioEngine:
    def __init__(self, languages: list[str] = ['en', 'it']):
        self._analyzer_local = None
        self._anonymizer = None
        self._nlp_engine = None
        self._languages = languages
        self._lang_model_mapping = {'it': 'it_core_news_md', 'en': 'en_core_web_lg'}

    def _get_nlp_engine(self):
        if not self._nlp_engine:
            nlp_config = {
                'nlp_engine_name': 'spacy',
                'models': [
                    {
                        'lang_code': language,
                        'model_name': self._lang_model_mapping.get(language),
                    }
                    for language in self._languages
                ],
            }
            provider = NlpEngineProvider(nlp_configuration=nlp_config)
            self._nlp_engine = provider.create_engine()
        return self._nlp_engine

    @property
    def analyzer(self):
        if not self._analyzer_local:
            logger.info('Presidio Analyzer initialization...')
            self._analyzer_local = AnalyzerEngine(
                supported_languages=self._languages,
                nlp_engine=self._get_nlp_engine(),
            )
        return self._analyzer_local

    @staticmethod
    def _build_ahds_credential(tenant_id, client_id, client_secret):
        if tenant_id and client_id and client_secret:
            logger.info(
                'AHDS auth: ClientSecretCredential (tenant=%s, client=%s)',
                tenant_id,
                client_id,
            )
            return ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )

        logger.info('AHDS auth: EnvironmentCredential (AZURE_* env vars)')
        return EnvironmentCredential()

    @staticmethod
    def _build_ahds_client(
        endpoint, api_version, tenant_id=None, client_id=None, client_secret=None
    ):
        credential = PresidioEngine._build_ahds_credential(
            tenant_id, client_id, client_secret
        )
        return DeidentificationClient(endpoint, credential, api_version=api_version)

    def _resolve_ahds_settings(self, ahds: AhdsParams | None):
        """Resolve AHDS connection settings from the per-guardrail AhdsParams."""
        endpoint = ahds.endpoint if ahds else None
        if not endpoint:
            raise ValueError(
                'AHDS endpoint must be set when backend="ahds" is used '
                '(guardrail parameters.ahds.endpoint)'
            )
        api_version = ahds.api_version if ahds else None
        tenant_id = ahds.tenant_id if ahds else None
        client_id = ahds.client_id if ahds else None
        client_secret = (
            ahds.client_secret.get_secret_value()
            if ahds and ahds.client_secret
            else None
        )
        return endpoint, api_version, tenant_id, client_id, client_secret

    def _get_ahds_analyzer(self, ahds: AhdsParams | None = None):
        endpoint, api_version, tenant_id, client_id, client_secret = (
            self._resolve_ahds_settings(ahds)
        )

        logger.info(
            'Presidio Analyzer (AHDS) initialization... endpoint=%s api_version=%s',
            endpoint,
            api_version,
        )
        client = self._build_ahds_client(
            endpoint, api_version, tenant_id, client_id, client_secret
        )
        recognizer = AzureHealthDeidRecognizer(client=client)
        entities = recognizer.get_supported_entities()
        if not entities or not isinstance(entities, list):
            raise ValueError(
                f'AzureHealthDeidRecognizer reported no supported entities '
                f'(got {type(entities).__name__}). '
                f'Check azure-health-deidentification installation.'
            )
        logger.info(
            'AHDS recognizer supports %d entities: %s',
            len(entities),
            entities[:5],
        )

        analyzer = AnalyzerEngine(
            supported_languages=self._languages,
            nlp_engine=self._get_nlp_engine(),
        )
        analyzer.registry.add_recognizer(recognizer)
        logger.info('AHDS recognizer registered on AnalyzerEngine')
        return analyzer

    @property
    def anonymizer(self):
        if not self._anonymizer:
            logger.info('Presidio Anonymizer initialization...')
            self._anonymizer = AnonymizerEngine()
        return self._anonymizer

    def get_analyzer(self, backend: str = 'local', ahds: AhdsParams | None = None):
        if backend == 'ahds':
            return self._get_ahds_analyzer(ahds)
        return self.analyzer
