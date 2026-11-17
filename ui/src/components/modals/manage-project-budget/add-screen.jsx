import HtmlAnchor from '@Components/html-anchor';
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
import useHandleOnSubmit from './useHandleOnSubmit';
import {
  ScreenEnum, getEditRow, getInitialValues, newRow,
} from './schema';

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

  return (
    <div className="flex flex-col gap-6">
      <Conflicts />

      <div className="flex items-center justify-between">
        <Button className="!min-w-0 !px-0" icon={<Lucide icon={ArrowLeft} />} onClick={handleOnBack} type="text">Budget limits</Button>

        <Button icon={<Lucide icon={Plus} />} onClick={handleOnAddRow}>Add another budget</Button>
      </div>

      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-4">
          <Rows />

          {backendError && <FormField message={backendError} />}
        </div>
      </div>

      <LimitNotes />
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

  const { handleOnSubmit } = useHandleOnSubmit();

  const handleOnChange = (next) => {
    onChange(index, next);
  };

  const handleOnPressEnter = () => {
    handleOnSubmit();
  };

  const handleOnRemove = () => {
    onRemove(index);
  };

  const isEditableDuplicate = error === DUPLICATE_BUDGET_ERROR && !!duplicateLimit;
  const message = error ?? formError(`silent.limits.${index}`);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2 items-start">
        <div className="flex-1 min-w-0">
          <LimitFields limit={row} onChange={handleOnChange} onPressEnter={handleOnPressEnter} path={`limits[${index}]`} rowLabel={`budget ${index + 1}`} withCategory={false} />
        </div>

        <div className="flex h-8 items-center mt-4">
          <Button aria-label={`Remove budget ${index + 1}`} disabled={isOnlyRow} onClick={handleOnRemove} type="text">
            <Lucide icon={Trash2} />
          </Button>
        </div>
      </div>

      {(isEditableDuplicate || message) && (
        <FormField message={isEditableDuplicate ? <DuplicateMessage limit={duplicateLimit} /> : message} />
      )}
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

      <HtmlAnchor onClick={handleOnEdit}>{DUPLICATE_EDIT_LINK}</HtmlAnchor>

      {DUPLICATE_SUFFIX}
    </span>
  );
}

export default AddScreen;
