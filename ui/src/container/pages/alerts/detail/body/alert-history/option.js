import dayjs from 'dayjs';

const SENT_COLOR = '#00A35C';
const FAILED_COLOR = '#F33D23';

export default ({ buckets }) => ({
  aria: { enabled: true },
  legend: { show: false },
  grid: {
    top: 10, right: 10, bottom: 10, left: 10, containLabel: true,
  },
  xAxis: {
    type: 'category',
    data: buckets.map(({ bucketStart }) => bucketStart),
    axisLabel: {
      interval: 11,
      formatter: (ts) => dayjs.unix(ts).format('ddd HH:mm'),
    },
  },
  yAxis: { type: 'value', minInterval: 1 },
  tooltip: {
    trigger: 'axis',
    confine: true,
    axisPointer: { type: 'shadow' },
    formatter(params) {
      const [sent, failed] = params;
      const dateStr = dayjs.unix(sent.axisValue).format('DD MMM, HH:mm');

      return `
        <div>${dateStr}</div>
        <div>${sent.marker}Sent: ${sent.value}</div>
        <div>${failed.marker}Failed: ${failed.value}</div>
      `;
    },
  },
  series: [
    {
      name: 'Sent',
      type: 'bar',
      stack: 'alerts',
      barMaxWidth: 8,
      itemStyle: { color: SENT_COLOR },
      data: buckets.map(({ sent }) => sent),
    },
    {
      name: 'Failed',
      type: 'bar',
      stack: 'alerts',
      barMaxWidth: 8,
      itemStyle: { color: FAILED_COLOR },
      data: buckets.map(({ failed }) => failed),
    },
  ],
});
