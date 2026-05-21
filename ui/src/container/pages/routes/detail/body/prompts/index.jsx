import CodeBlock from '@Components/code-block';
import CodeBlockMarkdown from '@Components/code-block/markdown';
import CodeBlockRawText from '@Components/code-block/raw-text';
import Logo from '@Img/logo.png';
import { useGetPromptsByRouteQuery } from '@State/routes/api';
import { faLock } from '@fortawesome/free-solid-svg-icons';
import {
  Board,
  Button,
  Collapse,
  FontAwesomeIcon,
  SectionTitle,
  Skeleton,
  Switchbox,
  Tag,
  Tooltip,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

function Prompts() {
  const { name } = useParams();
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { isLoading, isError, isSuccess, refetch } = useGetPromptsByRouteQuery({ projectUuid, name }, { skip: !projectUuid });

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess />;
}

function IsSuccess() {
  const { name } = useParams();
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data } = useGetPromptsByRouteQuery({ projectUuid, name }, { skip: !projectUuid });
  const prompts = data?.prompts || [];

  const items = prompts.map((entry, index) => {
    const category = entry?.category;
    const guardrailName = entry?.guardrailName;
    const modelId = entry?.modelId;
    const modelName = entry?.modelName;
    const prompt = entry?.prompt;
    const tokens = entry?.tokens;

    const hasPrompt = !!entry.prompt;

    const subtitle = category === 'guardrail-judge'
      ? `${category} | ${guardrailName}`
      : category;

    return {
      key: index,
      label: (
        <SectionTitle
          icon={category === 'guardrail-judge' ? <Tag type="full">Guardrail</Tag> : <Tag type="full">Model</Tag>}
          size="small"
          subtitle={`${subtitle} | ${modelId} | tokens: ${tokens}`}
          title={modelName}
          titleSuffix={!hasPrompt && <Tooltip title="Prompt not configured"><FontAwesomeIcon icon={faLock} /></Tooltip>}
        />
      ),
      children: hasPrompt
        ? <PromptCodeBlock prompt={prompt} />
        : (
          <CodeBlock wrapText>
            <CodeBlockRawText hideLines text="Prompt not configured" />
          </CodeBlock>
        ),

    };
  });

  return (
    <Collapse
      key={name}
      expandIconPosition="right"
      items={items}
      type="border-bottom"
    />
  );
}

function PromptCodeBlock({ prompt }) {
  const [isMarkdownView, setIsMarkdownView] = useState(true);

  const handleOnChange = () => {
    setIsMarkdownView(!isMarkdownView);
  };

  if (isMarkdownView) {
    return (
      <CodeBlock actions={<Switchbox checked={isMarkdownView} label="Preview" onChange={handleOnChange} />} code={prompt} hasCopyToClipboard wrapText>
        <CodeBlockMarkdown text={prompt} />
      </CodeBlock>
    );
  }

  return (
    <CodeBlock actions={<Switchbox checked={isMarkdownView} label="Raw" onChange={handleOnChange} />} code={prompt} hasCopyToClipboard wrapText>
      <CodeBlockRawText hideLines text={prompt} />
    </CodeBlock>
  );
}

function IsLoading() {
  return (
    <div className="flex flex-col gap-4 py-2">
      <Skeleton.Input
        active
        style={{
          height: '4rem',
          width: '100%',
          borderRadius: '1rem',
        }}
      />

      <Skeleton.Input
        active
        style={{
          height: '4rem',
          width: '100%',
          borderRadius: '1rem',
        }}
      />

      <Skeleton.Input
        active
        style={{
          height: '4rem',
          width: '100%',
          borderRadius: '1rem',
        }}
      />
    </div>
  );
}

function IsError({ refetch }) {
  return (
    <Board
      main={(
        <Void
          actions={<Button onClick={refetch}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<img alt="Logo" src={Logo} />}
          style={{ height: '80vh' }}
          title="Unable to load Prompts"
        />
      )}
    />
  );
}

export default Prompts;
