import Lucide from '@Components/lucide';
import { WINDOW_TYPE_HELP } from '@Components/limits/constants';
import { getNewLimitsErrors } from '@Components/limits/helpers';
import LimitFields from '@Components/limits/limit-fields';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import { getInitialValues, newRow } from './schema';

const FLUSH_BUTTON = '!min-w-0 !px-0';

function AddScreen() {
  const { error, form, initialize, write } = useFormbitContext();
  const rows = form?.limits ?? [];

  const handleOnBack = () => {
    initialize(getInitialValues());
  };

  const handleOnAddRow = () => {
    write('limits', [...rows, newRow()]);
  };

  const backendError = error('silent.backend');
  const backendErrorField = backendError ? <FormField message={backendError} /> : false;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex gap-2 items-center">
          <Button aria-label="Back" className={FLUSH_BUTTON} onClick={handleOnBack} type="text">
            <Lucide icon={ArrowLeft} />
          </Button>

          <strong>Limits</strong>
        </div>

        <Button onClick={handleOnAddRow} prefix={<Lucide icon={Plus} />} type="secondary">Add limit</Button>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs opacity-70">{WINDOW_TYPE_HELP}</span>

        <Rows />

        {backendErrorField}
      </div>
    </div>
  );
}

function Rows() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, write } = useFormbitContext();
  const formLimits = form?.limits;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const savedLimits = data?.limits;

  const rows = useMemo(() => formLimits ?? [], [formLimits]);
  const rowErrors = useMemo(() => getNewLimitsErrors({ limits: savedLimits ?? [], rows }), [rows, savedLimits]);

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

export default AddScreen;
