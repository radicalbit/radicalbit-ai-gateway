import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import { useGetCostsChartStreamWithRange } from '@State/usage/vertical-hooks';
import { Board, Radio, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import ReactEChartsCore from 'echarts-for-react/lib/core';
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
import { useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import '../_styles.less';
import { DEFAULT_GROUP_BY, GROUP_BY } from '../group-by';
import option from './option';
import useGetNameToId from './use-get-name-to-id';
import useLazyGetBreakdownByGroupBy from './use-lazy-get-breakdown-by-group-by';

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

function CostsGraphInner() {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || DEFAULT_GROUP_BY;
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data, isError, isLoading, isSuccess } = useGetCostsChartStreamWithRange({ routes, groupBy });

  if (isLoading) {
    return <Skeleton.Input active block style={chartWidthAndHeight} />;
  }

  if (isError) {
    return <SomethingWentWrong size="small" style={chartWidthAndHeight} />;
  }

  if (!data?.data?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess />;
}

function IsEmpty() {
  return (
    <div className="relative">
      <Board
        main={(
          <>
            <Void
              description="No cost data available yet. Chart will appear automatically when some data arrived."
              style={chartWidthAndHeight}
              title="Cost Analysis Overview"
            />

            <GroupByTabs />
          </>
        )}
        size="xsmall"
        type="secondary-light"
      />
    </div>
  );
}

function IsSuccess() {
  const [searchParams, setSearchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || DEFAULT_GROUP_BY;
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const chartRef = useRef(null);
  const nameToId = useGetNameToId();
  const { routeBreakdownCacheRef, handleOnMouseOver } = useRouteBreakdownTooltip(chartRef);

  const { data } = useGetCostsChartStreamWithRange({ routes, groupBy });
  const series = useMemo(() => (data.data || []).map(({ name, data: d }) => ({
    name,
    data: d || [],
  })), [data.data]);

  const handleOnClick = (params) => {
    const id = nameToId[params.seriesName];

    if (!id) {
      return;
    }

    setSearchParams((prev) => {
      prev.set('drillDownEntity', groupBy);
      prev.set('drillDownId', id);
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
        onChartReady={() => updateTheme(chartRef)}
        onEvents={{ click: handleOnClick, mouseover: handleOnMouseOver }}
        option={option({
          xAxisData: data.timestamp || [],
          series,
          granularity: data.granularity,
          total: data.total,
          routeBreakdownCache: routeBreakdownCacheRef.current,
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
  const groupBy = searchParams.get('groupBy') || DEFAULT_GROUP_BY;

  const handleOnChangeGroupBy = (e) => {
    setSearchParams((prev) => {
      prev.set('groupBy', e.target.value);
      return prev;
    });
  };

  return (
    <div className="absolute right-4 top-4 z-10">
      <Radio.Group
        className="c-echart-radio-button"
        onChange={handleOnChangeGroupBy}
        value={groupBy}
      >
        <Radio.Button value={GROUP_BY.groups.key}>{GROUP_BY.groups.label}</Radio.Button>

        <Radio.Button value={GROUP_BY.credentials.key}>{GROUP_BY.credentials.label}</Radio.Button>

        <Radio.Button value={GROUP_BY.models.key}>{GROUP_BY.models.label}</Radio.Button>
      </Radio.Group>
    </div>
  );
}

const useRouteBreakdownTooltip = (chartRef) => {
  const routeBreakdownCacheRef = useRef(new Map());
  const hoveredKeyRef = useRef(null);
  const inFlightRef = useRef(new Map());

  const nameToId = useGetNameToId();
  const [triggerRouteBreakdown] = useLazyGetBreakdownByGroupBy();

  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || DEFAULT_GROUP_BY;
  const routes = searchParams.get('routes')?.split(',') ?? [];

  const { data } = useGetCostsChartStreamWithRange({ routes, groupBy });
  const granularity = data?.granularity;
  const routesKey = routes.join(',');

  useEffect(() => {
    routeBreakdownCacheRef.current = new Map();

    inFlightRef.current.forEach((req) => req.abort?.());
    inFlightRef.current.clear();
  }, [groupBy, routesKey, granularity]);

  const handleOnMouseOver = (params) => {
    const cacheKey = `${params.seriesName}:${params.name}`;
    hoveredKeyRef.current = cacheKey;

    const cache = routeBreakdownCacheRef.current;
    if (cache.has(cacheKey)) return;

    const entityId = nameToId[params.seriesName];
    if (!entityId || !granularity) return;

    cache.set(cacheKey, 'loading');

    const projectUuid = searchParams.get('projectUuid');

    const req = triggerRouteBreakdown({
      projectUuid,
      groupBy,
      entityId,
      timestamp: params.name,
      granularity,
      routes,
    });

    inFlightRef.current.set(cacheKey, req);

    req.unwrap()
      .then((result) => {
        cache.set(cacheKey, result);

        if (hoveredKeyRef.current !== cacheKey) return;

        chartRef.current?.getEchartsInstance()?.dispatchAction({
          type: 'showTip',
          seriesIndex: params.seriesIndex,
          dataIndex: params.dataIndex,
        });
      })
      .catch(() => {
        cache.set(cacheKey, 'error');
      })
      .finally(() => {
        inFlightRef.current.delete(cacheKey);
      });
  };

  return { routeBreakdownCacheRef, handleOnMouseOver };
};

export default CostsGraphInner;
