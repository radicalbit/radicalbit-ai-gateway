import Event from '@Container/pages/alerts/detail/body/form-fields/event';
import Project from '@Container/pages/alerts/detail/body/form-fields/project';
import Route from '@Container/pages/alerts/detail/body/form-fields/route';
import Scope from '@Container/pages/alerts/detail/body/form-fields/scope';
import TimeAggregation from '@Container/pages/alerts/detail/body/form-fields/time-aggregation';

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
    </div>
  );
}

export default StepB;
