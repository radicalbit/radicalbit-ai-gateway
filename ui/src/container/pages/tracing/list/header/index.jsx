import Lucide from '@Components/lucide';
import { Helmet, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { Route } from 'lucide-react';

function TracingListHeader() {
  return (
    <>
      <Helmet title="Tracing – Radicalbit Platform" />

      <NewHeader
        title={(
          <SectionTitle
            level={1}
            subtitle="Inspect individual requests processed by the gateway."
            title="Tracing"
            titlePrefix={<Lucide icon={Route} />}
          />
        )}
      />
    </>
  );
}

export default TracingListHeader;
