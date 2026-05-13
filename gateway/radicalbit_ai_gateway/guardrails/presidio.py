import logging

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


class PresidioEngine:
    def __init__(self, languages: list[str] = ['en', 'it']):
        self._analyzer = None
        self._anonymizer = None
        self._languages = languages
        self._lang_model_mapping = {'it': 'it_core_news_md', 'en': 'en_core_web_lg'}

    @property
    def analyzer(self):
        if not self._analyzer:
            logger.info('Presidio Analyzer initialization...')
            self._analyzer = self._load_presidio_analyzer()
        return self._analyzer

    @property
    def anonymizer(self):
        if not self._anonymizer:
            logger.info('Presidio Anonymizer initialization...')
            self._anonymizer = self._load_presidio_anonymizer()
        return self._anonymizer

    def _load_presidio_analyzer(self):
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
        nlp_engine = provider.create_engine()
        return AnalyzerEngine(
            supported_languages=self._languages, nlp_engine=nlp_engine
        )

    def _load_presidio_anonymizer(self):
        return AnonymizerEngine()
