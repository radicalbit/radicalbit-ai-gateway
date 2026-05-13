from enum import Enum


class ProjectStatus(str, Enum):
    DEV = 'DEV'
    PROD = 'PROD'
