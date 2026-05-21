import { useEffect } from 'react';

export const updateTheme = (chartRef) => {
  const chartInstance = chartRef.current?.getEchartsInstance();

  if (!chartInstance) {
    console.warn('Chart non pronto per theme update');
    return;
  }

  const isDark = document.body.classList.contains('dark');
  const themeColors = {
    backgroundColor: isDark ? '#000' : '#ecece7',
    textStyle: { color: isDark ? '#e0e0e0' : '#333' },
    title: { textStyle: { color: isDark ? '#e0e0e0' : '#333' } },
    legend: { textStyle: { color: isDark ? '#e0e0e0' : '#333' } },
    tooltip: { backgroundColor: isDark ? '#000' : '#fff' },
    grid: {
      ...chartInstance.getOption().grid,
    },
    xAxis: {
      axisLine: { lineStyle: { color: isDark ? '#444' : '#ccc' } },
      splitLine: { lineStyle: { color: isDark ? '#333' : '#e0e0e0' } },
    },
    yAxis: {
      axisLine: { lineStyle: { color: isDark ? '#444' : '#ccc' } },
      splitLine: { lineStyle: { color: isDark ? '#333' : '#e0e0e0' } },
    },

    series: [{ lineStyle: { color: isDark ? '#666' : '#333' } }],
  };

  chartInstance.setOption(themeColors, { notMerge: false });
};

const useDarkModeChart = (chartRef) => {
  useEffect(() => {
    const observer = new MutationObserver(() => {
      updateTheme(chartRef);
    });

    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });

    return () => {
      observer.disconnect();
    };
  }, [chartRef]);
};

export default useDarkModeChart;
