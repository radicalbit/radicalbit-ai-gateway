const parseTagEntries = (entries) => {
  const tags = [];

  entries.forEach((entry) => {
    const separatorIndex = entry.indexOf('=');

    if (separatorIndex <= 0) {
      return;
    }

    const key = entry.slice(0, separatorIndex);
    const value = entry.slice(separatorIndex + 1);

    if (!value) {
      return;
    }

    const existing = tags.find((tag) => tag.key === key);

    if (existing) {
      existing.values.push(value);

      return;
    }

    tags.push({ key, values: [value] });
  });

  return tags;
};

export const parseTagsFromSearchParams = (searchParams) => parseTagEntries(searchParams.getAll('tags'));

export const parseTagsFromTagsKey = (tagsKey) => {
  if (!tagsKey) {
    return [];
  }

  return parseTagEntries(tagsKey.split('&'));
};

export const appendTagsToParams = (params, tags) => {
  if (!tags || tags.length === 0) {
    return params;
  }

  tags.forEach(({ key, values }) => {
    if (!key || !values || values.length === 0) {
      return;
    }

    values.forEach((value) => {
      params.append('tags', `${key}=${value}`);
    });
  });

  return params;
};
