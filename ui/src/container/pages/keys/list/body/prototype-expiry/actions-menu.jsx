// PROTOTYPE (AG-1034) — throwaway. Cells shared by every variant: the row three-dots menu
// (same shape as projects/list/body/columns.jsx) and the Associated Group link.
import HtmlAnchor from '@Components/html-anchor';
import Lucide from '@Components/lucide';
import { useGetThreeDotsMenuItems } from '@Container/pages/keys/three-dots-menu';
import { DATE_FORMAT, PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  Button,
  DataTableAction,
  Dropdown,
  RelativeDateTime,
  Tooltip,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export function Actions({ uuid }) {
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

export function AssociatedGroup({ group }) {
  const navigate = useNavigate();

  if (!group?.name) {
    return '--';
  }

  const handleOnClick = (e) => {
    e.stopPropagation();
    navigate(`/${PathsEnum.GROUPS}/${group.uuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(group.name)}`);
  };

  return <HtmlAnchor onClick={handleOnClick}>{group.name}</HtmlAnchor>;
}

export const marginColumn = (key) => ({ title: '', dataIndex: key, key, width: '10px' });

export const nameColumn = {
  title: 'Name',
  dataIndex: 'name',
  key: 'id',
  render: (value) => (
    <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
      <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
    </Truncate>
  ),
};

export const ownerColumn = { title: 'Owner', dataIndex: 'owner', key: 'owner' };

export const groupColumn = {
  title: 'Associated Group',
  dataIndex: 'group',
  key: 'group',
  align: 'center',
  render: (group) => <AssociatedGroup group={group} />,
};

export const createdColumn = {
  title: 'Created',
  dataIndex: 'createdAt',
  key: 'createdAt',
  align: 'right',
  sorter: (a, b) => a.createdAt.localeCompare(b.createdAt),
  defaultSortOrder: 'descend',
  render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
};

export const updatedColumn = {
  title: 'Updated',
  dataIndex: 'updatedAt',
  key: 'updatedAt',
  align: 'right',
  render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
};

export const actionsColumn = {
  title: '',
  dataIndex: 'uuid',
  key: 'actions',
  width: '50px',
  render: (uuid) => <DataTableAction noHide><Actions uuid={uuid} /></DataTableAction>,
};
