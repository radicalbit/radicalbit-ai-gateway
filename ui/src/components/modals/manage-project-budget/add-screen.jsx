import Lucide from '@Components/lucide';
import {
  DUPLICATE_BUDGET_ERROR, DUPLICATE_BUDGET_PREFIX, DUPLICATE_EDIT_LINK, DUPLICATE_SUFFIX,
} from '@Components/limits/constants';
import { asBudgets, getDuplicateLimit, getNewLimitsErrors } from '@Components/limits/helpers';
import focusLimitRow from '@Components/limits/focus-limit-row';
import LimitFields from '@Components/limits/limit-fields';
import LimitNotes from '@Components/limits/limit-notes';
import useModals from '@Hooks/use-modals';
import { useGetProjectBudgetQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import Conflicts from './conflicts';
import {
  ScreenEnum, getEditRow, getInitialValues, newRow,
} from './schema';

const FLUSH_BUTTON = '!min-w-0 !px-0';

const INLINE_LINK = 'p-0 border-0 bg-transparent text-inherit underline cursor-pointer font-[inherit]';

function AddScreen() {
  const { error, form, initialize, write } = useFormbitContext();
  const rows = form?.limits ?? [];

  const handleOnBack = () => {
    initialize(getInitialValues());
  };

  const handleOnAddRow = () => {
    write('limits', [...rows, newRow()]);
    focusLimitRow(rows.length);
  };

  const backendError = error('silent.backend');
  const backendErrorField = backendError ? <FormField message={backendError} /> : false;

  return (
    <div className="flex flex-col gap-6">
      <Conflicts />

      <div className="flex items-center justify-between">
        <Button className={FLUSH_BUTTON} icon={<Lucide icon={ArrowLeft} />} onClick={handleOnBack} type="text">Budget limits</Button>

        <Button icon={<Lucide icon={Plus} />} onClick={handleOnAddRow}>Add another budget</Button>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Rows />

          {backendErrorField}
        </div>

        <LimitNotes />
      </div>
    </div>
  );
}

function Rows() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, write } = useFormbitContext();
  const formLimits = form?.limits;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const savedLimits = data?.limits;

  const rows = useMemo(() => formLimits ?? [], [formLimits]);
  const rowErrors = useMemo(() => getNewLimitsErrors({
    duplicateError: DUPLICATE_BUDGET_ERROR,
    limits: asBudgets(savedLimits),
    rows,
  }), [rows, savedLimits]);
  const duplicateLimit = useMemo(() => getDuplicateLimit({ limits: asBudgets(savedLimits), rows }), [rows, savedLimits]);

  const handleOnChange = useCallback((index, next) => {
    write(`limits[${index}]`, next);
  }, [write]);

  const handleOnRemove = useCallback((index) => {
    write('limits', rows.filter((_, rowIndex) => rowIndex !== index));
    focusLimitRow(index);
  }, [rows, write]);

  const isOnlyRow = rows.length === 1;

  return rows.map((row, index) => (
    <Row
      key={row.rowKey}
      duplicateLimit={duplicateLimit}
      error={rowErrors[index]}
      index={index}
      isOnlyRow={isOnlyRow}
      onChange={handleOnChange}
      onRemove={handleOnRemove}
      row={row}
    />
  ));
}

function Row({
  duplicateLimit, error, index, isOnlyRow, onChange, onRemove, row,
}) {
  const { error: formError } = useFormbitContext();

  const handleOnChange = (next) => {
    onChange(index, next);
  };

  const handleOnRemove = () => {
    onRemove(index);
  };

  const rowLabel = `budget ${index + 1}`;
  const isEditableDuplicate = error === DUPLICATE_BUDGET_ERROR && !!duplicateLimit;
  const message = isEditableDuplicate ? <DuplicateMessage limit={duplicateLimit} /> : error ?? formError(`silent.limits.${index}`);
  const errorField = message ? <FormField message={message} /> : false;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2 items-end">
        <div className="flex-1 min-w-0">
          <LimitFields limit={row} onChange={handleOnChange} rowLabel={rowLabel} withCategory={false} />
        </div>

        <Button aria-label={`Remove budget ${index + 1}`} disabled={isOnlyRow} onClick={handleOnRemove} type="text">
          <Lucide icon={Trash2} />
        </Button>
      </div>

      {errorField}
    </div>
  );
}

function DuplicateMessage({ limit }) {
  const { writeAll } = useFormbitContext();

  const handleOnEdit = () => {
    writeAll([['limits', [getEditRow(limit)]], ['__metadata.limitUuid', limit.uuid], ['__metadata.screen', ScreenEnum.EDIT]]);
    focusLimitRow(0);
  };

  return (
    <span>
      {DUPLICATE_BUDGET_PREFIX}

      <button className={INLINE_LINK} onClick={handleOnEdit} type="button">{DUPLICATE_EDIT_LINK}</button>

      {DUPLICATE_SUFFIX}
    </span>
  );
}

export default AddScreen;
