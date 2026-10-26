import Lucide from '@Components/lucide';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import { useGetAlertHistoryQuery } from '@State/alerts/api';
import {
  Button, Collapse, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import dayjs from 'dayjs';
import { TriangleAlert } from 'lucide-react';
import { useMemo, useRef } from 'react';
import { useParams } from 'react-router-dom';
import option from './option';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

const HISTORY_HOURS = 48;

const LATEST_HOURS_SHOWN = 5;

const chartStyle = { width: '100%', height: '11rem' };

const SECONDS_PER_HOUR = 3600;

const toHourlyBuckets = (history) => {
  const counts = Object.fromEntries(history.map(({ bucketStart, sent, failed }) => [
    dayjs(bucketStart).unix(), { sent, failed },
  ]));
  const currentHour = Math.floor(dayjs().unix() / SECONDS_PER_HOUR) * SECONDS_PER_HOUR;

  return Array.from({ length: HISTORY_HOURS }, (_, i) => {
    const bucketStart = currentHour - (HISTORY_HOURS - 1 - i) * SECONDS_PER_HOUR;
    return {
      bucketStart, sent: 0, failed: 0, ...counts[bucketStart],
    };
  });
};

const hoursAgo = (ts) => {
  const hours = dayjs().diff(dayjs.unix(ts), 'hour');

  if (hours === 0) {
    return 'this hour';
  }

  return `${hours}h ago`;
};

function AlertHistory() {
  return (
    <Collapse
      defaultActiveKey={['alert-history']}
      items={[{
        key: 'alert-history',
        label: 'Alert history, last 48h',
        children: <AlertHistoryInner />,
      }]}
      type="no-border"
    />
  );
}

function AlertHistoryInner() {
  const { uuid } = useParams();
  const {
    data, isLoading, isFetching, isError, isSuccess, refetch,
  } = useGetAlertHistoryQuery(uuid);

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (!data?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess history={data} />;
}

function IsSuccess({ history }) {
  const buckets = useMemo(() => toHourlyBuckets(history), [history]);

  const activeBuckets = history.map(({ bucketStart, sent, failed }) => ({
    bucketStart: dayjs(bucketStart).unix(), sent, failed,
  }));
  const latestBuckets = activeBuckets.slice(-LATEST_HOURS_SHOWN).reverse();

  const sent = history.reduce((acc, bucket) => acc + bucket.sent, 0);
  const failed = history.reduce((acc, bucket) => acc + bucket.failed, 0);
  const lastAlert = activeBuckets.at(-1);
  const lastAlertLabel = lastAlert ? hoursAgo(lastAlert.bucketStart) : 'none';
  const failedClassName = failed > 0 ? 'text-[var(--coo-error)]' : '';
  const latestHours = latestBuckets.map((bucket) => <LatestHour key={bucket.bucketStart} bucket={bucket} />);

  return (
    <div className="flex flex-col gap-3 pr-4">
      <div className="flex gap-8">
        <Stat label="Sent" value={sent} />

        <Stat className={failedClassName} label="Failed" value={failed} />

        <Stat label="Last alert" value={lastAlertLabel} />
      </div>

      <HistoryChart buckets={buckets} />

      <div className="flex flex-col">
        <span className="text-xs text-[var(--coo-text-color-secondary)] pb-1">Latest hours with alerts</span>

        {latestHours}
      </div>
    </div>
  );
}

function HistoryChart({ buckets }) {
  const chartRef = useRef(null);

  const handleOnChartReady = () => {
    updateTheme(chartRef);
  };

  useDarkModeChart(chartRef);

  return (
    <ReactEChartsCore
      echarts={echarts}
      notMerge
      onChartReady={handleOnChartReady}
      option={option({ buckets })}
      ref={chartRef}
      style={chartStyle}
    />
  );
}

function Stat({ label, value, className = '' }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-[var(--coo-text-color-secondary)]">{label}</span>

      <span className={`text-xl font-[var(--coo-font-weight-bold)] ${className}`}>{value}</span>
    </div>
  );
}

function LatestHour({ bucket: { bucketStart, sent, failed } }) {
  const failedLabel = failed > 0
    ? <span className="text-[var(--coo-error)] font-[var(--coo-font-weight-bold)]">{`, ${failed} failed`}</span>
    : false;

  return (
    <div className="flex justify-between py-1 border-b border-[var(--coo-secondary-04)]">
      <span>{dayjs.unix(bucketStart).format('ddd DD MMM, HH:mm')}</span>

      <span>
        {`${sent} sent`}

        {failedLabel}
      </span>
    </div>
  );
}

function IsEmpty() {
  return <span className="text-[var(--coo-text-color-secondary)]">No alerts in the last 48 hours.</span>;
}

function IsError({ isFetching, refetch }) {
  return (
    <Void
      actions={<Button loading={isFetching} onClick={refetch}>Retry</Button>}
      description="This might be temporary, please retry later"
      image={<Lucide icon={TriangleAlert} />}
      title="Unable to load the alert history"
    />
  );
}

export default AlertHistory;
