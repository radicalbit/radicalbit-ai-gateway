const withChartAria = (option) => {
  const title = option?.title?.text;
  const seriesNames = (option?.series ?? []).map(({ name }) => name).filter(Boolean);
  const seriesDescription = seriesNames.length ? `Series: ${seriesNames.join(', ')}` : undefined;
  const description = [title, seriesDescription].filter(Boolean).join('. ');

  return {
    ...option,
    aria: {
      enabled: true,
      decal: { show: true },
      label: description ? { description } : undefined,
    },
  };
};

export default withChartAria;
