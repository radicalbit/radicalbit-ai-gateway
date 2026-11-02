import { EDIT_MAX_NOTE, EDIT_WINDOW_NOTE } from './constants';

function EditNote({ isWindowChanged }) {
  if (isWindowChanged) {
    return <span aria-live="polite" className="text-xs text-[var(--coo-warning)]">{EDIT_WINDOW_NOTE}</span>;
  }

  return <span aria-live="polite" className="text-xs opacity-70">{EDIT_MAX_NOTE}</span>;
}

export default EditNote;
