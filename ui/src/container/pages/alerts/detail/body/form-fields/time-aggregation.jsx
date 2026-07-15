import { AlertTimeAggregationEnum } from '@Src/constants';
import { FormField, Radio } from '@radicalbit/radicalbit-design-system';

function TimeAggregation() {
  return (
    <FormField label="Notification frequency">
      <Radio.Group value={AlertTimeAggregationEnum.INSTANT}>
        <Radio value={AlertTimeAggregationEnum.INSTANT}>Instant</Radio>

        <Radio disabled value="custom">Custom</Radio>
      </Radio.Group>
    </FormField>
  );
}

export default TimeAggregation;
