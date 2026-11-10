import LimitConsumption from '@Components/limits/limit-consumption';
import Lucide from '@Components/lucide';
import { LIMIT_CATEGORIES, LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  formatLimitValue, formatLimitWindow, formatLimitsCount, formatNeverReached, formatRouteLimitWarning, getLimitWarnings, sortLimits,
} from '@Components/limits/helpers';
import RouteLimitWarnings from '@Components/limits/route-limit-warnings';
import useModals from '@Hooks/use-modals';
import { CredentialStateEnum } from '@Src/constants';
import { useGetKeyQuery } from '@State/keys/api';
import { useKeyLimitSaveWarnings, useKeyLimitsConsumption } from '@State/keys/hooks';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Board, Button, DataTable, Void,
} from '@radicalbit/radicalbit-design-system';
import {
  ChevronDown, ChevronRight, Plus,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import LimitMenu from './limit-menu';
import { ScreenEnum } from './schema';

const EXPIRED_MESSAGE = 'This credential has expired: its limits can no longer be changed.';

const NO_LIMITS_TITLE = 'This credential has no limits';

const ROUTE_WARNINGS_TITLE = 'Saved. Some routes this credential reaches have a stricter limit';

const NO_LIMITS_DESCRIPTION = 'Only route and project limits apply.';

const getRowClassName = () => DataTable.ROW_NOT_CLICKABLE;

const getRowKey = ({ uuid }) => uuid;

function ListScreen() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];

  if (!limits.length) {
    return <IsEmpty />;
  }

  return <IsSuccess />;
}

function IsEmpty() {
  return (
    <div className="flex flex-col gap-6">
      <ExpiredAlert />

      <Board
        main={<Void actions={<AddLimits />} description={NO_LIMITS_DESCRIPTION} size="small" title={NO_LIMITS_TITLE} />}
        width="100%"
      />
    </div>
  );
}

function IsSuccess() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];

  const count = formatLimitsCount(limits.length);

  return (
    <div className="flex flex-col gap-6">
      <ExpiredAlert />

      <SavedWarnings />

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <strong>{count}</strong>

          <AddLimits />
        </div>

        <LimitsTable />
      </div>
    </div>
  );
}

function ExpiredAlert() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  if (!isExpired) {
    return false;
  }

  return <Alert title={EXPIRED_MESSAGE} type="info" />;
}

function SavedWarnings() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { clearWarnings, warnings } = useKeyLimitSaveWarnings(uuid);

  const lines = warnings.map((warning) => formatRouteLimitWarning(warning));

  return <RouteLimitWarnings lines={lines} onClose={clearWarnings} title={ROUTE_WARNINGS_TITLE} />;
}

function AddLimits() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { write } = useFormbitContext();

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  const handleOnAdd = () => {
    write('__metadata.screen', ScreenEnum.ADD);
  };

  if (isExpired) {
    return false;
  }

  return <Button icon={<Lucide icon={Plus} />} onClick={handleOnAdd}>Add limits</Button>;
}

function LimitsTable() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits;

  const categories = useMemo(
    () => LIMIT_CATEGORIES.filter((category) => (limits ?? []).some((limit) => limit.category === category)),
    [limits],
  );

  return (
    <div className="flex flex-col gap-4">
      {categories.map((category) => <CategoryBlock key={category} category={category} />)}
    </div>
  );
}

function CategoryBlock({ category }) {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits;
  const limitWarnings = data?.limitWarnings;
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  const [isExpanded, setIsExpanded] = useState(true);

  const dataSource = useMemo(() => sortLimits(limits ?? [])
    .filter((limit) => limit.category === category)
    .map((limit) => ({ ...limit, warnings: getLimitWarnings(limitWarnings, limit) })), [category, limitWarnings, limits]);

  const columns = useMemo(() => [
    {
      title: '',
      key: 'window',
      render: (_, record) => <Window record={record} />,
    },
    {
      title: '',
      key: 'consumption',
      width: '200px',
      render: (_, record) => <Consumption limit={record} />,
    },
    {
      title: '',
      key: 'actions',
      width: '50px',
      render: (_, record) => <Actions isExpired={isExpired} record={record} />,
    },
  ], [isExpired]);

  const handleOnToggle = () => {
    setIsExpanded((previous) => !previous);
  };

  const chevron = isExpanded ? ChevronDown : ChevronRight;
  const title = `${LIMIT_CATEGORY_LABELS[category]} · ${dataSource.length}`;
  const table = isExpanded ? (
    <DataTable
      columns={columns}
      dataSource={dataSource}
      pagination={false}
      rowClassName={getRowClassName}
      rowKey={getRowKey}
      showHeader={false}
      size="small"
    />
  ) : false;

  return (
    <Board
      header={(
        <button aria-expanded={isExpanded} className="flex gap-2 items-center p-0 border-0 bg-transparent text-inherit text-left font-[inherit] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coo-fg-black)] font-[var(--coo-font-weight-bold)]" onClick={handleOnToggle} type="button">
          <Lucide icon={chevron} />

          {title}
        </button>
      )}
      main={table}
      width="100%"
    />
  );
}

function Window({ record }) {
  const maxText = `${formatLimitValue(record?.category, record?.value)} / ${formatLimitWindow(record?.windowSize)}`;
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[record?.algorithm]} window`;
  const warnings = record?.warnings ?? [];

  return (
    <span className="flex flex-col">
      <span>
        {maxText}

        <span className="opacity-70">{windowTypeText}</span>
      </span>

      {warnings.map((warning) => <small key={warning.routeName} className="text-[var(--coo-warning)]">{formatNeverReached(warning)}</small>)}
    </span>
  );
}

function Consumption({ limit }) {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const consumption = useKeyLimitsConsumption(uuid ? [uuid] : []);

  const algorithm = limit?.algorithm;
  const limitUuid = limit?.uuid;

  return <LimitConsumption algorithm={algorithm} bar={consumption?.[limitUuid]} />;
}

function Actions({ isExpired, record }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (isExpired) {
    return false;
  }

  return (
    <span onClick={handleOnClick} role="presentation">
      <LimitMenu limit={record} />
    </span>
  );
}

export default ListScreen;
