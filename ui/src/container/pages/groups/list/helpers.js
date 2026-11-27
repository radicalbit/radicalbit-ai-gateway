const filterByName = (groups, searchValue) => {
  if (!searchValue) {
    return groups;
  }

  return groups.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()));
};

export { filterByName };
