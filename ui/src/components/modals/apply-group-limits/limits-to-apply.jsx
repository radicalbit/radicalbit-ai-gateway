import Lucide from '@Components/lucide';
import { WINDOW_TYPE_HELP } from '@Components/limits/constants';
import { getNewLimitsErrors } from '@Components/limits/helpers';
import LimitFields from '@Components/limits/limit-fields';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField } from '@radicalbit/radicalbit-design-system';
import { Plus, Trash2 } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import { newRow } from './schema';

function LimitsToApply() {
  const { form, write } = useFormbitContext();
  const rows = form?.limits ?? [];

  const handleOnAddRow = () => {
    write('limits', [...rows, newRow()]);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <strong>Limits to apply</strong>

        <Button icon={<Lucide icon={Plus} />} onClick={handleOnAddRow}>Add another limit</Button>
      </div>

      <span className="text-xs opacity-70">{WINDOW_TYPE_HELP}</span>

      <Rows />
    </div>
  );
}

function Rows() {
  const { form, write } = useFormbitContext();
  const formLimits = form?.limits;

  const rows = useMemo(() => formLimits ?? [], [formLimits]);
  // Only rows repeating each other: a limit a credential already has is a conflict, shown in the preview
  const rowErrors = useMemo(() => getNewLimitsErrors({ limits: [], rows }), [rows]);

  const handleOnChange = useCallback((index, next) => {
    write(`limits[${index}]`, next);
  }, [write]);

  const handleOnRemove = useCallback((index) => {
    write('limits', rows.filter((_, rowIndex) => rowIndex !== index));
  }, [rows, write]);

  const isOnlyRow = rows.length === 1;

  return rows.map((row, index) => (
    <Row
      key={row.rowKey}
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
  error, index, isOnlyRow, onChange, onRemove, row,
}) {
  const { error: formError } = useFormbitContext();

  const handleOnChange = (next) => {
    onChange(index, next);
  };

  const handleOnRemove = () => {
    onRemove(index);
  };

  const message = error ?? formError(`silent.limits.${index}`);
  const errorField = message ? <FormField message={message} /> : false;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2 items-end">
        <div className="flex-1 min-w-0">
          <LimitFields limit={row} onChange={handleOnChange} />
        </div>

        <Button aria-label="Remove limit" disabled={isOnlyRow} onClick={handleOnRemove} type="text">
          <Lucide icon={Trash2} />
        </Button>
      </div>

      {errorField}
    </div>
  );
}

export default LimitsToApply;
