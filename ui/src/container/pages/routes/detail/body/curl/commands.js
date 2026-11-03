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

const DECISION_CURL = (projectName, routeName, apiKey) => `curl ${GATEWAY_BASE_URL}/v1/systemone \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey || '<your-secret-key>'}" \\
  -d '{
    "model": "${projectName}/${routeName}",
    "state": "My card was charged twice",
    "questions": {
      "intent": {
        "type": "choice",
        "instructions": "What does the customer want?",
        "criteria": {
          "refund": "Wants money back",
          "information": "Wants an explanation"
        }
      }
    }
  }'`;

export { CHAT_CURL, DECISION_CURL, TRANSCRIPTION_CURL };
