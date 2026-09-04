import { useFormbitContext } from '@radicalbit/formbit';
import { CHAT_CURL } from '../../commands';
import useCurlParams from '../../use-curl-params';

export default (onClose) => {
  const { projectName, routeName } = useCurlParams();

  const { isFormInvalid, submitForm } = useFormbitContext();

  const isSubmitDisabled = isFormInvalid();

  const handleOnSubmit = () => {
    submitForm(async ({ form: formData }) => {
      await navigator.clipboard.writeText(CHAT_CURL(projectName, routeName, formData.apiKey));

      onClose();
    });
  };

  return { handleOnSubmit, isSubmitDisabled };
};
