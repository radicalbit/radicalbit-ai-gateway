const NOTE = 'text-xs opacity-70';

const WARNING_NOTE = 'text-xs text-[var(--coo-warning)]';

/**
 * The notes under the limit fields, in field order: category, window type, max.
 * Key words are in bold so the user can spot the concept without reading the whole sentence.
 *
 * @typedef {object} LimitNotesProps
 * @property {boolean} [isEditing=false] an existing limit is being edited
 * @property {boolean} [isWindowChanged=false] the edit changes window type or window
 * @property {boolean} [withCategory=false] the limit has a category (credential limits, not budgets)
 */

/**
 * @param {LimitNotesProps} props
 */
function LimitNotes({ isEditing = false, isWindowChanged = false, withCategory = false }) {
  return (
    <div className="flex flex-col gap-1">
      <CategoryNote isEditing={isEditing} withCategory={withCategory} />

      <WindowTypeNote />

      <EditNote isEditing={isEditing} isWindowChanged={isWindowChanged} />
    </div>
  );
}

function CategoryNote({ isEditing, withCategory }) {
  if (!isEditing || !withCategory) {
    return false;
  }

  return (
    <span className={NOTE}>
      {'The '}

      <strong>category</strong>

      {' can\'t be changed: '}

      <strong>delete</strong>

      {' this limit and '}

      <strong>add</strong>

      {' a new one.'}
    </span>
  );
}

function WindowTypeNote() {
  return (
    <span className={NOTE}>
      <strong>Fixed</strong>

      {': the window starts at the first request and lasts its full length. '}

      <strong>Aligned</strong>

      : the window follows the UTC clock (1 day runs from midnight to midnight).
    </span>
  );
}

function EditNote({ isEditing, isWindowChanged }) {
  if (!isEditing) {
    return false;
  }

  if (isWindowChanged) {
    return (
      <span aria-live="polite" className={WARNING_NOTE}>
        {'A new '}

        <strong>window type</strong>

        {' or '}

        <strong>window</strong>

        {' '}

        <strong>restarts the counter</strong>

        : what was already consumed is not carried over.
      </span>
    );
  }

  return (
    <span aria-live="polite" className={NOTE}>
      {'Changing only the '}

      <strong>max</strong>

      {' keeps what was already '}

      <strong>consumed</strong>

      {' in this window.'}
    </span>
  );
}

export default LimitNotes;
