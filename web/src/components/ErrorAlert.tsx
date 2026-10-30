export function ErrorAlert({
  title = "Unable to load data",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  /** Left out when retrying cannot help, such as a kit link that names no kit. */
  onRetry?: () => void;
}) {
  return (
    <div className="er-alert" role="alert">
      <div className="er-alert-body">
        <strong>{title}:</strong> <span>{message}</span>
      </div>
      {onRetry && (
        <button type="button" className="er-btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
