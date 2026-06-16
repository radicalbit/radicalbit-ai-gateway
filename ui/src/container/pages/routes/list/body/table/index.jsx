import Logo from '@Img/logo.png';
import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { Popup, usePopup } from '@Components/popup';
import { useGetThreeDotsMenuItems } from '@Container/pages/routes/detail/header/three-dots-menu';
import { PathsEnum } from '@Src/constants.js';
import { useGetRoutesWithRange } from '@Src/store/state/routes/vertical-hooks';
import { useAddGroupsToRouteMutation } from '@State/routes/api';
import {
  Board,
  DataTable,
  Spin,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate, useParams } from 'react-router-dom';
import columns from './columns';

function RoutesTable({ searchValue }) {
  const { popup, openPopup, closePopup } = usePopup();
  const items = useGetThreeDotsMenuItems(popup?.record?.routeName);

  const navigate = useNavigate();
  const { name } = useParams();

  const {
    data, error, isLoading, isError, isSuccess, refetch,
  } = useGetRoutesWithRange();

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError error={error} refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  const handleOnRowClick = (record) => {
    const { search } = window.location;
    navigate(`/${PathsEnum.ROUTES}/${record.routeName}${search}`);
  };

  const filteredData = searchValue
    ? data.filter(({ routeName }) => routeName.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  const components = { body: { row: RowWithSpinner } };

  return (
    <>
      <DataTable
        clickable
        columns={columns.filter(({ hide }) => !hide)}
        components={components}
        dataSource={filteredData}
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
        rowClassName={({ routeName }) => routeName === name ? DataTable.ROW_PRIMARY_LIGHT : undefined}
        rowKey={({ routeName }) => routeName}
        scroll={{ y: 'calc(100vh - 10rem)', x: '100vh' }}
      />

      <Popup
        items={items}
        onClose={closePopup}
        {...popup}
      />
    </>
  );
}

function RowWithSpinner({ children, ...other }) {
  const [, { isLoading: isAddingGroups }] = useAddGroupsToRouteMutation({ fixedCacheKey: `add-groups-to-route-${other['data-row-key']}` });

  return (isAddingGroups) ? (
    <tr {...other}>
      {/* IF scroll={{ y: 'calc(100vh - 10rem)' }} is defined, colSpan must be === columns.length */}
      <td colSpan={12}>
        <Spin spinning />
      </td>
    </tr>
  ) : (
    <tr {...other}>{children}</tr>
  );
}

function IsLoading() {
  return (
    <DataTable
      dataSource={[]}
      loading
      pagination={{
        hideOnSinglePage: true,
      }}
      scroll={{ y: 'calc(100vh - 10rem)', x: '100vh' }}
    />
  );
}

function IsError({ error, refetch }) {
  if (error?.status === 404) {
    return (
      <Board
        main={(
          <Void
            description="This project has no routes yet."
            image={<img alt="Logo" src={Logo} />}
            style={{ height: '50vh' }}
            title="No routes"
          />
        )}
      />
    );
  }

  return (
    <Board
      main={<SomethingWentWrong refetch={refetch} style={{ height: '50vh' }} />}
    />
  );
}

export default RoutesTable;
