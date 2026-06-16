import { faWandMagicSparkles } from '@fortawesome/free-solid-svg-icons';
import {
  FontAwesomeIcon, NewHeader, SectionTitle, TextArea,
} from '@radicalbit/radicalbit-design-system';

const TEXTAREA_ROWS = 4;

function ChatbotReadyToServe() {
  return (
    <div className="flex flex-col min-h-0 border rounded overflow-hidden gap-2 opacity-50 pointer-events-none">
      <div className="flex flex-col h-full">
        <NewHeader title={(
          <SectionTitle
            size="small"
            subtitle="AI can make mistakes, please check the answer"
            title="Generate Configuration"
            titlePrefix={<FontAwesomeIcon icon={faWandMagicSparkles} />}
          />
        )}
        />

        <div className="flex items-end gap-2 border rounded p-2">
          <TextArea
            bordered={false}
            disabled
            placeholder="Describe your routes and parameters, add api keys and any custom values. Read configuration docs"
            rows={TEXTAREA_ROWS}
          />
        </div>
      </div>
    </div>
  );
}

export default ChatbotReadyToServe;
