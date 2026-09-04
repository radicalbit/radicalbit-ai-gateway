import { useFormbitContext } from '@radicalbit/formbit';
import { TRANSCRIPTION_CURL } from '../../commands';
import useCurlParams from '../../use-curl-params';

export default (onClose) => {
  const { projectName, routeName } = useCurlParams();

  const { isFormInvalid, submitForm } = useFormbitContext();

  const isSubmitDisabled = isFormInvalid();

  const handleOnSubmit = () => {
    submitForm(async ({ form: formData }) => {
      await navigator.clipboard.writeText(
        TRANSCRIPTION_CURL(projectName, routeName, formData.apiKey, formData.audioPath),
      );

      onClose();
    });
  };

  return { handleOnSubmit, isSubmitDisabled };
};
