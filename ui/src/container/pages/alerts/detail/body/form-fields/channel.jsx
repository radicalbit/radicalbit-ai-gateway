import { ALERT_CHANNEL_LABELS, AlertChannelEnum } from '@Src/constants';
import { FormField, Select } from '@radicalbit/radicalbit-design-system';

const CHANNEL_OPTIONS = Object.values(AlertChannelEnum).map((value) => ({
  label: ALERT_CHANNEL_LABELS[value],
  value,
}));

function Channel() {
  return (
    <FormField label="Channel">
      <Select disabled options={CHANNEL_OPTIONS} value={AlertChannelEnum.EMAIL} />
    </FormField>
  );
}

export default Channel;
