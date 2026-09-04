import Lucide from '@Components/lucide';
import { Button } from '@radicalbit/radicalbit-design-system';
import { Copy } from 'lucide-react';
import useHandleOnSubmit from './use-handle-on-submit';

function Actions({ onClose }) {
  const { handleOnSubmit, isSubmitDisabled } = useHandleOnSubmit(onClose);

  return (
    <Button
      disabled={isSubmitDisabled}
      onClick={handleOnSubmit}
      type="primary"
    >
      <Lucide icon={Copy} />

      <div>Copy</div>
    </Button>
  );
}

export default Actions;
