import { Alert } from '@radicalbit/radicalbit-design-system';

function RouteLimitWarnings({ lines, onClose, title }) {
  if (!lines.length) {
    return false;
  }

  return (
    <Alert
      closable={!!onClose}
      description={(
        <ul className="list-disc pl-4">
          {lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      onClose={onClose}
      showIcon
      title={title}
      type="warning"
    />
  );
}

export default RouteLimitWarnings;
