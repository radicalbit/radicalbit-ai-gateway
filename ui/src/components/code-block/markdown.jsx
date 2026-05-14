import Markdown from 'markdown-to-jsx';

/** @typedef {Omit<React.HTMLAttributes<Element>, 'children'> & { options?: import('markdown-to-jsx').MarkdownToJSX.Options }} MarkdownProps */

/**
 * Renders a markdown string inside a styled container.
 *
 * @param {MarkdownProps & { text: string }} props
 * @param {string} props.text - Raw markdown string to render
 * @returns {JSX.Element}
 */
function CodeBlockMarkdown({ text, ...rest }) {
  return (
    <div className="c-code-block__markdown-content" style={{ fontSize: 'var(--code-block-font-size)' }}>
      <Markdown {...rest}>{text}</Markdown>
    </div>
  );
}

export default CodeBlockMarkdown;
