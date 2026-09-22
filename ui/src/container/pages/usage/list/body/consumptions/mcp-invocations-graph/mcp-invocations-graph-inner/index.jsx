import Lucide from '@Components/lucide';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import { useGetMcpServersChartSseWithRange } from '@State/usage/vertical-hooks';
import {
  Board, Button, Segmented, Spinner, Void,
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
import { TriangleAlert } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MCP_DEFAULT_GROUP_BY, MCP_GROUP_BY } from '../group-by';
import option from './option';
import useGetNameToId from './use-get-name-to-id';

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

const GROUP_BY_OPTIONS = [
  { value: MCP_GROUP_BY.groups.key, label: MCP_GROUP_BY.groups.label },
  { value: MCP_GROUP_BY.credentials.key, label: MCP_GROUP_BY.credentials.label },
  { value: MCP_GROUP_BY.services.key, label: MCP_GROUP_BY.services.label },
];

const useMcpInvocationsChart = (retryNonce) => {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('mcpGroupBy') || MCP_DEFAULT_GROUP_BY;
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  return useGetMcpServersChartSseWithRange({ routes, groupBy, retryNonce });
};

function McpInvocationsGraphInner() {
  const [retryNonce, setRetryNonce] = useState(0);

  const { data } = useMcpInvocationsChart(retryNonce);

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

            <GroupByTabs />
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

            <GroupByTabs />
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

            <GroupByTabs />
          </>
        )}
        size="xsmall"
      />
    </div>
  );
}

function IsSuccess({ chart }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const groupBy = searchParams.get('mcpGroupBy') || MCP_DEFAULT_GROUP_BY;

  const chartRef = useRef(null);
  const nameToId = useGetNameToId(chart?.data);

  const series = useMemo(() => (chart?.data || []).map(({ name, data: d }) => ({
    name: name || UNRESOLVED_ALIAS_LABEL,
    data: d || [],
  })), [chart?.data]);

  const handleOnChartReady = () => {
    updateTheme(chartRef);
  };

  const handleOnClick = (params) => {
    const id = nameToId[params.seriesName];

    if (!id) {
      return;
    }

    setSearchParams((prev) => {
      prev.set('mcpDrillDownEntity', groupBy);
      prev.set('mcpDrillDownId', id);
      return prev;
    });
  };

  useDarkModeChart(chartRef, series);

  return (
    <div className="relative">
      <ReactEChartsCore
        echarts={echarts}
        lazyUpdate
        notMerge={false}
        onChartReady={handleOnChartReady}
        onEvents={{ click: handleOnClick }}
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

      <GroupByTabs />
    </div>
  );
}

function GroupByTabs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const groupBy = searchParams.get('mcpGroupBy') || MCP_DEFAULT_GROUP_BY;

  const handleOnChangeGroupBy = (value) => {
    setSearchParams((prev) => {
      prev.set('mcpGroupBy', value);
      return prev;
    });
  };

  return (
    <div className="absolute right-4 top-4 z-10">
      <Segmented
        onChange={handleOnChangeGroupBy}
        options={GROUP_BY_OPTIONS}
        size="large"
        type="highlighted"
        value={groupBy}
      />
    </div>
  );
}

export default McpInvocationsGraphInner;
