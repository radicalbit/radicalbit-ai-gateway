import TimeFilter from '@Components/time-filter';
import { faMicrochip } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function RoutesListHeader() {
  return (
    <NewHeader
      details={{ one: <TimeFilter /> }}
      title={(
        <SectionTitle
          subtitle="Active routes currently served by the gateway. Only served configurations appear here."
          title="Routes"
          titlePrefix={<FontAwesomeIcon icon={faMicrochip} />}
        />
      )}
    />
  );
}

export default RoutesListHeader;
