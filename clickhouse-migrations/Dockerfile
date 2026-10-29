# goose is built from source with a patched Go toolchain and only the
# ClickHouse driver: the binary shipped in the upstream image lags behind on
# Go and module security fixes, and every other driver only adds dependencies.
FROM golang:1.27.3-alpine AS goose

ARG GOOSE_VERSION=v3.29.0

RUN CGO_ENABLED=0 go install -trimpath -ldflags="-s -w" \
    -tags="no_azuresql no_libsql no_mssql no_mysql no_postgres no_sqlite3 no_vertica no_ydb" \
    github.com/pressly/goose/v3/cmd/goose@${GOOSE_VERSION}

# The upstream image still provides the entrypoint and its GOOSE_* settings.
FROM kukymbr/goose-docker:3.28.0

COPY --from=goose /go/bin/goose /bin/goose
COPY ./migrations /migrations

CMD ["up"]
