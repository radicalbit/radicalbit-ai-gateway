import Lucide from '@Components/lucide';
import LimitFields from '@Components/limits/limit-fields';
import LimitNotes from '@Components/limits/limit-notes';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import useHandleOnEdit from './useHandleOnEdit';

function EditScreen() {
  const { form, write } = useFormbitContext();
  const row = form?.limits?.[0];

  const { duplicateError, errorMessage, handleOnCancel, handleOnSave, isWindowChanged } = useHandleOnEdit();

  const message = duplicateError ?? errorMessage;

  const handleOnChange = (next) => {
    write('limits[0]', next);
  };

  const handleOnPressEnter = () => {
    handleOnSave();
  };

  if (!row) {
    return false;
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button className="!min-w-0 !px-0" icon={<Lucide icon={ArrowLeft} />} onClick={handleOnCancel} type="text">Back</Button>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <LimitFields limit={row} onChange={handleOnChange} onPressEnter={handleOnPressEnter} path="limits[0]" withCategory={false} />

          {message && <FormField message={message} />}
        </div>

        <LimitNotes isEditing isWindowChanged={isWindowChanged} />
      </div>
    </div>
  );
}

export default EditScreen;
