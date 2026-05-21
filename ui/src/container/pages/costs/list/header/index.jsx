import TimeFilter from '@Components/time-filter';
import { faChartBar } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function CostsListHeader() {
  return (
    <NewHeader
      details={{ one: <TimeFilter /> }}
      title={(
        <SectionTitle
          subtitle="Cost distribution and token consumption by route"
          title="Usage"
          titlePrefix={<FontAwesomeIcon icon={faChartBar} />}
        />
      )}
    />
  );
}

export default CostsListHeader;
