import { ROTATION_FORMAT } from '@Src/constants';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);

const HOUR = 60 * 60 * 1000;

const UNIT_MS = { hours: HOUR, days: 24 * HOUR, weeks: 7 * 24 * HOUR };

const GraceModeEnum = {
  GRACE: 'grace',
  NONE: 'none',
};

const CUSTOM_PRESET = 'custom';

// Values are sent as-is: the API takes the same "N unit" strings
const GRACE_PRESETS = [
  { label: '1 hour', value: '1 hour', amount: 1, unit: 'hours' },
  { label: '24 hours', value: '24 hours', amount: 24, unit: 'hours' },
  { label: '7 days', value: '7 days', amount: 7, unit: 'days' },
];

const UNIT_OPTIONS = [
  { label: 'hours', value: 'hours' },
  { label: 'days', value: 'days' },
  { label: 'weeks', value: 'weeks' },
];

// The last instant the credential works: 23:59:59 UTC on its expiry date, or null for Never
const getExpiryInstant = (expiresOn) => (expiresOn ? dayjs.utc(expiresOn).endOf('day').valueOf() : null);

const getHoursLeft = (expiryInstant) => (expiryInstant === null ? Infinity : Math.floor((expiryInstant - Date.now()) / HOUR));

const getDuration = ({ amount, preset, unit }) => {
  const chosen = GRACE_PRESETS.find(({ value }) => value === preset);

  if (chosen) {
    return { amount: chosen.amount, unit: chosen.unit };
  }

  return { amount, unit };
};

const fitsBeforeExpiry = ({ amount, unit }, expiryInstant) => expiryInstant === null
  || Date.now() + amount * UNIT_MS[unit] <= expiryInstant;

// 24 hours by default, capped to the whole hours left before expiry; no grace only within 1 hour of it
const getInitialValues = (expiresOn) => {
  const hoursLeft = getHoursLeft(getExpiryInstant(expiresOn));

  if (hoursLeft < 1) {
    return { mode: GraceModeEnum.NONE, preset: CUSTOM_PRESET, amount: 1, unit: 'hours' };
  }

  if (hoursLeft < 24) {
    return { mode: GraceModeEnum.GRACE, preset: CUSTOM_PRESET, amount: hoursLeft, unit: 'hours' };
  }

  return { mode: GraceModeEnum.GRACE, preset: '24 hours', amount: 24, unit: 'hours' };
};

// The bounds that depend on the credential's expiry: the API enforces them too
const getBoundsError = (form, expiryInstant) => {
  if (form?.mode !== GraceModeEnum.GRACE) {
    return null;
  }

  const duration = getDuration(form);

  if (!duration.amount) {
    return null;
  }

  if (!fitsBeforeExpiry(duration, expiryInstant)) {
    return 'The grace period would end after the credential expires';
  }

  return null;
};

const getGracePeriod = (form) => {
  if (form?.mode === GraceModeEnum.NONE) {
    return null;
  }

  if (form?.preset === CUSTOM_PRESET) {
    return `${form.amount} ${form.unit}`;
  }

  return form?.preset;
};

const getGraceEnd = (form) => {
  const { amount, unit } = getDuration(form);

  return dayjs(Date.now() + amount * UNIT_MS[unit]).format(ROTATION_FORMAT);
};

export {
  CUSTOM_PRESET,
  GRACE_PRESETS,
  GraceModeEnum,
  UNIT_OPTIONS,
  fitsBeforeExpiry,
  getBoundsError,
  getExpiryInstant,
  getGraceEnd,
  getGracePeriod,
  getHoursLeft,
  getInitialValues,
};
