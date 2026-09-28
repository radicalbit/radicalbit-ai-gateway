import Lucide from '@Components/lucide';
import { NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { Lock } from 'lucide-react';

function SecretsListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Secret keys to reference in a configuration with !secret — not credentials, and their secret values are never shown."
          title="Secrets"
          titlePrefix={<Lucide icon={Lock} />}
        />
      )}
    />
  );
}

export default SecretsListHeader;
