import Lucide from '@Components/lucide';
import { getMessageFromQueryError } from '@Helpers/errors';
import { useGenerateConfigMutation } from '@State/projects/api';
import {
  Board,
  Button, NewHeader, Spin, TextArea,
} from '@radicalbit/radicalbit-design-system';
import { Send } from 'lucide-react';

const TEXTAREA_ROWS = 3;

function PromptInput({
  config, projectUuid, description, setDescription, setError, setIsGenerated, isGenerated,
}) {
  const configUuid = config.uuid;

  const [trigger, { isLoading }] = useGenerateConfigMutation({ fixedCacheKey: `generating-config-${configUuid}` });

  const canGenerate = description.trim().length > 0;

  const handleOnChangeDescription = (e) => {
    setDescription(e.target.value);
  };

  const handleOnGenerate = async () => {
    if (!description.trim() || isLoading) {
      return;
    }

    setError(null);

    const { error: requestError } = await trigger({
      projectUuid,
      configUuid,
      data: { description },
    });

    if (requestError) {
      setError(getMessageFromQueryError(requestError));
    }

    setIsGenerated(true);
  };

  const handleOnKeyDown = (e) => {
    if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault();
      handleOnGenerate();
    }
  };

  if (isGenerated) {
    return false;
  }

  return (
    <Board
      borderType="none"
      footer={(
        <NewHeader
          details={{
            one: (
              <>
                {isLoading && <Spin spinning />}

                {!isLoading && (
                  <Button
                    disabled={!canGenerate}
                    onClick={handleOnGenerate}
                    type="primary"
                  >
                    <Lucide icon={Send} />
                  </Button>
                )}
              </>
            ),
          }}
          title={<i className="color-secondary-01 font-normal">Describe your routes and parameters, add api keys and any custom values. Read configuration docs</i>}
        />
      )}
      main={(
        <TextArea
          bordered={false}
          disabled={isLoading}
          onChange={handleOnChangeDescription}
          onKeyDown={handleOnKeyDown}
          placeholder="Type here..."
          rows={TEXTAREA_ROWS}
          value={description}
        />
      )}
      size="xsmall"
    />
  );
}

export default PromptInput;
