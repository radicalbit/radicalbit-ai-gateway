import Event from '@Container/pages/alerts/detail/body/form-fields/event';
import Project from '@Container/pages/alerts/detail/body/form-fields/project';
import Route from '@Container/pages/alerts/detail/body/form-fields/route';
import Scope from '@Container/pages/alerts/detail/body/form-fields/scope';
import TimeAggregation from '@Container/pages/alerts/detail/body/form-fields/time-aggregation';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';
import useHandleOnNext from './useHandleOnNext';

function StepB() {
  return (
    <div className="flex flex-col gap-4">
      <strong>Alert Rule</strong>

      <Scope />

      <Project />

      <Route />

      <Event />

      <strong>Time aggregation</strong>

      <TimeAggregation />

      <Actions />
    </div>
  );
}

function Actions() {
  const { write } = useFormbitContext();
  const { handleOnNext } = useHandleOnNext();

  const handleOnBack = () => {
    write('__metadata.step', 0);
  };

  return (
    <div className="flex justify-between">
      <Button onClick={handleOnBack}>Back</Button>

      <Button onClick={handleOnNext} type="primary">Next</Button>
    </div>
  );
}

export default StepB;
