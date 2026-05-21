import { faChartBar } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function UsageListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Cost distribution and token consumption"
          title="Usage"
          titlePrefix={<FontAwesomeIcon icon={faChartBar} />}
        />
      )}
    />
  );
}

export default UsageListHeader;
