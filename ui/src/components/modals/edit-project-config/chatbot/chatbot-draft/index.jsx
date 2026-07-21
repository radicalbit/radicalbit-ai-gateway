import Lucide from '@Components/lucide';
import { useGenerateConfigMutation } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Board, Button, NewHeader, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { Check, RotateCcw, WandSparkles } from 'lucide-react';
import { useState } from 'react';
import AnswerBox from './answer-box';
import PromptInput from './prompt-input';

function ChatbotDraft({ config, projectUuid }) {
  const [description, setDescription] = useState('');
  const [error, setError] = useState(null);
  const [isGenerated, setIsGenerated] = useState(false);

  return (
    <div className="flex flex-col min-h-0">
      <NewHeader title={(
        <SectionTitle
          subtitle="AI can make mistakes, please check the answer"
          title="Generate Configuration"
          titlePrefix={<Lucide icon={WandSparkles} />}
        />
      )}
      />

      <ErrorAlert error={error} />

      <Board
        className="min-h-0"
        main={(
          <div className="flex flex-col h-full min-h-0">
            <PromptInput
              config={config}
              description={description}
              isGenerated={isGenerated}
              projectUuid={projectUuid}
              setDescription={setDescription}
              setError={setError}
              setIsGenerated={setIsGenerated}
            />

            <AnswerBox config={config} isGenerated={isGenerated} />
          </div>
        )}
        overflow="hidden"
        size="xsmall"
      />

      <Actions
        config={config}
        isGenerated={isGenerated}
        setDescription={setDescription}
        setIsGenerated={setIsGenerated}
      />
    </div>
  );
}

function ErrorAlert({ error }) {
  if (!error) {
    return false;
  }

  return <Alert message={error} type="error" />;
}

function Actions({ config, isGenerated, setIsGenerated, setDescription }) {
  const configUuid = config.uuid;

  const { write } = useFormbitContext();

  const [, { data }] = useGenerateConfigMutation({ fixedCacheKey: `generating-config-${configUuid}` });
  const configFile = data?.configFile;

  const handleOnDiscard = () => {
    setIsGenerated(false);
    setDescription('');
  };

  const handleOnApply = () => {
    write(`configs.${configUuid}`, configFile);
    setIsGenerated(false);
    setDescription('');
  };

  const visibilityClassName = isGenerated ? '' : 'invisible pointer-events-none';

  return (
    <div className={`flex justify-center items-center gap-4 ${visibilityClassName}`}>
      <Button
        onClick={handleOnDiscard}
        prefix={<Lucide icon={RotateCcw} />}
        type="text"
      >
        Discard
      </Button>

      <Button
        onClick={handleOnApply}
        prefix={<Lucide icon={Check} />}
        type="primary"
      >
        Use in configuration
      </Button>
    </div>
  );
}

export default ChatbotDraft;
