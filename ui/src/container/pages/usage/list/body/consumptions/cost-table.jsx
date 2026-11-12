import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import formatCost from '@Helpers/format-cost';
import { useGetCostsSummaryStreamWithRange } from '@Src/store/state/usage/vertical-hooks';
import columns from './columns';

function CostTable() {
  const dataSource = useGetDataSource();

  return (
    <DataTable
      columns={columns}
      dataSource={dataSource}
      pagination={false}
      rowKey="label"
      size="small"
    />
  );
}

const useGetDataSource = () => {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data } = useGetCostsSummaryStreamWithRange({ routes, withSavedTokens: false });
  const summary = data?.summary;
  const chatModels = summary?.chatModels;
  const embeddingModels = summary?.embeddingModels;
  const transcriptionModels = summary?.transcriptionModels;
  const decisionModels = summary?.decisionModels;
  const totals = summary?.totals;

  return useMemo(() => [
    {
      label: 'Input',
      chatModels: chatModels ? formatCost(chatModels?.input?.direct) : '--',
      judge: chatModels ? formatCost(chatModels?.input?.judges) : '--',
      embedding: embeddingModels ? formatCost(embeddingModels?.input?.embedding) : '--',
      semanticCache: embeddingModels ? formatCost(embeddingModels?.input?.semanticCache) : '--',
      transcription: transcriptionModels
        ? {
          total: formatCost(transcriptionModels?.input?.total),
          duration: formatCost(transcriptionModels?.input?.duration),
          audio: formatCost(transcriptionModels?.input?.audio),
          text: formatCost(transcriptionModels?.input?.text),
        }
        : '--',
      decision: decisionModels?.input == null ? '--' : formatCost(decisionModels.input),
      total: formatCost(totals?.input),
    },
    {
      label: 'Cached input',
      chatModels: chatModels ? formatCost(chatModels?.cachedInput?.direct) : '--',
      judge: chatModels ? formatCost(chatModels?.cachedInput?.judges) : '--',
      embedding: '--',
      semanticCache: '--',
      transcription: '--',
      decision: '--',
      total: formatCost(totals?.cachedInput),
    },
    {
      label: 'Output',
      chatModels: chatModels ? formatCost(chatModels?.output?.direct) : '--',
      judge: chatModels ? formatCost(chatModels?.output?.judges) : '--',
      embedding: '--',
      semanticCache: '--',
      transcription: transcriptionModels ? formatCost(transcriptionModels?.output) : '--',
      decision: '--',
      total: formatCost(totals?.output),
    },
  ], [chatModels, embeddingModels, transcriptionModels, decisionModels, totals]);
};

export default CostTable;
