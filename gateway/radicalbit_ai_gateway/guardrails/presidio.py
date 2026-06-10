import logging

from azure.health.deidentification import DeidentificationClient
from azure.identity import ClientSecretCredential, EnvironmentCredential
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import AzureHealthDeidRecognizer
from presidio_anonymizer import AnonymizerEngine

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


class PresidioEngine:
    def __init__(self, languages: list[str] = ['en', 'it']):
        self._analyzer_local = None
        self._analyzer_ahds_cache = {}
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

    def _resolve_ahds_settings(self, ahds):
        cfg = get_app_config().ahds_config
        global_secret = (
            cfg.ahds_client_secret.get_secret_value()
            if cfg.ahds_client_secret
            else None
        )

        def pick(attr, fallback):
            return getattr(ahds, attr, None) or fallback

        endpoint = pick('endpoint', cfg.ahds_endpoint)
        if not endpoint:
            raise ValueError(
                'AHDS endpoint must be set when backend="ahds" is used '
                '(guardrail parameters.ahds.endpoint or the AHDS_ENDPOINT env var)'
            )
        api_version = pick('api_version', None) or cfg.ahds_api_version
        tenant_id = pick('tenant_id', cfg.ahds_tenant_id)
        client_id = pick('client_id', cfg.ahds_client_id)
        client_secret = pick('client_secret', global_secret)
        return endpoint, api_version, tenant_id, client_id, client_secret

    def _get_ahds_analyzer(self, ahds=None):
        endpoint, api_version, tenant_id, client_id, client_secret = (
            self._resolve_ahds_settings(ahds)
        )
        cache_key = (endpoint, api_version, tenant_id, client_id)
        analyzer = self._analyzer_ahds_cache.get(cache_key)
        if analyzer is not None:
            return analyzer

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
        self._analyzer_ahds_cache[cache_key] = analyzer
        return analyzer

    @property
    def anonymizer(self):
        if not self._anonymizer:
            logger.info('Presidio Anonymizer initialization...')
            self._anonymizer = AnonymizerEngine()
        return self._anonymizer

    def get_analyzer(self, backend: str = 'local', ahds=None):
        if backend == 'ahds':
            return self._get_ahds_analyzer(ahds)
        return self.analyzer
