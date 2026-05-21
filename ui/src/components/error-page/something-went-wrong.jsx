import { faWarning } from '@fortawesome/free-solid-svg-icons';
import { Button, FontAwesomeIcon, Void } from '@radicalbit/radicalbit-design-system';
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
      image={withLogo && <FontAwesomeIcon icon={faWarning} />}
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
