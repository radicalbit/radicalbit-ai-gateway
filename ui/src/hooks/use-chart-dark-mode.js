import { useEffect } from 'react';

export const updateTheme = (chartRef) => {
  const chartInstance = chartRef.current?.getEchartsInstance();

  if (!chartInstance) {
    console.warn('Chart non pronto per theme update');
    return;
  }

  const isDark = document.body.classList.contains('dark');
  // Light-mode colors aligned to the new design-system palette:
  // bg = --coo-bk-lv1 (#fdfdfe, components resting on the page),
  // text = --coo-fg-black (#14141a), axes/grid = light secondary greys.
  // Dark mode left untouched for now.
  const themeColors = {
    backgroundColor: isDark ? '#000' : '#fdfdfe',
    textStyle: { color: isDark ? '#e0e0e0' : '#14141a' },
    title: { textStyle: { color: isDark ? '#e0e0e0' : '#14141a' } },
    legend: { textStyle: { color: isDark ? '#e0e0e0' : '#14141a' } },
    tooltip: { backgroundColor: isDark ? '#000' : '#fff' },
    grid: {
      ...chartInstance.getOption().grid,
    },
    xAxis: {
      axisLine: { lineStyle: { color: isDark ? '#444' : '#e4e4dd' } },
      splitLine: { lineStyle: { color: isDark ? '#333' : '#ecece7' } },
    },
    yAxis: {
      axisLine: { lineStyle: { color: isDark ? '#444' : '#e4e4dd' } },
      splitLine: { lineStyle: { color: isDark ? '#333' : '#ecece7' } },
    },

    series: [{ lineStyle: { color: isDark ? '#666' : '#14141a' } }],
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
