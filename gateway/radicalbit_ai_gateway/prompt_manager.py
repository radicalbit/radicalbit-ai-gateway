import logging
from pathlib import Path

from radicalbit_ai_gateway.utils.app_config import PromptManagerConfig, get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class PromptManager:
    """Manages loading prompts from the filesystem."""

    _global_instance: 'PromptManager | None' = None

    def __init__(self, conf: PromptManagerConfig):
        self.prompts_dir = conf.prompts_dir
        self.model_prompts_dir = Path(self.prompts_dir) if self.prompts_dir else None
        if self.model_prompts_dir:
            self.model_prompts_dir.mkdir(parents=True, exist_ok=True)

        self.judge_prompts_dir = conf.judge_prompts_dir
        self.judge_custom_prompts_dir = (
            Path(self.judge_prompts_dir) if self.judge_prompts_dir else None
        )
        if self.judge_custom_prompts_dir:
            self.judge_custom_prompts_dir.mkdir(parents=True, exist_ok=True)

        self.judge_base_prompts_dir = (
            Path(__file__).parent / 'guardrails' / 'judges' / 'prompts'
        )
        self.judge_base_prompts_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def set_global(cls, manager: 'PromptManager') -> None:
        cls._global_instance = manager

    @classmethod
    def get_global(cls) -> 'PromptManager | None':
        return cls._global_instance

    def _candidate_paths(self, prompt_ref: str, scope: str) -> list[Path]:
        ref_path = Path(prompt_ref)
        if ref_path.is_absolute():
            return [ref_path]

        if scope == 'judge':
            dirs: list[Path] = []
            if self.judge_custom_prompts_dir:
                dirs.append(self.judge_custom_prompts_dir)
            dirs.append(self.judge_base_prompts_dir)
            return [d / ref_path for d in dirs]

        if scope == 'model':
            if self.model_prompts_dir is None:
                raise ValueError('Model prompts directory not configured')
            return [self.model_prompts_dir / ref_path]

        raise ValueError(f"Unknown prompt scope '{scope}'")

    def _get_prompt(self, prompt_ref: str, scope: str = 'judge') -> str:
        logger.debug(
            'PromptManager resolving prompt_ref=%s scope=%s', prompt_ref, scope
        )

        candidate_paths = self._candidate_paths(prompt_ref, scope)
        prompt_path = next(
            (p for p in candidate_paths if p.exists()), candidate_paths[-1]
        )

        if not prompt_path.exists():
            raise FileNotFoundError(f'Prompt file not found: {prompt_path}')
        if not prompt_path.is_file():
            raise ValueError(f'Prompt reference is not a file: {prompt_path}')

        content = prompt_path.read_text(encoding='utf-8')
        logger.debug('PromptManager loaded prompt from %s', prompt_path)
        return content

    def get_judge_prompt(self, prompt_ref: str) -> str:
        return self._get_prompt(prompt_ref, scope='judge')

    def get_model_prompt(self, prompt_ref: str) -> str:
        return self._get_prompt(prompt_ref, scope='model')
