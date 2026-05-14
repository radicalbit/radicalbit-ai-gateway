import TimeFilter from '@Components/time-filter';
import { faMicrochip } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function RoutesListHeader() {
  return (
    <NewHeader
      details={{ one: <TimeFilter /> }}
      title={(
        <SectionTitle
          subtitle="Centralize, manage, and monitor the use of artificial intelligence within your company"
          title="Welcome to your AI Gateway"
          titlePrefix={<FontAwesomeIcon icon={faMicrochip} />}
        />
      )}
    />
  );
}

export default RoutesListHeader;
