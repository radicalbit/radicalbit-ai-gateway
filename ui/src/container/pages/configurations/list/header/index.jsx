import Lucide from '@Components/lucide';
import { NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { SlidersHorizontal } from 'lucide-react';

function ConfigurationsListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Write, generate, and publish your gateway configuration. AI-assisted or manual YAML."
          title="Configurations"
          titlePrefix={<Lucide icon={SlidersHorizontal} />}
        />
      )}
    />
  );
}

export default ConfigurationsListHeader;
