import { faCopy, faMinus, faPlus } from '@fortawesome/free-solid-svg-icons';
import {
  Button,
  CopyToClipboard,
  FontAwesomeIcon,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import { useState } from 'react';
import './_styles.less';

/**
 * @typedef {React.HTMLAttributes<HTMLDivElement>} DivProps
 */

/**
 * @typedef {Object} Props
 * @property {string} [code]
 * @property {number} [defaultFontSize=0.8]
 * @property {boolean} [isFontResizable=false]
 * @property {boolean} [hasCopyToClipboard=false]
 * @property {boolean} [minimal=false]
 * @property {boolean} [wrapText=false]
 * @property {string} [copyToClipboardText='Copy']
 * @property {React.ReactNode} [actions]
 * @property {React.ReactNode} [children]
 */

/**
 * Command component
 *
 * @param {Props & DivProps} props - Component props
 * @returns {JSX.Element}
 */
function CodeBlock({
  actions,
  children,
  code = '',
  copyToClipboardText = 'Copy',
  defaultFontSize = 0.8,
  minimal = false,
  hasCopyToClipboard = false,
  isFontResizable = false,
  wrapText = false,
  className = '',
  ...rest
}) {
  const [fontSize, setFontSize] = useState(defaultFontSize);

  const css = classNames('c-code-block', {
    'c-code-block--wrap-text': wrapText,
    'c-code-block--minimal': minimal,
  }, className);

  const handleOnIncreaseFontSize = () => {
    setFontSize((old) => old + 0.1);
  };

  const handleOnDecreaseFontSize = () => {
    setFontSize((old) => {
      const newSize = old - 0.1;

      if (newSize >= 0.1) {
        return newSize;
      }

      return old;
    });
  };

  return (
    <div
      aria-label="Code snippet with line numbers"
      className={css}
      role="region"
      style={{ '--code-block-font-size': `${fontSize}rem` }}
      {...rest}
    >
      {children}

      <div className="c-code-block__actions">
        {actions && (
          <div className="c-code-block__actions__custom">
            {actions}
          </div>
        )}

        {isFontResizable && (
          <div className="c-code-block__actions__resize">
            <Tooltip title="Increase font size">
              <Button onClick={handleOnIncreaseFontSize} size="small" type="secondary"><FontAwesomeIcon icon={faPlus} /></Button>
            </Tooltip>

            <Tooltip title="Decrease font size">
              <Button onClick={handleOnDecreaseFontSize} size="small" type="secondary"><FontAwesomeIcon icon={faMinus} /></Button>
            </Tooltip>
          </div>
        )}

        {hasCopyToClipboard && (
          <CopyToClipboard className="c-code-block__actions__copy-to-clipboard" link={code} tooltip={{ mouseEnterDelay: 0 }}>
            <FontAwesomeIcon icon={faCopy} />

            <div>{copyToClipboardText}</div>
          </CopyToClipboard>
        )}
      </div>
    </div>
  );
}

export default CodeBlock;
