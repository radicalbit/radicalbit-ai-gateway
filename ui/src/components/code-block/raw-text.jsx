/**
 * Renders raw text inside a <pre><code> block with optional line numbers.
 *
 * @param {Object} props
 * @param {string} props.text - Raw text to display
 * @param {boolean} [props.hideLines=false] - Whether to hide line numbers
 * @returns {JSX.Element}
 */
function CodeBlockRawText({ text = '', hideLines = false }) {
  const lines = text.split('\n');

  return (
    <pre style={{ fontSize: 'var(--code-block-font-size)' }}>
      {!hideLines && (
        <div aria-hidden="true" className="c-code-block__lines_numbers">
          {lines.map((_, index) => (
            <div key={index}>{index + 1}</div>
          ))}
        </div>
      )}

      <code aria-label="Code content">
        {text}
      </code>
    </pre>
  );
}

export default CodeBlockRawText;
