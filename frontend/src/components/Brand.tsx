export function Brand() {
  return (
    <div className="brand" role="img" aria-label="Pole Position">
      <svg className="brand__mark" aria-hidden="true" viewBox="0 0 42 32" fill="currentColor">
        <path d="M1 28 17 4h12L13 28zm19 0L36 4h6L26 28z" />
      </svg>
      <span className="brand__wordmark">POLE POSITION<span className="brand__period">.</span></span>
    </div>
  );
}
