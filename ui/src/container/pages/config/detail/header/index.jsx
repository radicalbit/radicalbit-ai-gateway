import { faFile } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

function ConfigDetailHeader() {
  return (
    <NewHeader
      title={(
        <SectionTitle
          subtitle="The YAML configuration file"
          title="Config File"
          titlePrefix={<FontAwesomeIcon icon={faFile} />}
        />
      )}
    />
  );
}

export default ConfigDetailHeader;
