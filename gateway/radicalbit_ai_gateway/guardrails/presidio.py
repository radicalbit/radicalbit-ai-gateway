import logging

from azure.health.deidentification import DeidentificationClient
from azure.identity import DefaultAzureCredential
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import AzureHealthDeidRecognizer
from presidio_anonymizer import AnonymizerEngine

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


class PresidioEngine:
    def __init__(self, languages: list[str] = ['en', 'it']):
        self._analyzer_local = None
        self._analyzer_ahds = None
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
    def _build_ahds_client(endpoint: str):
        """Construct a DeidentificationClient using DefaultAzureCredential.

        DefaultAzureCredential resolves credentials lazily and only includes
        WorkloadIdentityCredential in its chain when the relevant env vars are
        present, so it does not fail at construction time the way the recognizer's
        built-in ChainedTokenCredential helper does.
        """
        credential = DefaultAzureCredential()
        return DeidentificationClient(endpoint, credential)

    @property
    def analyzer_ahds(self):
        if not self._analyzer_ahds:
            logger.info('Presidio Analyzer (AHDS) initialization...')
            ahds_endpoint = get_app_config().ahds_config.ahds_endpoint
            if not ahds_endpoint:
                raise ValueError('AHDS_ENDPOINT must be set when backend=ahds is used')

            # Build the Azure client ourselves with DefaultAzureCredential instead of
            # relying on the recognizer's default get_azure_credential() helper. That
            # helper eagerly constructs WorkloadIdentityCredential() in production mode,
            # which raises at construction time when the AKS workload-identity env vars
            # are absent (e.g. Docker with service-principal env vars). DefaultAzureCredential
            # only adds workload identity to its chain when those vars exist, and still
            # resolves service principal env vars, managed identity, and `az login`.
            client = self._build_ahds_client(ahds_endpoint)
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

            self._analyzer_ahds = AnalyzerEngine(
                supported_languages=self._languages,
                nlp_engine=self._get_nlp_engine(),
            )
            self._analyzer_ahds.registry.add_recognizer(recognizer)
            logger.info('AHDS recognizer registered on AnalyzerEngine')
        return self._analyzer_ahds

    @property
    def anonymizer(self):
        if not self._anonymizer:
            logger.info('Presidio Anonymizer initialization...')
            self._anonymizer = AnonymizerEngine()
        return self._anonymizer

    def get_analyzer(self, backend: str = 'local'):
        if backend == 'ahds':
            return self.analyzer_ahds
        return self.analyzer
