import Lucide from '@Components/lucide';
import { Button, Void } from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { memo } from 'react';

function SomethingWentWrong({ size, withLogo = true, refetch, ...rest }) {
  return (
    <Void
      actions={refetch && <Button onClick={refetch}>Retry</Button>}
      description={(
        <>
          We are experiencing some errors in our infrastructure
        </>
      )}
      image={withLogo && <Lucide icon={TriangleAlert} />}
      size={size}
      title={(
        <>
          Oh no!
        </>
      )}
      {...rest}
    />
  );
}

export default memo(SomethingWentWrong);
