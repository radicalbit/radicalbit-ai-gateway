import HtmlAnchor from '@Components/html-anchor';
import useModals from '@Hooks/use-modals';

function Close() {
  const { hideModal } = useModals();

  const handleOnClose = () => {
    hideModal();
  };

  return (
    <HtmlAnchor onClick={handleOnClose} type="link">
      Close
    </HtmlAnchor>
  );
}

export default Close;
