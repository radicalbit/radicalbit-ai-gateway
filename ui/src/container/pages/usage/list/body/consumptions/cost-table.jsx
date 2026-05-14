import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import costFormatter from '@Helpers/cost-formatter';
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
  const chatModels = data?.chatModels;
  const embeddingModels = data?.embeddingModels;
  const totals = data?.totals;

  return useMemo(() => [
    {
      label: 'Input',
      chatModels: chatModels ? costFormatter({ cent: chatModels?.input?.direct }) : '--',
      judge: chatModels ? costFormatter({ cent: chatModels?.input?.judges }) : '--',
      embedding: embeddingModels ? costFormatter({ cent: embeddingModels?.input?.embedding }) : '--',
      semanticCache: embeddingModels ? costFormatter({ cent: embeddingModels?.input?.semanticCache }) : '--',
      total: costFormatter({ cent: totals?.input }),
    },
    {
      label: 'Cached input',
      chatModels: chatModels ? costFormatter({ cent: chatModels?.cachedInput?.direct }) : '--',
      judge: chatModels ? costFormatter({ cent: chatModels?.cachedInput?.judges }) : '--',
      embedding: '--',
      semanticCache: '--',
      total: costFormatter({ cent: totals?.cachedInput }),
    },
    {
      label: 'Output',
      chatModels: chatModels ? costFormatter({ cent: chatModels?.output?.direct }) : '--',
      judge: chatModels ? costFormatter({ cent: chatModels?.output?.judges }) : '--',
      embedding: '--',
      semanticCache: '--',
      total: costFormatter({ cent: totals?.output }),
    },
  ], [chatModels, embeddingModels, totals]);
};

export default CostTable;
