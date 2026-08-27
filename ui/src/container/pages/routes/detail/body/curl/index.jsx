import { GATEWAY_BASE_URL } from '@Api/config';
import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import Lucide from '@Components/lucide';
import { useGetProjectQuery } from '@State/projects/api';
import { useGetRouteByNameWithRange } from '@State/routes/vertical-hooks';
import { Input, Skeleton } from '@radicalbit/radicalbit-design-system';
import { Key } from 'lucide-react';
import { useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

const CURL_COMMAND = (projectName, routeName, apiKey) => `curl ${GATEWAY_BASE_URL}/v1/chat/completions \
-H "Content-Type: application/json" \
-H "Authorization: Bearer ${apiKey || '<your-secret-key>'}" \
-d '{
  "model": "${projectName}/${routeName}",
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}'`;

const CURL_COMMAND_TRANSCRIPTION = (projectName, routeName, apiKey) => `curl ${GATEWAY_BASE_URL}/v1/audio/transcriptions \
-H "Authorization: Bearer ${apiKey || '<your-secret-key>'}" \
-F "model=${projectName}/${routeName}" \
-F "file=@/path/to/audio.mp3"`;

function Curl() {
  const { name } = useParams();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { isLoading, isError, isSuccess } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const { isLoading: isRouteLoading,
    isError: isRouteError,
    isSuccess: isRouteSuccess } = useGetRouteByNameWithRange(name);

  if (isLoading || isRouteLoading) {
    return <Skeleton.Input active block />;
  }

  if (isError || isRouteError) {
    return <SomethingWentWrong />;
  }

  if (!isSuccess || !isRouteSuccess) {
    return false;
  }

  return (
    <div className="flex flex-col gap-4">
      <ChatCurl />

      <TranscriptionCurl />
    </div>
  );
}

function ChatCurl() {
  const { name } = useParams();
  const [apiKey, setApiKey] = useState('');

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = data?.name;

  const handleOnChangeApiKey = ({ target: { value } }) => { setApiKey(value); };

  return (
    <CodeBlock
      actions={(
        <Input
          onChange={handleOnChangeApiKey}
          placeholder="Paste your credential"
          prefix={<Lucide icon={Key} />}
          value={apiKey}
        />
      )}
      code={CURL_COMMAND(projectName, name, apiKey)}
      hasCopyToClipboard
    >
      <CodeBlockRawText text={CURL_COMMAND(projectName, name, apiKey)} />
    </CodeBlock>
  );
}

function TranscriptionCurl() {
  const { name } = useParams();
  const [apiKey, setApiKey] = useState('');

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = data?.name;

  const { data: route } = useGetRouteByNameWithRange(name);

  const handleOnChangeApiKey = ({ target: { value } }) => { setApiKey(value); };

  if (!route?.configuration?.transcriptionModels?.length) {
    return false;
  }

  return (
    <CodeBlock
      actions={(
        <Input
          onChange={handleOnChangeApiKey}
          placeholder="Paste your credential"
          prefix={<Lucide icon={Key} />}
          value={apiKey}
        />
      )}
      code={CURL_COMMAND_TRANSCRIPTION(projectName, name, apiKey)}
      hasCopyToClipboard
    >
      <CodeBlockRawText text={CURL_COMMAND_TRANSCRIPTION(projectName, name, apiKey)} />
    </CodeBlock>
  );
}

export default Curl;
