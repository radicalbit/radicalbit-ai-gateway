import { Divider, Popover } from '@radicalbit/radicalbit-design-system';
import { Fragment } from 'react';

const MODEL_GROUPS = [
  { key: 'chatModels', title: 'Chat models' },
  { key: 'embeddingModels', title: 'Embedding models' },
  { key: 'transcriptionModels', title: 'Transcription models' },
  { key: 'decisionModels', title: 'Decision models' },
];

function Models({ configuration }) {
  const groups = MODEL_GROUPS
    .map(({ key, title }) => ({ key, title, models: configuration?.[key] || [] }))
    .filter(({ models }) => models.length > 0);

  const count = groups.reduce((sum, { models }) => sum + models.length, 0);

  if (count === 0) {
    return '--';
  }

  const content = (
    <div className="flex flex-col gap-2">
      {groups.map(({ key, title, models }, index) => (
        <Fragment key={key}>
          {index > 0 && <Divider style={{ margin: 0 }} />}

          <div className="flex flex-col justify-center w-full gap-1">
            <strong>{title}</strong>

            <div className="flex flex-col">
              {models.map(({ model, modelId }) => (
                <div key={modelId}>{model}</div>
              ))}
            </div>
          </div>
        </Fragment>
      ))}
    </div>
  );

  return (
    <Popover content={content} minWidth="250">
      {count}
    </Popover>
  );
}

export default Models;
