import { RightColumnResizer } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

function VerticalResizableDivider() {
  const { uuid } = useParams();

  if (!uuid) {
    return false;
  }

  return <RightColumnResizer />;
}

export default VerticalResizableDivider;
