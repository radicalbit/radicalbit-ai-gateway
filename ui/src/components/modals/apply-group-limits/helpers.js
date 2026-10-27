import { getLimitSignature, getNewLimitsErrors, isLimitComplete } from '@Components/limits/helpers';

export const getPreviewItemKey = (keyUuid, limit) => `${keyUuid}|${getLimitSignature(limit)}`;

export const areRowsValid = (rows) => rows.length > 0
  && rows.every(isLimitComplete)
  && !getNewLimitsErrors({ limits: [], rows }).some(Boolean);

/**
 * Who receives what: for each member, each limit to apply is new or a conflict with the
 * limit the member already has on the same category, window type and window.
 */
export const getPreview = ({ limitsByKey, members, rows }) => members.map((member) => ({
  member,
  items: rows.map((limit) => {
    const existing = (limitsByKey[member.uuid] ?? [])
      .find((saved) => getLimitSignature(saved) === getLimitSignature(limit));

    return { key: getPreviewItemKey(member.uuid, limit), limit, existing };
  }),
}));

export const getConflicts = (preview) => preview.flatMap(({ items, member }) => items
  .filter(({ existing }) => existing)
  .map((item) => ({ ...item, member })));

// The members the apply writes on: a new limit, or a conflict chosen to be overwritten. Skipped ones are untouched
export const getTouchedMembers = (preview, overwrite) => preview
  .filter(({ items }) => items.some(({ existing, key }) => !existing || overwrite.includes(key)))
  .map(({ member }) => member);
