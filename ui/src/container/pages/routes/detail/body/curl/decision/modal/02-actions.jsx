import Lucide from '@Components/lucide';
import { Button } from '@radicalbit/radicalbit-design-system';
import { Check, Copy } from 'lucide-react';
import useHandleOnSubmit from './use-handle-on-submit';

function Actions({ onClose }) {
  const { handleOnSubmit, isCopied, isSubmitDisabled } = useHandleOnSubmit();

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={onClose} type="text">Close</Button>

      <Button
        disabled={isSubmitDisabled}
        onClick={handleOnSubmit}
        type="primary"
      >
        <Lucide icon={isCopied ? Check : Copy} />

        <div>{isCopied ? 'Copied' : 'Copy'}</div>
      </Button>
    </div>
  );
}

export default Actions;
