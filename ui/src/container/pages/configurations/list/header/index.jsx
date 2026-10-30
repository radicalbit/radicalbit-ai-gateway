import Lucide from '@Components/lucide';
import { Helmet, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { SlidersHorizontal } from 'lucide-react';

function ConfigurationsListHeader() {
  return (
    <>
      <Helmet title="Configurations – Radicalbit Platform" />

      <NewHeader
        title={(
          <SectionTitle
            level={1}
            subtitle="Write, generate, and publish your gateway configuration. AI-assisted or manual YAML."
            title="Configurations"
            titlePrefix={<Lucide icon={SlidersHorizontal} />}
          />
        )}
      />
    </>
  );
}

export default ConfigurationsListHeader;
