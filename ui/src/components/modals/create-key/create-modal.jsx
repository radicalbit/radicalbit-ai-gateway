import useAutoFocus from '@Hooks/use-auto-focus';
import useModals from '@Hooks/use-modals';
import { EXPIRES_ON_FORMAT } from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  DatePicker,
  FormField, Input, Radio, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useId, useRef } from 'react';
import { ExpiryModeEnum } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

dayjs.extend(utc);

// The earliest selectable day is today in UTC, not in the browser's timezone
const getUtcToday = () => dayjs.utc().format(EXPIRES_ON_FORMAT);

// A local dayjs built from the UTC calendar date, so the picker highlights the right day
const fromUtcToday = (days) => dayjs(getUtcToday()).add(days, 'day');

// Keep the popup above the modal, which sits on a higher layer than antd's default popup z-index
const PICKER_STYLES = { popup: { root: { zIndex: 10000 } } };

const EXPIRES_ON_PRESETS = [
  { label: 'Today', value: () => fromUtcToday(0) },
  { label: '+7 days', value: () => fromUtcToday(7) },
  { label: '+30 days', value: () => fromUtcToday(30) },
  { label: '+90 days', value: () => fromUtcToday(90) },
  { label: '+1 year', value: () => fromUtcToday(365) },
];

function CreateModal() {
  const { hideModal } = useModals();
  const { error } = useFormbitContext();

  return (
    <RbitModal
      actions={<Actions />}
      aria-label="Create credential"
      closable
      header={(
        <SectionTitle
          subtitle={(
            <>
              Please note that we do not display your credentials again
              <br />
              after you generate them.
            </>
          )}
          title="Create credential"
        />
      )}
      onCancel={hideModal}
      open
      width={550}
    >
      <Spinner isFormWrapper>
        <Name />

        <Expiration />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}
      </Spinner>
    </RbitModal>
  );
}

function Name() {
  const ref = useRef();
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const { handleOnSubmit, args: { isLoading } } = useHandleOnSubmit();
  const handleOnChange = ({ target: { value } }) => { write('name', value); };

  useAutoFocus(ref);

  return (
    <FormField
      htmlFor={id}
      label="Credential name"
      message={error('name')}
      required
    >
      <Input
        id={id}
        onChange={handleOnChange}
        onPressEnter={handleOnSubmit}
        readOnly={isLoading}
        ref={ref}
        value={name}
      />
    </FormField>
  );
}

function Expiration() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const expiryMode = form?.expiryMode;
  const expiresOn = form?.expiresOn;

  const { args: { isLoading } } = useHandleOnSubmit();

  const isDate = expiryMode === ExpiryModeEnum.DATE;
  const pickerValue = expiresOn ? dayjs(expiresOn) : null;

  const handleOnChangeExpiryMode = ({ target: { value } }) => {
    write('expiryMode', value);
  };

  const handleOnChangeExpiresOn = (date) => {
    write('expiresOn', date ? date.format(EXPIRES_ON_FORMAT) : null);
  };

  const handleOnDisabledDate = (date) => date.format(EXPIRES_ON_FORMAT) < getUtcToday();

  const datePicker = isDate ? (
    <DatePicker
      disabled={isLoading}
      disabledDate={handleOnDisabledDate}
      format="DD MMM YYYY"
      id={id}
      modifier="w-full"
      onChange={handleOnChangeExpiresOn}
      placeholder="Select a date"
      presets={EXPIRES_ON_PRESETS}
      showToday={false}
      styles={PICKER_STYLES}
      value={pickerValue}
    />
  ) : false;

  // FormField's description prop renders an info-icon tooltip, not helper text
  const helperText = isDate ? <span className="text-xs opacity-70">Expires at the end of the chosen day (UTC)</span> : false;

  return (
    <FormField
      htmlFor={id}
      label="Expiration"
      message={error('expiresOn')}
    >
      <div className="flex flex-col gap-2">
        <Radio.Group disabled={isLoading} onChange={handleOnChangeExpiryMode} value={expiryMode}>
          <Radio value={ExpiryModeEnum.NEVER}>Never</Radio>

          <Radio value={ExpiryModeEnum.DATE}>On date</Radio>
        </Radio.Group>

        {datePicker}

        {helperText}
      </div>
    </FormField>
  );
}

function Actions() {
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  return (
    <Button
      disabled={isSubmitDisabled}
      loading={isLoading}
      onClick={handleOnSubmit}
      type="primary"
    >
      Generate credential
    </Button>
  );
}

export default CreateModal;
