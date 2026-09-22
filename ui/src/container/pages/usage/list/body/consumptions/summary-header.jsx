import { useGetCostsSummaryStreamWithRange } from '@State/usage/vertical-hooks';
import { SectionTitle } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import costFormatter from '@Helpers/cost-formatter';

function SummaryHeader() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data } = useGetCostsSummaryStreamWithRange({ routes, withSavedTokens: false });
  const summary = data?.summary;
  const total = summary?.total;
  const totals = summary?.totals;
  const chatModels = summary?.chatModels;
  const embeddingModels = summary?.embeddingModels;
  const transcriptionModels = summary?.transcriptionModels;

  const totalCosts = costFormatter({ cent: total });
  const saved = costFormatter({ cent: totals?.saved || 0 });
  const chatModelsTotal = chatModels ? costFormatter({ cent: chatModels?.total }) : '--';
  const embeddingModelsTotal = embeddingModels ? costFormatter({ cent: embeddingModels?.total }) : '--';
  const transcriptionModelsTotal = transcriptionModels ? costFormatter({ cent: transcriptionModels?.total }) : '--';

  return (
    <div className="flex gap-16 items-start">
      <SectionTitle
        reverse
        size="large"
        subtitle="Total costs"
        title={(
          <>
            <div>{totalCosts}</div>

            <div className="text-sm font-normal">{`saved ${saved}`}</div>
          </>
        )}
      />

      <SectionTitle reverse size="large" subtitle="Chat models" title={chatModelsTotal} />

      <SectionTitle reverse size="large" subtitle="Embedding models" title={embeddingModelsTotal} />

      <SectionTitle reverse size="large" subtitle="Transcription models" title={transcriptionModelsTotal} />
    </div>
  );
}

export default SummaryHeader;
