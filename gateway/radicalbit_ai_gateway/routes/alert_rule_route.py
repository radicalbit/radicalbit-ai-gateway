import logging
from uuid import UUID

from fastapi import APIRouter, Path

from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventsOut,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleToggleIn,
    AlertRuleUpdateIn,
)
from radicalbit_ai_gateway.route_meta import route_meta
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class AlertRuleRoute:
    @staticmethod
    def get_alert_rule_router(alert_rule_service: AlertRuleService) -> APIRouter:
        router = APIRouter(tags=['alert_rules_api'])

        @router.get(
            '/rule',
            status_code=200,
            response_model=list[AlertRuleOut],
        )
        def get_all_rules():
            return alert_rule_service.get_all_rules()

        @router.get(
            '/rule/{rule_uuid}',
            status_code=200,
            response_model=AlertRuleOut,
        )
        def get_rule_by_uuid(rule_uuid: UUID = Path(...)):
            return alert_rule_service.get_rule_by_uuid(rule_uuid)

        @router.post(
            '/rule',
            status_code=201,
            response_model=AlertRuleOut,
        )
        @route_meta(entity_type='ALERT_RULE', response_uuid_field='uuid')
        def create_rule(alert_rule_in: AlertRuleIn):
            return alert_rule_service.create_rule(alert_rule_in)

        @router.patch(
            '/rule/{rule_uuid}',
            status_code=200,
            response_model=AlertRuleOut,
        )
        @route_meta(entity_type='ALERT_RULE', entity_uuid_param='rule_uuid')
        def update_rule(
            rule_uuid: UUID = Path(...), alert_rule_in: AlertRuleUpdateIn = ...
        ):
            return alert_rule_service.update_rule(rule_uuid, alert_rule_in)

        @router.patch(
            '/rule/{rule_uuid}/enabled',
            status_code=200,
            response_model=AlertRuleOut,
        )
        @route_meta(
            entity_type='ALERT_RULE', entity_uuid_param='rule_uuid', action='TOGGLE'
        )
        def toggle_rule_enabled(
            rule_uuid: UUID = Path(...), toggle_in: AlertRuleToggleIn = ...
        ):
            return alert_rule_service.toggle_rule_enabled(rule_uuid, toggle_in.enabled)

        @router.delete(
            '/rule/{rule_uuid}',
            status_code=200,
            response_model=AlertRuleOut,
        )
        @route_meta(entity_type='ALERT_RULE', entity_uuid_param='rule_uuid')
        def delete_rule(rule_uuid: UUID = Path(...)):
            return alert_rule_service.delete_rule(rule_uuid)

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/alertable-events',
            status_code=200,
            response_model=AlertableEventsOut,
        )
        def get_route_alertable_events(
            project_uuid: UUID = Path(...),
            route_name: str = Path(...),
        ):
            return alert_rule_service.get_alertable_events_for_route(
                project_uuid=project_uuid, route_name=route_name
            )

        return router
