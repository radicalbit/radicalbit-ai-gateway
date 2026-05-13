# Support workers via environment variable (default: 1)
WORKERS="${UVICORN_WORKERS:-1}"

exec uvicorn --host="$HTTP_INTERFACE" --port "$HTTP_PORT" --workers "$WORKERS" radicalbit_ai_gateway.server:app --loop uvloop
