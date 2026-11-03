import { useFormbitContext } from '@radicalbit/formbit';
import { useEffect, useState } from 'react';
import { DECISION_CURL } from '../../commands';
import useCurlParams from '../../use-curl-params';

// How long the Copy button shows it copied.
const COPIED_FEEDBACK_MS = 2000;

export default () => {
  const { projectName, routeName } = useCurlParams();

  const { isFormInvalid, submitForm } = useFormbitContext();

  const [isCopied, setIsCopied] = useState(false);

  useEffect(() => {
    if (!isCopied) {
      return undefined;
    }

    const timeout = setTimeout(() => { setIsCopied(false); }, COPIED_FEEDBACK_MS);

    return () => { clearTimeout(timeout); };
  }, [isCopied]);

  const isSubmitDisabled = isFormInvalid();

  const handleOnSubmit = () => {
    submitForm(async ({ form: formData }) => {
      await navigator.clipboard.writeText(DECISION_CURL(projectName, routeName, formData.apiKey));

      setIsCopied(true);
    });
  };

  return { handleOnSubmit, isCopied, isSubmitDisabled };
};
