import { InputNumber, Select } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';
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

function LimitFields({ limit, onChange, rowLabel, withCategory = true }) {
  const id = useId();

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
    <Field htmlFor={`${id}-category`} label="Category">
      <Select
        aria-label={getAriaLabel('Category')}
        id={`${id}-category`}
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
  const getAriaLabel = (label) => (rowLabel ? `${label}, ${rowLabel}` : undefined);

  return (
    <div className="flex gap-2 items-end w-0 min-w-full" data-limit-row>
      {categoryField}

      <Field htmlFor={`${id}-window-type`} label="Window type">
        <Select
          aria-label={getAriaLabel('Window type')}
          id={`${id}-window-type`}
          onChange={handleOnChangeAlgorithm}
          options={WINDOW_TYPE_OPTIONS}
          placeholder={SELECT_PLACEHOLDER}
          popupMatchSelectWidth={false}
          style={FULL_WIDTH}
          value={algorithm}
        />
      </Field>

      <Field htmlFor={`${id}-window`} label="Window">
        <Select
          aria-label={getAriaLabel('Window')}
          id={`${id}-window`}
          onChange={handleOnChangeWindow}
          options={windowOptions}
          placeholder={SELECT_PLACEHOLDER}
          popupMatchSelectWidth={false}
          style={FULL_WIDTH}
          value={windowSize}
        />
      </Field>

      <Field htmlFor={`${id}-max`} label={maxLabel}>
        <InputNumber
          aria-label={getAriaLabel(maxLabel)}
          id={`${id}-max`}
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

function Field({ children, htmlFor, label }) {
  return (
    <div className="flex flex-col flex-1 gap-1 min-w-0">
      <label htmlFor={htmlFor}>
        <small className="opacity-70">{label}</small>
      </label>

      {children}
    </div>
  );
}

export default LimitFields;
