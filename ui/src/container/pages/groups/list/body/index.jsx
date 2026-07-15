import { Popup, usePopup } from '@Components/popup';
import { DETAIL_LAYOUT_CONFIGURATION, MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetThreeDotsMenuItems } from '@Container/pages/groups/detail/header/three-dots-menu';
import useModals, { modals } from '@Hooks/use-modals';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  useGetGroupsQuery,
  useEditGroupMutation,
  useDeleteGroupMutation,
  useAddKeysToGroupMutation,
  useAddRoutesToGroupMutation,
} from '@State/groups/api';
import {
  faCircleXmark, faInbox, faPlus, faWarning,
} from '@fortawesome/free-solid-svg-icons';
import {
  Board, Button, DataTable, FontAwesomeIcon, Search, Spin, Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import columns from './columns';
import VerticalResizableDivider from './vertical-resizable-divider';

function GroupsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.groups) || '';

  const handleSearchChange = (e) => {
    const { value } = e.target;
    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.groups, value);
      } else {
        prev.delete(SEARCH_PARAMS.groups);
      }
      return prev;
    });
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex flex-row items-center gap-4">
        <Search
          allowClear={{ clearIcon: <FontAwesomeIcon icon={faCircleXmark} /> }}
          onChange={handleSearchChange}
          placeholder="Search groups by name"
          style={{ width: '300px' }}
          value={searchValue}
        />

        <GroupsCount searchValue={searchValue} />
      </div>

      <GroupsTable searchValue={searchValue} />
    </div>
  );
}

function GroupsCount({ searchValue }) {
  const { data = [], isSuccess } = useGetGroupsQuery();
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
        {`${count} Group`}
      </div>
    );
  }

  return (
    <div className="flex items-center">
      {`${count} Groups`}
    </div>
  );
}

function GroupsTable({ searchValue }) {
  const { popup, openPopup, closePopup } = usePopup();
  const items = useGetThreeDotsMenuItems(popup?.record?.uuid);

  const navigate = useNavigate();
  const { uuid } = useParams();

  const { data = [], isLoading, isError, isSuccess, refetch } = useGetGroupsQuery();

  useInitLayoutConfigurations();

  if (isError) {
    return (
      <div className="flex justify-center h-full">
        <IsError refetch={refetch} />
      </div>
    );
  }

  if (!isSuccess) {
    return false;
  }

  if (data.length === 0) {
    return (
      <div className="flex justify-center h-full">
        <IsEmpty />
      </div>
    );
  }

  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  const handleOnRowClick = (record) => {
    const { search } = window.location;
    navigate(`/${PathsEnum.GROUPS}/${record.uuid}${search}`);
  };

  const components = { body: { row: RowWithSpinner } };

  return (
    <>
      <DataTable
        clickable
        columns={columns}
        components={components}
        dataSource={filteredData}
        loading={isLoading}
        onRow={(record) => ({
          onClick: () => {
            handleOnRowClick(record);
          },
          onContextMenu: (event) => {
            openPopup(event, record);
          },
        })}
        pagination={{
          hideOnSinglePage: true,
        }}
        rowClassName={({ uuid: groupUUID }) => groupUUID === uuid ? DataTable.ROW_PRIMARY_LIGHT : undefined}
        rowKey={({ uuid: groupUUID }) => groupUUID}
        scroll={{ y: 'calc(100vh - 10rem)', x: '100vh' }}
      />

      <Popup
        items={items}
        onClose={closePopup}
        {...popup}
      />

      <VerticalResizableDivider />
    </>
  );
}

function RowWithSpinner({ children, ...other }) {
  const [, { isLoading: isEditing }] = useEditGroupMutation({ fixedCacheKey: `edit-group-${other['data-row-key']}` });
  const [, { isLoading: isDeleting }] = useDeleteGroupMutation({ fixedCacheKey: `delete-group-${other['data-row-key']}` });
  const [, { isLoading: isAddingKeys }] = useAddKeysToGroupMutation({ fixedCacheKey: `add-keys-to-groups-${other['data-row-key']}` });
  const [, { isLoading: isAddingRoutes }] = useAddRoutesToGroupMutation({ fixedCacheKey: `add-routes-to-groups-${other['data-row-key']}` });

  return isDeleting || isEditing || isAddingKeys || isAddingRoutes
    ? (
      <tr {...other}>
        {/* IF scroll={{ y: 'calc(100vh - 10rem)' }} is defined, colSpan must be === columns.length */}
        <td colSpan={7}>
          <Spin spinning />
        </td>
      </tr>
    )
    : <tr {...other}>{children}</tr>;
}

function IsEmpty() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_GROUPS);
  };

  return (
    <Board
      main={(
        <Void
          actions={<Button onClick={handleOnClick} prefix={<FontAwesomeIcon icon={faPlus} />} type="primary">Create groups</Button>}
          description={(
            <>
              Looks like you have to create you’re first group.
              <br />
              Each group can be associated with routes and keys
            </>
          )}
          image={<FontAwesomeIcon icon={faInbox} />}
          title="Groups"
        />
      )}
      width="100%"
    />
  );
}

function IsError({ refetch }) {
  return (
    <Board
      main={(
        <Void
          actions={<Button onClick={refetch}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<FontAwesomeIcon icon={faWarning} />}
          title="Unable to load groups"
        />
      )}
      width="100%"
    />
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();
  const { uuid } = useParams();

  useEffect(() => {
    if (!uuid) {
      MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    } else {
      DETAIL_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    }
  }, [dispatch, uuid]);
};

export default GroupsList;
