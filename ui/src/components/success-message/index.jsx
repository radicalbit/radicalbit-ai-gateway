function SuccessMessage({ prefix, strong, suffix }) {
  return (
    <>
      {`${prefix} `}

      <strong>{strong}</strong>

      {suffix && ` ${suffix}`}
    </>
  );
}

export default SuccessMessage;
