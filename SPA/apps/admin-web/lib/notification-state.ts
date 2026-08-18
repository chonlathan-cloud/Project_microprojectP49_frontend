export const NOTIFICATION_STATES = [
  "PENDING",
  "ENQUEUED",
  "PROCESSING",
  "RETRYABLE",
  "SENT",
  "FAILED"
] as const;

export type NotificationState = (typeof NOTIFICATION_STATES)[number];

const ACTION_REQUIRED_STATES = new Set<NotificationState>(["FAILED", "RETRYABLE"]);

export function isNotificationState(value: string): value is NotificationState {
  return (NOTIFICATION_STATES as readonly string[]).includes(value);
}

export function notificationRequiresAction(state: string): boolean {
  return isNotificationState(state) && ACTION_REQUIRED_STATES.has(state);
}

export function countNotificationsRequiringAction(items: Array<{ state?: string }>): number {
  return items.filter((item) => item.state && notificationRequiresAction(item.state)).length;
}
