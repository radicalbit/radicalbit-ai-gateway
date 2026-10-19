// PROTOTYPE (AG-1041) — throwaway. The dev backend doesn't return expiry nor rotation fields:
// fake them client-side, deterministically per uuid, so every state shows up in the list.
// Also holds the grace-period rules the rotation modal variants share (same as the backend).
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

export const RotationStateEnum = {
  NONE: 'none',
  IN_GRACE: 'in_grace',
  GRACE_ENDING: 'grace_ending',
  ROTATED: 'rotated',
};

const todayUtc = () => dayjs.utc().format('YYYY-MM-DD');
const addDays = (days) => dayjs.utc(todayUtc()).add(days, 'day').format('YYYY-MM-DD');

const getState = (expiresOn) => {
  if (!expiresOn) return 'active';
  const today = todayUtc();
  if (today > expiresOn) return 'expired';
  if (today >= dayjs.utc(expiresOn).subtract(1, 'day').format('YYYY-MM-DD')) return 'expiring';
  return 'active';
};

// [expiry offset in days (null = never), grace end from now in ms (null = none), last rotation from now in ms (null = never)]
const BUCKETS = [
  [null, null, null], // never rotated, never expires
  [45, 3 * DAY, -2 * HOUR], // in grace
  [null, 5 * HOUR, -19 * HOUR], // grace ending (last 24h)
  [45, null, -10 * DAY], // rotated, grace over
  [0, null, null], // never rotated, expiring today
  [-3, null, -5 * DAY], // expired mid-grace: Expired + Rotated
  [2, 30 * HOUR, -1 * HOUR], // in grace, expires in 2 days
  [120, null, null], // never rotated
];

const hash = (s = '') => [...s].reduce((acc, c) => (acc * 31 + c.charCodeAt(0)) % 4294967296, 7);

export const getMockCredential = (uuid) => {
  const [expiryOffset, graceIn, rotatedIn] = BUCKETS[hash(uuid) % BUCKETS.length];
  const now = Date.now();
  const expiresOn = expiryOffset === null ? null : addDays(expiryOffset);
  const state = getState(expiresOn);
  const lastRotatedAt = rotatedIn === null ? null : new Date(now + rotatedIn).toISOString();
  const isGraceRunning = graceIn !== null && state !== 'expired';
  const graceEndsAt = isGraceRunning ? new Date(now + graceIn).toISOString() : null;

  const rotationState = (() => {
    if (!lastRotatedAt) return RotationStateEnum.NONE;
    if (!isGraceRunning) return RotationStateEnum.ROTATED;
    if (graceIn <= DAY) return RotationStateEnum.GRACE_ENDING;
    return RotationStateEnum.IN_GRACE;
  })();

  return { expiresOn, state, graceEndsAt, rotationState, lastRotatedAt };
};

export const withMockCredentials = (keys) => keys.map((key) => (
  key.owner === 'gateway' ? { ...key, ...getMockCredential(key.uuid) } : { ...key, rotationState: RotationStateEnum.NONE }
));

// ---- Grace-period rules (mirror of the backend) ----

export const UNIT_MS = { hours: HOUR, days: DAY, weeks: 7 * DAY };

// The instant the credential stops working: 23:59:59 UTC on its expiry date.
// ?hoursToExpiry=N overrides it, to try the 10-hour cap and the "< 1 hour, no grace only" case.
export const getExpiryInstant = (expiresOn) => {
  const override = new URLSearchParams(window.location.search).get('hoursToExpiry');
  if (override !== null) return Date.now() + Number(override) * HOUR;
  if (!expiresOn) return null;
  return dayjs.utc(expiresOn).endOf('day').valueOf();
};

export const getHoursLeft = (expiryInstant) => (expiryInstant === null ? Infinity : Math.floor((expiryInstant - Date.now()) / HOUR));

// Preselect 24 hours, capped to the whole hours left before expiry
export const getDefaultGrace = (expiryInstant) => ({ amount: Math.min(24, getHoursLeft(expiryInstant)), unit: 'hours' });

export const isNoGraceOnly = (expiryInstant) => getHoursLeft(expiryInstant) < 1;

// Returns an error message, or null when the grace period is valid
export const validateGrace = ({ amount, unit }, expiryInstant) => {
  if (!amount || amount <= 0) return 'Enter a grace period';
  const ms = amount * UNIT_MS[unit];
  if (ms < HOUR) return 'The grace period must be at least 1 hour';
  if (expiryInstant !== null && Date.now() + ms > expiryInstant) return 'The grace period would end after the credential expires';
  return null;
};

export const getGraceEnd = ({ amount, unit }) => dayjs(Date.now() + amount * UNIT_MS[unit]);

export const formatInstant = (instant) => dayjs(instant).format('DD MMM YYYY, HH:mm');

export const formatExpiry = (expiresOn) => (expiresOn ? `${dayjs(expiresOn).format('DD MMM YYYY')} (end of day UTC)` : 'Never');
