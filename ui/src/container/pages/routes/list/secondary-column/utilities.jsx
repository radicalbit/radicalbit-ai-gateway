import HtmlAnchor from '@Components/html-anchor';
import { Board, SectionTitle } from '@radicalbit/radicalbit-design-system';

function Utilities() {
  return (
    <Board
      header={<SectionTitle size="small" title="Utilities 🤓" />}
      main={(
        <div className="flex flex-col gap-6">
          <Welcome />

          <Routes />

          <HowToUseUI />

          <Configuration />
        </div>
      )}
    />
  );
}

function Welcome() {
  return (
    <div className="flex gap-2 items-center">
      <HtmlAnchor
        href="https://docs.ai-gateway.radicalbit.ai/"
        rel="noopener noreferrer"
        target="_blank"
      >
        Welcome
      </HtmlAnchor>

      <div>&gt;</div>
    </div>
  );
}

function Routes() {
  return (
    <div className="flex gap-2 items-center">
      <HtmlAnchor
        href="https://docs.ai-gateway.radicalbit.ai/basic-concepts#routes"
        rel="noopener noreferrer"
        target="_blank"
      >
        What are Routes
      </HtmlAnchor>

      <div>&gt;</div>
    </div>
  );
}

function HowToUseUI() {
  return (
    <div className="flex gap-2 items-center">
      <HtmlAnchor
        href="https://docs.ai-gateway.radicalbit.ai/basic-concepts/#ui"
        rel="noopener noreferrer"
        target="_blank"
      >
        How to use the UI
      </HtmlAnchor>

      <div>&gt;</div>
    </div>
  );
}

function Configuration() {
  return (
    <div className="flex gap-2 items-center">
      <HtmlAnchor
        href="https://docs.ai-gateway.radicalbit.ai/configuration/advanced-configuration"
        rel="noopener noreferrer"
        target="_blank"
      >
        Configuration
      </HtmlAnchor>

      <div>&gt;</div>
    </div>
  );
}

export default Utilities;
