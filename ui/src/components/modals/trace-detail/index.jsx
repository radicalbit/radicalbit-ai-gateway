import { RbitModal } from '@radicalbit/radicalbit-design-system';
import Body from './body';
import Header from './header';
import useCloseRequestDetail from './use-close-request-detail';

function TraceDetail() {
  const handleOnClose = useCloseRequestDetail();

  return (
    <RbitModal
      aria-label="Request detail"
      closable={false}
      defaultMaximize
      header={<Header />}
      onCancel={handleOnClose}
      open
    >
      <Body />
    </RbitModal>
  );
}

export default TraceDetail;
