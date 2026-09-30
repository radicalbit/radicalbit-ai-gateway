import { ALERT_CHANNEL_LABELS, AlertChannelEnum } from '@Src/constants';
import { FormField, Select } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

const CHANNEL_OPTIONS = Object.values(AlertChannelEnum).map((value) => ({
  label: ALERT_CHANNEL_LABELS[value],
  value,
}));

function Channel() {
  const id = useId();

  return (
    <FormField htmlFor={id} label="Channel">
      <Select disabled id={id} options={CHANNEL_OPTIONS} value={AlertChannelEnum.EMAIL} />
    </FormField>
  );
}

export default Channel;
