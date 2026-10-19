// PROTOTYPE (AG-1034, reused for AG-1041) — throwaway. Floating variant switcher driven by a search param
// (?variant= by default). Never merge to main.
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';

const isModalOpen = () => !!document.querySelector('.ant-modal-wrap:not([style*="display: none"])');

export const usePrototypeVariant = (variants, param = 'variant') => {
  const [searchParams] = useSearchParams();
  const current = searchParams.get(param);
  return variants.some(({ key }) => key === current) ? current : variants[0].key;
};

// param: search param name · bottom: px from the bottom edge · pauseWhenModalOpen: ignore arrow keys while a
// modal is open (on by default for the page-level ?variant= switcher, so a modal's own switcher gets the keys)
function PrototypeSwitcher({ variants, param = 'variant', bottom = 24, pauseWhenModalOpen = param === 'variant' }) {
  const [, setSearchParams] = useSearchParams();
  const current = usePrototypeVariant(variants, param);
  const index = variants.findIndex(({ key }) => key === current);
  const { key, name } = variants[index];

  const go = (delta) => {
    const next = variants[(index + delta + variants.length) % variants.length];
    setSearchParams((prev) => {
      prev.set(param, next.key);
      return prev;
    }, { replace: true });
  };

  useEffect(() => {
    const handleOnKeyDown = (e) => {
      const { target } = e;
      if (target.closest?.('input, textarea, [contenteditable="true"]')) {
        return;
      }
      if (pauseWhenModalOpen && isModalOpen()) {
        return;
      }
      if (e.key === 'ArrowLeft') go(-1);
      if (e.key === 'ArrowRight') go(1);
    };
    window.addEventListener('keydown', handleOnKeyDown);
    return () => window.removeEventListener('keydown', handleOnKeyDown);
  });

  if (import.meta.env.PROD) {
    return false;
  }

  const buttonStyle = { background: 'transparent', border: 0, color: 'inherit', cursor: 'pointer', fontSize: 18, padding: '0 8px' };

  // Portal: a fixed element inside an animated (transformed) modal would be positioned relative to it
  return createPortal(
    <div
      style={{
        position: 'fixed',
        bottom,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 10000,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 16px',
        borderRadius: 999,
        background: '#111',
        color: '#fff',
        fontFamily: 'monospace',
        fontSize: 13,
        boxShadow: '0 6px 24px rgba(0,0,0,.35)',
      }}
    >
      <button aria-label="Previous variant" onClick={() => go(-1)} style={buttonStyle} type="button">←</button>

      <span>{`PROTOTYPE · ${param}=${key} (${name})`}</span>

      <button aria-label="Next variant" onClick={() => go(1)} style={buttonStyle} type="button">→</button>
    </div>,
    document.body,
  );
}

export default PrototypeSwitcher;
