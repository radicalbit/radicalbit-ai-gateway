#!/bin/bash
exec celery -A worker.task:celery_app worker --loglevel=info