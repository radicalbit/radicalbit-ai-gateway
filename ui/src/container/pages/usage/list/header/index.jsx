import { faChartBar } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function UsageListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Monitor request volume, costs, and limits across your projects."
          title="Usage"
          titlePrefix={<FontAwesomeIcon icon={faChartBar} />}
        />
      )}
    />
  );
}

export default UsageListHeader;
