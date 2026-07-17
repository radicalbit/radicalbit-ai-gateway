import Description from '@Container/pages/alerts/detail/body/form-fields/description';
import Name from '@Container/pages/alerts/detail/body/form-fields/name';

function StepA() {
  return (
    <div className="flex flex-col gap-4">
      <Name />

      <Description />
    </div>
  );
}

export default StepA;
