import useModals from '@Hooks/use-modals';
import { DATE_FORMAT_SHORT } from '@Src/constants';
import { useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField, InputNumber, Radio, RbitModal, SectionTitle, Segmented, Select, Spinner, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import {
  CUSTOM_PRESET,
  GRACE_PRESETS,
  GraceModeEnum,
  UNIT_OPTIONS,
  fitsBeforeExpiry,
  getExpiryInstant,
  getGraceEnd,
  getHoursLeft,
} from './grace-period';
import useHandleOnSubmit from './useHandleOnSubmit';

const NO_GRACE_ONLY_TOOLTIP = 'The credential expires in less than 1 hour: only no grace period is possible';

// The design system forces its own widths on these inputs: they fill flex-1 wrappers instead
const FULL_WIDTH = { width: '100%' };

function RotateModal() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { error } = useFormbitContext();

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const backendError = error('silent.backend');
  const backendErrorField = backendError ? <FormField message={backendError} /> : false;

  return (
    <RbitModal
      actions={<Actions />}
      aria-label="Rotate credential"
      closable
      header={(
        <SectionTitle
          subtitle={`A new value replaces the current one for ${name}. It is shown only once.`}
          title="Rotate credential"
        />
      )}
      onCancel={hideModal}
      open
      width={550}
    >
      <Spinner isFormWrapper>
        <div className="flex flex-col gap-6">
          <Expiry />

          <GracePeriod />

          {backendErrorField}
        </div>
      </Spinner>
    </RbitModal>
  );
}

function Expiry() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const expiresOn = data?.expiresOn;

  // expiresOn is a calendar date: shown as-is, never converted to the browser's timezone
  const expiry = expiresOn ? `${dayjs(expiresOn).format(DATE_FORMAT_SHORT.trim())} (end of day UTC)` : 'Never';

  return (
    <div>
      <span className="opacity-70">Credential expires: </span>

      <strong>{expiry}</strong>
    </div>
  );
}

function GracePeriod() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { error, form, write } = useFormbitContext();
  const mode = form?.mode;
  const preset = form?.preset;
  const amount = form?.amount;
  const unit = form?.unit;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const expiresOn = data?.expiresOn;

  const { boundsError, args: { isLoading } } = useHandleOnSubmit();

  const expiryInstant = getExpiryInstant(expiresOn);
  const isNoGraceOnly = getHoursLeft(expiryInstant) < 1;
  const isGrace = mode === GraceModeEnum.GRACE;
  const isCustom = preset === CUSTOM_PRESET;
  const fieldError = isGrace ? (error('amount') || boundsError) : undefined;

  const presetOptions = [
    ...GRACE_PRESETS.map(({ label, value, ...duration }) => ({ label, value, disabled: !fitsBeforeExpiry(duration, expiryInstant) })),
    { label: 'Custom', value: CUSTOM_PRESET },
  ];

  const help = (() => {
    if (!isGrace) {
      return 'The previous value stops working immediately.';
    }

    if (fieldError) {
      return false;
    }

    return `Both values work until ${getGraceEnd(form)}.`;
  })();

  const handleOnChangeMode = ({ target: { value } }) => {
    write('mode', value);
  };

  const handleOnChangePreset = (value) => {
    write('preset', value);
  };

  const handleOnChangeAmount = (value) => {
    write('amount', value, { pathsToValidate: ['amount'] });
  };

  const handleOnChangeUnit = (value) => {
    write('unit', value);
  };

  const graceRadio = isNoGraceOnly
    ? (
      <Tooltip title={NO_GRACE_ONLY_TOOLTIP}>
        <span><Radio disabled value={GraceModeEnum.GRACE}>Grace period</Radio></span>
      </Tooltip>
    )
    : <Radio value={GraceModeEnum.GRACE}>Grace period</Radio>;

  // w-0 min-w-full: the row never widens the group, it only fills the presets bar's width
  const customFields = isCustom ? (
    <div className="flex gap-2 w-0 min-w-full">
      <div className="flex-1 min-w-0">
        <InputNumber aria-label="Grace period amount" disabled={isLoading} min={1} onChange={handleOnChangeAmount} precision={0} style={FULL_WIDTH} value={amount} />
      </div>

      <div className="flex-1 min-w-0">
        <Select aria-label="Grace period unit" disabled={isLoading} onChange={handleOnChangeUnit} options={UNIT_OPTIONS} popupMatchSelectWidth={false} style={FULL_WIDTH} value={unit} />
      </div>
    </div>
  ) : false;

  // inline-flex: the group takes the presets bar's width, and the Custom row stretches to it
  const graceDetails = isGrace ? (
    <div className="inline-flex flex-col gap-2 self-start">
      <Segmented aria-label="Grace period duration" disabled={isLoading} onChange={handleOnChangePreset} options={presetOptions} value={preset} />

      {customFields}
    </div>
  ) : false;

  return (
    <FormField message={fieldError}>
      <div className="flex flex-col gap-2">
        <Radio.Group aria-label="Grace period" disabled={isLoading} onChange={handleOnChangeMode} value={mode}>
          {graceRadio}

          <Radio value={GraceModeEnum.NONE}>No grace period</Radio>
        </Radio.Group>

        {graceDetails}

        <span className="text-xs opacity-70">{help}</span>
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
      Generate new value
    </Button>
  );
}

export default RotateModal;
