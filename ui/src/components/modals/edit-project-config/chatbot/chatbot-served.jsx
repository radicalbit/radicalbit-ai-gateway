import Lucide from '@Components/lucide';
import {
  Board,
  Button,
  NewHeader, SectionTitle, TextArea, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { Send, WandSparkles } from 'lucide-react';

const TEXTAREA_ROWS = 4;

function ChatbotServed() {
  return (
    <div className="flex flex-col min-h-0 opacity-50 pointer-events-none">
      <div className="flex flex-col h-full">
        <NewHeader title={(
          <SectionTitle
            subtitle="AI can make mistakes, please check the answer"
            title="Generate Configuration"
            titlePrefix={<Lucide icon={WandSparkles} />}
          />
        )}
        />

        <Board
          backgroundLevel={0}
          borderType="none"
          footer={(
            <NewHeader
              details={{
                one: (
                  <Tooltip title="Send">
                    <div>
                      <Button
                        aria-label="Send"
                        disabled
                        type="primary"
                      >
                        <Lucide icon={Send} />
                      </Button>
                    </div>
                  </Tooltip>
                ),
              }}
              padding="vertical"
              title={(
                <i className="color-secondary-01 font-normal">
                  <div>
                    Describe your routes and parameters, add api keys and any custom values.
                    <br />
                    AI can read the current selected configuration.
                  </div>
                </i>
              )}
            />
          )}
          main={(
            <TextArea
              aria-label="Prompt"
              placeholder="Type here..."
              rows={TEXTAREA_ROWS}
            />
          )}
          size="small"
        />
      </div>
    </div>
  );
}

export default ChatbotServed;
