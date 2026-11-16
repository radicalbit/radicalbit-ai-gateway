import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  formatLimitValue, formatLimitWindow, formatResetsIn, sortLimits,
} from '@Components/limits/helpers';
import useNowSeconds from '@Components/limits/use-now-seconds';
import Lucide from '@Components/lucide';
import formatUsd from '@Helpers/format-usd';
import { numberFormatterInt } from '@Src/constants';
import { useProjectBudgetLimitsConsumption } from '@State/projects/hooks';
import { useGetProjectBudgetWithRange } from '@State/usage/vertical-hooks';
import {
  BarChart, Board, Button, DataTable, NewHeader, SectionTitle, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { filterBudgetsByStatus, formatNoBudgetMatches, parseWindowStatuses } from './helpers';
import LivePin from './live-pin';

const EMPTY_VALUE = '--';

const STATUS_TO_TYPE = {
  ok: 'success',
  warning: 'warning',
  critical: 'error',
};

const getRowKey = ({ uuid }) => uuid;

const getRowClassName = () => DataTable.ROW_NOT_CLICKABLE;

const COLUMNS = [
  {
    title: 'Budget',
    key: 'budget',
    render: (_, limit) => <Budget limit={limit} />,
  },
  {
    title: 'Consumption',
    key: 'consumption',
    width: '30%',
    render: (_, limit) => <Consumption limit={limit} />,
  },
  {
    title: 'Spent',
    key: 'spent',
    render: (_, limit) => <Spent limit={limit} />,
  },
  {
    title: 'Resets',
    key: 'resets',
    render: (_, limit) => <Resets limit={limit} />,
  },
];

function ProjectBudget() {
  return (
    <Board
      header={(
        <NewHeader
          padding="none"
          title={<SectionTitle subtitle="Shared by every route in this project" title="Project budget" titleSuffix={<LivePin />} />}
        />
      )}
      headerProps={{ divider: true, padding: 'compact' }}
      main={<Content />}
      width="100%"
    />
  );
}

function Content() {
  const { data, isError, isLoading, isSuccess } = useGetProjectBudgetWithRange();
  const limits = data?.limits ?? [];

  if (isLoading) {
    return <Skeleton active />;
  }

  if (isError) {
    return <IsError />;
  }

  if (!limits.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess />;
}

function IsError() {
  const { isFetching, refetch } = useGetProjectBudgetWithRange();

  const handleOnRetry = () => {
    refetch();
  };

  return (
    <Void
      actions={<Button loading={isFetching} onClick={handleOnRetry}>Retry</Button>}
      description={(
        <>
          This might be temporary
          <br />
          please retry later
        </>
      )}
      image={<Lucide icon={TriangleAlert} />}
      size="small"
      title="Unable to load the project budget"
    />
  );
}

function IsEmpty() {
  return <Void description="Spending in this project has no cap of its own. Route and credential limits still apply." size="small" title="This project has no budget" />;
}

function IsSuccess() {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const { data } = useGetProjectBudgetWithRange();
  const limits = data?.limits ?? [];

  const consumption = useProjectBudgetLimitsConsumption([projectUuid]);

  const visibleLimits = sortLimits(filterBudgetsByStatus({ limits, consumption, windowStatuses }));

  if (!visibleLimits.length) {
    return <NoMatch />;
  }

  return (
    <DataTable
      columns={COLUMNS}
      dataSource={visibleLimits}
      noPadding
      pagination={false}
      rowClassName={getRowClassName}
      rowKey={getRowKey}
      size="small"
    />
  );
}

function NoMatch() {
  const [searchParams] = useSearchParams();
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const { data } = useGetProjectBudgetWithRange();
  const limits = data?.limits ?? [];

  const description = formatNoBudgetMatches({ count: limits.length, windowStatuses });

  return <Void description={description} size="small" title="No budget matches the filter" />;
}

function Budget({ limit }) {
  const algorithm = limit?.algorithm;
  const value = limit?.value;
  const windowSize = limit?.windowSize;

  const maxText = `${formatLimitValue(LimitCategoryEnum.BUDGET, value)} / ${formatLimitWindow(windowSize)}`;
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[algorithm]}`;

  return (
    <span>
      {maxText}

      <span className="opacity-70">{windowTypeText}</span>
    </span>
  );
}

function Consumption({ limit }) {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const consumption = useProjectBudgetLimitsConsumption([projectUuid]);

  const uuid = limit?.uuid;
  const bar = consumption?.[uuid];
  const windowFilledPercentage = bar?.windowFilledPercentage;
  const windowStatus = bar?.windowStatus;

  const percentage = numberFormatterInt(windowFilledPercentage);

  if (!bar) {
    return EMPTY_VALUE;
  }

  return (
    <div className="flex flex-row gap-2 items-center">
      <BarChart className="w-full" type={STATUS_TO_TYPE[windowStatus]} value={percentage} />

      <small className="min-w-10 text-right">{`${percentage}%`}</small>
    </div>
  );
}

function Spent({ limit }) {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const consumption = useProjectBudgetLimitsConsumption([projectUuid]);

  const uuid = limit?.uuid;
  const bar = consumption?.[uuid];
  const windowFilledSize = bar?.windowFilledSize;

  if (!bar) {
    return EMPTY_VALUE;
  }

  return formatUsd(windowFilledSize);
}

function Resets({ limit }) {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const now = useNowSeconds();

  const consumption = useProjectBudgetLimitsConsumption([projectUuid]);

  const algorithm = limit?.algorithm;
  const uuid = limit?.uuid;
  const bar = consumption?.[uuid];

  const resetsIn = formatResetsIn({ algorithm, bar, now });

  if (!resetsIn) {
    return EMPTY_VALUE;
  }

  return `${resetsIn.charAt(0).toUpperCase()}${resetsIn.slice(1)}`;
}

export default ProjectBudget;
