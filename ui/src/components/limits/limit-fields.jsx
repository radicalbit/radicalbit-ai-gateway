import { InputNumber, Select } from '@radicalbit/radicalbit-design-system';
import {
  LIMIT_CATEGORIES, LIMIT_CATEGORY_LABELS, MAX_LABEL, MAX_LABELS, LimitCategoryEnum, WINDOW_TYPE_LABELS, WindowTypeEnum,
} from './constants';
import { getWindowOptions } from './helpers';

const CATEGORY_OPTIONS = LIMIT_CATEGORIES.map((value) => ({ label: LIMIT_CATEGORY_LABELS[value], value }));

const WINDOW_TYPE_OPTIONS = [WindowTypeEnum.FIXED, WindowTypeEnum.ALIGNED]
  .map((value) => ({ label: WINDOW_TYPE_LABELS[value], value }));

const SELECT_PLACEHOLDER = 'Select';

// The design system forces its own widths on these inputs: they fill flex-1 wrappers instead
const FULL_WIDTH = { width: '100%' };

function LimitFields({ limit, onChange, withCategory = true }) {
  const category = limit?.category;
  const algorithm = limit?.algorithm;
  const windowSize = limit?.windowSize;
  const max = limit?.value;
  const isBudget = category === LimitCategoryEnum.BUDGET;

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

  const minMax = isBudget ? 0.01 : 1;
  const precision = isBudget ? 2 : 0;
  const prefix = isBudget ? '$' : undefined;
  const windowOptions = getWindowOptions(algorithm);
  const categoryField = withCategory ? (
    <Field label="Category">
      <Select
        onChange={handleOnChangeCategory}
        options={CATEGORY_OPTIONS}
        placeholder={SELECT_PLACEHOLDER}
        popupMatchSelectWidth={false}
        style={FULL_WIDTH}
        value={category}
      />
    </Field>
  ) : false;
  const maxLabel = MAX_LABELS[category] ?? MAX_LABEL;

  return (
    <div className="flex gap-2 items-end w-0 min-w-full">
      {categoryField}

      <Field label="Window type">
        <Select
          onChange={handleOnChangeAlgorithm}
          options={WINDOW_TYPE_OPTIONS}
          placeholder={SELECT_PLACEHOLDER}
          popupMatchSelectWidth={false}
          style={FULL_WIDTH}
          value={algorithm}
        />
      </Field>

      <Field label="Window">
        <Select
          onChange={handleOnChangeWindow}
          options={windowOptions}
          placeholder={SELECT_PLACEHOLDER}
          popupMatchSelectWidth={false}
          style={FULL_WIDTH}
          value={windowSize}
        />
      </Field>

      <Field label={maxLabel}>
        <InputNumber
          min={minMax}
          onChange={handleOnChangeMax}
          precision={precision}
          prefix={prefix}
          style={FULL_WIDTH}
          value={max}
        />
      </Field>
    </div>
  );
}

function Field({ children, label }) {
  return (
    <div className="flex flex-col flex-1 gap-1 min-w-0">
      <small className="opacity-70">{label}</small>

      {children}
    </div>
  );
}

export default LimitFields;
