import { GATEWAY_BASE_URL } from '@Api/config';

const CHAT_CURL = (projectName, routeName, apiKey) => `curl ${GATEWAY_BASE_URL}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey || '<your-secret-key>'}" \\
  -d '{
    "model": "${projectName}/${routeName}",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'`;

const TRANSCRIPTION_CURL = (projectName, routeName, apiKey, audioPath) => `curl ${GATEWAY_BASE_URL}/v1/audio/transcriptions \\
  -H "Authorization: Bearer ${apiKey || '<your-secret-key>'}" \\
  -F "model=${projectName}/${routeName}" \\
  -F "file=@${audioPath || '<path-to-your-audio-file>'}"`;

export { CHAT_CURL, TRANSCRIPTION_CURL };
