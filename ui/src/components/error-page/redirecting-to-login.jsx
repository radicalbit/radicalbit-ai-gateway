import Logo from '@Img/logo.png';
import { Void } from '@radicalbit/radicalbit-design-system';
import { memo } from 'react';

function RedirectingToLogin() {
  return (
    <Void
      description="You will be redirected to the login page shortly."
      image={<img alt="login" src={Logo} />}
      title="Redirecting to login..."
    />
  );
}

export default memo(RedirectingToLogin);
