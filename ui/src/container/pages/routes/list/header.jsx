import Lucide from '@Components/lucide';
import TimeFilter from '@Components/time-filter';
import { NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { Cpu } from 'lucide-react';

function RoutesListHeader() {
  return (
    <NewHeader
      details={{ one: <TimeFilter /> }}
      title={(
        <SectionTitle
          subtitle="Active routes currently served by the gateway. Only served configurations appear here."
          title="Routes"
          titlePrefix={<Lucide icon={Cpu} />}
        />
      )}
    />
  );
}

export default RoutesListHeader;
