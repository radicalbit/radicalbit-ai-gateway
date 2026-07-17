import Lucide from '@Components/lucide';
import { NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { ChartColumn } from 'lucide-react';

function UsageListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Monitor request volume, costs, and limits across your projects."
          title="Usage"
          titlePrefix={<Lucide icon={ChartColumn} />}
        />
      )}
    />
  );
}

export default UsageListHeader;
