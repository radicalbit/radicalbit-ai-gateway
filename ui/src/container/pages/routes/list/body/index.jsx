import { DETAIL_LAYOUT_CONFIGURATION, MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import usePersistQueryParams from '@Hooks/use-persistence-query-params';
import { DEFAULT_POLLING_INTERVAL, SEARCH_PARAMS } from '@Src/constants';
import {
  useGetEventsByRouteWithRange,
  useGetMetricsWithRange, useGetRouteByNameWithRange, useGetRoutesWithRange,
} from '@Src/store/state/routes/vertical-hooks';
import { faCircleXmark } from '@fortawesome/free-solid-svg-icons';
import {
  FontAwesomeIcon, FormField, Search, Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  useParams, useSearchParams,
} from 'react-router-dom';
import Metrics from './metrics';
import ProjectFilter from './project-filter';
import RoutesTable from './table';
import VerticalResizableDivider from './vertical-resizable-divider';

function RoutesList() {
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
      <div className="flex flex-row items-center gap-4">
        <FormField label="Project">
          <ProjectFilter />
        </FormField>
      </div>

      <Void description="Select a project to view routes" />
    </div>
  );
}

function ProjectSelected() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.routes) || '';

  usePollingGetRoutes();
  usePollingGetRouteByName();
  usePollingGetMetrics();
  usePollingGetEventsByRoute();

  const handleSearchChange = (e) => {
    const { value } = e.target;
    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.routes, value);
      } else {
        prev.delete(SEARCH_PARAMS.routes);
      }
      return prev;
    });
  };

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-4">
        <Metrics />

        <div className="flex flex-row items-end gap-4">
          <FormField label="Project">
            <ProjectFilter />
          </FormField>

          <Search
            allowClear={{ clearIcon: <FontAwesomeIcon icon={faCircleXmark} /> }}
            onChange={handleSearchChange}
            placeholder="Search routes by name"
            style={{ width: '350px' }}
            suffix={<RoutesCount searchValue={searchValue} />}
            value={searchValue}
          />
        </div>

        <RoutesTable searchValue={searchValue} />
      </div>

      <VerticalResizableDivider />
    </div>
  );
}

function RoutesCount({ searchValue }) {
  const { data = [], isSuccess } = useGetRoutesWithRange();
  const filteredData = searchValue
    ? data.filter(({ routeName }) => routeName.toLowerCase().includes(searchValue.toLowerCase()))
    : data;
  const count = filteredData.length;

  if (!isSuccess) {
    return false;
  }

  if (count === 1) {
    return (
      <div className="flex items-center">
        {`${count} Route`}
      </div>
    );
  }

  return (
    <div className="flex items-center">
      {`${count} Routes`}
    </div>
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();
  const { name } = useParams();

  useEffect(() => {
    if (!name) {
      MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    } else {
      DETAIL_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    }
  }, [dispatch, name]);
};

/** Polling for demo */
const usePollingGetRoutes = () => {
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);

  const { isError } = useGetRoutesWithRange({ pollingInterval });

  useEffect(() => {
    if (isError) {
      setPollingInterval(0);
    } else {
      setPollingInterval(DEFAULT_POLLING_INTERVAL);
    }
  }, [isError]);
};

const usePollingGetRouteByName = () => {
  const { name } = useParams();
  const [pollingInterval, setPollingInterval] = useState(2000);

  const { isError } = useGetRouteByNameWithRange(name, { skip: !name, pollingInterval });

  useEffect(() => {
    if (isError) {
      setPollingInterval(0);
    } else {
      setPollingInterval(DEFAULT_POLLING_INTERVAL);
    }
  }, [isError]);
};

const usePollingGetMetrics = () => {
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);

  const { isError } = useGetMetricsWithRange({ pollingInterval });

  useEffect(() => {
    if (isError) {
      setPollingInterval(0);
    } else {
      setPollingInterval(DEFAULT_POLLING_INTERVAL);
    }
  }, [isError]);
};

const usePollingGetEventsByRoute = () => {
  const { name } = useParams();
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);

  const { isError } = useGetEventsByRouteWithRange(name, { skip: !name, pollingInterval });

  useEffect(() => {
    if (isError) {
      setPollingInterval(0);
    } else {
      setPollingInterval(DEFAULT_POLLING_INTERVAL);
    }
  }, [isError]);
};

export default RoutesList;
