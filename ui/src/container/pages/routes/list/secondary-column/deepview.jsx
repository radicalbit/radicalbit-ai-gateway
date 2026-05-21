import HtmlAnchor from '@Components/html-anchor';
import { Board, SectionTitle } from '@radicalbit/radicalbit-design-system';

const MAIN_TEXT = 'Dive deeper into the data collected by the AI gateway using the main tools of Remote Monitoring Software.';

function Deepview() {
  return (
    <Board
      header={<SectionTitle size="small" title="Deepview quickstart 🚀" />}
      main={MAIN_TEXT}
      secondary={(
        <div className="flex flex-col gap-6">
          <GetStarted />
        </div>
      )}
      secondaryType="single"
    />
  );
}

function GetStarted() {
  return (
    <div className="flex gap-2 items-center">
      <HtmlAnchor
        href="https://docs.ai-gateway.radicalbit.ai/configuration/basic-setup"
        rel="noopener noreferrer"
        target="_blank"
      >
        Get Started
      </HtmlAnchor>

      <div>&gt;</div>
    </div>
  );
}

export default Deepview;
