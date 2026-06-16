import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { DETAIL_LAYOUT_CONFIGURATION, WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { CreateProjectButton } from '@Container/pages/projects/list/header';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  useApproveConfigMutation,
  useCancelApprovalMutation,
  useDeleteProjectMutation,
  useGetProjectsQuery,
  useServeConfigMutation,
  useUnserveConfigMutation,
} from '@State/projects/api';
import { faCircleXmark } from '@fortawesome/free-solid-svg-icons';
import {
  Board,
  DataTable,
  FontAwesomeIcon,
  Search,
  Spin,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect, useMemo } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import getColumns from './columns';
import VerticalResizableDivider from './vertical-resizable-divider';

function ProjectsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.projects) || '';

  const handleSearchChange = (e) => {
    const { value } = e.target;
    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.projects, value);
      } else {
        prev.delete(SEARCH_PARAMS.projects);
      }
      return prev;
    });
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex flex-row items-center gap-4 pl-4 pt-4">
        <Search
          allowClear={{ clearIcon: <FontAwesomeIcon icon={faCircleXmark} /> }}
          onChange={handleSearchChange}
          placeholder="Search projects by name"
          style={{ width: '300px' }}
          value={searchValue}
        />

        <ProjectsCount searchValue={searchValue} />
      </div>

      <ProjectsTable searchValue={searchValue} />
    </div>
  );
}

function ProjectsCount({ searchValue }) {
  const { data = [], isSuccess } = useGetProjectsQuery();
  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;
  const count = filteredData.length;

  if (!isSuccess) {
    return false;
  }

  if (count === 1) {
    return (
      <div className="flex items-center">
        {`${count} Project`}
      </div>
    );
  }

  return (
    <div className="flex items-center">
      {`${count} Projects`}
    </div>
  );
}

function ProjectsTable({ searchValue }) {
  useInitLayoutConfigurations();

  const { data = [], isError, isLoading, isSuccess } = useGetProjectsQuery();

  if (isLoading) {
    return <DataTable loading />;
  }

  if (isError) {
    return (
      <Board
        main={<SomethingWentWrong size="small" />}
      />
    );
  }

  if (!data?.length) {
    return (
      <Board
        borderType="none"
        main={(
          <Void
            description="No projects found."
            title="Projects"
          />
        )}
        suffix={<CreateProjectButton />}
      />
    );
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess searchValue={searchValue} />;
}

function IsSuccess({ searchValue }) {
  const navigate = useNavigate();
  const { uuid } = useParams();

  const { data = [] } = useGetProjectsQuery();

  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  const sortedData = useMemo(
    () => [...filteredData].sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? '')),
    [filteredData],
  );

  const columns = getColumns();

  const handleOnRowClick = (record) => {
    const { search } = window.location;
    navigate(`/${PathsEnum.PROJECTS}/${record.uuid}${search}`);
  };

  const components = useMemo(() => ({ body: { row: makeRowWithSpinner(columns.length) } }), [columns.length]);

  return (
    <>
      <DataTable
        clickable
        columns={columns}
        components={components}
        dataSource={sortedData}
        onRow={(record) => ({
          onClick: () => {
            handleOnRowClick(record);
          },
        })}
        pagination={{ hideOnSinglePage: true }}
        rowClassName={({ uuid: projectUUID }) => projectUUID === uuid ? DataTable.ROW_PRIMARY_LIGHT : undefined}
        rowKey={({ uuid: projectUUID }) => projectUUID}
        scroll={{ y: 'calc(100vh - 10rem)' }}
      />

      <VerticalResizableDivider />
    </>
  );
}

const makeRowWithSpinner = (colSpan) => function RowWithSpinner({ children, ...other }) {
  const rowKey = other['data-row-key'];

  const { data = [] } = useGetProjectsQuery();
  const project = data.find(({ uuid }) => uuid === rowKey);
  const configs = project?.configs ?? [];
  const configAUuid = configs[0]?.uuid;
  const configBUuid = configs[1]?.uuid;

  const isConfigABusy = useIsConfigBusy(configAUuid);
  const isConfigBBusy = useIsConfigBusy(configBUuid);

  const [, { isLoading: isDeleting }] = useDeleteProjectMutation({ fixedCacheKey: `delete-project-${rowKey}` });

  const isBusy = isConfigABusy || isConfigBBusy || isDeleting;

  if (isBusy) {
    return (
      <tr {...other}>
        <td colSpan={colSpan}>
          <Spin spinning />
        </td>
      </tr>
    );
  }

  return <tr {...other}>{children}</tr>;
};

const useIsConfigBusy = (configUuid) => {
  const [, { isLoading: isApproving }] = useApproveConfigMutation({ fixedCacheKey: `approve-config-${configUuid}` });
  const [, { isLoading: isCancelling }] = useCancelApprovalMutation({ fixedCacheKey: `cancel-approval-${configUuid}` });
  const [, { isLoading: isServing }] = useServeConfigMutation({ fixedCacheKey: `serve-config-${configUuid}` });
  const [, { isLoading: isUnserving }] = useUnserveConfigMutation({ fixedCacheKey: `unserve-config-${configUuid}` });

  return isApproving || isCancelling || isServing || isUnserving;
};

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();
  const { uuid } = useParams();

  useEffect(() => {
    if (!uuid) {
      WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    } else {
      DETAIL_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    }
  }, [dispatch, uuid]);
};

export default ProjectsList;
