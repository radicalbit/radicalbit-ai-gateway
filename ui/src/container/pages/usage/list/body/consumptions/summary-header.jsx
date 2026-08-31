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
  const totalCosts = costFormatter({ cent: data?.total });
  const saved = costFormatter({ cent: data?.totals?.saved || 0 });
  const chatModelsTotal = data?.chatModels ? costFormatter({ cent: data?.chatModels?.total }) : '--';
  const embeddingModelsTotal = data?.embeddingModels ? costFormatter({ cent: data?.embeddingModels?.total }) : '--';
  const transcriptionModelsTotal = data?.transcriptionModels ? costFormatter({ cent: data?.transcriptionModels?.total }) : '--';

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
