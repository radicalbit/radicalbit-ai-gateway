import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import formatUsd from '@Helpers/format-usd';
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
      chatModels: chatModels ? formatUsd(chatModels?.input?.direct) : '--',
      judge: chatModels ? formatUsd(chatModels?.input?.judges) : '--',
      embedding: embeddingModels ? formatUsd(embeddingModels?.input?.embedding) : '--',
      semanticCache: embeddingModels ? formatUsd(embeddingModels?.input?.semanticCache) : '--',
      transcription: transcriptionModels
        ? {
          total: formatUsd(transcriptionModels?.input?.total),
          duration: formatUsd(transcriptionModels?.input?.duration),
          audio: formatUsd(transcriptionModels?.input?.audio),
          text: formatUsd(transcriptionModels?.input?.text),
        }
        : '--',
      decision: decisionModels?.input == null ? '--' : formatUsd(decisionModels.input),
      total: formatUsd(totals?.input),
    },
    {
      label: 'Cached input',
      chatModels: chatModels ? formatUsd(chatModels?.cachedInput?.direct) : '--',
      judge: chatModels ? formatUsd(chatModels?.cachedInput?.judges) : '--',
      embedding: '--',
      semanticCache: '--',
      transcription: '--',
      decision: '--',
      total: formatUsd(totals?.cachedInput),
    },
    {
      label: 'Output',
      chatModels: chatModels ? formatUsd(chatModels?.output?.direct) : '--',
      judge: chatModels ? formatUsd(chatModels?.output?.judges) : '--',
      embedding: '--',
      semanticCache: '--',
      transcription: transcriptionModels ? formatUsd(transcriptionModels?.output) : '--',
      decision: '--',
      total: formatUsd(totals?.output),
    },
  ], [chatModels, embeddingModels, transcriptionModels, decisionModels, totals]);
};

export default CostTable;
