import Lucide from '@Components/lucide';
import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  formatCount, formatLimitValue, formatLimitWindow, sortLimits,
} from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetProjectBudgetQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Board, Button, DataTable, Dropdown, Tooltip, Void,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical, Plus } from 'lucide-react';
import { useRef, useState } from 'react';
import Conflicts from './conflicts';
import DeleteBudget from './delete-budget';
import { ScreenEnum } from './schema';

const MENU_TRIGGER = ['hover', 'click'];

const NO_BUDGET_TITLE = 'This project has no budget';

const NO_BUDGET_DESCRIPTION = 'Spending is capped only by route and credential budgets, if any.';

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

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];

  if (!limits.length) {
    return <IsEmpty />;
  }

  return <IsSuccess />;
}

function IsEmpty() {
  return (
    <div className="flex flex-col gap-6">
      <Conflicts />

      <Board
        main={<Void actions={<AddBudget />} description={NO_BUDGET_DESCRIPTION} size="small" title={NO_BUDGET_TITLE} />}
        width="100%"
      />
    </div>
  );
}

function IsSuccess() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];

  const count = formatCount(limits.length, 'budget');
  const sortedLimits = sortLimits(limits);

  return (
    <div className="flex flex-col gap-6">
      <Conflicts />

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <strong>{count}</strong>

          <AddBudget />
        </div>

        <DataTable
          columns={columns}
          dataSource={sortedLimits}
          pagination={false}
          rowClassName={getRowClassName}
          rowKey={getRowKey}
          showHeader={false}
          size="small"
        />
      </div>
    </div>
  );
}

function AddBudget() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { write } = useFormbitContext();

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const isBlocked = (data?.routeBudgets?.published ?? []).length > 0;

  const handleOnAdd = () => {
    write('__metadata.screen', ScreenEnum.ADD);
  };

  if (isBlocked) {
    return (
      <Tooltip title={BLOCKED_TOOLTIP}>
        <span>
          <Button disabled icon={<Lucide icon={Plus} />}>Add budgets</Button>
        </span>
      </Tooltip>
    );
  }

  return <Button icon={<Lucide icon={Plus} />} onClick={handleOnAdd}>Add budgets</Button>;
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
  const buttonRef = useRef(null);

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const handleOnOpenChange = (isOpen) => {
    const { activeElement } = document;
    const isFocusLost = activeElement === document.body || activeElement?.closest('.ant-dropdown');

    if (!isOpen) {
      setIsOpenedByKeyboard(false);
    }

    if (!isOpen && isFocusLost) {
      buttonRef.current?.focus();
    }
  };

  const handleOnKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      setIsOpenedByKeyboard(true);
    }
  };

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  const items = [{ key: 'delete', label: <DeleteBudget limit={limit} /> }];

  return (
    <span onClick={handleOnClick} role="presentation">
      <Dropdown autoFocus={isOpenedByKeyboard} menu={{ items }} onOpenChange={handleOnOpenChange} trigger={MENU_TRIGGER}>
        <Button aria-label="More actions" onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </span>
  );
}

export default ListScreen;
