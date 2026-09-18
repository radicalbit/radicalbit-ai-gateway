from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.models.secret_dto import SecretOut
from radicalbit_ai_gateway.services.secret_service import SecretService


@dataclass
class SecretsRouteConfig:
    # The search argument is always None here. AG-968 adds the query parameter
    # that fills it. The signature ships now so Enterprise can build against it.
    get_secrets_fn: Callable[[Request, str | None], Any] | None = None


class SecretsRoute:
    @staticmethod
    def get_secrets_router(
        secret_service: SecretService,
        config: SecretsRouteConfig | None = None,
    ) -> APIRouter:
        config = config or SecretsRouteConfig()
        get_secrets_fn = config.get_secrets_fn or (
            lambda _request, _search: secret_service.get_secrets()
        )
        router = APIRouter(tags=['secrets_api'])

        @router.get(
            '/secrets',
            status_code=200,
            response_model=Page[SecretOut],
        )
        def get_secrets(
            request: Request,
            _page: Annotated[int, Query(ge=1)] = 1,
            _limit: Annotated[int, Query(ge=1, le=100)] = 50,
        ):
            rows = get_secrets_fn(request, None)
            offset = (_page - 1) * _limit
            return Page.create(
                items=rows[offset : offset + _limit],
                params=Params(page=_page, size=_limit),
                total=len(rows),
            )

        return router
