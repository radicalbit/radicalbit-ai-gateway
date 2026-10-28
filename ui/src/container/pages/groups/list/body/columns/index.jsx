import Lucide from '@Components/lucide';
import TableRowLink from '@Components/table-row-link';
import { useGetThreeDotsMenuItems } from '@Container/pages/groups/detail/header/three-dots-menu';
import { DATE_FORMAT, PathsEnum } from '@Src/constants';
import {
  Button, DataTableAction, Dropdown, RelativeDateTime, Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import Keys from './keys';
import Routes from './routes';

const columns = [
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
  {
    title: 'Name',
    dataIndex: 'name',
    key: 'name',
    render: (value, { uuid }) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <TableRowLink keepSearch to={`/${PathsEnum.GROUPS}/${uuid}`}>
          <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
        </TableRowLink>
      </Truncate>
    ),
  },
  {
    title: 'Owner',
    dataIndex: 'owner',
    key: 'owner',
  },
  {
    title: 'Routes',
    dataIndex: 'routes',
    key: 'routes',
    align: 'center',
    render: (routes) => <Routes routes={routes} />,
  },
  {
    title: 'Credentials',
    dataIndex: 'keys',
    key: 'keys',
    align: 'center',
    render: (keys) => <Keys keys={keys} />,
  },
  {
    title: 'Created',
    dataIndex: 'createdAt',
    key: 'createdAt',
    align: 'right',
    sorter: (a, b) => a.createdAt.localeCompare(b.createdAt),
    defaultSortOrder: 'descend',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    key: 'updatedAt',
    align: 'right',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: '',
    dataIndex: 'uuid',
    key: 'actions',
    width: '50px',
    render: (uuid) => <DataTableAction noHide><Actions uuid={uuid} /></DataTableAction>,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

function Actions({ uuid }) {
  const items = useGetThreeDotsMenuItems(uuid);

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!items.length) {
    return false;
  }

  return (
    <Tooltip title="More actions">
      <Dropdown menu={{ items }}>
        <Button aria-label="More actions" onClick={handleOnClick} type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </Tooltip>
  );
}

export default columns;
