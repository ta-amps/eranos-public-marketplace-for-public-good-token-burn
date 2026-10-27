export function ErrorAlert({
  title = "Unable to load data",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="er-alert" role="alert">
      <div className="er-alert-body">
        <strong>{title}:</strong> <span>{message}</span>
      </div>
      <button type="button" className="er-btn-secondary" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
