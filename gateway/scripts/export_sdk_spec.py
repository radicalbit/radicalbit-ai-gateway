"""Write the OpenAPI spec of the Management SDK (or, with --full, of the whole app).

Run from gateway/:  uv run python scripts/export_sdk_spec.py [--full] [--out PATH]
"""

import argparse
import json
from pathlib import Path

from radicalbit_ai_gateway.sdk_spec import build_sdk_spec
from radicalbit_ai_gateway.server import app

DEFAULT_OUT = Path(__file__).resolve().parents[2] / 'sdk' / 'openapi.json'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--full', action='store_true', help='the whole app, not the SDK subset'
    )
    parser.add_argument(
        '--out', type=Path, help=f'output file (default: {DEFAULT_OUT})'
    )
    args = parser.parse_args()
    out = args.out or (Path('openapi.full.json') if args.full else DEFAULT_OUT)
    spec = app.openapi() if args.full else build_sdk_spec(app)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + '\n')
    print(f'Wrote {out}')  # noqa: T201


if __name__ == '__main__':
    main()
