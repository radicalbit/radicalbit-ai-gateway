import Lucide from '@Components/lucide';
import { Helmet, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { ChartColumn } from 'lucide-react';

function UsageListHeader() {
  return (
    <>
      <Helmet title="Usage – Radicalbit Platform" />

      <NewHeader
        title={(
          <SectionTitle
            level={1}
            subtitle="Monitor request volume, costs, and limits across your projects."
            title="Usage"
            titlePrefix={<Lucide icon={ChartColumn} />}
          />
        )}
      />
    </>
  );
}

export default UsageListHeader;
