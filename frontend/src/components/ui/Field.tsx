import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react';
import './Field.css';

interface FieldShellProps {
  label: ReactNode;
  htmlFor: string;
  error?: string;
  hint?: ReactNode;
  required?: boolean;
  children: ReactNode;
}

function FieldShell({ label, htmlFor, error, hint, required, children }: FieldShellProps) {
  return (
    <div className={`field${error ? ' field--error' : ''}`}>
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required && <span className="field__required" aria-hidden="true"> *</span>}
      </label>
      {children}
      {hint && !error && <p className="field__hint">{hint}</p>}
      {error && (
        <p className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  error?: string;
  hint?: ReactNode;
}

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, error, hint, id, required, ...inputProps },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell label={label} htmlFor={fieldId} error={error} hint={hint} required={required}>
      <input
        ref={ref}
        id={fieldId}
        className="field__input"
        aria-invalid={error ? true : undefined}
        required={required}
        {...inputProps}
      />
    </FieldShell>
  );
});

export interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: ReactNode;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(
  function SelectField({ label, error, hint, id, required, children, ...selectProps }, ref) {
    const autoId = useId();
    const fieldId = id ?? autoId;
    return (
      <FieldShell label={label} htmlFor={fieldId} error={error} hint={hint} required={required}>
        <select
          ref={ref}
          id={fieldId}
          className="field__input field__select"
          aria-invalid={error ? true : undefined}
          required={required}
          {...selectProps}
        >
          {children}
        </select>
      </FieldShell>
    );
  },
);
