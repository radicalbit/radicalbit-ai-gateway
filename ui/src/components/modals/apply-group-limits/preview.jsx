import Lucide from '@Components/lucide';
import { LIMIT_CATEGORY_LABELS } from '@Components/limits/constants';
import { formatCount, formatLimitValue, formatLimitWindow } from '@Components/limits/helpers';
import { CredentialStateEnum } from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Board, Button, DataTable, Segmented,
} from '@radicalbit/radicalbit-design-system';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { areRowsValid, getConflicts, getPreview } from './helpers';
import useMembers from './use-members';

const ChoiceEnum = {
  SKIP: 'skip',
  OVERWRITE: 'overwrite',
};

const CHOICE_OPTIONS = [
  { label: 'Skip', value: ChoiceEnum.SKIP },
  { label: 'Overwrite', value: ChoiceEnum.OVERWRITE },
];

const EXPIRED_MESSAGE = 'Expired: receives the limits, can\'t use them';

const getRowClassName = () => DataTable.ROW_NOT_CLICKABLE;

const getRowKey = ({ key }) => key;

function Preview() {
  const { form } = useFormbitContext();
  const rows = form?.limits ?? [];

  const { members, limitsByKey } = useMembers();

  if (!areRowsValid(rows)) {
    return (
      <div className="flex flex-col gap-2">
        <strong>Preview</strong>

        <span className="opacity-70">Fill in the limits to see who receives them.</span>
      </div>
    );
  }

  const preview = getPreview({ limitsByKey, members, rows });
  const conflicts = getConflicts(preview);

  const conflictsMessage = conflicts.length
    ? `${formatCount(conflicts.length, 'limit')} already set on some credentials: skipped unless you choose Overwrite.`
    : 'No credential already has these limits.';

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <strong>Preview</strong>

        <ChooseAll conflicts={conflicts} />
      </div>

      <span className="text-xs opacity-70">{conflictsMessage}</span>

      <div className="flex flex-col gap-4">
        {preview.map(({ items, member }) => <MemberBlock key={member.uuid} items={items} member={member} />)}
      </div>
    </div>
  );
}

function ChooseAll({ conflicts }) {
  const { write } = useFormbitContext();

  const handleOnSkipAll = () => {
    write('overwrite', []);
  };

  const handleOnOverwriteAll = () => {
    write('overwrite', conflicts.map(({ key }) => key));
  };

  if (!conflicts.length) {
    return false;
  }

  return (
    <div className="flex gap-2">
      <Button onClick={handleOnSkipAll} size="small" type="text">Skip all</Button>

      <Button onClick={handleOnOverwriteAll} size="small" type="text">Overwrite all</Button>
    </div>
  );
}

function MemberBlock({ items, member }) {
  const [isExpanded, setIsExpanded] = useState(true);

  const conflictCount = items.filter(({ existing }) => existing).length;
  const dataSource = items.map((item) => ({ ...item, member }));

  const columns = [
    {
      key: 'name',
      render: (_, record) => <NameCell record={record} />,
    },
    {
      key: 'change',
      render: (_, record) => <ChangeCell record={record} />,
    },
    {
      key: 'choice',
      align: 'right',
      render: (_, record) => <ChoiceCell record={record} />,
    },
  ];

  const handleOnToggle = () => {
    setIsExpanded((previous) => !previous);
  };

  if (!isExpanded) {
    return (
      <Board
        header={<MemberHeader conflictCount={conflictCount} isExpanded={false} member={member} onToggle={handleOnToggle} />}
        width="100%"
      />
    );
  }

  return (
    <Board
      header={<MemberHeader conflictCount={conflictCount} isExpanded member={member} onToggle={handleOnToggle} />}
      main={(
        <DataTable
          columns={columns}
          dataSource={dataSource}
          pagination={false}
          rowClassName={getRowClassName}
          rowKey={getRowKey}
          showHeader={false}
          size="small"
        />
      )}
      width="100%"
    />
  );
}

function MemberHeader({ conflictCount, isExpanded, member, onToggle }) {
  return (
    <button aria-expanded={isExpanded} className="flex w-full items-center justify-between gap-4 p-0 border-0 bg-transparent text-inherit text-left font-[inherit] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coo-fg-black)]" onClick={onToggle} type="button">
      <span className="flex items-center gap-2">
        <Chevron isExpanded={isExpanded} />

        <span className="flex flex-col">
          <strong>{member.name}</strong>

          <ExpiredMark member={member} />
        </span>
      </span>

      <ConflictSummary conflictCount={conflictCount} />
    </button>
  );
}

function Chevron({ isExpanded }) {
  if (isExpanded) {
    return <Lucide icon={ChevronDown} />;
  }

  return <Lucide icon={ChevronRight} />;
}

function ConflictSummary({ conflictCount }) {
  if (conflictCount) {
    return <small className="text-[var(--coo-warning)]">{`${conflictCount} already set`}</small>;
  }

  return <small className="opacity-70">all new</small>;
}

function NameCell({ record }) {
  const { limit } = record;

  return `${LIMIT_CATEGORY_LABELS[limit.category]} · ${formatLimitWindow(limit.windowSize)}`;
}

function ExpiredMark({ member }) {
  if (member.state !== CredentialStateEnum.EXPIRED) {
    return false;
  }

  return <small className="text-[var(--coo-error)]">{EXPIRED_MESSAGE}</small>;
}

function ChangeCell({ record }) {
  const { existing, limit } = record;

  if (!existing) {
    return `New · ${formatLimitValue(limit.category, limit.value)}`;
  }

  return `${formatLimitValue(limit.category, existing.value)} → ${formatLimitValue(limit.category, limit.value)} / ${formatLimitWindow(limit.windowSize)}`;
}

function ChoiceCell({ record }) {
  const { form, write } = useFormbitContext();
  const overwrite = form?.overwrite ?? [];

  const { existing, key, limit, member } = record;

  if (!existing) {
    return false;
  }

  const handleOnChange = (value) => {
    const others = overwrite.filter((item) => item !== key);
    write('overwrite', value === ChoiceEnum.OVERWRITE ? [...others, key] : others);
  };

  const value = overwrite.includes(key) ? ChoiceEnum.OVERWRITE : ChoiceEnum.SKIP;

  const ariaLabel = `${member?.name}: ${LIMIT_CATEGORY_LABELS[limit?.category]} · ${formatLimitWindow(limit?.windowSize)}`;

  return <Segmented aria-label={ariaLabel} onChange={handleOnChange} options={CHOICE_OPTIONS} size="small" value={value} />;
}

export default Preview;
