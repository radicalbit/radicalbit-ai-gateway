"""Shared values for the decision routing tests."""

TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'
TYPESAFE_KEY = 'ts-upstream-secret'
BACKOFF_SLEEP = 'radicalbit_ai_gateway.invocation.decision_model_invoker.asyncio.sleep'
ROUTER_SPAN = 'radicalbit_ai_gateway.routing.decision_router.trace.get_current_span'
QUESTION_ID = 'decision_routing'

INSTRUCTIONS = 'Choose the model best suited to answer this request.'
EMAILS = 'Emails and business documents'
CHINESE = 'Translation to or from Chinese and Japanese'
USER_TEXT = 'Translate this to Japanese: good morning'

JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': TYPESAFE_KEY},
}
JEV_BACKUP = {
    'model_id': 'jev-backup',
    'model': 'typesafe/jev-backup',
    'credentials': {'api_key': TYPESAFE_KEY},
}
