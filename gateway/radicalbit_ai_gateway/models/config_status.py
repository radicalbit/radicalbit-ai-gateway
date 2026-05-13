from enum import Enum


class ConfigStatus(str, Enum):
    DRAFT = 'DRAFT'
    READY_TO_SERVE = 'READY_TO_SERVE'
    SERVED = 'SERVED'
