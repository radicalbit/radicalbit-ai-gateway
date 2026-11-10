import { skipToken } from '@reduxjs/toolkit/query';
import { useGetProjectBudgetLimitsConsumptionStreamQuery } from './api';

// Consumption of every budget of *projectUuids*, keyed by limit uuid: read a budget's bar
// with `consumption?.[limit.uuid]`. No stream is opened without uuids.
export const useProjectBudgetLimitsConsumption = (projectUuids) => {
  const { data } = useGetProjectBudgetLimitsConsumptionStreamQuery(projectUuids?.length ? { projects: projectUuids } : skipToken);

  return data?.consumption;
};
