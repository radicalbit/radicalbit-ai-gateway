import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import usePersistQueryParams from '@Hooks/use-persistence-query-params';
import { Tabs, Void } from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import Dashboard from './dashboard';
import Tracing from './tracing';

export const TRACING_LIST_TABS = {
  dashboard: {
    key: 'dashboard',
    label: 'Dashboard',
  },
  tracing: {
    key: 'tracing',
    label: 'Tracing',
  },
};

const items = [
  {
    key: TRACING_LIST_TABS.dashboard.key,
    label: TRACING_LIST_TABS.dashboard.label,
  },
  {
    key: TRACING_LIST_TABS.tracing.key,
    label: TRACING_LIST_TABS.tracing.label,
  },
];

function TracingList() {
  useInitLayoutConfigurations();

  usePersistQueryParams(['projectUuid'], 'rbit-gw');

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  if (!projectUuid) {
    return <NoProjectSelected />;
  }

  return <ProjectSelected />;
}

function NoProjectSelected() {
  return (
    <div className="flex flex-col gap-4 p-4">
      <Void description="Select a project to view tracing data" />
    </div>
  );
}

function ProjectSelected() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeKey = searchParams.get('tab') ?? 'dashboard';

  const handleOnChange = (key) => {
    searchParams.set('tab', key);
    setSearchParams(searchParams);
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <Tabs
        activeKey={activeKey}
        items={items}
        onChange={handleOnChange}
        sticky
      />

      {activeKey === 'dashboard' && <Dashboard />}

      {activeKey === 'tracing' && <Tracing />}
    </div>
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default TracingList;
