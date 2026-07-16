import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetGroupQuery } from '@State/groups/api';
import { useGetKeyQuery } from '@State/keys/api';
import {
  useGetCostsByGroupStreamWithRange,
  useGetCostsByKeyStreamWithRange,
  useGetCostsByModelStreamWithRange,
} from '@State/usage/vertical-hooks';
import { faArrowLeft } from '@fortawesome/free-solid-svg-icons';
import { Button, FontAwesomeIcon, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
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
import { useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import '../_styles.less';
import { GROUP_BY } from '../group-by';
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

function CostsGraphDrillDown() {
  const { data, isError, isLoading, isSuccess } = useDrillDownData();

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
      <Void
        description="No cost data available yet. Chart will appear automatically when some data arrived."
        style={chartWidthAndHeight}
        title="Cost Analysis Overview"
      />

      <BackButton />
    </div>
  );
}

function IsSuccess() {
  const chartRef = useRef(null);

  const { data } = useDrillDownData();

  const series = useMemo(() => (data.data || []).map(({ name, data: d }) => ({
    name,
    data: d || [],
  })), [data.data]);

  useDarkModeChart(chartRef, series);

  return (
    <div className="relative">
      <ReactEChartsCore
        echarts={echarts}
        lazyUpdate
        notMerge={false}
        onChartReady={() => updateTheme(chartRef)}
        option={option({
          xAxisData: data.timestamp || [],
          series,
          granularity: data.granularity,
          total: data.total,
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
      prev.delete('drillDownEntity');
      prev.delete('drillDownId');
      return prev;
    });
  };

  return (
    <div className="absolute right-8 top-4 z-10">
      <Button onClick={handleOnClick} suffix={<Label />} type="primary">
        <FontAwesomeIcon icon={faArrowLeft} />
      </Button>
    </div>
  );
}

function Label() {
  const [searchParams] = useSearchParams();
  const drillDownEntity = searchParams.get('drillDownEntity');
  const drillDownId = searchParams.get('drillDownId');

  const { data: groupData, isLoading: isLoadingGroup } = useGetGroupQuery(drillDownId, { skip: drillDownEntity !== GROUP_BY.groups.key });
  const { data: keyData, isLoading: isLoadingKey } = useGetKeyQuery(drillDownId, { skip: drillDownEntity !== GROUP_BY.credentials.key });

  if (isLoadingGroup || isLoadingKey) {
    return <span>Loading ...</span>;
  }

  switch (drillDownEntity) {
    case GROUP_BY.models.key:
      return <span>{`Model: ${drillDownId}`}</span>;

    case GROUP_BY.groups.key:
      return <span>{`Group: ${groupData?.name}`}</span>;

    case GROUP_BY.credentials.key:
      return <span>{`Credential: ${keyData?.name}`}</span>;

    default:
      return <span />;
  }
}

function useDrillDownData() {
  const [searchParams] = useSearchParams();
  const drillDownEntity = searchParams.get('drillDownEntity');
  const drillDownId = searchParams.get('drillDownId');
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const isModels = drillDownEntity === GROUP_BY.models.key;
  const isGroups = drillDownEntity === GROUP_BY.groups.key;
  const isKeys = drillDownEntity === GROUP_BY.credentials.key;

  const modelResult = useGetCostsByModelStreamWithRange(
    { modelId: drillDownId, routes },
    { skip: !isModels },
  );

  const groupResult = useGetCostsByGroupStreamWithRange(
    { groupUuid: drillDownId, routes },
    { skip: !isGroups },
  );

  const keyResult = useGetCostsByKeyStreamWithRange(
    { keyUuid: drillDownId, routes },
    { skip: !isKeys },
  );

  switch (drillDownEntity) {
    case GROUP_BY.models.key:
      return modelResult;
    case GROUP_BY.groups.key:
      return groupResult;
    case GROUP_BY.credentials.key:
      return keyResult;
    default:
      return modelResult;
  }
}

export default CostsGraphDrillDown;
