import { ALERT_TIME_AGGREGATION_LABELS, AlertTimeAggregationEnum } from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Radio } from '@radicalbit/radicalbit-design-system';

function TimeAggregation() {
  const { form } = useFormbitContext();
  const timeAggregation = form?.timeAggregation;

  if (timeAggregation === AlertTimeAggregationEnum.LIMIT_WINDOW) {
    return <LimitWindow />;
  }

  return (
    <FormField label="Notification frequency">
      <Radio.Group aria-label="Notification frequency" value={AlertTimeAggregationEnum.INSTANT}>
        <Radio value={AlertTimeAggregationEnum.INSTANT}>Instant</Radio>

        <Radio disabled value="custom">Custom</Radio>
      </Radio.Group>
    </FormField>
  );
}

function LimitWindow() {
  return (
    <FormField label="Notification frequency">
      <div className="flex flex-col gap-2">
        <Radio.Group aria-label="Notification frequency" disabled value={AlertTimeAggregationEnum.LIMIT_WINDOW}>
          <Radio value={AlertTimeAggregationEnum.LIMIT_WINDOW}>
            {ALERT_TIME_AGGREGATION_LABELS[AlertTimeAggregationEnum.LIMIT_WINDOW]}
          </Radio>
        </Radio.Group>

        <span>
          Limit and threshold events follow the window of their limit: the alert is sent the first time
          the event happens in each window, and not again until the limit resets.
        </span>
      </div>
    </FormField>
  );
}

export default TimeAggregation;
