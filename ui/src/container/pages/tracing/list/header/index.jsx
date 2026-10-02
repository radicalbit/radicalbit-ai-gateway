import Lucide from '@Components/lucide';
import { NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { Route } from 'lucide-react';

function TracingListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Inspect individual requests processed by the gateway."
          title="Tracing"
          titlePrefix={<Lucide icon={Route} />}
        />
      )}
    />
  );
}

export default TracingListHeader;
