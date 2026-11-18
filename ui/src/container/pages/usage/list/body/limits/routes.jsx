import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetLimitsStreamWithRange, useGetProjectBudgetWithRange } from '@State/usage/vertical-hooks';
import {
  Board, Button, DataTable, NewHeader, SectionTitle, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';
import { formatNoRouteMatches, parseWindowStatuses } from './helpers';
import LivePin from './live-pin';

const getRowKey = ({ routeName }) => routeName;

const getRowClassName = () => DataTable.ROW_NOT_CLICKABLE;

function Routes() {
  return (
    <Board
      header={<NewHeader details={{ one: <OpenConfiguration /> }} padding="none" title={<SectionTitle title="Routes" titleSuffix={<LivePin />} />} />}
      headerProps={{ divider: true, padding: 'compact' }}
      main={<Content />}
      width="100%"
    />
  );
}

function Content() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const { data } = useGetLimitsStreamWithRange({ routes, windowStatuses });
  const isSseLoading = data?.isSseLoading;
  const isSseError = data?.isSseError;
  const isSseSuccess = data?.isSseSuccess;
  const limits = data?.limits ?? [];

  const isFilteredOut = !limits.length && windowStatuses.length > 0;

  if (isSseLoading) {
    return <Skeleton active />;
  }

  if (isSseError) {
    return <IsError />;
  }

  if (isFilteredOut) {
    return <NoMatch />;
  }

  if (!limits.length) {
    return <IsEmpty />;
  }

  if (!isSseSuccess) {
    return false;
  }

  return <IsSuccess />;
}

function IsError() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const { isFetching, refetch } = useGetLimitsStreamWithRange({ routes, windowStatuses });

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
      title="Unable to load usage data"
    />
  );
}

function OpenConfiguration() {
  const { showModal } = useModals();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const { data } = useGetLimitsStreamWithRange({ routes, windowStatuses });
  const limits = data?.limits ?? [];

  const { data: budgetData } = useGetProjectBudgetWithRange();
  const servedConfigUuid = budgetData?.servedConfigUuid;

  const handleOnOpen = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid: projectUuid, activeConfigUuid: servedConfigUuid });
  };

  if (!limits.length && !windowStatuses.length) {
    return false;
  }

  return <Button onClick={handleOnOpen}>Open configuration</Button>;
}

function IsEmpty() {
  const { showModal } = useModals();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data } = useGetProjectBudgetWithRange();
  const servedConfigUuid = data?.servedConfigUuid;

  const handleOnOpen = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid: projectUuid, activeConfigUuid: servedConfigUuid });
  };

  return (
    <Void
      actions={<Button onClick={handleOnOpen}>Open configuration</Button>}
      description="Publish a configuration with routes to see their limits."
      size="small"
      title="This project has no routes"
    />
  );
}

function NoMatch() {
  const [searchParams] = useSearchParams();
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const description = formatNoRouteMatches(windowStatuses);

  return <Void description={description} size="small" title="No route matches the filter" />;
}

function IsSuccess() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];
  const windowStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const { data } = useGetLimitsStreamWithRange({ routes, windowStatuses });
  const limits = data?.limits ?? [];

  return (
    <DataTable
      columns={columns}
      dataSource={limits}
      noPadding
      pagination={false}
      rowClassName={getRowClassName}
      rowKey={getRowKey}
      size="small"
    />
  );
}

export default Routes;
