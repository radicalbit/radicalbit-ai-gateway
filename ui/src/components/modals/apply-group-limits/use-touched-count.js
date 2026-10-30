import { useFormbitContext } from '@radicalbit/formbit';
import { areRowsValid, getPreview, getTouchedMembers } from './helpers';
import useMembers from './use-members';

export default () => {
  const { form } = useFormbitContext();
  const rows = form?.limits ?? [];
  const overwrite = form?.overwrite ?? [];

  const { members, limitsByKey } = useMembers();

  if (!areRowsValid(rows)) {
    return members.length;
  }

  return getTouchedMembers(getPreview({ limitsByKey, members, rows }), overwrite).length;
};
