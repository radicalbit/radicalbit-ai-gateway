import Lucide from '@Components/lucide';
import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  formatCount, formatLimitValue, formatLimitWindow, sortLimits,
} from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button, DataTable, Dropdown, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical, Plus } from 'lucide-react';
import Conflicts from './conflicts';
import DeleteBudget from './delete-budget';
import { ScreenEnum } from './schema';

const NO_BUDGET_MESSAGE = 'This project has no budget: spending is capped only by route and credential budgets, if any.';

const BLOCKED_TOOLTIP = 'Routes of the published configuration have their own budget';

const getRowKey = ({ uuid }) => uuid;

const getRowClassName = () => DataTable.ROW_NOT_CLICKABLE;

const columns = [
  {
    title: '',
    key: 'window',
    render: (_, limit) => <Window limit={limit} />,
  },
  {
    title: '',
    key: 'value',
    align: 'right',
    render: (_, { value }) => formatLimitValue(LimitCategoryEnum.BUDGET, value),
  },
  {
    title: '',
    key: 'actions',
    width: '50px',
    render: (_, limit) => <Actions limit={limit} />,
  },
];

function ListScreen() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { write } = useFormbitContext();

  const { data } = useGetProjectQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];
  const isBlocked = (data?.routeBudgets?.published ?? []).length > 0;

  const handleOnAdd = () => {
    write('__metadata.screen', ScreenEnum.ADD);
  };

  const addButton = (
    <Button disabled={isBlocked} onClick={handleOnAdd} prefix={<Lucide icon={Plus} />} type="secondary">Add budget</Button>
  );
  const addAction = isBlocked ? <Tooltip title={BLOCKED_TOOLTIP}><span>{addButton}</span></Tooltip> : addButton;
  const count = limits.length ? formatCount(limits.length, 'budget') : 'No budget';
  const sortedLimits = sortLimits(limits);
  const content = limits.length ? (
    <DataTable
      columns={columns}
      dataSource={sortedLimits}
      pagination={false}
      rowClassName={getRowClassName}
      rowKey={getRowKey}
      showHeader={false}
      size="small"
    />
  ) : <span className="opacity-70">{NO_BUDGET_MESSAGE}</span>;

  return (
    <div className="flex flex-col gap-4">
      <Conflicts />

      <div className="flex items-center justify-between">
        <strong>{count}</strong>

        {addAction}
      </div>

      {content}
    </div>
  );
}

function Window({ limit }) {
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[limit?.algorithm]} window`;

  return (
    <span>
      {formatLimitWindow(limit?.windowSize)}

      <span className="opacity-70">{windowTypeText}</span>
    </span>
  );
}

function Actions({ limit }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  const items = [{ key: 'delete', label: <DeleteBudget limit={limit} /> }];

  return (
    <Dropdown menu={{ items }}>
      <Button aria-label="More actions" onClick={handleOnClick} type="text">
        <Lucide icon={EllipsisVertical} />
      </Button>
    </Dropdown>
  );
}

export default ListScreen;
