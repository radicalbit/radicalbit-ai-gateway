import Lucide from '@Components/lucide';
import LimitFields from '@Components/limits/limit-fields';
import LimitNotes from '@Components/limits/limit-notes';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import useHandleOnEdit from './useHandleOnEdit';

const FLUSH_BUTTON = '!min-w-0 !px-0';

function EditScreen() {
  const { form, write } = useFormbitContext();
  const row = form?.limits?.[0];

  const { duplicateError, errorMessage, handleOnCancel, isWindowChanged } = useHandleOnEdit();

  const message = duplicateError ?? errorMessage;
  const errorField = message ? <FormField message={message} /> : false;

  const handleOnChange = (next) => {
    write('limits[0]', next);
  };

  if (!row) {
    return false;
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button className={FLUSH_BUTTON} icon={<Lucide icon={ArrowLeft} />} onClick={handleOnCancel} type="text">Back</Button>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <LimitFields limit={row} onChange={handleOnChange} withCategory={false} />

          {errorField}
        </div>

        <LimitNotes isEditing isWindowChanged={isWindowChanged} />
      </div>
    </div>
  );
}

export default EditScreen;
