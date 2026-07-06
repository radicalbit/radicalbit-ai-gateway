import { faSliders } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function ConfigurationsListHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="Write, generate, and publish your gateway configuration. AI-assisted or manual YAML."
          title="Configurations"
          titlePrefix={<FontAwesomeIcon icon={faSliders} />}
        />
      )}
    />
  );
}

export default ConfigurationsListHeader;
