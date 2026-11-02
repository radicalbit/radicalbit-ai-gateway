import Lucide from '@Components/lucide';
import TimeFilter from '@Components/time-filter';
import { Helmet, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { Cpu } from 'lucide-react';

function RoutesListHeader() {
  return (
    <>
      <Helmet title="Routes – Radicalbit Platform" />

      <NewHeader
        details={{ one: <TimeFilter /> }}
        title={(
          <SectionTitle
            level={1}
            subtitle="Active routes currently served by the gateway. Only served configurations appear here."
            title="Routes"
            titlePrefix={<Lucide icon={Cpu} />}
          />
        )}
      />
    </>
  );
}

export default RoutesListHeader;
