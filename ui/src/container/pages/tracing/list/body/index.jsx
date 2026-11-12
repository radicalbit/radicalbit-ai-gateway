import Lucide from '@Components/lucide';
import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import usePersistProjectUuid from '@Hooks/use-persist-project-uuid';
import usePersistQueryParams from '@Hooks/use-persistence-query-params';
import { Tabs, Void } from '@radicalbit/radicalbit-design-system';
import { FolderOpen } from 'lucide-react';
import { useEffect, useId, useRef } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import Dashboard from './dashboard';
import Filters from './filters';
import ProjectFilter from './project-filter';
import Requests from './requests';
import './_styles.less';

const PERSISTED_KEYS = ['routes', 'requestType', 'preset', 'from', 'to'];
const STORAGE_KEY = 'rbit-gw-tracing';

const TRACING_LIST_TABS = {
  dashboard: {
    key: 'dashboard',
    label: 'Dashboard',
  },
  requests: {
    key: 'requests',
    label: 'Requests',
  },
};

const TAB_KEYS = Object.keys(TRACING_LIST_TABS);

const items = [
  {
    key: TRACING_LIST_TABS.dashboard.key,
    label: TRACING_LIST_TABS.dashboard.label,
  },
  {
    key: TRACING_LIST_TABS.requests.key,
    label: TRACING_LIST_TABS.requests.label,
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
        description="Select a project to view its requests"
        image={<Lucide icon={FolderOpen} />}
        title="No project selected"
      />
    </div>
  );
}

function ProjectSelected() {
  const containerRef = useRef(null);
  const filtersRef = useRef(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab');
  const activeKey = TAB_KEYS.includes(tab) ? tab : TRACING_LIST_TABS.dashboard.key;

  const handleOnChange = (key) => {
    searchParams.set('tab', key);
    setSearchParams(searchParams);
  };

  useStickyFiltersSize(containerRef, filtersRef);

  if (activeKey === TRACING_LIST_TABS.requests.key) {
    return (
      <div className="flex flex-col gap-5" ref={containerRef}>
        <div className="c-observability__filters flex flex-col gap-5" ref={filtersRef}>
          <Tabs activeKey={activeKey} items={items} onChange={handleOnChange} />

          <Filters />
        </div>

        <Requests />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5" ref={containerRef}>
      <div className="c-observability__filters flex flex-col gap-5" ref={filtersRef}>
        <Tabs activeKey={activeKey} items={items} onChange={handleOnChange} />

        <Filters />
      </div>

      <Dashboard />
    </div>
  );
}

function useStickyFiltersSize(containerRef, filtersRef) {
  useEffect(() => {
    const container = containerRef.current;
    const filters = filtersRef.current;
    const scroller = container?.closest('.ant-layout-content');

    if (!container || !filters || !scroller) {
      return undefined;
    }

    const handleOnResize = () => {
      container.style.setProperty('--observability-filters-height', `${filters.offsetHeight}px`);
      container.style.setProperty('--observability-viewport-height', `${scroller.clientHeight}px`);
    };

    const observer = new ResizeObserver(handleOnResize);

    observer.observe(filters);
    observer.observe(scroller);

    return () => observer.disconnect();
  }, [containerRef, filtersRef]);
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default TracingList;
