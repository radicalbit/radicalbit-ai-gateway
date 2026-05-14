import costFormatter from '@Helpers/cost-formatter';

function Label({ route }) {
  const routeName = route?.routeName;
  const summary = route?.summary;
  const chatModels = summary?.chatModels;
  const embeddingModels = summary?.embeddingModels;

  const chatModelsTotal = chatModels ? costFormatter({ cent: summary?.chatModels?.total }) : '--';
  const embeddingModelsTotal = embeddingModels ? costFormatter({ cent: summary?.embeddingModels?.total }) : '--';

  const total = costFormatter({ cent: summary?.total });
  const saved = costFormatter({ cent: summary?.totals?.saved || 0 });

  return (
    <div className="flex justify-between items-center">
      <div className="flex items-center gap-4 w-[75%]">
        {routeName}
      </div>

      <div className="flex justify-end w-full">
        <div className="flex items-center w-[300px] gap-2">
          <div style={{ fontWeight: 'normal', fontSize: '1.25rem' }}>Chat models:</div>

          <div>{chatModelsTotal}</div>
        </div>

        <div className="flex items-center w-[300px] gap-2">
          <div style={{ fontWeight: 'normal', fontSize: '1.25rem' }}>Embedding models:</div>

          <div>{embeddingModelsTotal}</div>
        </div>

        <div className="flex items-center w-[300px] gap-2 justify-end">
          <div style={{ fontWeight: 'normal', fontSize: '1.25rem' }}>Total:</div>

          <div style={{ fontSize: '1.25rem' }}>{total}</div>

          <div style={{ fontWeight: 'normal', fontSize: '1.25rem' }}>
            {` - (saved ${saved})`}
          </div>
        </div>
      </div>
    </div>
  );
}

function Children({ route }) {
  const summary = route?.summary;
  const { chatModels, embeddingModels, totals } = summary ?? {};

  const chatModelsInputJudges = chatModels ? costFormatter({ cent: chatModels?.input?.judges }) : '--';
  const chatModelsCachedJudges = chatModels ? costFormatter({ cent: chatModels?.cachedInput?.judges }) : '--';
  const chatModelsOutputJudges = chatModels ? costFormatter({ cent: chatModels?.output?.judges }) : '--';

  const chatModelsInputDirect = chatModels ? costFormatter({ cent: chatModels?.input?.direct }) : '--';
  const chatModelsCachedDirect = chatModels ? costFormatter({ cent: chatModels?.cachedInput?.direct }) : '--';
  const chatModelsOutputDirect = chatModels ? costFormatter({ cent: chatModels?.output?.direct }) : '--';

  const embeddingModelsInputEmbedding = embeddingModels ? costFormatter({ cent: embeddingModels?.input?.embedding }) : '--';
  const embeddingModelsInputSemanticCache = embeddingModels ? costFormatter({ cent: embeddingModels?.input?.semanticCache }) : '--';

  const totalInput = costFormatter({ cent: totals?.input });
  const totalCached = costFormatter({ cent: totals?.cachedInput });
  const totalOutput = costFormatter({ cent: totals?.output });

  return (
    <div className="flex gap-8">
      <div className="w-[75%] flex flex-col justify-end items-end">
        <div>&nbsp;</div>

        <div>Input:</div>

        <div>Cached Input:</div>

        <div>Output:</div>
      </div>

      <div className="flex justify-end">
        <div className="w-[300px] flex gap-4">
          <div>
            <div className="flex justify-end">Chat Models</div>

            <div className="flex">
              {chatModelsInputDirect}
            </div>

            <div className="flex">
              {chatModelsCachedDirect}
            </div>

            <div className="flex">
              {chatModelsOutputDirect}
            </div>
          </div>

          <div>
            <div className="flex justify-end">Judge</div>

            <div className="flex">
              {chatModelsInputJudges}
            </div>

            <div className="flex">
              {chatModelsCachedJudges}
            </div>

            <div className="flex">
              {chatModelsOutputJudges}
            </div>
          </div>
        </div>

        <div className="w-[300px] flex gap-4">
          <div>
            <div className="flex justify-end">Embedding Models</div>

            <div className="flex">
              {embeddingModelsInputEmbedding}
            </div>

            <div className="flex">
              --
            </div>

            <div className="flex">
              --
            </div>
          </div>

          <div>
            <div className="flex justify-end">Semantic Cache</div>

            <div className="flex">
              {embeddingModelsInputSemanticCache}
            </div>

            <div className="flex">
              --
            </div>

            <div className="flex">
              --
            </div>
          </div>
        </div>

        <div className="w-[300px]">
          <div className="flex justify-end">&nbsp;</div>

          <strong className="flex justify-end">
            {totalInput}
          </strong>

          <strong className="flex justify-end">
            {totalCached}
          </strong>

          <strong className="flex justify-end">
            {totalOutput}
          </strong>
        </div>
      </div>
    </div>
  );
}

export { Children, Label };
