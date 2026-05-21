import { Menu } from '@radicalbit/radicalbit-design-system';
import { useCallback, useEffect, useState } from 'react';

/**
 * Custom hook to control popup visibility/position
 */
export const usePopup = () => {
  const [popup, setPopup] = useState({
    visible: false,
    x: 0,
    y: 0,
    record: null,
  });

  const openPopup = useCallback((event, record) => {
    event.preventDefault();

    setPopup({
      visible: true,
      x: event.clientX,
      y: event.clientY,
      record,
    });
  }, []);

  const closePopup = useCallback(() => {
    setPopup((prev) => ({ ...prev, visible: false }));
  }, []);

  return { popup, openPopup, closePopup };
};

/**
 * Popup component
 */
export function Popup(props) {
  const items = props?.items;
  const onClose = props?.onClose;
  const visible = props?.visible;
  const x = props?.x;
  const y = props?.y;

  useEffect(() => {
    if (visible) {
      const handleClickOutside = () => onClose();
      document.addEventListener('click', handleClickOutside);

      return () => document.removeEventListener('click', handleClickOutside);
    }

    return undefined;
  }, [visible, onClose]);

  if (!visible) {
    // Instead of just return false we are returning the <Menu /> with display: none because of
    // some problems with the <Popconfirm /> of the delete operation
    return (
      <Menu
        items={items}
        selectedKeys={[]} // Needed because the item I click do not has to become selected
        style={{
          display: 'none',
          position: 'fixed',
          top: y,
          left: x,
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          zIndex: 1000,
        }}
      />
    );
  }

  return (
    <Menu
      items={items}
      selectedKeys={[]} // Needed because the item I click do not has to become selected
      style={{
        position: 'fixed',
        top: y,
        left: x,
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        zIndex: 1000,
      }}
    />
  );
}
