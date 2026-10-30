import focusFirstInvalidField from '@Helpers/focus-first-invalid-field';
import { useFormbitContext } from '@radicalbit/formbit';
import { paths } from './schema';

export default () => {
  const { validateAll, write } = useFormbitContext();

  const handleOnNext = () => {
    validateAll(paths, {
      successCallback: () => {
        write('__metadata.step', 1);
      },
      errorCallback: focusFirstInvalidField,
    });
  };

  return { handleOnNext };
};
