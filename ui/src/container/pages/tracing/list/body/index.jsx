import Lucide from '@Components/lucide';
import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import usePersistProjectUuid from '@Hooks/use-persist-project-uuid';
import usePersistQueryParams from '@Hooks/use-persistence-query-params';
import { Tabs, Void } from '@radicalbit/radicalbit-design-system';
import { FolderOpen } from 'lucide-react';
import { useEffect, useId } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import Dashboard from './dashboard';
import Filters from './filters';
import ProjectFilter from './project-filter';
import Tracing from './tracing';

const PERSISTED_KEYS = ['routes', 'requestType', 'preset', 'from', 'to'];
const STORAGE_KEY = 'rbit-gw-tracing';

const TRACING_LIST_TABS = {
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

  usePersistProjectUuid();

  usePersistQueryParams(PERSISTED_KEYS, STORAGE_KEY);

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  if (!projectUuid) {
    return <NoProjectSelected />;
  }

  return <ProjectSelected />;
}

function NoProjectSelected() {
  const projectId = useId();

  return (
    <div className="flex justify-center items-center h-full">
      <Void
        actions={<ProjectFilter id={projectId} />}
        description="Select a project to view tracing data"
        image={<Lucide icon={FolderOpen} />}
        title="No project selected"
      />
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
    <>
      <Tabs
        activeKey={activeKey}
        items={items}
        onChange={handleOnChange}
        sticky
      />

      <Filters />

      {activeKey === 'dashboard' && <Dashboard />}

      {activeKey === 'tracing' && <Tracing />}
    </>
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default TracingList;
