import Lucide from '@Components/lucide';
import { getNewLimitsErrors } from '@Components/limits/helpers';
import focusLimitRow from '@Components/limits/focus-limit-row';
import LimitFields from '@Components/limits/limit-fields';
import LimitNotes from '@Components/limits/limit-notes';
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
    focusLimitRow(rows.length);
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <strong>Limits to apply</strong>

        <Button icon={<Lucide icon={Plus} />} onClick={handleOnAddRow}>Add another limit</Button>
      </div>

      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-4">
          <Rows />
        </div>
      </div>

      <LimitNotes />
    </div>
  );
}

function Rows() {
  const { form, write } = useFormbitContext();
  const formLimits = form?.limits;

  const rows = useMemo(() => formLimits ?? [], [formLimits]);
  const rowErrors = useMemo(() => getNewLimitsErrors({ limits: [], rows }), [rows]);

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

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2 items-start">
        <div className="flex-1 min-w-0">
          <LimitFields limit={row} onChange={handleOnChange} path={`limits[${index}]`} rowLabel={`limit ${index + 1}`} />
        </div>

        <div className="flex h-8 items-center mt-4">
          <Button aria-label={`Remove limit ${index + 1}`} disabled={isOnlyRow} onClick={handleOnRemove} type="text">
            <Lucide icon={Trash2} />
          </Button>
        </div>
      </div>

      {message && <FormField message={message} />}
    </div>
  );
}

export default LimitsToApply;
