import { schema as stepASchema } from './step-a/schema';
import { schema as stepBSchema } from './step-b/schema';
import { schema as stepCSchema } from './step-c/schema';

const schema = stepASchema.concat(stepBSchema).concat(stepCSchema);

export { schema };
