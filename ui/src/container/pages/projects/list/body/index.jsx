import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { CreateProjectButton } from '@Container/pages/projects/list/header';
import { SEARCH_PARAMS } from '@Src/constants';
import { useGetProjectsQuery } from '@State/projects/api';
import { faCircleXmark } from '@fortawesome/free-solid-svg-icons';
import {
  Board,
  DataTable,
  FontAwesomeIcon,
  Search,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';

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
  const { data = [] } = useGetProjectsQuery();

  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  return (
    <DataTable
      columns={columns}
      dataSource={filteredData}
      pagination={{ hideOnSinglePage: true }}
      rowClassName={() => DataTable.ROW_NOT_CLICKABLE}
      rowKey={({ uuid: projectUUID }) => projectUUID}
      scroll={{ y: 'calc(100vh - 10rem)' }}
    />
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default ProjectsList;
