import React from 'react';
import { useToast } from '../context/ToastContext';
import { ErrorToast } from './ErrorToast';

export interface ToastContainerProps {
  className?: string;
}

export const ToastContainer: React.FC<ToastContainerProps> = ({ className = '' }) => {
  const { toasts, dismissToast } = useToast();

  if (!toasts || toasts.length === 0) {
    return null;
  }

  // Enforce stacking cap: maximum 5 most recent toasts
  const visibleToasts = toasts.slice(-5);

  return (
    <div
      role="region"
      aria-label="Notifications"
      className={`fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-md w-full pointer-events-none p-4 ${className}`.trim()}
    >
      {visibleToasts.map((toast) => (
        <ErrorToast key={toast.id} toast={toast} onDismiss={dismissToast} />
      ))}
    </div>
  );
};

export default ToastContainer;
