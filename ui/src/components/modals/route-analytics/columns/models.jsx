import { Divider, Popover } from '@radicalbit/radicalbit-design-system';

function Models({ configuration }) {
  const chatModels = configuration?.chatModels || [];
  const embeddingModels = configuration?.embeddingModels || [];
  const transcriptionModels = configuration?.transcriptionModels || [];

  const chatModelsCount = chatModels.length;
  const embeddingModelsCount = embeddingModels.length;
  const transcriptionModelsCount = transcriptionModels.length;
  const count = chatModelsCount + embeddingModelsCount + transcriptionModelsCount;

  if (count === 0) {
    return '--';
  }

  const content = (
    <div className="flex flex-col gap-2">
      {chatModelsCount > 0 && (
        <div className="flex flex-col justify-center w-full gap-1">
          <strong>Chat models</strong>

          <div className="flex flex-col">
            {chatModels.map(({ model }) => (
              <div>{model}</div>
            ))}
          </div>
        </div>
      )}

      {chatModelsCount > 0 && embeddingModelsCount > 0 && <Divider style={{ margin: 0 }} />}

      {embeddingModelsCount > 0 && (
        <div className="flex flex-col justify-center w-full gap-1">
          <strong>Embedding models</strong>

          <div className="flex flex-col">
            {embeddingModels.map(({ model }) => (
              <div>{model}</div>
            ))}
          </div>
        </div>
      )}

      {(chatModelsCount > 0 || embeddingModelsCount > 0) && transcriptionModelsCount > 0 && <Divider style={{ margin: 0 }} />}

      {transcriptionModelsCount > 0 && (
        <div className="flex flex-col justify-center w-full gap-1">
          <strong>Transcription models</strong>

          <div className="flex flex-col">
            {transcriptionModels.map(({ model }) => (
              <div>{model}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <Popover content={content} minWidth="250">
      {count}
    </Popover>
  );
}

export default Models;
