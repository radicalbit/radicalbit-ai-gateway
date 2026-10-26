import { useGetProjectQuery } from '@State/projects/api';
import { Alert } from '@radicalbit/radicalbit-design-system';

const MESSAGE = 'This project has a project budget: routes can\'t declare budget_limiting.';

function BudgetBanner({ projectUuid }) {
  const { data, isError, isLoading, isSuccess } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const hasBudget = (data?.limits ?? []).length > 0;

  if (isLoading) {
    return false;
  }

  if (isError) {
    return false;
  }

  if (!data) {
    return false;
  }

  if (!isSuccess) {
    return false;
  }

  if (!hasBudget) {
    return false;
  }

  return <Alert showIcon title={MESSAGE} type="info" />;
}

export default BudgetBanner;
