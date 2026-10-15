// PROTOTYPE (AG-1034) — throwaway. The API doesn't return expiresOn/state yet (AG-1035):
// fake them client-side, deterministically per uuid, so every state shows up in the list.
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);

const todayUtc = () => dayjs.utc().format('YYYY-MM-DD');

const addDays = (date, days) => dayjs.utc(date).add(days, 'day').format('YYYY-MM-DD');

// index → offset in days from today (UTC); null = Never
const BUCKETS = [null, 45, 0, 1, -3, null, 120, -30];

const hash = (s = '') => [...s].reduce((acc, c) => (acc * 31 + c.charCodeAt(0)) % 4294967296, 7);

// Same rule as the spec: compare UTC calendar dates
export const getState = (expiresOn) => {
  if (!expiresOn) return 'active';
  const today = todayUtc();
  if (today > expiresOn) return 'expired';
  if (today >= addDays(expiresOn, -1)) return 'expiring';
  return 'active';
};

export const getMockExpiry = (uuid) => {
  const offset = BUCKETS[hash(uuid) % BUCKETS.length];
  const expiresOn = offset === null ? null : addDays(todayUtc(), offset);
  return { expiresOn, state: getState(expiresOn) };
};

export const withMockExpiry = (keys) => keys.map((key) => ({ ...key, ...getMockExpiry(key.uuid) }));

// Days from today (UTC) to expiresOn: negative once expired
export const daysLeft = (expiresOn) => dayjs.utc(expiresOn).diff(dayjs.utc(todayUtc()), 'day');

// Date-only: no timezone conversion, on purpose
export const formatExpiresOn = (expiresOn) => dayjs(expiresOn, 'YYYY-MM-DD').format('DD MMM YYYY');

export const EXPIRY_TOOLTIP = 'Expires at end of day (UTC)';
export const EXPIRED_TOOLTIP = 'This credential has expired: it can only be deleted';
