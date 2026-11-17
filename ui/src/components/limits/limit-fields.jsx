import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, InputNumber, Select } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';
import {
  LIMIT_CATEGORIES, LIMIT_CATEGORY_LABELS, MAX_LABEL, MAX_LABELS, LimitCategoryEnum, WINDOW_TYPE_LABELS, WindowTypeEnum,
} from './constants';
import { getWindowOptions } from './helpers';

const CATEGORY_OPTIONS = LIMIT_CATEGORIES.map((value) => ({ label: LIMIT_CATEGORY_LABELS[value], value }));

const WINDOW_TYPE_OPTIONS = [WindowTypeEnum.FIXED, WindowTypeEnum.ALIGNED]
  .map((value) => ({ label: WINDOW_TYPE_LABELS[value], value }));

const parseMax = (text) => text;

function LimitFields({
  isCategoryLocked = false, limit, onChange, onPressEnter, path, rowLabel, withCategory = true,
}) {
  const id = useId();

  const { error } = useFormbitContext();

  const category = limit?.category;
  const algorithm = limit?.algorithm;
  const windowSize = limit?.windowSize;
  const max = limit?.value;

  const isBudget = category === LimitCategoryEnum.BUDGET;
  const allowedMaxKeys = isBudget ? /[\d.]/ : /\d/;
  const maxLabel = MAX_LABELS[category] ?? MAX_LABEL;
  const getAriaLabel = (label) => (rowLabel ? `${label}, ${rowLabel}` : undefined);

  const handleOnChangeCategory = (next) => {
    onChange({ ...limit, category: next });
  };

  const handleOnChangeAlgorithm = (next) => {
    const isWindowAllowed = getWindowOptions(next).some((option) => option.value === windowSize);
    onChange({ ...limit, algorithm: next, windowSize: isWindowAllowed ? windowSize : undefined });
  };

  const handleOnChangeWindow = (next) => {
    onChange({ ...limit, windowSize: next });
  };

  const handleOnChangeMax = (next) => {
    onChange({ ...limit, value: next });
  };

  const handleOnInputMax = (text) => {
    if (text && Number.isNaN(Number(text))) {
      onChange({ ...limit, value: text });
    }
  };

  const handleOnKeyDownMax = (event) => {
    const { ctrlKey, key, metaKey } = event;

    if (key.length > 1 || ctrlKey || metaKey) {
      return;
    }

    if (!allowedMaxKeys.test(key)) {
      event.preventDefault();
    }
  };

  return (
    <div className="flex gap-4 items-start w-0 min-w-full" data-limit-row>
      {withCategory && (
        <FormField className="flex-1 min-w-0" htmlFor={`${id}-category`} label="Category" message={error(`${path}.category`)}>
          <Select
            aria-label={getAriaLabel('Category')}
            disabled={isCategoryLocked}
            id={`${id}-category`}
            onChange={handleOnChangeCategory}
            options={CATEGORY_OPTIONS}
            placeholder="Select"
            popupMatchSelectWidth={false}
            style={{ width: '100%' }}
            value={category}
          />
        </FormField>
      )}

      <FormField className="flex-1 min-w-0" htmlFor={`${id}-window-type`} label="Window type" message={error(`${path}.algorithm`)}>
        <Select
          aria-label={getAriaLabel('Window type')}
          id={`${id}-window-type`}
          onChange={handleOnChangeAlgorithm}
          options={WINDOW_TYPE_OPTIONS}
          placeholder="Select"
          popupMatchSelectWidth={false}
          style={{ width: '100%' }}
          value={algorithm}
        />
      </FormField>

      <FormField className="flex-1 min-w-0" htmlFor={`${id}-window`} label="Window" message={error(`${path}.windowSize`)}>
        <Select
          aria-label={getAriaLabel('Window')}
          id={`${id}-window`}
          onChange={handleOnChangeWindow}
          optionFilterProp="label"
          options={getWindowOptions(algorithm)}
          placeholder="Select"
          popupMatchSelectWidth={false}
          showSearch
          style={{ width: '100%' }}
          value={windowSize}
        />
      </FormField>

      <FormField className="flex-1 min-w-0" htmlFor={`${id}-max`} label={maxLabel} message={error(`${path}.value`)}>
        <InputNumber
          aria-label={getAriaLabel(maxLabel)}
          id={`${id}-max`}
          onChange={handleOnChangeMax}
          onInput={handleOnInputMax}
          onKeyDown={handleOnKeyDownMax}
          onPressEnter={onPressEnter}
          parser={parseMax}
          precision={isBudget ? undefined : 0}
          prefix={isBudget ? '$' : undefined}
          style={{ width: '100%' }}
          value={max}
        />
      </FormField>
    </div>
  );
}

export default LimitFields;
