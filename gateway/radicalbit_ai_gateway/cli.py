import os
from pathlib import Path
import subprocess
import sys

import typer

from radicalbit_ai_gateway.utils.app_config import LogMode

app = typer.Typer(
    help='A command-line interface for the Radicalbit AI Gateway.',
)


@app.callback()
def callback():
    pass


@app.command()
def serve(
    secrets_path: Path = typer.Option(
        'secrets.yaml',
        '--secrets',
        '-s',
        help='Path to the secrets YAML file.',
        file_okay=True,
        readable=True,
    ),
    debug: bool = typer.Option(False, '-d', '--debug', help='Enable debug mode.'),
    host: str = typer.Option('127.0.0.1', '--host', help='Host to bind the server to.'),
    port: int = typer.Option(8000, '--port', '-p', help='Port to bind the server to.'),
    prometheus_metrics_port: int = typer.Option(
        8001, '--metrics-port', help='Port to bind the prometheus metrics server to.'
    ),
    log_mode: LogMode = typer.Option(
        LogMode.PLAIN,
        '--log',
        case_sensitive=False,
        help='Log output: json | plain | color',
    ),
    workers: int = typer.Option(
        1,
        '--workers',
        '-w',
        help='Number of worker processes (uvicorn --workers). Use 1 for development, 2-4x CPU cores for production.',
    ),
):
    """Start the Radicalbit AI Gateway server."""
    typer.secho('Starting radicalbit-ai-gateway', fg=typer.colors.GREEN)

    server_env = os.environ.copy()
    server_env['GATEWAY_SECRETS_PATH'] = str(secrets_path)
    server_env['GATEWAY_DEBUG_MODE'] = 'true' if debug else 'false'
    server_env['PROMETHEUS_METRICS_PORT'] = str(prometheus_metrics_port)
    server_env['LOG_MODE'] = log_mode.value

    command = [
        sys.executable,
        '-m',
        'uvicorn',
        'radicalbit_ai_gateway.server:app',
        '--host',
        host,
        '--port',
        str(port),
    ]

    # Add workers parameter if specified (default is 1, uvicorn default)
    if workers > 1:
        command.extend(['--workers', str(workers)])
    typer.echo(f'Starting server with command: {" ".join(command)}')
    typer.echo('Press Ctrl+C to stop the server.')

    process = None
    try:
        process = subprocess.Popen(command, env=server_env)
        process.wait()

    except KeyboardInterrupt:
        typer.echo('\nSIGINT received, shutting down server...')

    finally:
        if process and process.poll() is None:
            typer.echo('Terminating server process...')
            process.terminate()
            try:
                process.wait(timeout=5)
                typer.echo('Server shut down gracefully.')
            except subprocess.TimeoutExpired:
                typer.secho(
                    'Server did not terminate in time, killing it.', fg=typer.colors.RED
                )
                process.kill()
