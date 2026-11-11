import dateFormatter from '@Src/helpers/date-formatter';
import { numberFormatterFloat, numberFormatterInt } from '@Src/constants';

export const formatMs = (value) => {
  if (value === null || value === undefined) {
    return '--';
  }

  return `${numberFormatterFloat(value)}ms`;
};

export const formatInt = (value) => {
  if (value === null || value === undefined) {
    return '--';
  }

  return numberFormatterInt(value);
};

export const formatTimestamp = (value) => {
  if (value === null || value === undefined) {
    return '--';
  }

  return dateFormatter(value * 1000);
};

export function FormatBold({ value }) {
  return <span className="font-bold">{value ?? '--'}</span>;
}

export const formatText = (value) => value ?? '--';
