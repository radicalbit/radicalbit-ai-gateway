import { RightColumnResizer } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

function VerticalResizableDivider() {
  const { name } = useParams();

  if (!name) {
    return false;
  }

  return <RightColumnResizer />;
}

export default VerticalResizableDivider;
