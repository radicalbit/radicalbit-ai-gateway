import { DATE_FORMAT } from '@Src/constants';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);

export default (date, format = DATE_FORMAT) => dayjs.utc(date).tz(Intl.DateTimeFormat().resolvedOptions().timeZone).format(format);
