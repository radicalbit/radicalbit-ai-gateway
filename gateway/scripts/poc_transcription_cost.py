"""POC per AG-835: chiama l'endpoint OpenAI /v1/audio/transcriptions con più modelli
e calcola il costo replicando la logica che dovrebbe finire in CostService.

Uso:
    uv run python scripts/poc_transcription_cost.py path/to/audio.wav
    (richiede OPENAI_API_KEY in env, oppure legge secrets.yaml nella root del repo)

Per generare rapidamente un audio di test su macOS (nessun file necessario):
    say -o test.aiff "Frase di prova per la trascrizione"
    afconvert -f WAVE -d LEI16 test.aiff test.wav
    uv run python scripts/poc_transcription_cost.py test.wav
"""

import json
import os
from pathlib import Path
import sys

from openai import OpenAI
import yaml

MODELS = ['whisper-1', 'gpt-4o-transcribe', 'gpt-4o-mini-transcribe']

# Sottoinsieme di gateway/radicalbit_ai_gateway/resources/model_prices.json,
# copiato qui solo per il POC: nel gateway andrebbe letto da lì, non duplicato.
PRICES = {
    'whisper-1': {'input_cost_per_second': 0.0001},
    'gpt-4o-transcribe': {
        'input_cost_per_audio_token': 6e-06,
        'input_cost_per_token': 2.5e-06,
        'output_cost_per_token': 1e-05,
    },
    'gpt-4o-mini-transcribe': {
        'input_cost_per_audio_token': 3e-06,
        'input_cost_per_token': 1.25e-06,
        'output_cost_per_token': 5e-06,
    },
}


def load_api_key() -> str:
    if key := os.environ.get('OPENAI_API_KEY'):
        return key
    secrets_path = Path(__file__).resolve().parents[2] / 'secrets.yaml'
    secrets = yaml.safe_load(secrets_path.read_text())
    return secrets['OPENAI_API_KEY']


def compute_cost(model: str, usage: dict) -> dict:
    prices = PRICES[model]

    if usage['type'] == 'duration':
        seconds = usage['seconds']
        cost = seconds * prices['input_cost_per_second']
        return {'basis': 'duration', 'seconds': seconds, 'total_cost': cost}

    if usage['type'] == 'tokens':
        details = usage['input_token_details']
        audio_tokens = details['audio_tokens']
        text_tokens = details['text_tokens']
        output_tokens = usage['output_tokens']

        audio_cost = audio_tokens * prices['input_cost_per_audio_token']
        text_cost = text_tokens * prices['input_cost_per_token']
        output_cost = output_tokens * prices['output_cost_per_token']

        return {
            'basis': 'tokens',
            'audio_tokens': audio_tokens,
            'audio_cost': audio_cost,
            'text_tokens': text_tokens,
            'text_cost': text_cost,
            'output_tokens': output_tokens,
            'output_cost': output_cost,
            'total_cost': audio_cost + text_cost + output_cost,
        }

    raise ValueError(f'unknown usage type: {usage["type"]!r}')


def main(audio_path: str) -> None:
    client = OpenAI(api_key=load_api_key())

    for model in MODELS:
        with open(audio_path, 'rb') as audio_file:
            response = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format='json',
            )

        usage = response.usage.model_dump()
        cost = compute_cost(model, usage)

        print(f'=== {model} ===')
        print('usage:', json.dumps(usage, indent=2))
        print('cost:', json.dumps(cost, indent=2))
        print()


if __name__ == '__main__':
    main(sys.argv[1])
