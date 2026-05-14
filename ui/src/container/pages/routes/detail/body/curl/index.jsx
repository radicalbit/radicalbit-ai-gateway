import { GATEWAY_BASE_URL } from '@Api/config';
import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetProjectQuery } from '@State/projects/api';
import { faKey } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, Input, Skeleton } from '@radicalbit/radicalbit-design-system';
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

function Curl() {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { isLoading, isError, isSuccess } = useGetProjectQuery(projectUuid, { skip: !projectUuid });

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  if (isError) {
    return <SomethingWentWrong />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess />;
}

function IsSuccess() {
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
          prefix={<FontAwesomeIcon icon={faKey} />}
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

export default Curl;
