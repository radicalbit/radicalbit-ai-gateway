from importlib.metadata import entry_points
import logging

from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

_EP_GROUP = 'radicalbit_ai_gateway.plugins'
_plugin_modules: dict[str, object] = {}


def discover_plugins():
    """Discover and load all enabled plugin entry points (once)."""
    if _plugin_modules:
        return
    app_config = get_app_config()
    enabled = app_config.runtime_config.plugins()
    if not enabled:
        return

    available = {ep.name: ep for ep in entry_points(group=_EP_GROUP)}
    logger.info('Available plugins: %s', sorted(available))

    missing = set(enabled) - set(available)
    if missing:
        raise RuntimeError(
            f'Plugins {sorted(missing)} listed in ENABLED_PLUGINS '
            f'but not registered as entry points in group {_EP_GROUP!r}. '
            f'Available plugins: {sorted(available)}'
        )

    for plugin_name in sorted(available):
        if plugin_name not in enabled:
            continue
        logger.debug('Loading plugin: %s', plugin_name)
        _plugin_modules[plugin_name] = available[plugin_name].load()


def init_plugins(app):
    """Initialize all discovered plugins with the FastAPI app."""
    discover_plugins()
    for plugin_name, module in _plugin_modules.items():
        if hasattr(module, 'init'):
            logger.debug('Initializing plugin %s', plugin_name)
            module.init(app)
            logger.debug('Plugin %s initialized', plugin_name)
