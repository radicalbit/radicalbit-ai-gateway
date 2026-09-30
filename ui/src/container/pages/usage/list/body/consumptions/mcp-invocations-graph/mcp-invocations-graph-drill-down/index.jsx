import Lucide from '@Components/lucide';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import { useGetGroupQuery } from '@State/groups/api';
import { useGetKeyQuery } from '@State/keys/api';
import {
  useGetMcpInvocationsByGroupStreamWithRange,
  useGetMcpInvocationsByKeyStreamWithRange,
  useGetMcpInvocationsByServiceStreamWithRange,
} from '@State/usage/vertical-hooks';
import {
  Board, Button, Spinner, Void,
} from '@radicalbit/radicalbit-design-system';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import { BarChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { ArrowLeft, TriangleAlert } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MCP_GROUP_BY } from '../group-by';
import option from './option';

echarts.use([
  BarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
  TitleComponent,
]);

const chartWidthAndHeight = {
  width: '100%',
  height: '25rem',
};

const UNRESOLVED_ALIAS_LABEL = 'Unresolved alias';

function McpInvocationsGraphDrillDown() {
  const [retryNonce, setRetryNonce] = useState(0);

  const { data } = useMcpDrillDownChart(retryNonce);

  const handleOnRetry = () => {
    setRetryNonce((prev) => prev + 1);
  };

  if (data?.isSseLoading) {
    return <IsLoading />;
  }

  if (data?.isSseError) {
    return <IsError onRetry={handleOnRetry} />;
  }

  if (!data?.chart?.data?.length) {
    return <IsEmpty />;
  }

  if (!data?.isSseSuccess) {
    return false;
  }

  return <IsSuccess chart={data.chart} />;
}

function IsLoading() {
  return (
    <div className="relative">
      <Board
        main={(
          <>
            <Void
              actions={<Spinner spinning />}
              description="Fetching the latest MCP invocations. The chart will appear as soon as it is ready."
              style={chartWidthAndHeight}
              title="Loading MCP Invocations"
            />

            <BackButton />
          </>
        )}
        size="xsmall"
      />
    </div>
  );
}

function IsError({ onRetry }) {
  return (
    <div className="relative">
      <Board
        main={(
          <>
            <Void
              actions={<Button onClick={onRetry}>Retry</Button>}
              description={(
                <>
                  This might be temporary
                  <br />
                  please retry later
                </>
              )}
              image={<Lucide icon={TriangleAlert} />}
              style={chartWidthAndHeight}
              title="Unable to load MCP invocations"
            />

            <BackButton />
          </>
        )}
        size="xsmall"
      />
    </div>
  );
}

function IsEmpty() {
  return (
    <div className="relative">
      <Board
        main={(
          <>
            <Void
              description="No MCP invocations data available yet. Chart will appear automatically when some data arrived."
              style={chartWidthAndHeight}
              title="MCP Invocations Overview"
            />

            <BackButton />
          </>
        )}
        size="xsmall"
      />
    </div>
  );
}

function IsSuccess({ chart }) {
  const chartRef = useRef(null);

  const series = useMemo(() => (chart?.data || []).map(({ name, data: d }) => ({
    name: name || UNRESOLVED_ALIAS_LABEL,
    data: d || [],
  })), [chart?.data]);

  const handleOnChartReady = () => {
    updateTheme(chartRef);
  };

  useDarkModeChart(chartRef, series);

  return (
    <div className="relative">
      <ReactEChartsCore
        echarts={echarts}
        lazyUpdate
        notMerge={false}
        onChartReady={handleOnChartReady}
        option={option({
          xAxisData: chart?.timestamp || [],
          series,
          granularity: chart?.granularity,
          total: chart?.total,
        })}
        ref={chartRef}
        style={{
          ...chartWidthAndHeight,
          borderRadius: 'var(--coo-border-radius-small)',
          overflow: 'hidden',
        }}
      />

      <BackButton />
    </div>
  );
}

function BackButton() {
  const [, setSearchParams] = useSearchParams();

  const handleOnClick = () => {
    setSearchParams((prev) => {
      prev.delete('mcpDrillDownEntity');
      prev.delete('mcpDrillDownId');
      return prev;
    });
  };

  return (
    <div className="absolute right-8 top-4 z-10">
      <Button onClick={handleOnClick} suffix={<Label />} type="primary">
        <Lucide icon={ArrowLeft} />
      </Button>
    </div>
  );
}

function Label() {
  const [searchParams] = useSearchParams();
  const mcpDrillDownEntity = searchParams.get('mcpDrillDownEntity');
  const mcpDrillDownId = searchParams.get('mcpDrillDownId');

  const { data: groupData, isLoading: isLoadingGroup } = useGetGroupQuery(mcpDrillDownId, { skip: mcpDrillDownEntity !== MCP_GROUP_BY.groups.key });
  const { data: keyData, isLoading: isLoadingKey } = useGetKeyQuery(mcpDrillDownId, { skip: mcpDrillDownEntity !== MCP_GROUP_BY.credentials.key });

  if (isLoadingGroup || isLoadingKey) {
    return <span>Loading ...</span>;
  }

  switch (mcpDrillDownEntity) {
    case MCP_GROUP_BY.services.key:
      return <span>{`MCP Service: ${mcpDrillDownId}`}</span>;

    case MCP_GROUP_BY.groups.key:
      return <span>{`Group: ${groupData?.name}`}</span>;

    case MCP_GROUP_BY.credentials.key:
      return <span>{`Credential: ${keyData?.name}`}</span>;

    default:
      return <span />;
  }
}

const useMcpDrillDownChart = (retryNonce) => {
  const [searchParams] = useSearchParams();
  const mcpDrillDownEntity = searchParams.get('mcpDrillDownEntity');
  const mcpDrillDownId = searchParams.get('mcpDrillDownId');
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const isServices = mcpDrillDownEntity === MCP_GROUP_BY.services.key;
  const isGroups = mcpDrillDownEntity === MCP_GROUP_BY.groups.key;
  const isKeys = mcpDrillDownEntity === MCP_GROUP_BY.credentials.key;

  const serviceResult = useGetMcpInvocationsByServiceStreamWithRange(
    { serviceAlias: mcpDrillDownId, routes, retryNonce },
    { skip: !isServices },
  );

  const groupResult = useGetMcpInvocationsByGroupStreamWithRange(
    { groupUuid: mcpDrillDownId, routes, retryNonce },
    { skip: !isGroups },
  );

  const keyResult = useGetMcpInvocationsByKeyStreamWithRange(
    { keyUuid: mcpDrillDownId, routes, retryNonce },
    { skip: !isKeys },
  );

  switch (mcpDrillDownEntity) {
    case MCP_GROUP_BY.groups.key:
      return groupResult;
    case MCP_GROUP_BY.credentials.key:
      return keyResult;
    default:
      return serviceResult;
  }
};

export default McpInvocationsGraphDrillDown;
