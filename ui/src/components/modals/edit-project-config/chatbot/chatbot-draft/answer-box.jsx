import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import { useGenerateConfigMutation } from '@State/projects/api';

function AnswerBox({ config, isGenerated }) {
  const configUuid = config.uuid;

  const [, { data }] = useGenerateConfigMutation({ fixedCacheKey: `generating-config-${configUuid}` });
  const configFile = data?.configFile;

  if (!isGenerated) {
    return false;
  }

  return (
    <CodeBlock
      className="flex-1 min-h-0 overflow-hidden [&_pre]:!max-h-full"
      code={configFile}
      hasCopyToClipboard
      minimal
    >
      <CodeBlockRawText hideLines text={configFile} />
    </CodeBlock>
  );
}

export default AnswerBox;
